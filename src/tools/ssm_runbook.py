"""SSM Automation Runbook executor for v4.

v4 replaces v3's L2 Execution Lambda with SSM Automation:
  * Standardized, auditable execution via AWS console
  * Built-in approval workflow (CLI: aws ssm start-automation-execution)
  * Pre-defined runbook documents for common operations

Pre-defined Runbooks (created out-of-band via CDK or console):
  - nlops-ecs-scale          : adjust ECS service desiredCount
  - nlops-rds-proxy-expand   : modify RDS Proxy max connections
  - nlops-ec2-reboot         : reboot tagged EC2 instance
"""
from __future__ import annotations

import json
import os
from typing import Any

import boto3
from botocore.exceptions import ClientError

from common.logging_utils import get_logger

logger = get_logger(__name__)

_REGION = os.getenv("AWS_REGION", "us-east-1")


class SSMRunbook:
    """Thin facade over SSM Automation API."""

    def __init__(self) -> None:
        self._ssm = boto3.client("ssm", region_name=_REGION)

    def execute(self, document_name: str, parameters: dict[str, list[str]],
                dry_run: bool = False) -> dict[str, Any]:
        """Start an SSM Automation execution.

        Args:
            document_name: SSM document name (e.g. 'nlops-ecs-scale')
            parameters: Map[str, List[str]] per SSM API
            dry_run: if True, only return what would be executed
        """
        if dry_run:
            return {
                "dry_run": True,
                "document_name": document_name,
                "parameters": parameters,
                "preview": f"Would execute {document_name} with {parameters}",
            }

        try:
            resp = self._ssm.start_automation_execution(
                DocumentName=document_name,
                Parameters=parameters,
            )
            execution_id = resp["AutomationExecutionId"]
            logger.info("ssm.started",
                        extra={"document": document_name, "execution_id": execution_id})
            return {
                "status": "started",
                "execution_id": execution_id,
                "document_name": document_name,
                "console_url": (
                    f"https://console.aws.amazon.com/systems-manager/automation/"
                    f"execution/{execution_id}?region={_REGION}"
                ),
            }
        except ClientError as exc:
            logger.exception("ssm.start_failed")
            return {"status": "error", "error": str(exc)[:300]}

    def get_status(self, execution_id: str) -> dict[str, Any]:
        """Query an automation execution's status."""
        try:
            resp = self._ssm.get_automation_execution(
                AutomationExecutionId=execution_id,
            )
            exe = resp.get("AutomationExecution", {})
            return {
                "execution_id": execution_id,
                "status": exe.get("AutomationExecutionStatus"),
                "started": str(exe.get("ExecutionStartTime", "")),
                "ended": str(exe.get("ExecutionEndTime", "")),
                "outputs": exe.get("Outputs", {}),
            }
        except ClientError as exc:
            return {"error": str(exc)[:300]}
