"""NLOps v4 MCP Tools — 5 simplified tools.

v4 design philosophy: only expose what DOA itself doesn't provide.
The Quick Desktop / external LLM does the orchestration; we provide
the client-specific glue (HTML rendering, IM push, etc.).

Tools:
  1. query_doa            - One-shot Q&A via DOA Chat
  2. start_investigation  - Async deep investigation via DOA
  3. get_html_report      - Render HTML diagnostic page (S3 presigned URL)
  4. trigger_runbook      - Execute SSM Automation document
  5. notify_im            - Push message to IM channel (WeCom/Lark/SES)
"""
from __future__ import annotations

import json
import os
import uuid
from datetime import datetime, timezone
from typing import Any

import boto3

from common.logging_utils import get_logger
from mcp_server.server import McpServer
from report.generator import ReportGenerator
from tools.devops_agent import DevOpsAgent
from tools.ssm_runbook import SSMRunbook

logger = get_logger(__name__)
server = McpServer()

_REGION = os.getenv("AWS_REGION", "us-east-1")
_ALERT_EMAIL_FROM = os.getenv("ALERT_EMAIL_FROM", "")
_ALERT_EMAIL_TO = os.getenv("ALERT_EMAIL_TO", "")

# Cached helpers (warm container reuse)
_doa: DevOpsAgent | None = None
_ssm: SSMRunbook | None = None
_report: ReportGenerator | None = None
_ses = boto3.client("ses", region_name=_REGION)


def _get_doa() -> DevOpsAgent:
    global _doa
    if _doa is None:
        _doa = DevOpsAgent()
    return _doa


def _get_ssm() -> SSMRunbook:
    global _ssm
    if _ssm is None:
        _ssm = SSMRunbook()
    return _ssm


def _get_report() -> ReportGenerator:
    global _report
    if _report is None:
        _report = ReportGenerator()
    return _report


# ============================================================ #
# 1. query_doa
# ============================================================ #
@server.tool
def query_doa(question: str) -> dict[str, Any]:
    """Ask AWS DevOps Agent a one-shot question (5-30s).

    Use for quick health queries, "is X service OK", "what's the latency of Y".
    DOA will use its CloudWatch / X-Ray / Config integrations to answer.

    Args:
        question: Natural-language question (English or Chinese).
    """
    answer = _get_doa().chat(question, user_id="nlops-mcp")
    return {
        "question": question,
        "answer": answer,
        "engine": "aws-devops-agent",
        "agent_space_id": os.getenv("DOA_AGENT_SPACE_ID", ""),
    }


# ============================================================ #
# 2. start_investigation
# ============================================================ #
@server.tool
def start_investigation(title: str, description: str = "",
                        priority: str = "MEDIUM") -> dict[str, Any]:
    """Start a deep DOA Investigation (async, 5-15 min).

    Use for "why is X slow", "find the root cause of Y" — questions that
    need DOA to correlate metrics, logs, traces, deployments.

    The result will be delivered via EventBridge when complete; an HTML
    diagnostic page is auto-generated and emailed.

    Args:
        title: Short title (max 200 chars).
        description: Optional context (max 4000 chars).
        priority: CRITICAL | HIGH | MEDIUM | LOW | MINIMAL
    """
    task_id = _get_doa().start_investigation(title, description, priority)
    return {
        "task_id": task_id,
        "title": title,
        "status": "in_progress",
        "expected_minutes": "5-15",
        "engine": "aws-devops-agent",
        "operator_console_url": (
            f"https://console.aws.amazon.com/devops-agent/spaces/"
            f"{os.getenv('DOA_AGENT_SPACE_ID', '')}/tasks/{task_id}"
        ),
    }


# ============================================================ #
# 3. get_html_report
# ============================================================ #
@server.tool
def get_html_report(task_id: str = "", title: str = "",
                    summary: str = "", findings: str = "") -> dict[str, Any]:
    """Render an HTML diagnostic report and upload to S3 (presigned URL, 30 days).

    If task_id is provided, fetches investigation details from DOA.
    Otherwise renders an ad-hoc report from the provided title/summary/findings.

    Args:
        task_id: Optional DOA investigation taskId.
        title: Report title (used if task_id empty).
        summary: Markdown summary.
        findings: JSON or markdown findings.
    """
    finding: dict[str, Any] = {}
    if task_id:
        inv = _get_doa().get_investigation(task_id)
        # Pull AI findings from journal records (the actual report)
        execution_id = inv.get("executionId", "") if isinstance(inv, dict) else ""
        ai_findings = _get_doa().get_investigation_findings(execution_id) if execution_id else {}
        report_md = ai_findings.get("report_md", "")
        tool_uses = ai_findings.get("tool_uses", [])

        finding = {
            "title": inv.get("title") or title or f"Investigation {task_id}",
            "investigation_id": task_id,
            "execution_id": execution_id,
            "status": inv.get("status", "UNKNOWN"),
            "report_md": report_md,
            "tool_uses": tool_uses,
            "root_cause": (
                report_md.split("\n")[0][:300] if report_md
                else inv.get("description", "")[:600]
            ),
            "operator_portal_url": (
                f"https://console.aws.amazon.com/devops-agent/spaces/"
                f"{os.getenv('DOA_AGENT_SPACE_ID', '')}/tasks/{task_id}"
            ),
            "ts": int(datetime.now(timezone.utc).timestamp()),
        }
    else:
        finding = {
            "title": title or "NLOps Diagnostic",
            "summary": summary,
            "findings": findings,
            "ts": int(datetime.now(timezone.utc).timestamp()),
        }

    try:
        url = _get_report().render_and_upload(
            finding=finding,
            kind="diagnostic",
            trace_id=task_id or f"rpt-{uuid.uuid4().hex[:8]}",
        )
        return {"status": "ok", "html_url": url, "title": finding["title"]}
    except Exception as exc:
        logger.exception("report.render_failed")
        return {"status": "error", "error": str(exc)[:300]}


# ============================================================ #
# 4. trigger_runbook
# ============================================================ #
@server.tool
def trigger_runbook(document_name: str, parameters_json: str = "{}",
                    dry_run: bool = True) -> dict[str, Any]:
    """Execute an SSM Automation Runbook (write operation).

    Pre-defined runbooks:
      - nlops-ecs-scale          : adjust ECS service desiredCount
      - nlops-rds-proxy-expand   : modify RDS Proxy max connections percent
      - nlops-ec2-reboot         : reboot a tagged EC2 instance

    SAFETY: defaults to dry_run=true. Set dry_run=false to actually execute.
    The caller (Quick LLM / user) MUST present the dry-run output to the user
    and get explicit confirmation before calling with dry_run=false.

    Args:
        document_name: SSM document name.
        parameters_json: JSON string of parameters, e.g.
            '{"ClusterName": ["demo"], "ServiceName": ["api"], "DesiredCount": ["4"]}'
        dry_run: If true, return preview without executing.
    """
    try:
        params = json.loads(parameters_json) if parameters_json else {}
    except json.JSONDecodeError as exc:
        return {"status": "error", "error": f"invalid parameters_json: {exc}"}

    # Normalise: SSM expects List[str] values
    norm = {}
    for k, v in params.items():
        if isinstance(v, list):
            norm[k] = [str(x) for x in v]
        else:
            norm[k] = [str(v)]

    return _get_ssm().execute(document_name, norm, dry_run=dry_run)


# ============================================================ #
# 5. notify_im
# ============================================================ #
@server.tool
def notify_im(channel: str, subject: str, body: str,
              html_url: str = "") -> dict[str, Any]:
    """Push a message to an IM channel (currently SES email; WeCom/Lark TBD).

    Args:
        channel: 'email' | 'wecom' | 'lark' (only 'email' implemented in v4 MVP).
        subject: Message subject.
        body: Plain-text body (markdown supported in HTML email).
        html_url: Optional HTML diagnostic URL to include.
    """
    if channel not in ("email", "wecom", "lark"):
        return {"status": "error", "error": f"unknown channel: {channel}"}

    if channel != "email":
        return {"status": "todo", "note": f"{channel} integration not yet implemented in v4 MVP"}

    if not _ALERT_EMAIL_TO or not _ALERT_EMAIL_FROM:
        return {"status": "error", "error": "ALERT_EMAIL_FROM / ALERT_EMAIL_TO not set"}

    body_html = (
        f"<html><body style='font-family:-apple-system,sans-serif'>"
        f"<h2>{subject}</h2>"
        f"<pre style='background:#f6f6f6;padding:1em;white-space:pre-wrap'>{body}</pre>"
        + (f"<p>📊 <a href='{html_url}'>查看完整诊断书</a></p>" if html_url else "")
        + f"<hr/><small>NLOps v4 · {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}</small>"
        + "</body></html>"
    )

    try:
        resp = _ses.send_email(
            Source=_ALERT_EMAIL_FROM,
            Destination={"ToAddresses": [_ALERT_EMAIL_TO]},
            Message={
                "Subject": {"Data": subject[:99], "Charset": "UTF-8"},
                "Body": {
                    "Html": {"Data": body_html, "Charset": "UTF-8"},
                    "Text": {"Data": body, "Charset": "UTF-8"},
                },
            },
        )
        return {"status": "sent", "message_id": resp.get("MessageId", ""),
                "to": _ALERT_EMAIL_TO, "channel": channel}
    except Exception as exc:
        logger.exception("ses.send_failed")
        return {"status": "error", "error": str(exc)[:300]}
