"""L4 MCP Server Lambda — exposes customer's private tools to AWS DevOps Agent
and Amazon Quick Desktop / Suite.

Behind API Gateway with routes:
  POST /mcp        AWS_IAM (SigV4)  — for AWS DevOps Agent
  POST /mcp-public NONE             — for Amazon Quick (No Auth) / public clients
  GET  /mcp-public NONE             — health/discovery probes
  GET/POST /sse    NONE             — SSE transport for Quick Desktop
  POST /message    NONE             — SSE transport message endpoint
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
    headers_in = {k.lower(): v for k, v in (event.get("headers") or {}).items()}
    accept = (headers_in.get("accept") or "").lower()

    # Detailed debug: what did the client actually send?
    logger.info(
        "mcp.request_received",
        extra={
            "http_method": method,
            "path": event.get("path"),
            "client_accept": accept,
            "client_session": headers_in.get("mcp-session-id"),
            "client_user_agent": headers_in.get("user-agent"),
            "body_preview": (event.get("body") or "")[:500],
        },
    )

    # Echo / generate a session id (MCP Streamable HTTP convention)
    session_id = headers_in.get("mcp-session-id") or trace_id

    # CORS preflight
    if method == "OPTIONS":
        return _resp(200, {}, body_str="", session_id=session_id)

    # GET — clients (Quick Desktop / mcp-inspector) use this to open the
    # SSE stream that delivers JSON-RPC responses asynchronously.
    # Per MCP SSE Transport spec: GET /sse returns an 'endpoint' event
    # telling the client where to POST JSON-RPC messages.
    if method == "GET":
        path = event.get("path", "/mcp-quick")
        if "text/event-stream" in accept or path == "/sse":
            # SSE Transport: tell client to POST to /message
            # This is what sse_client (used by Quick Desktop) expects.
            # The endpoint should be an absolute path from root.
            sse_body = (
                "event: endpoint\n"
                "data: /message\n\n"
            )
            return {
                "statusCode": 200,
                "headers": {
                    "Content-Type": "text/event-stream",
                    "Cache-Control": "no-cache, no-store",
                    "Connection": "keep-alive",
                    "X-Accel-Buffering": "no",
                    "Mcp-Session-Id": session_id,
                    **_CORS_HEADERS,
                },
                "body": sse_body,
            }
        # Plain GET (no SSE) — return server info as JSON
        return _resp(
            200,
            {
                "jsonrpc": "2.0",
                "result": {
                    "serverInfo": {"name": "NLOps Private Tools", "version": "1.0.0"},
                    "protocolVersion": "2024-11-05",
                    "transport": "sse",
                    "endpoint": "POST /message with a JSON-RPC body",
                    "tools_count": len(server._tools),
                },
            },
            session_id=session_id,
        )

    # POST — JSON-RPC
    body = event.get("body")
    if isinstance(body, str):
        try:
            body = json.loads(body)
        except json.JSONDecodeError:
            return _resp(400, {"error": "invalid json"}, session_id=session_id)
    body = body or {}

    rpc_method = body.get("method", "")
    response = server.handle(body)

    AUDIT.log(
        trace_id,
        "McpServer",
        rpc_method or "unknown",
        "ok" if (response is None or "error" not in response) else "error",
        {"id": body.get("id"), "session_id": session_id},
    )

    # Notifications return None — respond 202 Accepted (MCP convention)
    if response is None:
        return _resp(202, None, body_str="", session_id=session_id)

    # If client asked for SSE, wrap response as a single SSE event
    if "text/event-stream" in accept:
        payload = json.dumps(response, ensure_ascii=False)
        sse_body = f"event: message\ndata: {payload}\n\n"
        return {
            "statusCode": 200,
            "headers": {
                "Content-Type": "text/event-stream",
                "Cache-Control": "no-cache, no-store",
                "Mcp-Session-Id": session_id,
                **_CORS_HEADERS,
            },
            "body": sse_body,
        }

    # Log what we're returning
    logger.info(
        "mcp.response",
        extra={"method": rpc_method, "result_keys": list(response.get("result", {}).keys()) if "result" in response else None},
    )
    return _resp(200, response, session_id=session_id)


def _resp(status: int, body: Any, body_str: str | None = None, session_id: str | None = None) -> dict:
    headers = {
        "Content-Type": "application/json",
        **_CORS_HEADERS,
    }
    if session_id:
        headers["Mcp-Session-Id"] = session_id
    return {
        "statusCode": status,
        "headers": headers,
        "body": body_str if body_str is not None else json.dumps(body, ensure_ascii=False),
    }
