"""Analysis Agent — root cause analysis via DOA investigation."""
from __future__ import annotations

from typing import Any

from common.logging_utils import get_logger
from common.policy import guard
from tools.devops_agent import DevOpsAgentTool
from .base import Agent, AgentContext

logger = get_logger(__name__)


class AnalysisAgent(Agent):
    name = "analysis"
    description = "Run a deep root-cause investigation. Async — returns inv_id."

    def __init__(self, doa: DevOpsAgentTool | None = None) -> None:
        self.doa = doa or DevOpsAgentTool()

    def run(
        self,
        ctx: AgentContext,
        service: str = "",
        window_minutes: int = 30,
        signal: str = "",
    ) -> dict[str, Any]:
        guard("Analysis", "read", ["bedrock", "devops_agent_ro"], ctx.to_guard_context())

        # Kick off async investigation; completion comes via EventBridge (L3)
        inv_id = self.doa.start_investigation(
            title=f"{service} {signal or 'incident'}",
            context={
                "service": service,
                "window_minutes": window_minutes,
                "signal": signal,
                "trace_id": ctx.trace_id,
            },
        )
        logger.info(
            "analysis.investigation_started",
            extra={"trace_id": ctx.trace_id, "investigation_id": inv_id},
        )
        return {
            "investigation_id": inv_id,
            "status": "in_progress",
            "expected_minutes": "5-15",
            "engine": "aws_devops_agent",
        }
