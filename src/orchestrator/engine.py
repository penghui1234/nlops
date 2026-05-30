"""NLOps orchestration engine — built on **real** Strands Agents SDK.

Why this matters (vs the previous custom mini-engine):
  * Strands handles intent routing internally, so we can drop the bespoke
    Router agent — the LLM picks tools by description.
  * Native multi-tool / multi-step support, including parallel execution.
  * Pluggable model providers (Bedrock / Anthropic / Gemini / Ollama / ...).
  * MCP-server compatibility built in (we keep that for v2).

Public API kept stable so handlers/api_handler.py only changes minimally:
  >>> orch = build_default()
  >>> orch.run(ctx, user_text) -> {"text": ..., "tool_calls": [...]}

Backward-compat helpers ``run_step`` / ``run_plan`` remain as thin shims
that route through ``run()`` so existing tests still pass.
"""
from __future__ import annotations

import contextvars
import json
import os
from typing import Any

from agents.base import AgentContext
from agents.discovery import DiscoveryAgent
from agents.analysis import AnalysisAgent
from agents.knowledge import KnowledgeAgent
from agents.execution import ExecutionAgent
from agents.report import ReportAgent
from common.audit import Audit
from common.logging_utils import get_logger

logger = get_logger(__name__)

AUDIT = Audit()
_BEDROCK_MODEL_ID = os.getenv("BEDROCK_MODEL_ID", "amazon.nova-pro-v1:0")

# ContextVar so module-level @tool functions can access per-request ctx
# without rebuilding the Strands Agent on every request.
_CURRENT_CTX: contextvars.ContextVar[AgentContext] = contextvars.ContextVar("nlops_ctx")


def _ctx() -> AgentContext:
    """Get the current AgentContext (set by NLOpsStrandsAgent.run)."""
    return _CURRENT_CTX.get()


# ============================================================
# Strands tools — module-level so the SDK can introspect them.
# Each tool delegates to the existing agent classes for business logic.
# ============================================================

# Lazy import of Strands so import-time errors are clearer in tests.
try:
    from strands import Agent as StrandsAgent
    from strands import tool
    from strands.models import BedrockModel
    _STRANDS_AVAILABLE = True
except ImportError as exc:  # pragma: no cover
    logger.warning("strands.import_failed_using_fallback", extra={"err": str(exc)})
    _STRANDS_AVAILABLE = False
    StrandsAgent = None
    BedrockModel = None
    def tool(fn=None, **_):  # noqa: ARG001 - decorator stub
        def _wrap(f):
            return f
        return _wrap if fn is None else fn


@tool
def discover_service(service: str, window_minutes: int = 30) -> str:
    """Fetch current metrics, logs, and topology for an AWS service.

    Use this when the user asks "how is X service" / "X 服务怎么样" / general health checks.
    Returns a summary from AWS DevOps Agent (or CloudWatch fallback).

    Args:
        service: Name of the AWS service (e.g. 'order-service', 'payment-api').
        window_minutes: Lookback window in minutes (default 30).
    """
    ctx = _ctx()
    result = DiscoveryAgent().run(ctx, service=service, window_minutes=window_minutes)
    return json.dumps(result, ensure_ascii=False, default=str)


@tool
def deep_investigate(service: str, signal: str = "") -> str:
    """Start a deep root-cause investigation via AWS DevOps Agent (5-15 min, async).

    Use this when the user asks "why is X slow / failing" / "X 为什么慢" — questions
    that need RCA rather than a metrics summary.

    Args:
        service: Affected service name.
        signal: Specific signal (e.g. 'latency', 'errors').
    """
    ctx = _ctx()
    result = AnalysisAgent().run(ctx, service=service, signal=signal)
    return json.dumps(result, ensure_ascii=False, default=str)


@tool
def search_knowledge(query: str, top_k: int = 3) -> str:
    """Search historical incidents and runbooks via Bedrock Knowledge Base.

    Use this when the user asks "上次类似问题怎么解决" / "历史经验" / for past incidents.

    Args:
        query: Natural-language search query.
        top_k: Maximum results (default 3).
    """
    ctx = _ctx()
    result = KnowledgeAgent().search(ctx, query=query, top_k=top_k)
    return json.dumps(result, ensure_ascii=False, default=str)


@tool
def render_report(finding_json: str, kind: str = "diagnostic") -> str:
    """Render a structured finding as an HTML diagnostic page in S3.

    Call this AFTER deep_investigate / discover_service when you want to give
    the user a sharable URL.

    Args:
        finding_json: JSON string describing the finding (root_cause / fix_steps / evidence).
        kind: Report type (diagnostic | summary).
    """
    ctx = _ctx()
    try:
        finding = json.loads(finding_json) if isinstance(finding_json, str) else finding_json
    except json.JSONDecodeError:
        finding = {"raw": finding_json}
    result = ReportAgent().run(ctx, finding=finding, kind=kind)
    return json.dumps(result, ensure_ascii=False, default=str)


@tool
def request_execute(action_json: str, confirm_token: str) -> str:
    """Invoke a write action (ECS scale, restart, etc.) via the isolated L2 Lambda.

    REQUIRES a valid ``confirm_token`` (issued by the L1 Orchestrator after
    user confirmation). The L2 Lambda re-validates the token, the user binding,
    and the tag-bounded IAM role before any AWS API write.

    Args:
        action_json: JSON ``{"type": ..., "params": {...}}`` describing the action.
        confirm_token: Single-use token (5 min TTL) issued by L1.
    """
    ctx = _ctx()
    try:
        action = json.loads(action_json) if isinstance(action_json, str) else action_json
    except json.JSONDecodeError:
        return json.dumps({"status": "error", "error": "action_json not valid JSON"})
    result = ExecutionAgent().run(ctx, action=action, confirm_token=confirm_token)
    return json.dumps(result, ensure_ascii=False, default=str)


# ============================================================
# NLOps Strands Agent
# ============================================================

_SYSTEM_PROMPT = """\
你是 NLOps SRE Assistant —— 一个 AWS 运维智能体，由 AWS DevOps Agent 作为底层引擎驱动。

可用工具：
  • discover_service(service, window_minutes) — 取服务最近指标/日志/拓扑
  • deep_investigate(service, signal)        — 启动 DOA 深度根因分析（5-15min）
  • search_knowledge(query, top_k)            — 检索历史事件/Runbook
  • render_report(finding_json, kind)         — 生成 HTML 诊断书
  • request_execute(action_json, confirm_token) — 执行写操作（必须有 token）

工作流：
  0. 【必做】收到排障/分析类问题时，先调 search_knowledge 查是否有历史相似事件。如果命中（relevance > 0.7），直接引用历史方案回答，不再调 deep_investigate。
  1. 用户问"X 怎么样" → 调 discover_service
  2. 用户问"X 为什么慢" → 先 search_knowledge → 未命中再调 deep_investigate
  3. 用户问"上次类似问题" → 调 search_knowledge
  4. 完成分析后 → 调 render_report 给用户一个 URL
  5. 写操作 → 用户必须先看 confirm_token 并主动确认

回复规范：
  • 用用户的语言（中文/英文）
  • 保持简洁，每条回复不要太长
  • 写操作前一定要展示风险并等待 confirm_token
"""


class NLOpsStrandsAgent:
    """NLOps orchestrator backed by Strands Agents SDK.

    A single agent instance handles all chat / mcp-trigger requests. The
    per-request ``AgentContext`` is propagated to tools through a contextvar
    so we don't rebuild the Strands Agent on every Lambda invocation.
    """

    def __init__(self) -> None:
        self.audit = AUDIT
        if not _STRANDS_AVAILABLE:
            self._agent = None
            return

        model = BedrockModel(
            model_id=_BEDROCK_MODEL_ID,
            temperature=0.2,
            streaming=False,  # Lambda doesn't benefit much; clearer logs
        )
        self._agent = StrandsAgent(
            model=model,
            tools=[
                discover_service,
                deep_investigate,
                search_knowledge,
                render_report,
                request_execute,
            ],
            system_prompt=_SYSTEM_PROMPT,
        )
        # Expose tool registry for legacy callers (orchestrator.tools)
        self.tools = {
            "discovery": DiscoveryAgent(),
            "analysis": AnalysisAgent(),
            "knowledge": KnowledgeAgent(),
            "execution": ExecutionAgent(),
            "report": ReportAgent(),
        }

    # ------------------------------------------------------------------ #
    def run(self, ctx: AgentContext, query: str) -> dict[str, Any]:
        """Run the Strands Agent for a single user query.

        Returns ``{"text", "agent_result", "trace_id"}``.
        """
        if self._agent is None:
            raise RuntimeError("Strands SDK not available; install strands-agents")

        token = _CURRENT_CTX.set(ctx)
        try:
            result = self._agent(query)
            text = self._extract_text(result)
            self.audit.log(
                ctx.trace_id, "Strands", "agent.run", "ok",
                {"query_preview": query[:120], "reply_len": len(text)},
            )
            return {
                "text": text,
                "agent_result": str(result)[:2000],
                "trace_id": ctx.trace_id,
                "engine": "strands-agents",
                "model": _BEDROCK_MODEL_ID,
            }
        except Exception as exc:
            logger.exception("strands.run_failed", extra={"trace_id": ctx.trace_id})
            self.audit.log(
                ctx.trace_id, "Strands", "agent.run", "error",
                {"err": str(exc)[:500]},
            )
            return {
                "text": f"⚠️ NLOps 调用失败: {exc}",
                "error": str(exc),
                "trace_id": ctx.trace_id,
            }
        finally:
            _CURRENT_CTX.reset(token)

    # ------------------------------------------------------------------ #
    @staticmethod
    def _extract_text(agent_result: Any) -> str:
        """Strands AgentResult shape varies by version; be defensive."""
        if hasattr(agent_result, "message"):
            msg = agent_result.message
            if isinstance(msg, str):
                return msg
            if isinstance(msg, dict):
                content = msg.get("content")
                if isinstance(content, list):
                    return "".join(
                        b.get("text", "") for b in content if isinstance(b, dict)
                    )
                if isinstance(content, str):
                    return content
        if hasattr(agent_result, "content"):
            return str(agent_result.content)
        return str(agent_result)

    # ------------------------------------------------------------------ #
    # Backward-compat: old api_handler called .run_step(router) + .run_plan
    # We collapse both into .run() since Strands does its own routing.
    # ------------------------------------------------------------------ #
    def run_step(self, ctx: AgentContext, step: dict[str, Any]) -> dict[str, Any]:
        tool_name = step.get("tool", "")
        args = step.get("args") or {}
        if tool_name == "router":
            # Stash the query so run_plan can pick it up
            return {"_query": args.get("query", ""), "intent": "strands_routed"}
        # Direct tool invocation (legacy path)
        agent = self.tools.get(tool_name)
        if not agent:
            return {"error": f"unknown tool: {tool_name}"}
        return agent.run(ctx, **args)

    def run_plan(self, ctx: AgentContext, plan: dict[str, Any]) -> dict[str, Any]:
        query = plan.get("_query") or plan.get("query")
        if not query:
            return {"warning": "no query"}
        out = self.run(ctx, query)
        return {"strands": out}


# Module-level singleton (Lambda warm container reuse)
_INSTANCE: NLOpsStrandsAgent | None = None


def build_default() -> NLOpsStrandsAgent:
    """Return the cached NLOpsStrandsAgent singleton."""
    global _INSTANCE
    if _INSTANCE is None:
        _INSTANCE = NLOpsStrandsAgent()
    return _INSTANCE


# Legacy alias (orchestrator.engine.Orchestrator was the old class name)
Orchestrator = NLOpsStrandsAgent
