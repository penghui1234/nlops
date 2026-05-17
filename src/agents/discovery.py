"""Discovery Agent — pull metrics / logs / topology.

Primary path: AWS DevOps Agent on-demand chat (cheap, fast).
Fallback: direct CloudWatch (when DOA is unavailable).
"""
from __future__ import annotations

from typing import Any

from common.logging_utils import get_logger
from common.policy import guard
from tools.devops_agent import DevOpsAgentTool
from tools.cloudwatch_mcp import CloudWatchTool
from .base import Agent, AgentContext

logger = get_logger(__name__)


class DiscoveryAgent(Agent):
    name = "discovery"
    description = "Fetch current metrics / logs / topology for a target service."

    def __init__(
        self,
        doa: DevOpsAgentTool | None = None,
        cw: CloudWatchTool | None = None,
    ) -> None:
        self.doa = doa or DevOpsAgentTool()
        self.cw = cw or CloudWatchTool()

    def run(
        self,
        ctx: AgentContext,
        service: str = "",
        window_minutes: int = 30,
    ) -> dict[str, Any]:
        guard("Discovery", "read", ["bedrock", "cloudwatch"], ctx.to_guard_context())

        # Path A: DOA on-demand chat
        try:
            findings = self.doa.chat(
                f"What is the current health of service {service} over the past "
                f"{window_minutes} minutes? Return key metrics, anomalies, and recent deployments.",
                session_id=ctx.session_id,
            )
            return {"source": "devops_agent_chat", "findings": findings}
        except Exception as exc:
            logger.warning(
                "discovery.doa_failed_fallback_to_cw",
                extra={"trace_id": ctx.trace_id, "err": str(exc)},
            )

        # Path B: CloudWatch fallback (best-effort summary)
        try:
            cpu = self.cw.get_metric(
                namespace="AWS/ECS",
                metric="CPUUtilization",
                dimensions={"ServiceName": service},
                window_minutes=window_minutes,
            )
            return {"source": "cloudwatch_fallback", "metrics": {"cpu": cpu}}
        except Exception as exc:
            logger.exception("discovery.fallback_failed", extra={"trace_id": ctx.trace_id})
            return {"source": "error", "error": str(exc)}
