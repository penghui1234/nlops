"""Bedrock Knowledge Base adapter for incident report dual-write."""
from __future__ import annotations

import json
import os
import time
import uuid
from typing import Any

import boto3
from botocore.exceptions import ClientError

from ..common.logging_utils import get_logger

logger = get_logger(__name__)

_KB_ID = os.getenv("BEDROCK_KB_ID", "")
_DATA_SOURCE_ID = os.getenv("BEDROCK_KB_DATA_SOURCE_ID", "")
_REPORT_BUCKET = os.getenv("REPORT_BUCKET", "")
_KB_PREFIX = os.getenv("KB_DOC_PREFIX", "kb/incidents/")
_REGION = os.getenv("AWS_REGION", "us-east-1")


class KnowledgeBaseTool:
    def __init__(self, kb_id: str | None = None) -> None:
        self.kb_id = kb_id or _KB_ID
        self._agent_rt = boto3.client("bedrock-agent-runtime", region_name=_REGION)
        self._agent = boto3.client("bedrock-agent", region_name=_REGION)
        self._s3 = boto3.client("s3", region_name=_REGION)

    def search(self, query: str, top_k: int = 3) -> list[dict[str, Any]]:
        if not self.kb_id:
            return []
        try:
            resp = self._agent_rt.retrieve(
                knowledgeBaseId=self.kb_id,
                retrievalQuery={"text": query},
                retrievalConfiguration={
                    "vectorSearchConfiguration": {"numberOfResults": top_k}
                },
            )
        except ClientError:
            logger.exception("kb.retrieve_failed")
            return []

        return [
            {
                "score": item.get("score"),
                "content": item.get("content", {}).get("text", ""),
                "source": item.get("location", {}),
                "metadata": item.get("metadata", {}),
            }
            for item in resp.get("retrievalResults", [])
        ]

    def sink_incident(self, report: dict[str, Any]) -> str:
        if not _REPORT_BUCKET:
            raise RuntimeError("REPORT_BUCKET env not set; cannot sink incident")

        incident_id = report.get("incident_id") or f"inc-{uuid.uuid4()}"
        report.setdefault("incident_id", incident_id)
        report.setdefault("ts", int(time.time()))

        key = f"{_KB_PREFIX}{incident_id}.json"
        self._s3.put_object(
            Bucket=_REPORT_BUCKET,
            Key=key,
            Body=json.dumps(report, ensure_ascii=False, indent=2).encode("utf-8"),
            ContentType="application/json",
        )
        logger.info("kb.sink_uploaded", extra={"key": key, "incident_id": incident_id})

        if self.kb_id and _DATA_SOURCE_ID:
            try:
                self._agent.start_ingestion_job(
                    knowledgeBaseId=self.kb_id,
                    dataSourceId=_DATA_SOURCE_ID,
                )
            except ClientError:
                logger.exception("kb.ingest_trigger_failed")

        return key
