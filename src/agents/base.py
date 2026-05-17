"""Base classes for Tool-style Agents."""
from __future__ import annotations

import abc
import inspect
from dataclasses import dataclass, field
from typing import Any

from common.policy import GuardContext


@dataclass
class AgentContext:
    """Per-request context passed to every Agent invocation."""
    trace_id: str
    user_id: str
    session_id: str
    channel: str
    user_confirmed: bool = False
    confirm_token: str | None = None
    extras: dict[str, Any] = field(default_factory=dict)

    def to_guard_context(self) -> GuardContext:
        return GuardContext(
            user_id=self.user_id,
            trace_id=self.trace_id,
            user_confirmed=self.user_confirmed,
            confirm_token=self.confirm_token,
        )


class Agent(abc.ABC):
    """Tool-style logical Agent.

    Subclasses set ``name`` and ``description`` and implement ``run``.
    The Orchestrator collects these via the registry and exposes them
    as Tools to a Strands SDK runner (or any other in-process router).
    """
    name: str = ""
    description: str = ""

    @abc.abstractmethod
    def run(self, ctx: AgentContext, **kwargs: Any) -> dict[str, Any]:
        ...

    # Schema introspection (used by Router to plan calls) ---------------- #
    @classmethod
    def tool_schema(cls) -> dict[str, Any]:
        sig = inspect.signature(cls.run)
        params = {}
        for p in sig.parameters.values():
            if p.name in ("self", "ctx") or p.kind == inspect.Parameter.VAR_KEYWORD:
                continue
            params[p.name] = {"type": "string"}
        return {
            "name": cls.name,
            "description": cls.description,
            "input": params,
        }
