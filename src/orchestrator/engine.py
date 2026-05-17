"""Lightweight Strands-style orchestrator.

Why custom and not the real Strands SDK?
  * The Strands SDK pip package is fast-moving; for production deployment we
    pin a thin local engine that mirrors the same patterns (Tool registration
    + plan execution + parallel groups). When Strands GA stabilises we swap
    this engine without touching the Agents.

Capabilities:
  * Register Tool-style Agents
  * Take a plan from the Router and execute steps
  * Support parallel execution within a group
"""
from __future__ import annotations

import asyncio
import time
from typing import Any

from agents.base import Agent, AgentContext
from common.audit import Audit
from common.logging_utils import get_logger

logger = get_logger(__name__)


class Orchestrator:
    def __init__(self) -> None:
        self.tools: dict[str, Agent] = {}
        self.audit = Audit()

    # ------------------------------------------------------------------ #
    def register(self, agent: Agent) -> None:
        if not agent.name:
            raise ValueError("Agent.name must be set")
        self.tools[agent.name] = agent

    # ------------------------------------------------------------------ #
    def run_step(self, ctx: AgentContext, step: dict[str, Any]) -> dict[str, Any]:
        tool_name = step["tool"]
        agent = self.tools.get(tool_name)
        if agent is None:
            raise KeyError(f"unknown tool: {tool_name}")

        args = dict(step.get("args") or {})
        t0 = time.time()
        try:
            result = agent.run(ctx, **args)
            self.audit.log(
                trace_id=ctx.trace_id,
                agent=tool_name,
                action="run",
                status="ok",
                payload={"duration_ms": int((time.time() - t0) * 1000)},
            )
            return result
        except Exception as exc:
            logger.exception("orchestrator.step_failed", extra={"trace_id": ctx.trace_id, "tool": tool_name})
            self.audit.log(
                trace_id=ctx.trace_id,
                agent=tool_name,
                action="run",
                status="error",
                payload={"error": str(exc)},
            )
            raise

    # ------------------------------------------------------------------ #
    def run_plan(self, ctx: AgentContext, plan: dict[str, Any]) -> dict[str, Any]:
        """Execute a plan produced by the Router.

        A step may declare ``parallel_group``; steps with the same group
        run concurrently via asyncio.
        """
        steps = plan.get("tools_to_call") or []
        results: dict[str, Any] = {}

        # Group by parallel_group; steps without one run sequentially.
        groups: list[list[dict]] = []
        current: list[dict] = []
        last_group: str | None = None
        for s in steps:
            g = s.get("parallel_group")
            if g and g == last_group:
                current.append(s)
            else:
                if current:
                    groups.append(current)
                current = [s]
                last_group = g
        if current:
            groups.append(current)

        for group in groups:
            if len(group) == 1:
                step = group[0]
                results[step["tool"]] = self.run_step(ctx, step)
            else:
                # asyncio.to_thread for IO-bound (boto3) parallelism
                async def _run_all() -> dict[str, Any]:
                    coros = [
                        asyncio.to_thread(self.run_step, ctx, s)
                        for s in group
                    ]
                    raw = await asyncio.gather(*coros, return_exceptions=True)
                    out = {}
                    for s, r in zip(group, raw):
                        out[s["tool"]] = r if not isinstance(r, Exception) else {"error": str(r)}
                    return out

                out = asyncio.run(_run_all())
                results.update(out)

        return results
