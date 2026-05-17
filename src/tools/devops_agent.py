"""AWS DevOps Agent (DOA) adapter.

This wraps the GA service ``aws-devops-agent`` (boto3 client name
candidate: ``aidevops``).  We expose 3 high-level operations:

  chat(prompt, session_id)              -> str        (5-30s, sync)
  start_investigation(title, context)   -> inv_id     (async, 5-15min)
  get_investigation(inv_id)             -> dict       (poll)
  register_custom_skill(name, ...)      -> skill_id

The boto3 service / operation names below follow the public docs and
blog naming as of 2026-05. If the live SDK exposes slightly different
names (e.g., ``CreateInvestigation`` vs ``StartInvestigation``) the
``_OP_*`` constants below are the only place to change.

We intentionally degrade gracefully when DOA is not configured (env var
``DOA_AGENT_SPACE_ID`` empty), so the code remains importable in dev /
unit-test environments.
"""
from __future__ import annotations

import os
import uuid
from typing import Any

import boto3
from botocore.exceptions import BotoCoreError, ClientError

from ..common.logging_utils import get_logger

logger = get_logger(__name__)


_REGION = os.getenv("AWS_REGION", "us-east-1")
_AGENT_SPACE_ID = os.getenv("DOA_AGENT_SPACE_ID", "").strip()
_DOA_SERVICE = os.getenv("DOA_BOTO3_SERVICE", "aidevops")  # tunable
_OP_CHAT = "start_chat_session"
_OP_INVEST_CREATE = "create_investigation"
_OP_INVEST_GET = "get_investigation"
_OP_REGISTER_SKILL = "register_custom_skill"


class DevOpsAgentTool:
    """Thin facade over the AWS DevOps Agent boto3 client."""

    def __init__(
        self,
        agent_space_id: str | None = None,
        region: str | None = None,
    ) -> None:
        self.agent_space_id = agent_space_id or _AGENT_SPACE_ID
        self.region = region or _REGION
        try:
            self._client = boto3.client(_DOA_SERVICE, region_name=self.region)
        except Exception as exc:
            # Older boto3 versions may not know the service yet.
            logger.warning(
                "doa.client_init_failed_using_mock",
                extra={"err": str(exc), "service": _DOA_SERVICE},
            )
            self._client = None

    # ------------------------------------------------------------------ #
    # On-demand chat (5-30s, sync)
    # ------------------------------------------------------------------ #
    def chat(self, prompt: str, session_id: str | None = None) -> str:
        if not self._configured():
            return self._mock_chat(prompt)

        try:
            op = getattr(self._client, _OP_CHAT)
            resp = op(
                agentSpaceId=self.agent_space_id,
                sessionId=session_id or f"chat-{uuid.uuid4()}",
                inputText=prompt,
            )
        except (ClientError, BotoCoreError, AttributeError) as exc:
            logger.exception("doa.chat_failed", extra={"err": str(exc)})
            return self._mock_chat(prompt, error=str(exc))

        # Streaming chunks -> single str
        chunks: list[str] = []
        for evt in resp.get("completion", []):
            if "chunk" in evt:
                chunks.append(evt["chunk"]["bytes"].decode("utf-8", errors="ignore"))
        return "".join(chunks)

    # ------------------------------------------------------------------ #
    # Investigation (async, 5-15min)
    # ------------------------------------------------------------------ #
    def start_investigation(self, title: str, context: dict[str, Any]) -> str:
        if not self._configured():
            return f"mock-inv-{uuid.uuid4()}"

        try:
            op = getattr(self._client, _OP_INVEST_CREATE)
            resp = op(
                agentSpaceId=self.agent_space_id,
                title=title,
                context=context,
            )
            return resp.get("investigationId") or resp.get("InvestigationId", "")
        except (ClientError, BotoCoreError, AttributeError) as exc:
            logger.exception("doa.create_investigation_failed")
            return f"err-{uuid.uuid4()}"

    def get_investigation(self, investigation_id: str) -> dict[str, Any]:
        if not self._configured():
            return {"investigationId": investigation_id, "status": "MOCK"}

        try:
            op = getattr(self._client, _OP_INVEST_GET)
            return op(investigationId=investigation_id).get("investigation", {})
        except (ClientError, BotoCoreError, AttributeError) as exc:
            logger.exception("doa.get_investigation_failed")
            return {"error": str(exc)}

    # ------------------------------------------------------------------ #
    # Custom Skills (Knowledge Agent uses this on incident sink)
    # ------------------------------------------------------------------ #
    def register_custom_skill(
        self,
        name: str,
        description: str,
        content: dict[str, Any],
    ) -> str:
        if not self._configured():
            return f"mock-skill-{uuid.uuid4()}"

        try:
            op = getattr(self._client, _OP_REGISTER_SKILL)
            resp = op(
                agentSpaceId=self.agent_space_id,
                name=name[:64],                      # MCP tool name limit
                description=description[:1024],
                content=content,
            )
            return resp.get("skillId", "")
        except (ClientError, BotoCoreError, AttributeError):
            logger.exception("doa.register_skill_failed")
            return ""

    # ------------------------------------------------------------------ #
    # Internals
    # ------------------------------------------------------------------ #
    def _configured(self) -> bool:
        return bool(self._client and self.agent_space_id)

    @staticmethod
    def _mock_chat(prompt: str, error: str | None = None) -> str:
        """Used in dev / unit tests / CI when DOA is unreachable."""
        suffix = f" (mock; err={error})" if error else " (mock)"
        return f"[Discovery summary for prompt: {prompt[:80]}]" + suffix
