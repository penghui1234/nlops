"""HTML diagnostic page generator: Jinja2 + ECharts CDN + S3 upload."""
from __future__ import annotations

import json
import os
import time
import uuid
from pathlib import Path
from typing import Any

import boto3

from common.logging_utils import get_logger

logger = get_logger(__name__)

_BUCKET = os.getenv("REPORT_BUCKET", "")
_REGION = os.getenv("AWS_REGION", "us-east-1")
_PRESIGN_DAYS = int(os.getenv("REPORT_URL_TTL_DAYS", "30"))
_TEMPLATES_DIR = Path(__file__).resolve().parent / "templates"


class ReportGenerator:
    """Render a finding dict to HTML, upload to S3, return Presigned URL."""

    def __init__(self, bucket: str | None = None) -> None:
        self.bucket = bucket or _BUCKET
        self._s3 = boto3.client("s3", region_name=_REGION)

    def render_and_upload(
        self,
        finding: dict[str, Any],
        kind: str = "diagnostic",
        trace_id: str | None = None,
    ) -> str:
        if not self.bucket:
            raise RuntimeError("REPORT_BUCKET env not set")

        report_id = trace_id or f"rpt-{uuid.uuid4()}"
        ts = int(time.time())

        html = self._render(finding, kind=kind, report_id=report_id, ts=ts)
        key = f"reports/{kind}/{ts}/{report_id}.html"

        self._s3.put_object(
            Bucket=self.bucket,
            Key=key,
            Body=html.encode("utf-8"),
            ContentType="text/html; charset=utf-8",
        )
        # Use direct virtual-hosted-style URL since bucket has public read on
        # /reports/* via bucket policy. This avoids STS temp credential expiry
        # issues with presigned URLs.
        url = f"https://{self.bucket}.s3.{_REGION}.amazonaws.com/{key}"
        logger.info("report.uploaded", extra={"key": key, "report_id": report_id})
        return url

    # ------------------------------------------------------------------ #
    def _render(
        self,
        finding: dict[str, Any],
        kind: str,
        report_id: str,
        ts: int,
    ) -> str:
        try:
            from jinja2 import Environment, FileSystemLoader, select_autoescape
        except ImportError:
            # Lambda layer without jinja2 — fallback to simple template
            return _fallback_render(finding, kind, report_id, ts)

        env = Environment(
            loader=FileSystemLoader(str(_TEMPLATES_DIR)),
            autoescape=select_autoescape(["html"]),
        )
        tmpl = env.get_template("analysis.html")
        # Format ts as human-readable (UTC+8 China time)
        from datetime import datetime, timezone, timedelta
        cn_tz = timezone(timedelta(hours=8))
        ts_human = datetime.fromtimestamp(ts, tz=cn_tz).strftime(
            "%Y-%m-%d %H:%M:%S CST"
        )
        return tmpl.render(
            finding=finding,
            kind=kind,
            report_id=report_id,
            ts=ts,
            ts_human=ts_human,
            finding_json=json.dumps(finding, ensure_ascii=False, indent=2, default=str),
        )


def _fallback_render(
    finding: dict[str, Any],
    kind: str,
    report_id: str,
    ts: int,
) -> str:
    """Bare-bones HTML when Jinja2 is not in the runtime."""
    title = finding.get("title", "NLOps Diagnostic")
    pretty = json.dumps(finding, ensure_ascii=False, indent=2, default=str)
    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8"/>
<title>{title}</title>
<style>
  body {{ font-family: -apple-system, "Helvetica Neue", "Microsoft YaHei", sans-serif;
         max-width: 960px; margin: 2em auto; padding: 0 1em; color: #2a2a2a; }}
  h1 {{ border-bottom: 2px solid #ff9900; padding-bottom: 8px; }}
  pre {{ background: #f6f6f6; padding: 1em; overflow-x: auto; }}
  .meta {{ color: #888; font-size: 0.9em; }}
</style>
</head>
<body>
<h1>{title}</h1>
<div class="meta">Report ID: {report_id} · Generated: {ts} · Kind: {kind}</div>
<h2>Finding</h2>
<pre>{pretty}</pre>
</body>
</html>"""
