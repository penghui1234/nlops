"""AWS DevOps Agent (DOA) adapter — real boto3 API.

Service name: ``devops-agent`` (boto3 ≥ 1.34)
Verified via ``boto3.client('devops-agent').meta.service_model.operation_names``
in 2026-05.

API operation mapping (logical -> real):
  chat (one-shot Q&A)         -> CreateChat + SendMessage
  start investigation         -> CreateBacklogTask (taskType=INVESTIGATION)
  get investigation           -> GetBacklogTask
  list investigations         -> ListBacklogTasks
  list agent spaces           -> ListAgentSpaces

When ``DOA_AGENT_SPACE_ID`` env is empty, the adapter degrades to a
deterministic mock so unit tests and offline demos still work.
"""
from __future__ import annotations

import os
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeoutError
from typing import Any

import boto3
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError, ReadTimeoutError

from common.logging_utils import get_logger

logger = get_logger(__name__)

_REGION = os.getenv("AWS_REGION", "us-east-1")
_AGENT_SPACE_ID = os.getenv("DOA_AGENT_SPACE_ID", "").strip()
_DOA_SERVICE = os.getenv("DOA_BOTO3_SERVICE", "devops-agent")
_CHAT_TIMEOUT_SEC = int(os.getenv("DOA_CHAT_TIMEOUT_SEC", "20"))


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
            cfg = Config(
                read_timeout=_CHAT_TIMEOUT_SEC,
                connect_timeout=5,
                retries={"max_attempts": 1},
            )
            self._client = boto3.client(_DOA_SERVICE, region_name=self.region, config=cfg)
        except Exception as exc:
            logger.warning(
                "doa.client_init_failed_using_mock",
                extra={"err": str(exc), "service": _DOA_SERVICE},
            )
            self._client = None

    # ------------------------------------------------------------------ #
    # Chat: CreateChat + SendMessage  (5-30s sync, with hard timeout)
    # ------------------------------------------------------------------ #
    def chat(self, prompt: str, session_id: str | None = None, user_id: str = "nlops") -> str:
        if not self._configured():
            return self._mock_chat(prompt)

        # Use a thread with hard timeout so we never block the Lambda longer
        # than _CHAT_TIMEOUT_SEC. DOA's event-stream iteration can block if
        # the Agent Space has no associated services.
        try:
            with ThreadPoolExecutor(max_workers=1) as pool:
                fut = pool.submit(self._do_chat, prompt, user_id)
                return fut.result(timeout=_CHAT_TIMEOUT_SEC)
        except FutureTimeoutError:
            logger.warning("doa.chat_hard_timeout", extra={"deadline_s": _CHAT_TIMEOUT_SEC})
            return self._mock_chat(prompt, error=f"DOA timeout > {_CHAT_TIMEOUT_SEC}s; check Agent Space services")
        except Exception as exc:
            logger.exception("doa.chat_failed")
            return self._mock_chat(prompt, error=str(exc)[:120])

    def _do_chat(self, prompt: str, user_id: str) -> str:
        # 1) Create a chat execution
        create_resp = self._client.create_chat(
            agentSpaceId=self.agent_space_id,
            userId=user_id,
            userType="STATIC",
        )
        execution_id = create_resp["executionId"]

        # 2) Send the prompt
        send_resp = self._client.send_message(
            agentSpaceId=self.agent_space_id,
            executionId=execution_id,
            content=prompt,
            userId=user_id,
        )

        # 3) Aggregate event stream into a single string
        chunks: list[str] = []
        for evt in send_resp.get("events", []) or []:
            if isinstance(evt, dict):
                for k in ("content", "text", "message", "output"):
                    v = evt.get(k)
                    if isinstance(v, str):
                        chunks.append(v)
                        break
                    if isinstance(v, dict) and "text" in v:
                        chunks.append(v["text"])
                        break
        text = "".join(chunks)
        if not text:
            raise RuntimeError("DOA returned no content (Agent Space likely has no services associated)")
        return text

    # ------------------------------------------------------------------ #
    # Investigation: CreateBacklogTask + GetBacklogTask  (5-15min async)
    # ------------------------------------------------------------------ #
    def start_investigation(self, title: str, context: dict[str, Any]) -> str:
        if not self._configured():
            return f"mock-inv-{uuid.uuid4()}"

        try:
            ref_id = context.get("trace_id") or f"nlops-{uuid.uuid4()}"
            resp = self._client.create_backlog_task(
                agentSpaceId=self.agent_space_id,
                reference={
                    "system": "NLOps",
                    "title": title[:200],
                    "referenceId": ref_id,
                    "referenceUrl": f"https://nlops.local/trace/{ref_id}",
                    "associationId": context.get("association_id", "nlops-default"),
                },
                taskType="INVESTIGATION",
                title=title[:200],
                description=str(context)[:4000],
                priority=context.get("priority", "MEDIUM"),
                clientToken=str(uuid.uuid4()),
            )
            return resp["task"]["taskId"]
        except (ClientError, BotoCoreError, KeyError) as exc:
            logger.exception("doa.create_backlog_task_failed")
            return f"err-{uuid.uuid4()}"

    def get_investigation(self, investigation_id: str) -> dict[str, Any]:
        if not self._configured():
            return {"taskId": investigation_id, "status": "MOCK"}

        try:
            resp = self._client.get_backlog_task(
                agentSpaceId=self.agent_space_id,
                taskId=investigation_id,
            )
            return resp.get("task", {})
        except (ClientError, BotoCoreError) as exc:
            logger.exception("doa.get_backlog_task_failed")
            return {"error": str(exc)}

    # ------------------------------------------------------------------ #
    # Knowledge sink — best-effort
    # ------------------------------------------------------------------ #
    def register_custom_skill(
        self,
        name: str,
        description: str,
        content: dict[str, Any],
    ) -> str:
        """Persist the incident as a backlog 'note' task (closest analog).

        DOA's GA API exposes Custom Skills mainly via console; from SDK we
        approximate by creating a NOTE / KNOWLEDGE backlog task that the
        agent space can reference. If a future API like CreateSkill is
        added we'll switch to it.
        """
        if not self._configured():
            return f"mock-skill-{uuid.uuid4()}"
        try:
            resp = self._client.create_backlog_task(
                agentSpaceId=self.agent_space_id,
                reference={
                    "system": "NLOps",
                    "title": name[:200],
                    "referenceId": name[:200],
                    "referenceUrl": f"https://nlops.local/skill/{name[:200]}",
                    "associationId": "nlops-knowledge",
                },
                taskType="KNOWLEDGE",
                title=name[:200],
                description=description[:4000],
                priority="LOW",
                clientToken=str(uuid.uuid4()),
            )
            return resp["task"]["taskId"]
        except (ClientError, BotoCoreError) as exc:
            logger.warning(
                "doa.register_skill_failed_or_unsupported",
                extra={"err": str(exc)},
            )
            return ""

    # ------------------------------------------------------------------ #
    def list_agent_spaces(self) -> list[dict[str, Any]]:
        """Helper for diagnostics; returns ``[]`` on any error."""
        if not self._client:
            return []
        try:
            resp = self._client.list_agent_spaces(maxResults=50)
            return resp.get("agentSpaces", [])
        except (ClientError, BotoCoreError):
            return []

    # ------------------------------------------------------------------ #
    def _configured(self) -> bool:
        return bool(self._client and self.agent_space_id)

    @staticmethod
    def _mock_chat(prompt: str, error: str | None = None) -> str:
        suffix = f" [mock; err={error}]" if error else " [mock]"
        sample = (
            "P99 延迟在过去 30 分钟从 200ms 升至 320ms。"
            "RDS proxy 连接池使用率 78%，疑似数据库连接饥饿。"
            "建议关注 RDS proxy max_connections 配置。"
        )
        return f"[Discovery summary] prompt={prompt[:60]!r} → {sample}" + suffix
