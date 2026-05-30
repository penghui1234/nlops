"""AWS DevOps Agent (DOA) adapter for v4.

v4 simplifications vs v3:
  * No Strands intermediate layer - direct boto3 calls
  * No backward-compat with mock service names
  * Hard timeout via threading
  * Cleaner error handling
"""
from __future__ import annotations

import json
import os
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeoutError
from typing import Any

import boto3
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError

from common.logging_utils import get_logger

logger = get_logger(__name__)

_REGION = os.getenv("AWS_REGION", "us-east-1")
_AGENT_SPACE_ID = os.getenv("DOA_AGENT_SPACE_ID", "").strip()
_ASSOCIATION_ID = os.getenv("DOA_ASSOCIATION_ID", "").strip()
_CHAT_TIMEOUT_SEC = int(os.getenv("DOA_CHAT_TIMEOUT_SEC", "25"))


class DevOpsAgent:
    """Thin facade over AWS DevOps Agent boto3 client."""

    def __init__(self) -> None:
        self.agent_space_id = _AGENT_SPACE_ID
        self.association_id = _ASSOCIATION_ID
        self.region = _REGION
        cfg = Config(read_timeout=_CHAT_TIMEOUT_SEC, connect_timeout=5,
                     retries={"max_attempts": 1})
        self._client = boto3.client("devops-agent", region_name=self.region, config=cfg)

    # -------------------------------------------------------------- #
    def chat(self, prompt: str, user_id: str = "nlops-v4") -> str:
        """One-shot chat with DOA. Returns aggregated text or mock fallback."""
        if not self.agent_space_id:
            return self._mock(prompt, "DOA_AGENT_SPACE_ID not set")

        try:
            with ThreadPoolExecutor(max_workers=1) as pool:
                fut = pool.submit(self._do_chat, prompt, user_id)
                return fut.result(timeout=_CHAT_TIMEOUT_SEC)
        except FutureTimeoutError:
            logger.warning("doa.chat_timeout", extra={"deadline_s": _CHAT_TIMEOUT_SEC})
            return self._mock(prompt, f"timeout > {_CHAT_TIMEOUT_SEC}s")
        except (ClientError, BotoCoreError) as exc:
            logger.exception("doa.chat_failed")
            return self._mock(prompt, str(exc)[:120])

    def _do_chat(self, prompt: str, user_id: str) -> str:
        # CreateChat requires a real IAM identity context - handled by Lambda role
        create = self._client.create_chat(
            agentSpaceId=self.agent_space_id,
            userId=user_id,
            userType="STATIC",
        )
        execution_id = create["executionId"]

        send = self._client.send_message(
            agentSpaceId=self.agent_space_id,
            executionId=execution_id,
            content=prompt,
            userId=user_id,
        )

        chunks: list[str] = []
        for evt in send.get("events", []) or []:
            if isinstance(evt, dict):
                for k in ("content", "text", "message", "output"):
                    v = evt.get(k)
                    if isinstance(v, str):
                        chunks.append(v); break
                    if isinstance(v, dict) and "text" in v:
                        chunks.append(v["text"]); break
        text = "".join(chunks)
        if not text:
            raise RuntimeError("empty DOA response (Agent Space may have no services)")
        return text

    # -------------------------------------------------------------- #
    def start_investigation(self, title: str, description: str = "",
                            priority: str = "MEDIUM") -> str:
        """Create a backlog INVESTIGATION task. Returns taskId."""
        if not self.agent_space_id:
            return f"mock-inv-{uuid.uuid4().hex[:8]}"

        try:
            resp = self._client.create_backlog_task(
                agentSpaceId=self.agent_space_id,
                taskType="INVESTIGATION",
                title=title[:200],
                description=description[:4000] or title,
                priority=priority,
                clientToken=str(uuid.uuid4()),
            )
            return resp.get("task", {}).get("taskId", "")
        except (ClientError, BotoCoreError) as exc:
            logger.exception("doa.create_task_failed")
            return f"err-{uuid.uuid4().hex[:8]}"

    def get_investigation(self, task_id: str) -> dict[str, Any]:
        """Get investigation detail by taskId."""
        if not self.agent_space_id or not task_id:
            return {"taskId": task_id, "status": "MOCK"}
        try:
            resp = self._client.get_backlog_task(
                agentSpaceId=self.agent_space_id, taskId=task_id,
            )
            return resp.get("task", {})
        except (ClientError, BotoCoreError) as exc:
            logger.exception("doa.get_task_failed")
            return {"error": str(exc)[:200]}

    # -------------------------------------------------------------- #
    @staticmethod
    def _mock(prompt: str, reason: str) -> str:
        return (
            f"[DOA mock — {reason}]\n"
            f"问题: {prompt[:100]}\n"
            "初步分析: 检测到指标异常,建议关注 RDS 连接池和 Lambda 并发。"
        )
