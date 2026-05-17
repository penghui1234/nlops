"""Sample customer-private tools exposed via MCP to AWS DevOps Agent.

These are stub implementations meant to be replaced with real customer
adapters in production. The pattern is:

  @server.tool
  def tool_name(arg1: type, arg2: type = default) -> dict | list | str:
      \"\"\"One-line description shown to DOA.\"\"\"
      ...

Constraints (from DOA docs):
  - Tool name ≤ 64 chars
  - Read-only ONLY — never expose write operations
  - Sanitize outputs to prevent prompt injection
"""
from __future__ import annotations

from typing import Any

from .server import McpServer

server = McpServer()


@server.tool
def get_service_owner(service_name: str) -> dict[str, Any]:
    """Look up service owner team and on-call contact (read-only)."""
    # In production: call internal CMDB API via VPC Link
    # Stub data:
    return {
        "service": service_name,
        "team": "order-team",
        "on_call": "alice@corp.example",
        "slack_channel": "#order-alerts",
        "runbook_url": f"https://wiki.corp/runbook/{service_name}",
    }


@server.tool
def get_recent_jira_tickets(service: str, limit: int = 5) -> list[dict[str, Any]]:
    """Recent OPEN Jira tickets associated with a service (read-only)."""
    # In production: call Jira REST API
    return [
        {
            "key": "OPS-123",
            "title": f"{service} — RDS proxy upgrade plan",
            "status": "In Progress",
            "url": "https://jira.corp/browse/OPS-123",
        }
    ][:limit]


@server.tool
def get_internal_apm_metric(metric: str, window_minutes: int = 30) -> dict[str, Any]:
    """Fetch a custom APM metric not in CloudWatch (read-only)."""
    # In production: call internal APM API via VPC Link
    return {
        "metric": metric,
        "window_minutes": window_minutes,
        "samples": [
            {"ts": "2026-05-17T14:30:00Z", "value": 42.0},
            {"ts": "2026-05-17T14:31:00Z", "value": 47.5},
        ],
    }
