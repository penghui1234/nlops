"""L4 MCP Server Lambda — exposes customer's private tools to AWS DevOps Agent
and Amazon Quick Desktop / Suite.

Behind API Gateway with two routes:
  POST /mcp        AWS_IAM (SigV4)  — for AWS DevOps Agent
  POST /mcp-public NONE             — for Amazon Quick (No Auth) / public clients
  GET  /mcp-public NONE             — health/discovery probes
"""
from __future__ import annotations

import json
from typing import Any

from common.audit import Audit
from common.logging_utils import get_logger
from mcp_server.private_tools import server  # registers tools

logger = get_logger(__name__)
AUDIT = Audit()


_CORS_HEADERS = {
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Headers": "Content-Type, Authorization, Mcp-Session-Id",
    "Access-Control-Allow-Methods": "POST, GET, OPTIONS",
    "Access-Control-Max-Age": "3600",
}


def handler(event: dict, context) -> dict:
    trace_id = event.get("requestContext", {}).get("requestId") or "trc-mcp-unknown"
    method = (event.get("httpMethod") or "").upper()

    # CORS preflight
    if method == "OPTIONS":
        return _resp(200, {}, body_str="")

    # GET — allow simple health probe / serverInfo (some MCP clients try GET first)
    if method == "GET":
        return _resp(
            200,
            {
                "jsonrpc": "2.0",
                "result": {
                    "serverInfo": {"name": "NLOps Private Tools", "version": "1.0.0"},
                    "protocolVersion": "2024-11-05",
                    "transport": "streamable-http",
                    "endpoint": "POST this same URL with a JSON-RPC body",
                    "tools_count": len(server._tools),
                },
            },
        )

    # POST — JSON-RPC
    body = event.get("body")
    if isinstance(body, str):
        try:
            body = json.loads(body)
        except json.JSONDecodeError:
            return _resp(400, {"error": "invalid json"})
    body = body or {}

    rpc_method = body.get("method", "")
    response = server.handle(body)

    AUDIT.log(
        trace_id,
        "McpServer",
        rpc_method or "unknown",
        "ok" if (response is None or "error" not in response) else "error",
        {"id": body.get("id")},
    )

    # Notifications return None — respond 204 No Content (still with CORS headers)
    if response is None:
        return _resp(204, None, body_str="")

    return _resp(200, response)


def _resp(status: int, body: Any, body_str: str | None = None) -> dict:
    return {
        "statusCode": status,
        "headers": {"Content-Type": "application/json", **_CORS_HEADERS},
        "body": body_str if body_str is not None else json.dumps(body, ensure_ascii=False),
    }
