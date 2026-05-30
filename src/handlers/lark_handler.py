"""Lark (飞书) event subscription handler for @-mention bot.

Handles events from Lark's event subscription:
  - url_verification (initial setup challenge)
  - im.message.receive_v1 (user sends or @-mentions the bot)

⚠️ Important: Lark requires HTTP 200 within 3 seconds, else it retries.
Since DOA chat / start_investigation can take 5-30s, we use a two-stage flow:

  Stage 1 (sync, < 1s):
    - Receive event from Lark
    - If url_verification: respond directly with challenge
    - Otherwise: invoke self async with event payload
    - Return 200 OK immediately

  Stage 2 (async, processed in background Lambda):
    - Triggered via lambda.invoke (InvocationType=Event)
    - Process message, call DOA, reply via Lark API
"""
from __future__ import annotations

import json
import os
import re
from typing import Any

import boto3

from common.logging_utils import get_logger
from tools.devops_agent import DevOpsAgent
from tools.lark_app import LarkApp

logger = get_logger(__name__)

_doa = DevOpsAgent()
_lark_app = LarkApp()
_lambda = boto3.client("lambda", region_name=os.getenv("AWS_REGION", "us-east-1"))
_SELF_FN = os.getenv("AWS_LAMBDA_FUNCTION_NAME", "")


def handler(event: dict, context) -> dict:
    """Entry point for /lark-event POST.

    Two modes:
      1. Sync HTTP request from API Gateway (Lark webhook)
         → ack fast (< 3s), kick off async self-invoke for processing
      2. Async invocation from self (event["_async_lark"] == True)
         → actually process the message and reply
    """
    # Mode 2: self-invoked async — do the heavy work
    if event.get("_async_lark") is True:
        return _process_async(event)

    # Mode 1: sync HTTP — ack fast and kick off async
    body = _parse_body(event)

    # === 1. URL Verification (initial setup) ===
    if body.get("type") == "url_verification":
        challenge = body.get("challenge", "")
        logger.info("lark.url_verification", extra={"challenge_len": len(challenge)})
        return {
            "statusCode": 200,
            "headers": {"Content-Type": "application/json"},
            "body": json.dumps({"challenge": challenge}),
        }

    # === 2. Encrypted event (if Encrypt Key configured) ===
    if "encrypt" in body:
        logger.warning("lark.encrypted_event_received")
        return _resp(400, {"error": "encryption not configured"})

    # === 3. Event callback — async dispatch ===
    schema = body.get("schema", "")
    header = body.get("header", {})
    event_type = header.get("event_type", "")
    event_id = header.get("event_id", "")

    logger.info("lark.event_received", extra={
        "schema": schema, "event_type": event_type, "event_id": event_id,
    })

    if event_type != "im.message.receive_v1":
        return _resp(200, {"status": "ignored", "event_type": event_type})

    # De-dup: Lark may retry. Use event_id (deterministic per delivery).
    # We use a simple per-container in-memory cache; for cross-container dedup
    # use DynamoDB.
    if _seen_event(event_id):
        logger.info("lark.duplicate_event_skipped", extra={"event_id": event_id})
        return _resp(200, {"status": "duplicate", "event_id": event_id})

    # Async self-invoke for processing
    try:
        if _SELF_FN:
            _lambda.invoke(
                FunctionName=_SELF_FN,
                InvocationType="Event",  # async, non-blocking
                Payload=json.dumps({"_async_lark": True, "lark_body": body}).encode(),
            )
            logger.info("lark.async_dispatched", extra={"event_id": event_id})
    except Exception as exc:
        logger.exception("lark.dispatch_failed")

    # Return 200 immediately (within Lark's 3s window)
    return _resp(200, {"status": "queued", "event_id": event_id})


# ============================================================ #
# Per-container event_id cache (in-memory, ~5 min sliding window)
# ============================================================ #
_seen: dict[str, float] = {}
_SEEN_TTL_SEC = 300


def _seen_event(event_id: str) -> bool:
    """Return True if event_id was seen recently. Mark it seen otherwise."""
    if not event_id:
        return False
    import time
    now = time.time()
    # Garbage collect old entries (cheap, runs each call)
    expired = [k for k, t in _seen.items() if now - t > _SEEN_TTL_SEC]
    for k in expired:
        _seen.pop(k, None)
    if event_id in _seen:
        return True
    _seen[event_id] = now
    return False


# ============================================================ #
def _process_async(invoke_event: dict) -> dict:
    """Run in a separate Lambda invocation (no time pressure for 3s ack)."""
    body = invoke_event.get("lark_body", {})
    return _handle_message(body)


# ============================================================ #
def _handle_message(body: dict) -> dict:
    """Process incoming message event."""
    event_data = body.get("event", {})
    message = event_data.get("message", {})

    msg_id = message.get("message_id", "")
    msg_type = message.get("message_type", "")
    chat_type = message.get("chat_type", "")  # group | p2p
    chat_id = message.get("chat_id", "")
    content_str = message.get("content", "{}")

    # Only handle text messages for v4 MVP
    if msg_type != "text":
        return _resp(200, {"status": "ignored", "reason": f"msg_type={msg_type}"})

    try:
        content = json.loads(content_str)
        raw_text = content.get("text", "")
    except json.JSONDecodeError:
        return _resp(200, {"status": "ignored", "reason": "invalid content"})

    # Strip @-mention markers like @_user_1
    cleaned = re.sub(r"@_user_\d+\s*", "", raw_text).strip()
    cleaned = re.sub(r"@\S+\s*", "", cleaned).strip()

    if not cleaned:
        return _resp(200, {"status": "ignored", "reason": "empty after strip"})

    logger.info("lark.message_parsed",
                extra={"chat_type": chat_type, "preview": cleaned[:80]})

    # Process the question
    reply_text = _process_question(cleaned)

    # Reply to the message
    if msg_id:
        result = _lark_app.reply_message(msg_id, text=reply_text)
        logger.info("lark.replied", extra={"chat_id": chat_id, "result_code": result.get("code")})
    else:
        result = _lark_app.send_message(chat_id, text=reply_text)

    return _resp(200, {"status": "ok", "reply_len": len(reply_text)})


# ============================================================ #
def _process_question(question: str) -> str:
    """Decide how to handle the user's question and return a reply.

    Heuristic intent routing:
      - greeting / "you can do" / "list tools" → tool list reply
      - "诊断书" / "报告" / "task_id ..." → get_html_report URL
      - "调查" / "深度" / "为什么" / "排查" → start_investigation
      - everything else → DOA chat (with safe fallback)
    """
    q_lower = question.lower()

    # Intent: greeting / capability listing
    greeting_kw = ["你好", "hello", "hi ", "在吗", "在不", "你能", "可以做",
                   "做什么", "做啥", "怎么用", "help", "命令", "帮助"]
    if any(kw in q_lower for kw in greeting_kw) and len(question) < 30:
        return (
            "👋 你好！我是 NLOps 智能运维助手,基于 AWS DevOps Agent。\n\n"
            "我可以帮你做这些事:\n\n"
            "🔍 **启动深度调查**\n"
            "   说: \"@NLOps 帮我调查 demo-api 为什么慢\"\n\n"
            "📊 **查看诊断书**\n"
            "   说: \"@NLOps 看看 task_id xxx-xxx 的诊断书\"\n\n"
            "💬 **直接问诊**\n"
            "   说: \"@NLOps demo-api 现在什么情况\"\n\n"
            "🚨 **告警闭环**\n"
            "   CW Alarm 触发后自动调查,完成后推送本群\n\n"
            "试着 @ 我吧!"
        )

    # Intent: extract task_id and return HTML report URL
    m = re.search(r"([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})",
                  question)
    if m and any(kw in question for kw in ["诊断书", "报告", "html"]):
        try:
            from mcp_server.v4_tools import get_html_report
            result = get_html_report(task_id=m.group(1))
            if isinstance(result, dict) and result.get("html_url"):
                return f"📊 诊断书已生成:\n{result['html_url']}"
            return f"⚠️ 生成失败: {result}"
        except Exception as exc:
            logger.exception("lark.report_failed")
            return f"⚠️ 生成诊断书时出错: {str(exc)[:200]}"

    # Intent: start investigation (deep dive)
    if any(kw in question for kw in ["调查", "深度", "排查", "为什么", "为啥",
                                       "怎么回事", "investigation"]):
        try:
            title = question[:200]
            task_id = _doa.start_investigation(
                title=title,
                description=question[:4000],
                priority="MEDIUM",
            )
            if task_id and not task_id.startswith("err-"):
                return (
                    f"🔍 已启动深度调查\n\n"
                    f"任务 ID: `{task_id}`\n"
                    f"预计 5-15 分钟完成\n\n"
                    f"完成后将自动推送诊断书到本群。\n"
                    f"你也可以稍后 @ 我说 \"生成 task_id {task_id} 的诊断书\" 立即查看。"
                )
            return f"⚠️ 调查启动失败: {task_id}"
        except Exception as exc:
            logger.exception("lark.start_investigation_failed")
            return f"⚠️ 调查启动失败: {str(exc)[:200]}"

    # Default: DOA chat with safe fallback
    try:
        answer = _doa.chat(question, user_id="lark-bot")
        # If DOA returned its mock fallback (empty real answer), redirect to investigation
        if "[mock" in answer or "mock fallback" in answer.lower():
            return (
                "⚠️ DOA Chat 暂时无法直接回答这个问题。\n\n"
                "建议改用 **深度调查** 模式:\n"
                f"@NLOps 帮我调查: {question[:80]}"
            )
        if len(answer) > 1500:
            answer = answer[:1500] + "...\n\n（回复过长已截断）"
        return f"💬 {answer}"
    except Exception as exc:
        logger.exception("lark.chat_failed")
        return (
            "⚠️ 直接问诊暂时不可用 (DOA Agent Space 当前无关联服务)。\n\n"
            "建议改用 **深度调查** 模式:\n"
            f"@NLOps 帮我调查: {question[:80]}"
        )


# ============================================================ #
def _parse_body(event: dict) -> dict:
    body = event.get("body")
    if isinstance(body, str):
        try:
            return json.loads(body)
        except json.JSONDecodeError:
            return {}
    return body or {}


def _resp(status: int, body: dict) -> dict:
    return {
        "statusCode": status,
        "headers": {"Content-Type": "application/json"},
        "body": json.dumps(body, ensure_ascii=False),
    }
