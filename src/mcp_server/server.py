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

from ..common.logging_utils import get_logger

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
        return {
            "content": [
                {
                    "type": "text",
                    "text": json.dumps(result, ensure_ascii=False, default=str),
                }
            ]
        }

    # ------------------------------------------------------------------ #
    def handle(self, body: dict[str, Any]) -> dict[str, Any]:
        """Handle one JSON-RPC request."""
        rpc_id = body.get("id")
        method = body.get("method", "")
        params = body.get("params") or {}

        try:
            if method == "tools/list":
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
