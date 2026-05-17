"""Knowledge Agent — sink incidents to DevOps Agent Custom Skills + Bedrock KB."""
from __future__ import annotations

from typing import Any

from ..common.logging_utils import get_logger
from ..common.policy import guard
from ..tools.bedrock_kb import KnowledgeBaseTool
from ..tools.devops_agent import DevOpsAgentTool
from .base import Agent, AgentContext

logger = get_logger(__name__)


class KnowledgeAgent(Agent):
    name = "knowledge"
    description = (
        "Search historical incidents (via DOA Skills + Bedrock KB) "
        "or sink a new incident report into both stores (dual-write)."
    )

    def __init__(
        self,
        doa: DevOpsAgentTool | None = None,
        kb: KnowledgeBaseTool | None = None,
    ) -> None:
        self.doa = doa or DevOpsAgentTool()
        self.kb = kb or KnowledgeBaseTool()

    # ------------------------------------------------------------------ #
    def search(self, ctx: AgentContext, query: str = "", top_k: int = 3) -> dict[str, Any]:
        guard("Knowledge", "read", ["bedrock", "kb"], ctx.to_guard_context())
        # DOA already auto-applies matching Skills inside an investigation;
        # for explicit historical lookup, we query the KB directly.
        results = self.kb.search(query, top_k=top_k)
        return {"matches": results}

    # ------------------------------------------------------------------ #
    def sink(self, ctx: AgentContext, report: dict[str, Any]) -> dict[str, Any]:
        guard("Knowledge", "write", ["kb"], ctx.to_guard_context())
        # 1. Bedrock KB: dual-write (compatibility with customer-owned KB)
        kb_key = self.kb.sink_incident(report)
        # 2. DOA Custom Skill (primary path)
        skill_id = self.doa.register_custom_skill(
            name=f"nlops-incident-{report.get('incident_id')}",
            description=report.get("title", "auto-generated from incident"),
            content=report,
        )
        logger.info(
            "knowledge.sunk",
            extra={
                "trace_id": ctx.trace_id,
                "kb_key": kb_key,
                "skill_id": skill_id,
            },
        )
        return {"kb_key": kb_key, "skill_id": skill_id}

    # ------------------------------------------------------------------ #
    def run(self, ctx: AgentContext, op: str = "search", **kwargs: Any) -> dict[str, Any]:
        if op == "search":
            return self.search(ctx, **kwargs)
        if op == "sink":
            return self.sink(ctx, **kwargs)
        raise ValueError(f"unknown knowledge op: {op}")
