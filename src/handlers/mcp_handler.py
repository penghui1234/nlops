"""L4 MCP Server Lambda — exposes customer's private tools to AWS DevOps Agent.

Behind API Gateway with AWS_IAM (SigV4) auth.
DevOps Agent assumes ``DOAInvokeMcpRole`` to sign requests to this endpoint.
"""
from __future__ import annotations

import json
from typing import Any

from common.audit import Audit
from common.logging_utils import get_logger
from mcp_server.private_tools import server  # registers tools

logger = get_logger(__name__)
AUDIT = Audit()


def handler(event: dict, context) -> dict:
    trace_id = event.get("requestContext", {}).get("requestId") or "trc-mcp-unknown"

    body = event.get("body")
    if isinstance(body, str):
        try:
            body = json.loads(body)
        except json.JSONDecodeError:
            return _resp(400, {"error": "invalid json"})
    body = body or {}

    method = body.get("method")
    response = server.handle(body)

    AUDIT.log(
        trace_id,
        "McpServer",
        method or "unknown",
        "ok" if "error" not in response else "error",
        {"id": body.get("id")},
    )
    return _resp(200, response)


def _resp(status: int, body: dict) -> dict:
    return {
        "statusCode": status,
        "headers": {"Content-Type": "application/json"},
        "body": json.dumps(body, ensure_ascii=False),
    }
