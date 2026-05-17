"""CloudWatch direct adapter — fallback path when DevOps Agent is unreachable.

Kept lean intentionally; not the primary observability source.
The primary path is AWS DevOps Agent's built-in CloudWatch integration.
"""
from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from typing import Any

import boto3

from common.logging_utils import get_logger

logger = get_logger(__name__)
_REGION = os.getenv("AWS_REGION", "us-east-1")


class CloudWatchTool:
    def __init__(self, region: str | None = None) -> None:
        self.region = region or _REGION
        self._cw = boto3.client("cloudwatch", region_name=self.region)
        self._logs = boto3.client("logs", region_name=self.region)

    def get_metric(
        self,
        namespace: str,
        metric: str,
        dimensions: dict[str, str],
        window_minutes: int = 30,
        period_seconds: int = 60,
        stat: str = "Average",
    ) -> list[dict[str, Any]]:
        end = datetime.now(timezone.utc)
        start = end - timedelta(minutes=window_minutes)
        resp = self._cw.get_metric_data(
            MetricDataQueries=[
                {
                    "Id": "m1",
                    "MetricStat": {
                        "Metric": {
                            "Namespace": namespace,
                            "MetricName": metric,
                            "Dimensions": [
                                {"Name": k, "Value": v} for k, v in dimensions.items()
                            ],
                        },
                        "Period": period_seconds,
                        "Stat": stat,
                    },
                    "ReturnData": True,
                }
            ],
            StartTime=start,
            EndTime=end,
            ScanBy="TimestampAscending",
        )
        result = resp["MetricDataResults"][0]
        return [
            {"ts": ts.isoformat(), "value": v}
            for ts, v in zip(result["Timestamps"], result["Values"])
        ]

    def filter_logs(
        self,
        log_group: str,
        pattern: str,
        window_minutes: int = 30,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        end_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
        start_ms = end_ms - window_minutes * 60 * 1000
        resp = self._logs.filter_log_events(
            logGroupName=log_group,
            startTime=start_ms,
            endTime=end_ms,
            filterPattern=pattern,
            limit=limit,
        )
        return [
            {"ts": e["timestamp"], "message": e["message"], "stream": e["logStreamName"]}
            for e in resp.get("events", [])
        ]
