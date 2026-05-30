"""NLOps v4 Orchestrator Lambda — single entry, 4 routes.

Routing logic (handler dispatches by event shape):
  • event.source == "aws.devopsagent" → eventbridge handler
    (DOA Investigation Completed → render HTML + send SES email)
  • path /chat or /webhook            → chat handler (forwards to DOA)
  • path /mcp* or /sse or /message    → MCP handler (5 v4 tools)
  • path /webhook-incoming            → CW Alarm webhook → forward to DOA
                                       webhook with HMAC signature

v4 simplifications vs v3:
  - No Strands SDK
  - No L2 Execution Lambda (SSM Runbook replaces it)
  - 5 MCP tools instead of 21
  - Direct DOA chat (no intermediate routing layer)
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import time
import uuid
from datetime import datetime, timezone
from typing import Any

import boto3
import urllib.request
import urllib.error

from common.audit import Audit
from common.logging_utils import get_logger
from mcp_server.v4_tools import server as MCP_SERVER  # registers all 5 tools
from report.generator import ReportGenerator
from tools.devops_agent import DevOpsAgent
from tools.lark_bot import LarkBot

logger = get_logger(__name__)
AUDIT = Audit()

_REGION = os.getenv("AWS_REGION", "us-east-1")
_DOA_WEBHOOK_URL = os.getenv("DOA_WEBHOOK_URL", "").strip()
_DOA_WEBHOOK_SECRET = os.getenv("DOA_WEBHOOK_SECRET", "").strip()
_ALERT_EMAIL_FROM = os.getenv("ALERT_EMAIL_FROM", "")
_ALERT_EMAIL_TO = os.getenv("ALERT_EMAIL_TO", "")

_doa = DevOpsAgent()
_report = ReportGenerator()
_lark = LarkBot()
_ses = boto3.client("ses", region_name=_REGION)


# ============================================================ #
# Top-level router
# ============================================================ #
def handler(event: dict, context) -> dict:
    """Single entry. Routes by event shape."""
    # 1. EventBridge event from DOA
    src = event.get("source", "")
    if src in ("aws.devopsagent", "aws.aidevops"):  # GA + preview names
        return _handle_doa_event(event)

    # 2. SNS event (CW Alarm via SNS subscription)
    if "Records" in event and event["Records"]:
        first_rec = event["Records"][0]
        if first_rec.get("EventSource") == "aws:sns" or first_rec.get("Sns"):
            return _handle_alarm_webhook(event)

    # 3. API Gateway proxy event — branch by path
    path = (event.get("path") or event.get("resource") or "").lower()
    method = (event.get("httpMethod") or "").upper()

    if path.startswith("/mcp") or "/sse" in path or "/message" in path:
        return _handle_mcp(event)

    if path == "/webhook-incoming" or "webhook-incoming" in path:
        return _handle_alarm_webhook(event)

    if path == "/chat" or "chat" in path or "webhook" in path:
        return _handle_chat(event)

    # Default — health probe
    return _resp(200, {"service": "nlops-v4", "status": "ok",
                       "tools": list(MCP_SERVER._tools.keys())})


# ============================================================ #
# Route 1: /chat — direct DOA chat passthrough
# ============================================================ #
def _handle_chat(event: dict) -> dict:
    trace_id = f"trc-chat-{uuid.uuid4().hex[:12]}"
    body = _parse_body(event)
    user_text = (body.get("text") or body.get("message") or "").strip()
    user_id = body.get("user_id", "anonymous")

    if not user_text:
        return _resp(400, {"error": "empty input", "trace_id": trace_id})

    AUDIT.log(trace_id, "Chat", "received", "ok",
              {"len": len(user_text), "user_id": user_id})

    answer = _doa.chat(user_text, user_id=user_id)

    AUDIT.log(trace_id, "Chat", "answered", "ok", {"reply_len": len(answer)})

    return _resp(200, {
        "trace_id": trace_id,
        "reply": {"text": answer},
        "engine": "aws-devops-agent",
    })


# ============================================================ #
# Route 2: /mcp — MCP JSON-RPC server
# ============================================================ #
def _handle_mcp(event: dict) -> dict:
    method = (event.get("httpMethod") or "").upper()
    headers_in = {k.lower(): v for k, v in (event.get("headers") or {}).items()}
    accept = (headers_in.get("accept") or "").lower()
    session_id = headers_in.get("mcp-session-id") or f"sess-{uuid.uuid4().hex[:12]}"

    cors = {
        "Access-Control-Allow-Origin": "*",
        "Access-Control-Allow-Headers": "Content-Type, Authorization, Mcp-Session-Id",
        "Access-Control-Allow-Methods": "POST, GET, OPTIONS",
        "Mcp-Session-Id": session_id,
    }

    if method == "OPTIONS":
        return {"statusCode": 200, "headers": cors, "body": ""}

    if method == "GET":
        # SSE handshake or info probe
        if "text/event-stream" in accept or "/sse" in (event.get("path") or "").lower():
            return {
                "statusCode": 200,
                "headers": {**cors, "Content-Type": "text/event-stream",
                            "Cache-Control": "no-cache"},
                "body": "event: endpoint\ndata: /message\n\n",
            }
        return {
            "statusCode": 200,
            "headers": {**cors, "Content-Type": "application/json"},
            "body": json.dumps({
                "jsonrpc": "2.0",
                "result": {
                    "serverInfo": {"name": "NLOps v4", "version": "4.0.0"},
                    "protocolVersion": "2024-11-05",
                    "tools_count": len(MCP_SERVER._tools),
                },
            }),
        }

    # POST — JSON-RPC
    body = event.get("body")
    if isinstance(body, str):
        try:
            body = json.loads(body)
        except json.JSONDecodeError:
            return {"statusCode": 400, "headers": cors,
                    "body": json.dumps({"error": "invalid json"})}
    body = body or {}

    response = MCP_SERVER.handle(body)

    if response is None:
        return {"statusCode": 202, "headers": cors, "body": ""}

    if "text/event-stream" in accept:
        sse = f"event: message\ndata: {json.dumps(response, ensure_ascii=False)}\n\n"
        return {"statusCode": 200,
                "headers": {**cors, "Content-Type": "text/event-stream"},
                "body": sse}

    return {"statusCode": 200,
            "headers": {**cors, "Content-Type": "application/json"},
            "body": json.dumps(response, ensure_ascii=False)}


# ============================================================ #
# Route 3: /webhook-incoming — CW Alarm → forward to DOA Webhook (HMAC)
# ============================================================ #
def _handle_alarm_webhook(event: dict) -> dict:
    """Forward CloudWatch alarm to DOA webhook with HMAC signature.

    Reference: AWS End-to-End Agentic SRE blog.
    Schema for DOA webhook:
        {eventType: 'incident', incidentId, action, priority,
         title, description, timestamp, service, data}
    """
    trace_id = f"trc-wh-{uuid.uuid4().hex[:12]}"
    body = _parse_body(event)

    # CloudWatch sends via SNS -> Lambda; sometimes nested
    if "Records" in body:
        # SNS event from raw event
        sns_msg = body["Records"][0].get("Sns", {}).get("Message", "{}")
        try:
            body = json.loads(sns_msg)
        except json.JSONDecodeError:
            pass
    elif "Records" in event:
        # Direct SNS event (Lambda invoked by SNS subscription)
        sns_msg = event["Records"][0].get("Sns", {}).get("Message", "{}")
        try:
            body = json.loads(sns_msg)
        except json.JSONDecodeError:
            body = {"raw": sns_msg}

    alarm_name = (body.get("AlarmName") or body.get("alarmName")
                  or body.get("title") or "Unknown Alarm")
    state = (body.get("NewStateValue") or body.get("state") or "ALARM")
    reason = body.get("NewStateReason") or body.get("reason", "")
    region = body.get("Region") or _REGION

    if not _DOA_WEBHOOK_URL:
        # No DOA webhook configured — fall back to creating Investigation directly
        logger.warning("webhook.no_doa_url_creating_investigation_directly")
        task_id = _doa.start_investigation(
            title=f"[{state}] {alarm_name}",
            description=f"Alarm: {alarm_name}\nState: {state}\nReason: {reason}\nRegion: {region}",
            priority="HIGH" if state == "ALARM" else "MEDIUM",
        )
        AUDIT.log(trace_id, "Webhook", "direct_investigation", "ok",
                  {"task_id": task_id, "alarm": alarm_name})
        return _resp(200, {"trace_id": trace_id, "task_id": task_id,
                           "method": "direct_investigation"})

    # Build DOA webhook payload (per blog spec)
    payload = {
        "eventType": "incident",
        "incidentId": f"cw-{uuid.uuid4().hex[:12]}",
        "action": "created",
        "priority": "HIGH" if state == "ALARM" else "MEDIUM",
        "title": f"[{state}] {alarm_name}",
        "description": reason,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "service": body.get("service") or alarm_name.split("-")[0],
        "data": body,
    }

    payload_json = json.dumps(payload, ensure_ascii=False)
    timestamp = datetime.now(timezone.utc).isoformat()

    # HMAC signature
    signature = ""
    if _DOA_WEBHOOK_SECRET:
        mac = hmac.new(
            _DOA_WEBHOOK_SECRET.encode("utf-8"),
            f"{timestamp}:{payload_json}".encode("utf-8"),
            hashlib.sha256,
        )
        signature = mac.digest().hex()  # blog uses base64; sha256 hex also accepted

    req = urllib.request.Request(
        _DOA_WEBHOOK_URL,
        data=payload_json.encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "x-amzn-event-timestamp": timestamp,
            "x-amzn-event-signature": signature,
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            body_resp = resp.read().decode("utf-8")[:500]
        AUDIT.log(trace_id, "Webhook", "forwarded", "ok",
                  {"alarm": alarm_name, "incident_id": payload["incidentId"]})
        return _resp(200, {"trace_id": trace_id, "forwarded": True,
                           "incident_id": payload["incidentId"],
                           "doa_response": body_resp})
    except urllib.error.URLError as exc:
        logger.exception("webhook.forward_failed")
        AUDIT.log(trace_id, "Webhook", "forward", "error", {"err": str(exc)[:200]})
        return _resp(500, {"trace_id": trace_id, "error": str(exc)[:200]})


# ============================================================ #
# Route 4: EventBridge — DOA Investigation Completed
# ============================================================ #
def _handle_doa_event(event: dict) -> dict:
    """Render HTML report + send SES email when DOA completes."""
    trace_id = event.get("id") or f"trc-eb-{uuid.uuid4().hex[:12]}"
    detail = event.get("detail") or {}
    detail_type = event.get("detail-type", "")

    # DOA EB event structure (GA): { version, metadata: {agent_space_id, task_id,
    # execution_id}, data: {task_type, priority, status, created_at, updated_at} }
    metadata = detail.get("metadata") or {}
    data = detail.get("data") or {}

    # DEBUG: log full event structure for first time understanding
    logger.info("eb.event_dump", extra={
        "trace_id": trace_id,
        "source": event.get("source"),
        "detail_type": detail_type,
        "detail_keys": list(detail.keys()) if isinstance(detail, dict) else [],
        "detail_preview": json.dumps(detail, default=str)[:1500],
    })

    # Try many possible field names: nested metadata/data first, then flat
    task_id = (metadata.get("task_id") or metadata.get("taskId")
               or detail.get("taskId") or detail.get("investigationId")
               or detail.get("evaluationId") or detail.get("task_id")
               or detail.get("backlogTaskId") or "")
    severity = (data.get("priority") or detail.get("severity")
                or detail.get("priority") or "info").lower()
    status = (data.get("status") or detail.get("status")
              or detail.get("state") or "").upper()
    agent_space = (metadata.get("agent_space_id") or metadata.get("agentSpaceId")
                   or detail.get("agentSpaceId") or detail.get("agent_space_id")
                   or os.getenv("DOA_AGENT_SPACE_ID", ""))

    logger.info("eb.received", extra={
        "trace_id": trace_id, "detail_type": detail_type,
        "task_id": task_id, "status": status,
    })

    if status and status not in ("COMPLETED", "RESOLVED", ""):
        AUDIT.log(trace_id, "EventBridge", detail_type, "skipped",
                  {"status": status})
        return {"skipped": True, "reason": f"status={status}"}

    # Pull full investigation
    inv = _doa.get_investigation(task_id) if task_id else {}

    # Pull AI findings (the actual investigation report)
    execution_id = metadata.get("execution_id") or metadata.get("executionId") or ""
    findings = _doa.get_investigation_findings(execution_id) if execution_id else {}
    report_md = findings.get("report_md", "")
    tool_uses = findings.get("tool_uses", [])

    finding = {
        "title": ((inv.get("title") if isinstance(inv, dict) else "")
                  or data.get("title") or detail.get("title")
                  or detail_type),
        "investigation_id": task_id,
        "execution_id": execution_id,
        "severity": severity,
        "service": detail.get("service", ""),
        "report_md": report_md,            # full markdown report from DOA AI
        "tool_uses": tool_uses,            # list of AWS tools DOA used
        "root_cause": (
            # Try to extract first heading or first 800 chars of report
            (report_md.split("\n")[0][:300] if report_md else "")
            or (inv.get("description", "")[:600]
                if isinstance(inv, dict) else "")
        ),
        "operator_portal_url": (
            f"https://console.aws.amazon.com/devops-agent/spaces/"
            f"{agent_space}/tasks/{task_id}" if task_id else ""
        ),
        "timeline": inv.get("timeline", []) if isinstance(inv, dict) else [],
        "ts": int(time.time()),
    }

    # 1) Render HTML
    html_url = ""
    try:
        html_url = _report.render_and_upload(finding, kind="alert", trace_id=trace_id)
    except Exception as exc:
        logger.exception("eb.render_failed")

    # 2) Send SES email
    email_status = _send_email(finding, html_url, trace_id)

    # 3) Push to Lark (飞书) if configured
    lark_status = _send_lark(finding, html_url, trace_id)

    AUDIT.log(trace_id, "EventBridge", detail_type, "ok",
              {"task_id": task_id, "html_url": html_url,
               "email": email_status, "lark": lark_status})

    return {"status": "ok", "html_url": html_url, "email": email_status,
            "lark": lark_status, "trace_id": trace_id}


def _send_lark(finding: dict, html_url: str, trace_id: str) -> dict:
    """Push alarm closure summary to Lark group via webhook."""
    if not _lark.configured:
        return {"skipped": True, "reason": "LARK_WEBHOOK_URL not set"}

    severity = finding.get("severity", "info").upper()
    template_map = {
        "CRITICAL": "red", "HIGH": "red", "MEDIUM": "orange",
        "LOW": "yellow", "MINIMAL": "grey", "INFO": "blue",
    }
    template = template_map.get(severity, "blue")

    title = f"🚨 [{severity}] {finding.get('title', 'NLOps Alert')}"[:200]

    # Body markdown
    root_cause = finding.get("root_cause", "")[:600]
    if not root_cause and finding.get("report_md"):
        root_cause = finding.get("report_md", "").split("\n\n")[0][:600]
    if not root_cause:
        root_cause = "调查已完成,详情请查看诊断书。"

    body_md_parts = [f"**🔬 根因摘要**\n{root_cause}"]
    if finding.get("tool_uses"):
        tools_str = " · ".join(f"`{t}`" for t in finding["tool_uses"][:5])
        body_md_parts.append(f"\n**🛠️ DOA 调用的工具**\n{tools_str}")
    body_md = "\n\n".join(body_md_parts)

    # Metadata fields
    metadata = []
    if finding.get("investigation_id"):
        metadata.append(("Investigation", finding["investigation_id"][:24] + "..."))
    if finding.get("service"):
        metadata.append(("Service", finding["service"]))
    metadata.append(("时间", datetime.now(timezone.utc).strftime("%H:%M UTC")))

    # URL buttons
    buttons = []
    if html_url:
        buttons.append(("📊 查看完整诊断书", html_url))
    if finding.get("operator_portal_url"):
        buttons.append(("🔍 DOA Operator", finding["operator_portal_url"]))

    return _lark.send_card(
        title=title, body_md=body_md, template=template,
        url_buttons=buttons or None,
        metadata=metadata or None,
    )


def _send_email(finding: dict, html_url: str, trace_id: str) -> dict:
    if not _ALERT_EMAIL_FROM or not _ALERT_EMAIL_TO:
        return {"skipped": True, "reason": "email not configured"}

    subject = f"🚨 [{finding.get('severity', 'info').upper()}] {finding.get('title', 'NLOps')}"[:99]
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    text = (
        f"NLOps Alert: {finding.get('title')}\n"
        f"Severity: {finding.get('severity')}\n"
        f"Root cause: {finding.get('root_cause', '')[:500]}\n"
        f"Diagnostic: {html_url}\n"
        f"Time: {ts}\n"
    )
    html = (
        f"<html><body style='font-family:-apple-system,sans-serif;max-width:720px;margin:auto'>"
        f"<h2 style='border-bottom:2px solid #ff9900;padding-bottom:8px'>{finding.get('title')}</h2>"
        f"<p><b>Severity:</b> {finding.get('severity')}</p>"
        f"<p><b>Root cause:</b><br/>{finding.get('root_cause', '')[:1500]}</p>"
        + (f"<p><a href='{html_url}' style='background:#ff9900;color:#fff;"
           f"padding:10px 20px;text-decoration:none;border-radius:4px'>"
           f"📊 查看完整诊断书</a></p>" if html_url else "")
        + (f"<p><a href='{finding.get('operator_portal_url')}'>DevOps Agent Operator Portal</a></p>"
           if finding.get('operator_portal_url') else "")
        + f"<hr/><small>Trace: {trace_id} · {ts}</small>"
        + "</body></html>"
    )

    try:
        resp = _ses.send_email(
            Source=_ALERT_EMAIL_FROM,
            Destination={"ToAddresses": [_ALERT_EMAIL_TO]},
            Message={
                "Subject": {"Data": subject, "Charset": "UTF-8"},
                "Body": {
                    "Html": {"Data": html, "Charset": "UTF-8"},
                    "Text": {"Data": text, "Charset": "UTF-8"},
                },
            },
        )
        return {"status": "sent", "message_id": resp.get("MessageId", "")}
    except Exception as exc:
        logger.exception("ses.send_failed")
        return {"status": "error", "error": str(exc)[:200]}


# ============================================================ #
# Helpers
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
        "headers": {
            "Content-Type": "application/json",
            "Access-Control-Allow-Origin": "*",
        },
        "body": json.dumps(body, ensure_ascii=False),
    }
