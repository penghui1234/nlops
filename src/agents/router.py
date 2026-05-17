"""Router Agent — intent classification.

Reads the user's free-form text (after ASR if voice), and emits a
structured ``Plan`` describing which downstream Tools to call.
"""
from __future__ import annotations

import json
from typing import Any

from common.llm import LLM
from common.logging_utils import get_logger
from .base import Agent, AgentContext

logger = get_logger(__name__)


_INTENTS = (
    "health_check",       # 巡检
    "troubleshoot",       # 排障
    "execute_action",     # 修复
    "knowledge_query",    # 历史经验
    "small_talk",         # 闲聊 / 不识别
)


_SYSTEM_PROMPT = """\
You are the intent router for an AIOps platform. Reply ONLY a JSON object.
Available tools (you MUST pick from this list, no others):
  - "discovery"  : fetch metrics/logs for a service. args: {service: str, window_minutes: int}
  - "analysis"   : start a deep root-cause investigation. args: {service: str, signal: str, window_minutes: int}
  - "knowledge"  : search historical incidents. args: {op: "search", query: str, top_k: int}
  - "execution"  : invoke a write-action (REQUIRES user confirmation). args: {action: object, confirm_token: str}
  - "report"     : render an HTML diagnostic page. args: {finding: object, kind: str}

Schema:
{
  "intent": one of [health_check, troubleshoot, execute_action, knowledge_query, small_talk],
  "confidence": float in [0, 1],
  "service": string or null,           // 如果用户提到具体服务名
  "window_minutes": int,               // 关注的时间窗，默认 30
  "action": object or null,            // execute_action 时的结构化动作
  "tools_to_call": array of step objects [{tool, args}]  // tool MUST be one of the names above
}

Examples:
- 用户说"系统怎么样" -> intent=health_check, tools_to_call=[{"tool":"discovery","args":{"service":"all","window_minutes":30}},{"tool":"report","args":{"kind":"diagnostic"}}]
- 用户说"X 服务为什么慢" -> intent=troubleshoot, tools_to_call=[{"tool":"discovery","args":{"service":"X","window_minutes":30}},{"tool":"analysis","args":{"service":"X","signal":"latency"}},{"tool":"report","args":{"kind":"diagnostic"}}]

Use Chinese for any prose fields. Keep keys English."""


class RouterAgent(Agent):
    name = "router"
    description = "Classify user intent and produce an execution plan."

    def __init__(self, llm: LLM | None = None) -> None:
        self.llm = llm or LLM()

    def run(self, ctx: AgentContext, query: str = "") -> dict[str, Any]:
        plan = self.llm.complete_json(
            prompt=query,
            system=_SYSTEM_PROMPT,
            schema_hint={"intent": "...", "tools_to_call": [{"tool": "...", "args": {}}]},
        )
        if plan.get("intent") not in _INTENTS:
            logger.warning("router.unknown_intent", extra={"plan": plan, "trace_id": ctx.trace_id})
            plan["intent"] = "small_talk"
            plan["confidence"] = 0.0
        logger.info(
            "router.plan",
            extra={
                "trace_id": ctx.trace_id,
                "intent": plan.get("intent"),
                "confidence": plan.get("confidence"),
            },
        )
        return plan
