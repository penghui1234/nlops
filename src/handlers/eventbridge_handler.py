"""L3 EventBridge Subscriber Lambda — handles aws.aidevops investigation events.

Triggered by EventBridge rule matching:
  source        = aws.aidevops
  detail-type   = "Investigation Completed" | "Investigation Updated" | "Evaluation Completed"
"""
from __future__ import annotations

import os
import uuid
from typing import Any

import boto3

from ..common.audit import Audit
from ..common.logging_utils import get_logger
from ..report.generator import ReportGenerator
from ..tools.devops_agent import DevOpsAgentTool

logger = get_logger(__name__)
_REGION = os.getenv("AWS_REGION", "us-east-1")
_NOTIFY_TOPIC = os.getenv("NOTIFY_TOPIC_ARN", "")

DOA = DevOpsAgentTool()
REPORT = ReportGenerator()
AUDIT = Audit()
_sns = boto3.client("sns", region_name=_REGION) if _NOTIFY_TOPIC else None


def handler(event: dict, context) -> dict:
    trace_id = event.get("id") or f"trc-eb-{uuid.uuid4()}"
    detail = event.get("detail") or {}
    detail_type = event.get("detail-type", "")

    inv_id = detail.get("investigationId") or detail.get("evaluationId") or ""
    severity = detail.get("severity", "low")
    status = detail.get("status", "")

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

    if status not in ("COMPLETED", "Completed", "completed"):
        AUDIT.log(trace_id, "EventBridge", detail_type, "skipped", {"status": status})
        return {"skipped": True, "reason": f"status={status}"}

    # 1. Pull full investigation
    investigation = DOA.get_investigation(inv_id) if inv_id else {}

    # 2. Render HTML
    finding = {
        "title": detail.get("title", "AWS DevOps Agent Investigation"),
        "severity": severity,
        "investigation_id": inv_id,
        "operator_portal_url": detail.get("operatorPortalUrl", ""),
        "trigger_arn": detail.get("triggerArn", ""),
        "investigation": investigation,
    }
    html_url = REPORT.render_and_upload(finding, kind="alert", trace_id=trace_id)

    # 3. Push notification
    if _sns:
        message = (
            f"🚨 自动调查完成\n"
            f"标题: {finding['title']}\n"
            f"严重度: {severity}\n"
            f"分析页: {html_url}\n"
            f"DevOps Agent: {finding['operator_portal_url']}"
        )
        _sns.publish(
            TopicArn=_NOTIFY_TOPIC,
            Subject=f"[NLOps] {detail_type}",
            Message=message,
        )

    AUDIT.log(trace_id, "EventBridge", detail_type, "ok", {"html_url": html_url})
    return {"status": "ok", "html_url": html_url}
