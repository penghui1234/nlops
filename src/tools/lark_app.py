"""Lark (飞书) Custom App API client for v4.

Used by the @-mention bot to:
  - Get tenant_access_token (cached, 2h TTL)
  - Reply to messages
  - Send messages to specific chats

Reference:
  https://open.feishu.cn/document/server-docs/im-v1/message/create
"""
from __future__ import annotations

import json
import os
import time
import urllib.request
import urllib.error
from typing import Any

from common.logging_utils import get_logger

logger = get_logger(__name__)

_APP_ID = os.getenv("LARK_APP_ID", "").strip()
_APP_SECRET = os.getenv("LARK_APP_SECRET", "").strip()
_TIMEOUT_SEC = 8

# Token cache (in-memory, per Lambda warm container)
_token_cache: dict[str, Any] = {"token": "", "expires_at": 0}


class LarkApp:
    """Lark (Feishu) Open Platform API client."""

    BASE_URL = "https://open.feishu.cn/open-apis"

    def __init__(self, app_id: str | None = None, app_secret: str | None = None) -> None:
        self.app_id = app_id or _APP_ID
        self.app_secret = app_secret or _APP_SECRET

    @property
    def configured(self) -> bool:
        return bool(self.app_id and self.app_secret)

    # ------------------------------------------------------------ #
    def get_access_token(self) -> str:
        """Get tenant_access_token (cached). Refresh if expiring within 5 min."""
        now = int(time.time())
        if _token_cache["token"] and _token_cache["expires_at"] - now > 300:
            return _token_cache["token"]

        url = f"{self.BASE_URL}/auth/v3/tenant_access_token/internal"
        body = {"app_id": self.app_id, "app_secret": self.app_secret}
        try:
            resp = self._http_post(url, body, with_token=False)
            token = resp.get("tenant_access_token", "")
            expire = resp.get("expire", 7200)
            if token:
                _token_cache["token"] = token
                _token_cache["expires_at"] = now + int(expire)
                logger.info("lark_app.token_refreshed",
                            extra={"expires_in": expire})
            return token
        except Exception as exc:
            logger.exception("lark_app.token_fetch_failed")
            return ""

    # ------------------------------------------------------------ #
    def reply_message(self, message_id: str, text: str = "",
                      card: dict | None = None) -> dict[str, Any]:
        """Reply to an existing message thread.

        Args:
            message_id: The original message_id to reply to
            text: Plain text reply (used if card is None)
            card: Lark interactive card object (overrides text)
        """
        url = f"{self.BASE_URL}/im/v1/messages/{message_id}/reply"

        if card:
            body = {
                "msg_type": "interactive",
                "content": json.dumps(card, ensure_ascii=False),
            }
        else:
            body = {
                "msg_type": "text",
                "content": json.dumps({"text": text}, ensure_ascii=False),
            }

        try:
            return self._http_post(url, body)
        except Exception as exc:
            logger.exception("lark_app.reply_failed")
            return {"status": "error", "error": str(exc)[:300]}

    # ------------------------------------------------------------ #
    def send_message(self, chat_id: str, text: str = "",
                     card: dict | None = None,
                     receive_id_type: str = "chat_id") -> dict[str, Any]:
        """Send a message to a chat or user.

        Args:
            chat_id: Target chat_id or user_id (depends on receive_id_type)
            text: Plain text (if card is None)
            card: Interactive card object
            receive_id_type: chat_id | open_id | user_id | union_id | email
        """
        url = f"{self.BASE_URL}/im/v1/messages?receive_id_type={receive_id_type}"

        if card:
            body = {
                "receive_id": chat_id,
                "msg_type": "interactive",
                "content": json.dumps(card, ensure_ascii=False),
            }
        else:
            body = {
                "receive_id": chat_id,
                "msg_type": "text",
                "content": json.dumps({"text": text}, ensure_ascii=False),
            }

        try:
            return self._http_post(url, body)
        except Exception as exc:
            logger.exception("lark_app.send_failed")
            return {"status": "error", "error": str(exc)[:300]}

    # ------------------------------------------------------------ #
    def _http_post(self, url: str, body: dict,
                   with_token: bool = True) -> dict[str, Any]:
        headers = {"Content-Type": "application/json; charset=utf-8"}
        if with_token:
            token = self.get_access_token()
            if not token:
                return {"status": "error", "error": "no token"}
            headers["Authorization"] = f"Bearer {token}"

        data = json.dumps(body, ensure_ascii=False).encode("utf-8")
        req = urllib.request.Request(url, data=data, headers=headers, method="POST")
        with urllib.request.urlopen(req, timeout=_TIMEOUT_SEC) as resp:
            text = resp.read().decode("utf-8")
        return json.loads(text) if text else {}
