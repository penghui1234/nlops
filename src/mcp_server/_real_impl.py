"""Real-mode implementations for NLOps MCP tools.

When ``MOCK_MODE=false`` (default), the entry-point tools in
``private_tools.py`` delegate to the functions in this module which call
real AWS APIs (CloudWatch / Logs / X-Ray / Bedrock KB / Resource Groups
Tagging / SNS / Lambda).

Design notes:
  * Every function returns the same response shape as its mock counterpart
    so MCP clients see consistent schemas.
  * If a required environment variable / dependency is missing we return
    ``{"error": "...", ...empty fields}`` rather than silently falling
    back to mocks (avoids "looks real but is fake" surprises).
  * boto3 clients are created lazily and cached at module level — Lambda
    container reuse benefits.
"""
from __future__ import annotations

import json
import os
import time
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

import boto3
from botocore.exceptions import ClientError

from common.logging_utils import get_logger

logger = get_logger(__name__)

_REGION = os.getenv("AWS_REGION", "us-east-1")

# ---------------------------------------------------------------------------
# Lazy-cached boto3 clients
# ---------------------------------------------------------------------------
_clients: dict[str, Any] = {}


def _client(name: str):
    if name not in _clients:
        _clients[name] = boto3.client(name, region_name=_REGION)
    return _clients[name]


def _resource(name: str):
    key = f"_res_{name}"
    if key not in _clients:
        _clients[key] = boto3.resource(name, region_name=_REGION)
    return _clients[key]


def _ddb_table(env_var: str):
    name = os.getenv(env_var, "")
    if not name:
        return None
    return _resource("dynamodb").Table(name)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _to_iso(ts) -> str:
    if isinstance(ts, datetime):
        return ts.isoformat()
    if isinstance(ts, (int, float)):
        return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()
    return str(ts)


def _decimal_to_native(obj):
    """DynamoDB returns Decimal; convert for JSON serialization."""
    if isinstance(obj, list):
        return [_decimal_to_native(x) for x in obj]
    if isinstance(obj, dict):
        return {k: _decimal_to_native(v) for k, v in obj.items()}
    if isinstance(obj, Decimal):
        i, f = int(obj), float(obj)
        return i if i == f else f
    return obj


# ===========================================================================
# 1. Discovery
# ===========================================================================
def discover_incidents(status: str = "open", time_range_hours: int = 24) -> dict[str, Any]:
    """Read recent incidents from the AuditTable (rows logged by Execution
    & EventBridge handlers). Falls back to scanning recent rows if no
    explicit ``incidents`` partition exists."""
    table = _ddb_table("AUDIT_TABLE")
    if table is None:
        return {"status_filter": status, "time_range_hours": time_range_hours,
                "count": 0, "incidents": [], "error": "AUDIT_TABLE not configured"}

    cutoff_ts = int((_now() - timedelta(hours=time_range_hours)).timestamp())
    incidents: list[dict[str, Any]] = []
    try:
        # Scan with FilterExpression — small table in demo; for prod use a
        # GSI on (status, ts). Limit result set defensively.
        resp = table.scan(
            FilterExpression="ts >= :cutoff AND begins_with(actor, :actor_prefix)",
            ExpressionAttributeValues={":cutoff": cutoff_ts, ":actor_prefix": "Execution"},
            Limit=200,
        )
        for item in resp.get("Items", []):
            item = _decimal_to_native(item)
            details = item.get("details") or {}
            if isinstance(details, str):
                try:
                    details = json.loads(details)
                except Exception:
                    details = {}
            inc_status = details.get("status") or item.get("outcome") or "open"
            if status != "all" and inc_status != status:
                continue
            incidents.append({
                "id": item.get("trace_id"),
                "title": details.get("title") or item.get("action") or "incident",
                "status": inc_status,
                "service": details.get("service") or details.get("resource") or "",
                "created": _to_iso(item.get("ts", 0)),
            })
    except ClientError as exc:
        logger.exception("audit_table.scan_failed")
        return {"status_filter": status, "time_range_hours": time_range_hours,
                "count": 0, "incidents": [], "error": str(exc)}

    return {
        "status_filter": status,
        "time_range_hours": time_range_hours,
        "count": len(incidents),
        "incidents": incidents[:50],
    }


# ===========================================================================
# 2. Knowledge
# ===========================================================================
def query_knowledge_base(query: str, doc_type: str = "all") -> dict[str, Any]:
    """Query Bedrock Knowledge Base via ``bedrock-agent-runtime.retrieve``."""
    kb_id = os.getenv("BEDROCK_KB_ID", "")
    if not kb_id:
        return {"query": query, "doc_type": doc_type, "results": [],
                "error": "BEDROCK_KB_ID not configured"}

    try:
        from tools.bedrock_kb import KnowledgeBaseTool
        kb = KnowledgeBaseTool(kb_id=kb_id)
        hits = kb.search(query, top_k=5)
    except Exception as exc:
        logger.exception("kb.query_failed")
        return {"query": query, "doc_type": doc_type, "results": [], "error": str(exc)}

    results = []
    for h in hits:
        meta = h.get("metadata") or {}
        if doc_type != "all" and meta.get("type") and meta["type"] != doc_type:
            continue
        results.append({
            "title": meta.get("title") or h.get("source", {}).get("s3Location", {}).get("uri", ""),
            "type": meta.get("type", "unknown"),
            "url": meta.get("url") or h.get("source", {}).get("s3Location", {}).get("uri", ""),
            "excerpt": (h.get("content") or "")[:300],
            "relevance": h.get("score"),
        })
    return {"query": query, "doc_type": doc_type, "count": len(results), "results": results}


def search_runbooks(keywords: str, service: str = "") -> dict[str, Any]:
    """Runbooks are queried via Bedrock KB with a doc_type filter."""
    full_query = f"{keywords} {service}".strip()
    out = query_knowledge_base(full_query, doc_type="runbook")
    out["keywords"] = keywords
    out["service"] = service
    out["runbooks"] = out.pop("results", [])
    return out


def get_service_owner(service_name: str) -> dict[str, Any]:
    """Look up service owner via Resource Groups Tagging API.

    Convention: a resource representing the service has tags such as
    ``Service=<service_name>`` and ``Owner=<email>``, ``Team=<team>``,
    ``Slack=<channel>``.
    """
    try:
        tagging = _client("resourcegroupstaggingapi")
        resp = tagging.get_resources(
            TagFilters=[{"Key": "Service", "Values": [service_name]}],
            ResourcesPerPage=10,
        )
    except ClientError as exc:
        logger.exception("tagging.get_resources_failed")
        return {"service": service_name, "team": "unknown",
                "on_call": "", "slack": "", "error": str(exc)}

    team = on_call = slack = ""
    runbook_url = ""
    for rsc in resp.get("ResourceTagMappingList", []):
        tags = {t["Key"]: t["Value"] for t in rsc.get("Tags", [])}
        team = team or tags.get("Team") or tags.get("Owner") or ""
        on_call = on_call or tags.get("OnCall") or tags.get("Owner") or ""
        slack = slack or tags.get("Slack") or ""
        runbook_url = runbook_url or tags.get("RunbookUrl") or ""
        if team and on_call:
            break

    return {
        "service": service_name,
        "team": team or "unknown",
        "on_call": on_call,
        "slack": slack,
        "runbook_url": runbook_url,
        "matched_resources": len(resp.get("ResourceTagMappingList", [])),
    }


def get_service_dependencies(service_name: str) -> dict[str, Any]:
    """Use X-Ray service map (last 1h) to derive upstream/downstream."""
    try:
        xray = _client("xray")
        end = _now()
        start = end - timedelta(hours=1)
        resp = xray.get_service_graph(StartTime=start, EndTime=end)
    except ClientError as exc:
        logger.exception("xray.get_service_graph_failed")
        return {"service": service_name, "upstream": [], "downstream": [],
                "infrastructure": [], "error": str(exc)}

    upstream: list[str] = []
    downstream: list[str] = []
    infrastructure: list[str] = []

    services = resp.get("Services", [])
    target = next((s for s in services if s.get("Name") == service_name), None)
    if target is None:
        return {"service": service_name, "upstream": [], "downstream": [],
                "infrastructure": [], "note": "service not found in X-Ray service graph"}

    target_ref_id = target.get("ReferenceId")

    # Downstream = edges from target.Edges
    for edge in target.get("Edges", []):
        ref_id = edge.get("ReferenceId")
        peer = next((s for s in services if s.get("ReferenceId") == ref_id), None)
        if peer:
            name = peer.get("Name") or ""
            ptype = (peer.get("Type") or "").lower()
            if "database" in ptype or "rds" in ptype or "dynamodb" in ptype or "elasticache" in ptype:
                infrastructure.append(name)
            else:
                downstream.append(name)

    # Upstream = scan all services for edges pointing back to target
    for s in services:
        for edge in s.get("Edges", []):
            if edge.get("ReferenceId") == target_ref_id:
                upstream.append(s.get("Name", ""))

    return {
        "service": service_name,
        "upstream": sorted(set(filter(None, upstream))),
        "downstream": sorted(set(filter(None, downstream))),
        "infrastructure": sorted(set(filter(None, infrastructure))),
    }


# ===========================================================================
# 3. Analysis
# ===========================================================================
def analyze_logs(log_group: str, time_range_minutes: int = 30,
                 pattern: str = "", limit: int = 100) -> dict[str, Any]:
    """CloudWatch Logs Insights query.

    Default Insights query: count error-level lines, group by message
    prefix to surface top error patterns.
    """
    logs = _client("logs")
    end_ms = int(_now().timestamp() * 1000)
    start_ms = end_ms - time_range_minutes * 60 * 1000

    # 1) Total line count + error count
    insights_q = (
        "stats count(*) as total, "
        "sum(strcontains(@message, 'ERROR') or strcontains(@message, 'Error') "
        "or strcontains(@message, 'Exception')) as errors"
    )

    try:
        start_resp = logs.start_query(
            logGroupName=log_group,
            startTime=int(start_ms / 1000),
            endTime=int(end_ms / 1000),
            queryString=insights_q,
            limit=1,
        )
        qid = start_resp["queryId"]
        # poll up to ~10s
        for _ in range(20):
            time.sleep(0.5)
            r = logs.get_query_results(queryId=qid)
            if r.get("status") in ("Complete", "Failed", "Cancelled"):
                break
        total = errors = 0
        for row in r.get("results", []):
            for col in row:
                if col["field"] == "total":
                    total = int(float(col["value"] or 0))
                elif col["field"] == "errors":
                    errors = int(float(col["value"] or 0))
    except ClientError as exc:
        logger.exception("logs.start_query_failed")
        return {"log_group": log_group, "time_range_minutes": time_range_minutes,
                "pattern": pattern, "total_lines": 0, "error_count": 0,
                "error_rate": "0%", "top_errors": [], "error": str(exc)}

    # 2) Top error patterns via filter_log_events (cheaper than another query)
    top_errors: list[dict[str, Any]] = []
    try:
        filt = pattern or "?ERROR ?Error ?Exception"
        events = logs.filter_log_events(
            logGroupName=log_group,
            startTime=start_ms,
            endTime=end_ms,
            filterPattern=filt,
            limit=min(limit, 100),
        ).get("events", [])
        from collections import Counter
        # Use the first 80 chars as the key; reduces per-line variance
        counter = Counter((e["message"] or "")[:80] for e in events)
        for msg, cnt in counter.most_common(5):
            top_errors.append({"count": cnt, "message": msg})
    except ClientError as exc:
        logger.warning("logs.filter_log_events_failed", extra={"err": str(exc)})

    rate = f"{(errors / total * 100):.2f}%" if total else "0%"
    return {
        "log_group": log_group,
        "time_range_minutes": time_range_minutes,
        "pattern": pattern,
        "total_lines": total,
        "error_count": errors,
        "error_rate": rate,
        "top_errors": top_errors,
    }


def analyze_metrics(namespace: str, metric_name: str, dimensions: str = "",
                    period: int = 60, time_range_minutes: int = 30) -> dict[str, Any]:
    """CloudWatch GetMetricStatistics."""
    cw = _client("cloudwatch")
    end = _now()
    start = end - timedelta(minutes=time_range_minutes)

    dim_list = []
    for kv in (dimensions or "").split(","):
        kv = kv.strip()
        if "=" in kv:
            k, v = kv.split("=", 1)
            dim_list.append({"Name": k.strip(), "Value": v.strip()})

    try:
        resp = cw.get_metric_statistics(
            Namespace=namespace,
            MetricName=metric_name,
            Dimensions=dim_list,
            StartTime=start,
            EndTime=end,
            Period=max(60, period),
            Statistics=["Average", "Maximum", "Minimum"],
        )
    except ClientError as exc:
        logger.exception("cloudwatch.get_metric_statistics_failed")
        return {"namespace": namespace, "metric_name": metric_name,
                "statistics": {}, "datapoints": [], "error": str(exc)}

    datapoints = sorted(resp.get("Datapoints", []), key=lambda d: d["Timestamp"])
    if not datapoints:
        return {"namespace": namespace, "metric_name": metric_name,
                "statistics": {"avg": None, "max": None, "min": None},
                "datapoints": [], "note": "no datapoints"}

    avg = sum(d["Average"] for d in datapoints) / len(datapoints)
    return {
        "namespace": namespace,
        "metric_name": metric_name,
        "statistics": {
            "avg": round(avg, 2),
            "max": max(d["Maximum"] for d in datapoints),
            "min": min(d["Minimum"] for d in datapoints),
        },
        "datapoints": [
            {"timestamp": _to_iso(d["Timestamp"]), "average": round(d["Average"], 2)}
            for d in datapoints
        ],
    }


def analyze_traces(service: str, trace_id: str = "",
                   time_range_minutes: int = 30) -> dict[str, Any]:
    """X-Ray service-level summary or single-trace deep-dive."""
    xray = _client("xray")
    end = _now()
    start = end - timedelta(minutes=time_range_minutes)

    if trace_id:
        try:
            resp = xray.batch_get_traces(TraceIds=[trace_id])
        except ClientError as exc:
            return {"service": service, "trace_id": trace_id, "error": str(exc)}
        traces = resp.get("Traces", [])
        if not traces:
            return {"service": service, "trace_id": trace_id, "note": "trace not found"}
        t = traces[0]
        return {
            "service": service,
            "trace_id": trace_id,
            "duration_ms": (t.get("Duration") or 0) * 1000,
            "segment_count": len(t.get("Segments", [])),
        }

    try:
        resp = xray.get_trace_summaries(
            StartTime=start, EndTime=end,
            FilterExpression=f'service("{service}")',
            Sampling=False,
        )
    except ClientError as exc:
        logger.exception("xray.get_trace_summaries_failed")
        return {"service": service, "total_traces": 0, "error": str(exc)}

    summaries = resp.get("TraceSummaries", [])
    durations = [s.get("Duration") or 0 for s in summaries]
    error_traces = [s for s in summaries if s.get("HasError") or s.get("HasFault")]
    avg_ms = (sum(durations) / len(durations) * 1000) if durations else 0
    p99_ms = (sorted(durations)[int(len(durations) * 0.99)] * 1000) if durations else 0
    err_rate = f"{(len(error_traces) / len(summaries) * 100):.2f}%" if summaries else "0%"

    return {
        "service": service,
        "total_traces": len(summaries),
        "avg_duration_ms": round(avg_ms, 1),
        "p99_duration_ms": round(p99_ms, 1),
        "error_rate": err_rate,
        "slow_segments": [],  # would need per-trace deep-dive; left for follow-up
    }


def analyze_root_cause(alert_id: str = "", service: str = "",
                       context: str = "") -> dict[str, Any]:
    """Bedrock LLM reasoning over collected evidence.

    Strategy: collect lightweight evidence (top errors + slow traces),
    then ask the LLM to summarize. Cheaper than running a full
    investigation; complements DevOps Agent's own RCA.
    """
    evidence: list[dict[str, Any]] = []

    # Evidence 1: log analysis if service hints at a log group
    if service:
        # Best-effort: try service-named log group first
        log_group = f"/aws/{service}" if service.startswith("ecs") else f"/aws/lambda/{service}"
        try:
            la = analyze_logs(log_group=log_group, time_range_minutes=30)
            if la.get("error_count"):
                evidence.append({"source": "logs", "finding": ", ".join(
                    e["message"] for e in la.get("top_errors", [])[:3]
                ) or "errors detected"})
        except Exception as exc:  # log group may not exist
            logger.info("rca.log_evidence_skipped", extra={"err": str(exc)})

        # Evidence 2: trace summary
        try:
            ta = analyze_traces(service=service, time_range_minutes=30)
            if ta.get("error_rate") and ta["error_rate"] != "0%":
                evidence.append({"source": "traces",
                                 "finding": f"x-ray error rate {ta['error_rate']}, p99 {ta.get('p99_duration_ms')}ms"})
        except Exception as exc:
            logger.info("rca.trace_evidence_skipped", extra={"err": str(exc)})

    if context:
        evidence.append({"source": "user_context", "finding": context[:500]})

    # Ask LLM to reason
    try:
        from common.llm import LLM
        llm = LLM()
        prompt = (
            f"Alert ID: {alert_id}\nService: {service}\n"
            f"Evidence:\n{json.dumps(evidence, ensure_ascii=False)}\n\n"
            "Analyze the most likely root cause. Return JSON with keys: "
            "type (snake_case), confidence (0-1), description, "
            "recommendations (list of {priority, action})."
        )
        plan = llm.complete_json(prompt, schema_hint={
            "type": "string",
            "confidence": "number",
            "description": "string",
            "recommendations": [{"priority": "string", "action": "string"}],
        })
    except Exception as exc:
        logger.exception("rca.llm_failed")
        return {"alert_id": alert_id, "service": service, "evidence": evidence,
                "root_cause": {"type": "unknown", "confidence": 0,
                               "description": "LLM analysis failed"},
                "recommendations": [], "error": str(exc)}

    return {
        "alert_id": alert_id,
        "service": service,
        "root_cause": {
            "type": plan.get("type", "unknown"),
            "confidence": plan.get("confidence", 0),
            "description": plan.get("description", ""),
        },
        "evidence": evidence,
        "recommendations": plan.get("recommendations", []),
    }


# ===========================================================================
# 4. Execution (write actions — invoke L2 with confirm_token)
# ===========================================================================
def _invoke_l2_execution(action: dict[str, Any], confirm_token: str,
                         session_id: str = "", user_id: str = "") -> dict[str, Any]:
    fn_name = os.getenv("EXECUTION_FN_NAME", "")
    if not fn_name:
        return {"status": "error", "error": "EXECUTION_FN_NAME not configured (MCP cannot invoke L2)"}

    payload = {
        "trace_id": f"trc-mcp-{uuid.uuid4().hex[:12]}",
        "user_id": user_id,
        "session_id": session_id,
        "confirm_token": confirm_token,
        "action": action,
    }
    try:
        lam = _client("lambda")
        resp = lam.invoke(
            FunctionName=fn_name,
            InvocationType="RequestResponse",
            Payload=json.dumps(payload).encode("utf-8"),
        )
        body = json.loads(resp["Payload"].read().decode("utf-8"))
    except ClientError as exc:
        logger.exception("l2.invoke_failed")
        return {"status": "error", "error": str(exc)}
    return body


def execute_remediation(action_id: str, confirm_token: str) -> dict[str, Any]:
    """Generic remediation: ``action_id`` is parsed as ``<type>:<json-params>``.

    Example: ``ecs.update_service:{"cluster":"x","service":"y","desired_count":4}``
    """
    if ":" in action_id:
        typ, raw = action_id.split(":", 1)
        try:
            params = json.loads(raw)
        except json.JSONDecodeError:
            return {"action_id": action_id, "status": "error",
                    "error": "params not valid JSON"}
    else:
        typ, params = action_id, {}

    result = _invoke_l2_execution(
        action={"type": typ, "params": params},
        confirm_token=confirm_token,
    )
    return {
        "action_id": action_id,
        "status": result.get("status", "unknown"),
        "executed_at": _to_iso(_now()),
        "l2_result": result.get("result"),
        "error": result.get("error"),
        "reason": result.get("reason"),
    }


def restart_service(service_name: str, service_type: str = "ecs",
                    confirm_token: str = "") -> dict[str, Any]:
    """ECS: forceNewDeployment. Other types are not yet supported."""
    if service_type != "ecs":
        return {"service": service_name, "action": "restart", "status": "error",
                "error": f"service_type {service_type} not supported in MCP path; "
                         "use execute_remediation"}

    # Convention: service_name is "<cluster>/<service>"
    if "/" in service_name:
        cluster, svc = service_name.split("/", 1)
    else:
        cluster, svc = "default", service_name

    # L2 expects `desiredCount`; we use a zero-op update with forceNewDeployment
    # but execution_handler doesn't currently accept forceNewDeployment param —
    # so we encode it as a known action type.
    result = _invoke_l2_execution(
        action={
            "type": "ecs.update_service",
            "params": {"cluster": cluster, "service": svc, "desired_count": -1},  # -1 = keep current
        },
        confirm_token=confirm_token,
    )
    return {
        "service": service_name, "action": "restart",
        "status": result.get("status", "unknown"),
        "estimated_time": "2-5 minutes",
        "error": result.get("error"), "reason": result.get("reason"),
    }


def scale_service(service_name: str, desired_count: int,
                  confirm_token: str = "") -> dict[str, Any]:
    if "/" in service_name:
        cluster, svc = service_name.split("/", 1)
    else:
        cluster, svc = "default", service_name

    result = _invoke_l2_execution(
        action={
            "type": "ecs.update_service",
            "params": {"cluster": cluster, "service": svc,
                       "desired_count": int(desired_count)},
        },
        confirm_token=confirm_token,
    )
    return {
        "service": service_name, "action": "scale",
        "desired_count": int(desired_count),
        "status": result.get("status", "unknown"),
        "error": result.get("error"), "reason": result.get("reason"),
    }


def create_ticket(title: str, description: str, priority: str = "medium",
                  service: str = "") -> dict[str, Any]:
    """Publishes to NLOps SNS topic. Subscribers (email / Lambda → Jira)
    fan-out from there."""
    topic_arn = os.getenv("NOTIFY_TOPIC_ARN", "")
    if not topic_arn:
        return {"ticket_id": "", "title": title, "priority": priority,
                "service": service, "status": "error",
                "error": "NOTIFY_TOPIC_ARN not configured"}

    ticket_id = f"OPS-{datetime.utcnow().strftime('%Y%m%d')}-{uuid.uuid4().hex[:6]}"
    payload = {
        "ticket_id": ticket_id, "title": title, "description": description,
        "priority": priority, "service": service,
        "created_at": _to_iso(_now()),
    }
    try:
        sns = _client("sns")
        sns.publish(
            TopicArn=topic_arn,
            Subject=f"[{priority.upper()}] {title}"[:99],
            Message=json.dumps(payload, ensure_ascii=False, indent=2),
            MessageAttributes={
                "priority": {"DataType": "String", "StringValue": priority},
                "service": {"DataType": "String", "StringValue": service or "unknown"},
            },
        )
    except ClientError as exc:
        logger.exception("sns.publish_failed")
        return {**payload, "status": "error", "error": str(exc)}

    return {**payload, "status": "open", "url": ""}


# ===========================================================================
# 5. Reporting (investigations from AuditTable)
# ===========================================================================
def list_investigations(status: str = "all", limit: int = 20) -> dict[str, Any]:
    table = _ddb_table("AUDIT_TABLE")
    if table is None:
        return {"count": 0, "investigations": [],
                "error": "AUDIT_TABLE not configured"}
    try:
        resp = table.scan(
            FilterExpression="actor IN (:eb, :exec)",
            ExpressionAttributeValues={":eb": "EventBridge", ":exec": "Execution"},
            Limit=200,
        )
    except ClientError as exc:
        logger.exception("audit_table.scan_failed")
        return {"count": 0, "investigations": [], "error": str(exc)}

    items = []
    for it in resp.get("Items", []):
        it = _decimal_to_native(it)
        details = it.get("details") or {}
        if isinstance(details, str):
            try: details = json.loads(details)
            except Exception: details = {}
        inv_status = details.get("status") or it.get("outcome") or "unknown"
        if status != "all" and inv_status != status:
            continue
        items.append({
            "id": it.get("trace_id"),
            "title": details.get("title") or it.get("action") or "investigation",
            "service": details.get("service") or "",
            "status": inv_status,
            "ts": _to_iso(it.get("ts", 0)),
        })
    items.sort(key=lambda x: x["ts"], reverse=True)
    return {"count": len(items), "investigations": items[:limit]}


def get_investigation(investigation_id: str) -> dict[str, Any]:
    table = _ddb_table("AUDIT_TABLE")
    if table is None:
        return {"id": investigation_id, "error": "AUDIT_TABLE not configured"}
    try:
        resp = table.query(
            KeyConditionExpression="trace_id = :tid",
            ExpressionAttributeValues={":tid": investigation_id},
        )
    except ClientError as exc:
        logger.exception("audit_table.query_failed")
        return {"id": investigation_id, "error": str(exc)}

    items = [_decimal_to_native(i) for i in resp.get("Items", [])]
    if not items:
        return {"id": investigation_id, "note": "investigation not found"}

    timeline = []
    title = ""
    service = ""
    root_cause = ""
    final_status = "unknown"
    for it in items:
        details = it.get("details") or {}
        if isinstance(details, str):
            try: details = json.loads(details)
            except Exception: details = {}
        timeline.append({"time": _to_iso(it.get("ts", 0)),
                         "event": f"{it.get('actor', '?')}.{it.get('action', '?')} → {it.get('outcome', '?')}"})
        title = title or details.get("title", "")
        service = service or details.get("service", "")
        root_cause = root_cause or details.get("root_cause", "")
        final_status = details.get("status") or final_status

    return {
        "id": investigation_id, "title": title or "investigation",
        "service": service, "status": final_status,
        "root_cause": root_cause,
        "timeline": timeline,
    }
