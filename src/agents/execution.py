"""Execution Agent — Tool stub that invokes the L2 Execution Lambda.

This is the *only* logical Agent that crosses Lambda boundaries.
Reason: write-permission isolation. Inside the Orchestrator (L1) we
have no IAM rights to mutate AWS resources; we delegate to L2 which
holds the write permissions and validates the Confirm Token.
"""
from __future__ import annotations

import json
import os
from typing import Any

import boto3

from common.logging_utils import get_logger
from common.policy import guard
from .base import Agent, AgentContext

logger = get_logger(__name__)

_EXEC_FN = os.getenv("EXECUTION_FN_NAME", "")


class ExecutionAgent(Agent):
    name = "execution"
    description = "Invoke a write-action through the isolated Execution Lambda."

    def __init__(self) -> None:
        self._lambda = boto3.client("lambda")

    def run(
        self,
        ctx: AgentContext,
        action: dict[str, Any] | None = None,
        confirm_token: str | None = None,
    ) -> dict[str, Any]:
        action = action or {}
        if not confirm_token:
            confirm_token = ctx.confirm_token

        guard(
            "Execution",
            "write",
            ["devops_agent_rw"],
            ctx.to_guard_context(),
        )

        if not _EXEC_FN:
            return {"status": "error", "error": "EXECUTION_FN_NAME env not set"}

        payload = {
            "trace_id": ctx.trace_id,
            "session_id": ctx.session_id,
            "user_id": ctx.user_id,
            "confirm_token": confirm_token,
            "action": action,
        }
        resp = self._lambda.invoke(
            FunctionName=_EXEC_FN,
            InvocationType="RequestResponse",
            Payload=json.dumps(payload).encode(),
        )
        body = json.loads(resp["Payload"].read())
        logger.info(
            "execution.invoked",
            extra={"trace_id": ctx.trace_id, "status_code": resp.get("StatusCode")},
        )
        return body
