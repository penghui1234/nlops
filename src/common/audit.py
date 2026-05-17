"""Audit logger — writes one row per Agent step to DynamoDB."""
from __future__ import annotations

import os
import time
from typing import Any

import boto3

from .logging_utils import get_logger

logger = get_logger(__name__)

_TABLE_NAME = os.getenv("AUDIT_TABLE", "nlops-audit")
_TTL_DAYS = int(os.getenv("AUDIT_TTL_DAYS", "90"))
_REGION = os.getenv("AWS_REGION", "us-east-1")


class Audit:
    def __init__(self, table_name: str | None = None) -> None:
        self.table_name = table_name or _TABLE_NAME
        self._table = boto3.resource("dynamodb", region_name=_REGION).Table(self.table_name)

    def log(
        self,
        trace_id: str,
        agent: str,
        action: str,
        status: str,                 # "ok" | "deny" | "error"
        payload: dict[str, Any] | None = None,
    ) -> None:
        ts = int(time.time() * 1000)
        item = {
            "trace_id": trace_id,
            "ts": ts,
            "agent": agent,
            "action": action,
            "status": status,
            "payload": payload or {},
            "ttl": int(time.time()) + _TTL_DAYS * 86400,
        }
        try:
            self._table.put_item(Item=item)
        except Exception:
            # Audit failure must never block the request.
            logger.exception("audit.put_item failed", extra={"trace_id": trace_id})
