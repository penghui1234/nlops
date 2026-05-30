"""L1 Orchestrator Lambda — single entry for all NLOps traffic.

After the v3 merge (方案 B), this Lambda hosts:
  • POST /chat /voice /webhook                    (chat path — IM / Quick / voice)
  • POST /mcp /mcp-public /mcp-quick /sse /message (MCP path — Quick Desktop / DOA)
  • GET  /sse /mcp-public                         (MCP SSE handshake)
  • EventBridge events (source=aws.aidevops)      (DOA investigation completion)

Routing is done by ``handler()`` based on event shape:
  - event.source == "aws.aidevops" → eventbridge_handler
  - path startswith /mcp or /sse or /message → mcp_handler
  - otherwise → _chat_flow (Strands Agents SDK driven)

Write actions are still isolated in L2 ExecutionFn (cross-Lambda invoke).
"""
from __future__ import annotations

import json
import os
import uuid
from typing import Any

from agents.base import AgentContext
from common.audit import Audit
from common.logging_utils import get_logger
from common.session import SessionStore
from orchestrator.factory import build_default

logger = get_logger(__name__)

# Build orchestrator once per warm container (Strands Agent + Bedrock client)
ORCH = build_default()
SESSIONS = SessionStore()
AUDIT = Audit()


# ============================================================
# Top-level router — distinguishes EventBridge / MCP / chat
# ============================================================
def handler(event: dict, context) -> dict:
    """Single entry handler. Routes by event shape."""
    # 1. EventBridge event (DOA investigation completion etc.)
    if event.get("source") == "aws.aidevops":
        from handlers.eventbridge_handler import handler as eb_handler
        return eb_handler(event, context)

    # 2. API Gateway proxy event — branch by path
    path = (event.get("path") or event.get("resource") or "").lower()
    if path.startswith("/mcp") or path in ("/sse", "/message") or "/sse" in path or "/message" in path:
        from handlers.mcp_handler import handler as mcp_h
        return mcp_h(event, context)

    # 3. Default — chat / voice / webhook
    return _chat_flow(event, context)


# ============================================================
# Chat / Voice / Webhook flow (Strands Agents SDK)
# ============================================================
def _chat_flow(event: dict, context) -> dict:
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

    # ---- ASR if voice (Nova Sonic) ---------------------------------- #
    user_text: str = body.get("text", "") or body.get("message", "")
    if path.endswith("/voice") and body.get("audio_b64"):
        try:
            from voice.nova_sonic import NovaSonic
            user_text = NovaSonic().transcribe_b64(body["audio_b64"])
            logger.info("api.asr_done", extra={"trace_id": trace_id, "len": len(user_text)})
        except Exception as exc:  # noqa
            logger.warning("api.asr_failed", extra={"err": str(exc), "trace_id": trace_id})

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

    AUDIT.log(trace_id, "Entry", "received", "ok",
              {"channel": channel, "len": len(user_text)})

    # ---- Strands Agent does the heavy lifting ----------------------- #
    try:
        result = ORCH.run(ctx, user_text)
    except Exception as exc:
        logger.exception("api.strands_failed", extra={"trace_id": trace_id})
        AUDIT.log(trace_id, "Entry", "strands", "error", {"err": str(exc)})
        return _resp(500, {"error": str(exc), "trace_id": trace_id})

    reply_text = result.get("text", "")
    session.append("assistant", reply_text)
    SESSIONS.save(session)

    return _resp(200, {
        "trace_id": trace_id,
        "session_id": session.session_id,
        "reply": {"text": reply_text},
        "engine": result.get("engine", "strands-agents"),
        "model": result.get("model"),
    })


# ============================================================
# Helpers
# ============================================================
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


def _resp(status: int, body: dict) -> dict:
    return {
        "statusCode": status,
        "headers": {
            "Content-Type": "application/json",
            "Access-Control-Allow-Origin": "*",
        },
        "body": json.dumps(body, ensure_ascii=False),
    }
