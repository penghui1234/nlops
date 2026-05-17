"""L2 Execution Lambda — write-isolated AWS API actions with Confirm Token.

Invoked synchronously from L1 Orchestrator via boto3 lambda.invoke.
Independent IAM Role with tag-bounded write permissions.
"""
from __future__ import annotations

import json
import os
import time
from typing import Any

import boto3
from botocore.exceptions import ClientError

from common.audit import Audit
from common.logging_utils import get_logger

logger = get_logger(__name__)


_TOKEN_TABLE = os.getenv("CONFIRM_TOKENS_TABLE", "")
_REGION = os.getenv("AWS_REGION", "us-east-1")

_ddb = boto3.resource("dynamodb", region_name=_REGION).Table(_TOKEN_TABLE) if _TOKEN_TABLE else None
AUDIT = Audit()


def handler(event: dict, context) -> dict:
    trace_id = event.get("trace_id") or "trc-execution-unknown"
    user_id = event.get("user_id", "")
    session_id = event.get("session_id", "")
    confirm_token = event.get("confirm_token") or ""
    action = event.get("action") or {}

    # 1. Validate Confirm Token ---------------------------------------- #
    ok, reason = _consume_token(
        token=confirm_token,
        session_id=session_id,
        user_id=user_id,
    )
    if not ok:
        AUDIT.log(trace_id, "Execution", "validate_token", "deny", {"reason": reason})
        return {"status": "denied", "reason": reason}

    # 2. Dispatch action ----------------------------------------------- #
    try:
        result = _dispatch(action)
    except (ClientError, Exception) as exc:
        logger.exception("execution.dispatch_failed", extra={"trace_id": trace_id})
        AUDIT.log(trace_id, "Execution", action.get("type", "?"), "error", {"err": str(exc)})
        return {"status": "error", "error": str(exc)}

    AUDIT.log(trace_id, "Execution", action.get("type", "?"), "ok", result)
    return {"status": "ok", "result": result}


# --------------------------------------------------------------------- #
# Confirm Token: single-use, 5-min TTL, session+user bound
# --------------------------------------------------------------------- #
def _consume_token(token: str, session_id: str, user_id: str) -> tuple[bool, str]:
    if not _ddb:
        return False, "confirm tokens table not configured"
    if not token:
        return False, "missing confirm_token"

    resp = _ddb.get_item(Key={"token": token})
    item = resp.get("Item")
    if not item:
        return False, "token not found"
    if item.get("used"):
        return False, "token already used"
    if item.get("session_id") != session_id:
        return False, "session mismatch"
    if item.get("user_id") != user_id:
        return False, "user mismatch"
    if item.get("expires_at", 0) < int(time.time()):
        return False, "token expired"

    # Mark as used (idempotent)
    _ddb.update_item(
        Key={"token": token},
        UpdateExpression="SET used = :t, used_at = :ts",
        ExpressionAttributeValues={":t": True, ":ts": int(time.time())},
    )
    return True, "ok"


# --------------------------------------------------------------------- #
# Action dispatch — keep it small + auditable
# --------------------------------------------------------------------- #
def _dispatch(action: dict[str, Any]) -> dict[str, Any]:
    typ = action.get("type")
    params = action.get("params") or {}

    if typ == "ecs.update_service":
        ecs = boto3.client("ecs")
        return ecs.update_service(
            cluster=params["cluster"],
            service=params["service"],
            desiredCount=int(params["desired_count"]),
        )

    if typ == "rds.modify_proxy_connections":
        rds = boto3.client("rds")
        return rds.modify_db_proxy(
            DBProxyName=params["proxy_name"],
            # Connection pool config goes via target_group endpoint normally;
            # placeholder for the relevant API; in practice you'd update
            # the proxy's target group connection limits.
            DebugLogging=params.get("debug_logging", False),
        )

    if typ == "autoscaling.set_desired_capacity":
        asg = boto3.client("autoscaling")
        return asg.set_desired_capacity(
            AutoScalingGroupName=params["asg_name"],
            DesiredCapacity=int(params["desired"]),
            HonorCooldown=False,
        )

    if typ == "ec2.reboot_instances":
        ec2 = boto3.client("ec2")
        return ec2.reboot_instances(InstanceIds=params["instance_ids"])

    raise ValueError(f"unknown action type: {typ}")
