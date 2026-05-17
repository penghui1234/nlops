"""Report Agent — render a structured finding into an HTML diagnostic page."""
from __future__ import annotations

from typing import Any

from ..common.logging_utils import get_logger
from ..common.policy import guard
from ..report.generator import ReportGenerator
from .base import Agent, AgentContext

logger = get_logger(__name__)


class ReportAgent(Agent):
    name = "report"
    description = "Render a structured finding into an HTML diagnostic page in S3."

    def __init__(self, generator: ReportGenerator | None = None) -> None:
        self.gen = generator or ReportGenerator()

    def run(
        self,
        ctx: AgentContext,
        finding: dict[str, Any] | None = None,
        kind: str = "diagnostic",
    ) -> dict[str, Any]:
        guard("Report", "write", ["s3:reports"], ctx.to_guard_context())
        url = self.gen.render_and_upload(finding or {}, kind=kind, trace_id=ctx.trace_id)
        logger.info("report.rendered", extra={"trace_id": ctx.trace_id, "url": url})
        return {"html_url": url}
