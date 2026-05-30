"""Lark (飞书) IM Bot adapter for v4.

Supports:
  - Incoming webhook (push messages to a group via custom robot URL)
  - Interactive card with title, body markdown, and action buttons

Usage:
    lark = LarkBot()
    lark.send_text(content="hello")
    lark.send_card(title="🚨 Alarm", body_md="**Root cause:** ...",
                   url_buttons=[("查看诊断书", "https://...")])
"""
from __future__ import annotations

import json
import os
import urllib.request
import urllib.error
from typing import Any

from common.logging_utils import get_logger

logger = get_logger(__name__)

_WEBHOOK_URL = os.getenv("LARK_WEBHOOK_URL", "").strip()
_TIMEOUT_SEC = 8


class LarkBot:
    """Lark custom robot incoming webhook client."""

    def __init__(self, webhook_url: str | None = None) -> None:
        self.webhook_url = (webhook_url or _WEBHOOK_URL).strip()

    @property
    def configured(self) -> bool:
        return bool(self.webhook_url)

    # ------------------------------------------------------------ #
    def send_text(self, content: str) -> dict[str, Any]:
        """Send plain text message."""
        return self._post({
            "msg_type": "text",
            "content": {"text": content},
        })

    def send_card(self, title: str, body_md: str,
                  template: str = "blue",
                  url_buttons: list[tuple[str, str]] | None = None,
                  metadata: list[tuple[str, str]] | None = None) -> dict[str, Any]:
        """Send interactive card with title, markdown body, and link buttons.

        Args:
            title: Header text (will be prefixed with emoji based on template)
            body_md: Lark markdown body (supports **bold**, lists, etc.)
            template: red | orange | yellow | green | blue | purple | grey
            url_buttons: list of (label, url) tuples → action buttons
            metadata: list of (key, value) tuples → small fields shown above body
        """
        elements: list[dict[str, Any]] = []

        # Optional metadata fields (key:value pairs in a 2-column grid)
        if metadata:
            fields = []
            for k, v in metadata:
                fields.append({
                    "is_short": True,
                    "text": {
                        "tag": "lark_md",
                        "content": f"**{k}**\n{v}",
                    },
                })
            elements.append({"tag": "div", "fields": fields})
            elements.append({"tag": "hr"})

        # Body markdown
        if body_md:
            elements.append({
                "tag": "div",
                "text": {"tag": "lark_md", "content": body_md},
            })

        # Action buttons (URLs)
        if url_buttons:
            actions = []
            for label, url in url_buttons:
                actions.append({
                    "tag": "button",
                    "text": {"tag": "plain_text", "content": label},
                    "url": url,
                    "type": "primary",
                })
            elements.append({"tag": "action", "actions": actions})

        card = {
            "msg_type": "interactive",
            "card": {
                "config": {"wide_screen_mode": True},
                "header": {
                    "title": {"tag": "plain_text", "content": title[:200]},
                    "template": template,
                },
                "elements": elements,
            },
        }
        return self._post(card)

    # ------------------------------------------------------------ #
    def _post(self, body: dict[str, Any]) -> dict[str, Any]:
        if not self.configured:
            return {"status": "skipped", "reason": "LARK_WEBHOOK_URL not set"}

        data = json.dumps(body, ensure_ascii=False).encode("utf-8")
        req = urllib.request.Request(
            self.webhook_url, data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=_TIMEOUT_SEC) as resp:
                resp_body = resp.read().decode("utf-8")
                resp_json = json.loads(resp_body) if resp_body else {}
            # Lark returns {"StatusCode": 0, "StatusMessage": "success"} on success
            if resp_json.get("StatusCode") == 0 or resp_json.get("code") == 0:
                logger.info("lark.sent_ok", extra={"msg_type": body.get("msg_type")})
                return {"status": "sent", "msg_type": body.get("msg_type"),
                        "response": resp_json}
            logger.warning("lark.api_error",
                           extra={"resp": resp_json, "msg_type": body.get("msg_type")})
            return {"status": "error", "error": str(resp_json)[:300]}
        except urllib.error.URLError as exc:
            logger.exception("lark.send_failed")
            return {"status": "error", "error": str(exc)[:300]}
        except Exception as exc:
            logger.exception("lark.unexpected_error")
            return {"status": "error", "error": str(exc)[:300]}
