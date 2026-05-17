"""L1 Orchestrator Lambda — API Gateway entry for /chat /voice /webhook.

Flow:
  1. Parse caller-channel envelope (Quick / WeCom / Feishu / Quick voice)
  2. Load or create Session (DDB)
  3. If voice payload: ASR via Nova Sonic
  4. Build Plan via Router Agent
  5. Run Plan via Orchestrator (Strands-style in-proc)
  6. If plan asks for Execution -> issue Confirm Token + return confirm card
  7. If plan finishes -> render Report -> return URL
  8. Save Session + audit
"""
from __future__ import annotations

import json
import os
import time
import uuid
from typing import Any

from agents.base import AgentContext
from common.audit import Audit
from common.logging_utils import get_logger
from common.session import SessionStore
from orchestrator.factory import build_default

logger = get_logger(__name__)

# Build orchestrator once per Lambda warm container
ORCH = build_default()
SESSIONS = SessionStore()
AUDIT = Audit()


def handler(event: dict, context) -> dict:
    """API Gateway proxy integration handler."""
    trace_id = f"trc-{uuid.uuid4()}"
    body = _parse_body(event)
    path = event.get("resource") or event.get("path", "/")
    user_id = body.get("user_id", "anonymous")
    channel = body.get("channel", _channel_from_path(path))

    session = SESSIONS.get_or_create(
        session_id=body.get("session_id"),
        user_id=user_id,
        channel=channel,
    )

    # ---- ASR if voice ------------------------------------------------- #
    user_text: str = body.get("text", "")
    if path.endswith("/voice") and body.get("audio_b64"):
        from voice.nova_sonic import NovaSonic
        user_text = NovaSonic().transcribe_b64(body["audio_b64"])
        logger.info("api.asr_done", extra={"trace_id": trace_id, "len": len(user_text)})

    if not user_text:
        return _resp(400, {"error": "empty input"})

    session.append("user", user_text)

    ctx = AgentContext(
        trace_id=trace_id,
        user_id=user_id,
        session_id=session.session_id,
        channel=channel,
        confirm_token=body.get("confirm_token"),
        user_confirmed=bool(body.get("user_confirmed")),
    )

    AUDIT.log(trace_id, "Entry", "received", "ok", {"channel": channel, "len": len(user_text)})

    # ---- Plan + execute ---------------------------------------------- #
    try:
        plan = ORCH.run_step(ctx, {"tool": "router", "args": {"query": user_text}})
        logger.info("api.plan", extra={"trace_id": trace_id, "intent": plan.get("intent")})

        results = ORCH.run_plan(ctx, plan)
    except Exception as exc:
        logger.exception("api.plan_failed", extra={"trace_id": trace_id})
        AUDIT.log(trace_id, "Entry", "plan", "error", {"err": str(exc)})
        return _resp(500, {"error": str(exc)})

    # ---- Compose response -------------------------------------------- #
    reply = _summarise(plan, results)
    session.append("assistant", reply.get("text", ""))
    SESSIONS.save(session)

    return _resp(200, {
        "trace_id": trace_id,
        "session_id": session.session_id,
        "intent": plan.get("intent"),
        "reply": reply,
        "results": results,
    })


# --------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------- #
def _parse_body(event: dict) -> dict:
    body = event.get("body")
    if isinstance(body, str):
        try:
            return json.loads(body)
        except json.JSONDecodeError:
            return {}
    return body or {}


def _channel_from_path(path: str) -> str:
    if "voice" in path:
        return "quick"
    if "webhook" in path:
        return "wecom_or_feishu"
    return "quick"


def _summarise(plan: dict, results: dict) -> dict:
    intent = plan.get("intent")
    if "report" in results and isinstance(results["report"], dict) and results["report"].get("html_url"):
        return {
            "text": f"分析完成：{plan.get('title') or intent}",
            "html_url": results["report"]["html_url"],
        }
    if "analysis" in results and results["analysis"].get("status") == "in_progress":
        return {
            "text": "我正在调用 AWS DevOps Agent 做深度调查，预计 5-15 分钟出完整报告。完成后会推送到此对话。",
            "investigation_id": results["analysis"]["investigation_id"],
        }
    if "discovery" in results:
        return {
            "text": "已获取最新指标和健康状况。",
            "findings": results["discovery"].get("findings"),
        }
    return {"text": "已收到，正在处理。"}


def _resp(status: int, body: dict) -> dict:
    return {
        "statusCode": status,
        "headers": {"Content-Type": "application/json"},
        "body": json.dumps(body, ensure_ascii=False),
    }
