"""MCP Streamable HTTP server (JSON-RPC 2.0 subset).

Supports two methods:
  - tools/list   -> declare available tools
  - tools/call   -> invoke a tool

Each request is a single HTTP POST with a JSON-RPC body.
Auth is enforced upstream by API Gateway (AWS_IAM / SigV4); we trust
the request reached us via the right Role.
"""
from __future__ import annotations

import inspect
import json
import os
from typing import Any, Callable

from common.logging_utils import get_logger

logger = get_logger(__name__)


_ALLOWLIST = {
    s.strip()
    for s in os.getenv("MCP_TOOLS_ALLOWLIST", "").split(",")
    if s.strip()
}


class McpServer:
    """Tool registry + JSON-RPC dispatcher."""

    def __init__(self) -> None:
        self._tools: dict[str, Callable] = {}

    def tool(self, fn: Callable) -> Callable:
        """Decorator: register an MCP tool."""
        name = fn.__name__
        if len(name) > 64:
            raise ValueError(f"MCP tool name too long: {name}")
        self._tools[name] = fn
        return fn

    # ------------------------------------------------------------------ #
    def list_tools(self) -> dict[str, Any]:
        tools = []
        for name, fn in self._tools.items():
            if _ALLOWLIST and name not in _ALLOWLIST:
                continue
            tools.append(
                {
                    "name": name,
                    "description": (fn.__doc__ or "").strip().split("\n")[0],
                    "inputSchema": _schema_from_signature(fn),
                }
            )
        return {"tools": tools}

    def call_tool(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        if _ALLOWLIST and name not in _ALLOWLIST:
            raise PermissionError(f"tool '{name}' not in allowlist")
        fn = self._tools.get(name)
        if fn is None:
            raise KeyError(f"unknown tool: {name}")
        result = fn(**arguments)

        # Display hint to the calling LLM (Claude / Nova / etc. in Quick Desktop).
        # Without this, the LLM tends to add commentary, status messages, and
        # speculation about why results look the way they do. The hint asks it
        # to render the data faithfully and only volunteer interpretation when
        # the user explicitly asks.
        #
        # Set MCP_VERBOSE_LLM=true to disable the hint (e.g. when you actively
        # WANT the LLM to interpret).
        text = json.dumps(result, ensure_ascii=False, default=str)
        if os.getenv("MCP_VERBOSE_LLM", "false").strip().lower() not in ("1", "true", "yes"):
            text = (
                "[NLOps Display Instructions for the calling LLM]\n"
                "1. Render the JSON below as a clean Markdown table or list.\n"
                "2. DO NOT add commentary, status messages (e.g. \"已经跑通了 ✅\") "
                "or status badges that aren't in the data.\n"
                "3. DO NOT speculate why results look certain ways "
                "(e.g. \"可能查询限制\" / \"可能没绑\"). Only state what's in the data.\n"
                "4. If you have observations, put them under a single line "
                "headed `## AI 备注` (≤ 1 sentence). Skip if no observation.\n"
                "5. Keep the user's language (Chinese/English) consistent with their input.\n"
                "[End Instructions]\n\n"
                + text
            )

        return {
            "content": [
                {
                    "type": "text",
                    "text": text,
                }
            ]
        }

    # ------------------------------------------------------------------ #
    def handle(self, body: dict[str, Any]) -> dict[str, Any] | None:
        """Handle one JSON-RPC request.

        Returns ``None`` for notifications (no response expected).
        """
        rpc_id = body.get("id")
        method = body.get("method", "")
        params = body.get("params") or {}

        # Notifications (no id, no response)
        if method.startswith("notifications/"):
            logger.info("mcp.notification", extra={"method": method})
            return None

        try:
            if method == "initialize":
                result = {
                    "protocolVersion": params.get("protocolVersion", "2024-11-05"),
                    "capabilities": {
                        "tools": {"listChanged": False},
                    },
                    "serverInfo": {
                        "name": "NLOps Private Tools",
                        "version": "1.0.0",
                    },
                }
            elif method == "ping":
                result = {}
            elif method == "tools/list":
                result = self.list_tools()
            elif method == "tools/call":
                tool_name = params.get("name", "")
                args = params.get("arguments") or {}
                result = self.call_tool(tool_name, args)
            else:
                return _rpc_error(rpc_id, -32601, f"unknown method: {method}")
            return {"jsonrpc": "2.0", "id": rpc_id, "result": result}
        except KeyError as exc:
            return _rpc_error(rpc_id, -32601, str(exc))
        except PermissionError as exc:
            return _rpc_error(rpc_id, -32604, str(exc))
        except Exception as exc:
            logger.exception("mcp.tool_call_failed", extra={"method": method})
            return _rpc_error(rpc_id, -32603, str(exc))


def _rpc_error(rpc_id: Any, code: int, message: str) -> dict[str, Any]:
    return {
        "jsonrpc": "2.0",
        "id": rpc_id,
        "error": {"code": code, "message": message},
    }


def _schema_from_signature(fn: Callable) -> dict[str, Any]:
    sig = inspect.signature(fn)
    props = {}
    required = []
    for p in sig.parameters.values():
        if p.name == "self":
            continue
        type_str = "string"
        if p.annotation is int:
            type_str = "integer"
        elif p.annotation is float:
            type_str = "number"
        elif p.annotation is bool:
            type_str = "boolean"
        props[p.name] = {"type": type_str}
        if p.default is inspect.Parameter.empty:
            required.append(p.name)
    return {"type": "object", "properties": props, "required": required}
