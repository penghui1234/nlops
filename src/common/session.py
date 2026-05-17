"""Session store backed by DynamoDB.

Schema (matches infra/nlops_stack.py):
    PK:  session_id (S)
    TTL: ttl (N, epoch seconds)
    Attrs: user_id, channel, messages (L of M), context (M), updated_at (N)
"""
from __future__ import annotations

import os
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

import boto3

from .logging_utils import get_logger

logger = get_logger(__name__)

_TABLE_NAME = os.getenv("SESSIONS_TABLE", "nlops-sessions")
_TTL_SECONDS = int(os.getenv("SESSION_TTL_SECONDS", str(60 * 60)))  # 1h
_REGION = os.getenv("AWS_REGION", "us-east-1")


@dataclass
class Session:
    session_id: str
    user_id: str
    channel: str
    messages: list[dict[str, Any]] = field(default_factory=list)
    context: dict[str, Any] = field(default_factory=dict)

    def append(self, role: str, content: str) -> None:
        self.messages.append({"role": role, "content": content, "ts": int(time.time())})

    def to_item(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "user_id": self.user_id,
            "channel": self.channel,
            "messages": self.messages,
            "context": self.context,
            "updated_at": int(time.time()),
            "ttl": int(time.time()) + _TTL_SECONDS,
        }

    @classmethod
    def from_item(cls, item: dict[str, Any]) -> "Session":
        return cls(
            session_id=item["session_id"],
            user_id=item["user_id"],
            channel=item["channel"],
            messages=item.get("messages", []),
            context=item.get("context", {}),
        )


class SessionStore:
    """Thin DynamoDB-backed session repository."""

    def __init__(self, table_name: str | None = None) -> None:
        self.table_name = table_name or _TABLE_NAME
        self._table = boto3.resource("dynamodb", region_name=_REGION).Table(self.table_name)

    def get_or_create(
        self,
        session_id: str | None,
        user_id: str,
        channel: str,
    ) -> Session:
        if session_id:
            resp = self._table.get_item(Key={"session_id": session_id})
            if "Item" in resp:
                return Session.from_item(resp["Item"])
        return Session(
            session_id=session_id or f"sess-{uuid.uuid4()}",
            user_id=user_id,
            channel=channel,
        )

    def save(self, session: Session) -> None:
        self._table.put_item(Item=session.to_item())
        logger.info(
            "session.saved",
            extra={"session_id": session.session_id, "messages": len(session.messages)},
        )
