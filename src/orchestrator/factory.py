"""Convenience factory: build a fully-wired Orchestrator with all 6 Tools."""
from __future__ import annotations

from ..agents.analysis import AnalysisAgent
from ..agents.discovery import DiscoveryAgent
from ..agents.execution import ExecutionAgent
from ..agents.knowledge import KnowledgeAgent
from ..agents.report import ReportAgent
from ..agents.router import RouterAgent
from .engine import Orchestrator


def build_default() -> Orchestrator:
    orch = Orchestrator()
    orch.register(RouterAgent())
    orch.register(DiscoveryAgent())
    orch.register(AnalysisAgent())
    orch.register(KnowledgeAgent())
    orch.register(ExecutionAgent())
    orch.register(ReportAgent())
    return orch
