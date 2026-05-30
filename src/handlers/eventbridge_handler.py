"""L3 (now in-merged into L1 OrchestratorFn) — handles aws.aidevops events.

Subscribed via EventBridge rule:
  source        = aws.aidevops
  detail-type   = Investigation Completed | Investigation Updated | Evaluation Completed

For each completed investigation we:
  1. Pull full detail via DOA GetBacklogTask
  2. Render an HTML diagnostic page → S3 (Presigned URL)
  3. Render an HTML alert email → SES SendEmail (HTML)
  4. Sink to Bedrock KB for future similarity search
  5. Audit log
"""
from __future__ import annotations

import json
import os
import time
import uuid
from datetime import datetime, timezone
from typing import Any

import boto3
from jinja2 import Environment, FileSystemLoader, select_autoescape

from common.audit import Audit
from common.logging_utils import get_logger
from report.generator import ReportGenerator
from tools.devops_agent import DevOpsAgentTool

logger = get_logger(__name__)
_REGION = os.getenv("AWS_REGION", "us-east-1")
_NOTIFY_TOPIC = os.getenv("NOTIFY_TOPIC_ARN", "")
_ALERT_EMAIL_FROM = os.getenv("ALERT_EMAIL_FROM", "")
_ALERT_EMAIL_TO = os.getenv("ALERT_EMAIL_TO", "")

# Cached at module level (warm container reuse)
DOA = DevOpsAgentTool()
REPORT = ReportGenerator()
AUDIT = Audit()
_sns = boto3.client("sns", region_name=_REGION) if _NOTIFY_TOPIC else None
_ses = boto3.client("ses", region_name=_REGION)

# Email Jinja2 env (separate from the diagnostic-page template loader)
_TEMPLATE_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "report", "templates",
)
_jinja = Environment(
    loader=FileSystemLoader(_TEMPLATE_DIR),
    autoescape=select_autoescape(["html"]),
)


def handler(event: dict, context) -> dict:
    trace_id = event.get("id") or f"trc-eb-{uuid.uuid4()}"
    detail = event.get("detail") or {}
    detail_type = event.get("detail-type", "")

    inv_id = detail.get("investigationId") or detail.get("evaluationId") or detail.get("taskId") or ""
    severity = (detail.get("severity") or "info").lower()
    status = (detail.get("status") or "").upper()

    logger.info(
        "eb.received",
        extra={
            "trace_id": trace_id,
            "detail_type": detail_type,
            "inv_id": inv_id,
            "severity": severity,
            "status": status,
        },
    )

    # Skip non-completed events
    if status and status not in ("COMPLETED", "RESOLVED"):
        AUDIT.log(trace_id, "EventBridge", detail_type, "skipped",
                  {"status": status})
        return {"skipped": True, "reason": f"status={status}"}

    # 1. Pull full investigation detail (best effort)
    investigation = DOA.get_investigation(inv_id) if inv_id else {}

    # 2. Build finding object
    finding = _build_finding(detail, detail_type, investigation, trace_id)

    # 3. Render full HTML diagnostic page → S3
    try:
        html_url = REPORT.render_and_upload(finding, kind="alert", trace_id=trace_id)
    except Exception as exc:
        logger.exception("eb.render_html_failed", extra={"trace_id": trace_id})
        html_url = ""

    # 4. Render alert email → SES
    email_status = _send_alert_email(finding, html_url, trace_id)

    # 5. KB sink (best-effort, async-safe)
    kb_result = _sink_to_kb(finding, trace_id)

    # 6. Legacy SNS push (kept as fan-out fallback)
    if _sns:
        try:
            _sns.publish(
                TopicArn=_NOTIFY_TOPIC,
                Subject=f"[NLOps][{severity.upper()}] {finding.get('title', detail_type)}"[:99],
                Message=(
                    f"🚨 自动调查完成\n"
                    f"标题: {finding.get('title')}\n"
                    f"严重度: {severity}\n"
                    f"分析页: {html_url}\n"
                    f"DevOps Agent: {finding.get('operator_portal_url', '')}"
                ),
            )
        except Exception as exc:
            logger.warning("eb.sns_failed", extra={"err": str(exc)})

    AUDIT.log(trace_id, "EventBridge", detail_type, "ok",
              {"html_url": html_url, "email": email_status,
               "kb_key": kb_result.get("key", ""),
               "investigation_id": inv_id})

    return {
        "status": "ok",
        "html_url": html_url,
        "email": email_status,
        "kb_sink": kb_result,
        "trace_id": trace_id,
    }


# --------------------------------------------------------------------- #
def _build_finding(detail: dict, detail_type: str,
                   investigation: dict, trace_id: str) -> dict[str, Any]:
    """Build a structured finding from the EventBridge event + DOA detail."""
    rc = (detail.get("rootCause") or {})
    root_cause = rc.get("summary") if isinstance(rc, dict) else str(rc)

    inv_title = investigation.get("title") if isinstance(investigation, dict) else ""
    timeline = investigation.get("timeline") if isinstance(investigation, dict) else []
    if not isinstance(timeline, list):
        timeline = []

    return {
        "title": detail.get("title") or inv_title or detail_type,
        "service": detail.get("service") or detail.get("triggerArn", "").split(":")[-1].split("/")[0] or "",
        "severity": (detail.get("severity") or "info").lower(),
        "investigation_id": detail.get("investigationId") or detail.get("taskId", ""),
        "operator_portal_url": detail.get("operatorPortalUrl", ""),
        "trigger_arn": detail.get("triggerArn", ""),
        "root_cause": root_cause or "调查已完成，详情请查看分析页",
        "timeline": timeline,
        "fix_steps": investigation.get("fixSteps", []) if isinstance(investigation, dict) else [],
        "evidence": investigation.get("evidence", {}) if isinstance(investigation, dict) else {},
        "trace_id": trace_id,
    }


# --------------------------------------------------------------------- #
def _send_alert_email(finding: dict, html_url: str, trace_id: str) -> dict:
    """Render alert_email.html and send via SES."""
    if not _ALERT_EMAIL_TO:
        return {"skipped": True, "reason": "ALERT_EMAIL_TO not configured"}
    if not _ALERT_EMAIL_FROM:
        return {"skipped": True, "reason": "ALERT_EMAIL_FROM not configured"}

    try:
        tmpl = _jinja.get_template("alert_email.html")
        ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        body_html = tmpl.render(
            finding=finding,
            html_url=html_url,
            report_id=trace_id,
            ts=ts,
        )
        # Plain-text fallback for clients that don't render HTML
        body_text = (
            f"NLOps Alert: {finding.get('title')}\n"
            f"Severity: {finding.get('severity')}\n"
            f"Root cause: {finding.get('root_cause')}\n"
            f"Diagnostic: {html_url}\n"
            f"Time: {ts}\n"
        )

        subject = f"🚨 [{finding.get('severity', 'info').upper()}] {finding.get('title', 'NLOps Alert')}"[:99]

        resp = _ses.send_email(
            Source=_ALERT_EMAIL_FROM,
            Destination={"ToAddresses": [_ALERT_EMAIL_TO]},
            Message={
                "Subject": {"Data": subject, "Charset": "UTF-8"},
                "Body": {
                    "Html": {"Data": body_html, "Charset": "UTF-8"},
                    "Text": {"Data": body_text, "Charset": "UTF-8"},
                },
            },
        )
        return {"status": "sent", "message_id": resp.get("MessageId", ""),
                "to": _ALERT_EMAIL_TO}
    except Exception as exc:
        logger.exception("eb.ses_send_failed", extra={"trace_id": trace_id})
        return {"status": "error", "error": str(exc)[:200]}


# --------------------------------------------------------------------- #
def _sink_to_kb(finding: dict, trace_id: str) -> dict:
    """Persist incident to S3 (and Bedrock KB if configured)."""
    try:
        from tools.bedrock_kb import KnowledgeBaseTool
        kb = KnowledgeBaseTool()
        report = {
            "incident_id": finding.get("investigation_id") or trace_id,
            "title": finding.get("title", ""),
            "severity": finding.get("severity", ""),
            "service": finding.get("service", ""),
            "root_cause": finding.get("root_cause", ""),
            "timeline": finding.get("timeline", []),
            "fix_steps": finding.get("fix_steps", []),
            "evidence": finding.get("evidence", {}),
            "ts": int(time.time()),
        }
        key = kb.sink_incident(report)
        return {"key": key, "kb_id": os.getenv("BEDROCK_KB_ID", "(not configured)")}
    except Exception as exc:
        logger.warning("eb.kb_sink_failed", extra={"err": str(exc), "trace_id": trace_id})
        return {"key": "", "error": str(exc)[:200]}
