"""NLOps MCP Tools — full capability surface.

6 categories of tools: discover / knowledge / analyze / execute / report.

Each entry is a thin shim that routes between two backends:

    MOCK_MODE=true   → return demo-canned data (kept inline for clarity)
    MOCK_MODE=false  → delegate to ``_real_impl`` which calls real AWS APIs

Default is MOCK_MODE=false (real). Set MOCK_MODE=true on the Lambda
environment when running the rehearsal demo to get reproducible canned
results.

Constraints (from DOA docs):
  - Tool name ≤ 64 chars
  - Write operations require confirm_token
  - Sanitize outputs to prevent prompt injection
"""
from __future__ import annotations

import os
from datetime import datetime, timedelta
from typing import Any

import boto3

from . import _real_impl
from .server import McpServer

server = McpServer()

# ---------------------------------------------------------------------------
# MOCK_MODE switch
# ---------------------------------------------------------------------------
def _is_mock() -> bool:
    """Read at call time so tests / runtime overrides take effect."""
    return os.getenv("MOCK_MODE", "false").strip().lower() in ("1", "true", "yes")


# ---------------------------------------------------------------------------
# Cached AWS clients (used by the small set of tools that already call real
# APIs even in mock mode — discovery / alerts).
# ---------------------------------------------------------------------------
_REGION = os.getenv("AWS_REGION", "us-east-1")
_clients: dict[str, Any] = {}


def _client(name: str):
    if name not in _clients:
        _clients[name] = boto3.client(name, region_name=_REGION)
    return _clients[name]


# ============================================================
# 1. Resource Discovery
# ============================================================

@server.tool
def discover_resources(resource_type: str = "all", region: str = "", tags: str = "") -> dict[str, Any]:
    """Discover AWS resources (EC2 / ECS / RDS / ELB / Lambda / S3 / DynamoDB / SNS / SQS / API Gateway).

    Args:
        resource_type: resource type (ec2|ecs|rds|elb|lambda|s3|dynamodb|sns|sqs|apigw|all). Case-insensitive.
        region: AWS region; defaults to the Lambda region
        tags: tag filter, e.g. "Env=prod,Team=core"
    """
    region = region or _REGION
    rt = (resource_type or "all").strip().lower()
    # Normalize a few common aliases the LLM might emit
    rt = {"ec2-instance": "ec2", "ecs-service": "ecs", "rds-instance": "rds",
          "elasticloadbalancing": "elb", "elb-v2": "elb", "alb": "elb",
          "nlb": "elb", "lambda-function": "lambda",
          "s3-bucket": "s3", "bucket": "s3",
          "dynamodb-table": "dynamodb", "ddb": "dynamodb", "table": "dynamodb",
          "sns-topic": "sns", "topic": "sns",
          "sqs-queue": "sqs", "queue": "sqs",
          "api-gateway": "apigw", "apigateway": "apigw", "rest-api": "apigw",
          "api": "apigw"}.get(rt, rt)

    if _is_mock():
        return {
            "resource_type": rt, "region": region, "count": 7,
            "resources": [
                {"type": "ec2-instance", "name": "demo-app-1", "instance_id": "i-mock0001",
                 "state": "running", "instance_type": "t3.medium", "region": region},
                {"type": "ecs-service", "name": "payment-api", "cluster": "demo", "region": region},
                {"type": "rds-instance", "name": "payment-db", "engine": "mysql", "region": region},
                {"type": "s3-bucket", "name": "demo-reports", "region": region},
                {"type": "dynamodb-table", "name": "demo-sessions", "region": region},
                {"type": "sns-topic", "name": "demo-alerts", "region": region},
                {"type": "sqs-queue", "name": "demo-tasks", "region": region},
            ],
        }

    resources = []
    errors: list[str] = []

    def _safe(label: str, fn):
        try:
            fn()
        except Exception as exc:  # pragma: no cover - graceful per-service degrade
            errors.append(f"{label}: {exc}")

    # EC2 instances
    if rt in ("ec2", "all"):
        def _do_ec2():
            ec2 = boto3.client("ec2", region_name=region)
            paginator = ec2.get_paginator("describe_instances")
            for page in paginator.paginate():
                for rsv in page.get("Reservations", []):
                    for inst in rsv.get("Instances", []):
                        name = next(
                            (t["Value"] for t in inst.get("Tags", []) if t["Key"] == "Name"),
                            "",
                        )
                        resources.append({
                            "type": "ec2-instance",
                            "name": name or inst["InstanceId"],
                            "instance_id": inst["InstanceId"],
                            "state": inst.get("State", {}).get("Name"),
                            "instance_type": inst.get("InstanceType"),
                            "az": inst.get("Placement", {}).get("AvailabilityZone"),
                            "private_ip": inst.get("PrivateIpAddress"),
                            "public_ip": inst.get("PublicIpAddress"),
                            "launch_time": (inst.get("LaunchTime").isoformat()
                                            if inst.get("LaunchTime") else None),
                            "region": region,
                        })
        _safe("ec2", _do_ec2)

    # ECS services
    if rt in ("ecs", "all"):
        def _do_ecs():
            ecs = boto3.client("ecs", region_name=region)
            for cluster in ecs.list_clusters().get("clusterArns", []):
                cluster_name = cluster.split("/")[-1]
                for svc_arn in ecs.list_services(cluster=cluster_name).get("serviceArns", []):
                    resources.append({
                        "type": "ecs-service",
                        "name": svc_arn.split("/")[-1],
                        "cluster": cluster_name,
                        "arn": svc_arn,
                        "region": region,
                    })
        _safe("ecs", _do_ecs)

    # RDS instances
    if rt in ("rds", "all"):
        def _do_rds():
            rds = boto3.client("rds", region_name=region)
            for db in rds.describe_db_instances().get("DBInstances", []):
                resources.append({
                    "type": "rds-instance", "name": db["DBInstanceIdentifier"],
                    "engine": db.get("Engine"), "status": db.get("DBInstanceStatus"),
                    "arn": db["DBInstanceArn"], "region": region,
                })
        _safe("rds", _do_rds)

    # ELB v2 (ALB / NLB)
    if rt in ("elb", "all"):
        def _do_elb():
            elb = boto3.client("elbv2", region_name=region)
            for lb in elb.describe_load_balancers().get("LoadBalancers", []):
                resources.append({
                    "type": "elb", "name": lb["LoadBalancerName"],
                    "lb_type": lb.get("Type"),
                    "dns_name": lb.get("DNSName"), "arn": lb["LoadBalancerArn"],
                    "region": region,
                })
        _safe("elb", _do_elb)

    # Lambda functions
    if rt in ("lambda", "all"):
        def _do_lambda():
            lam = boto3.client("lambda", region_name=region)
            paginator = lam.get_paginator("list_functions")
            for page in paginator.paginate():
                for fn in page.get("Functions", []):
                    resources.append({
                        "type": "lambda-function",
                        "name": fn["FunctionName"],
                        "runtime": fn.get("Runtime"),
                        "memory_mb": fn.get("MemorySize"),
                        "arn": fn["FunctionArn"],
                        "last_modified": fn.get("LastModified"),
                        "region": region,
                    })
        _safe("lambda", _do_lambda)

    # S3 buckets (region-agnostic — list_buckets returns all)
    if rt in ("s3", "all"):
        def _do_s3():
            s3 = boto3.client("s3", region_name=region)
            for b in s3.list_buckets().get("Buckets", []):
                # Get bucket region (s3 list_buckets doesn't include it)
                try:
                    loc = s3.get_bucket_location(Bucket=b["Name"]).get("LocationConstraint")
                    bucket_region = loc or "us-east-1"
                except Exception:
                    bucket_region = "unknown"
                # Filter by current region (s3 buckets are global but live in one region)
                if rt == "s3" or bucket_region == region:
                    resources.append({
                        "type": "s3-bucket",
                        "name": b["Name"],
                        "region": bucket_region,
                        "created": (b.get("CreationDate").isoformat()
                                    if b.get("CreationDate") else None),
                    })
        _safe("s3", _do_s3)

    # DynamoDB tables
    if rt in ("dynamodb", "all"):
        def _do_ddb():
            ddb = boto3.client("dynamodb", region_name=region)
            paginator = ddb.get_paginator("list_tables")
            for page in paginator.paginate():
                for name in page.get("TableNames", []):
                    resources.append({
                        "type": "dynamodb-table",
                        "name": name,
                        "region": region,
                    })
        _safe("dynamodb", _do_ddb)

    # SNS topics
    if rt in ("sns", "all"):
        def _do_sns():
            sns = boto3.client("sns", region_name=region)
            paginator = sns.get_paginator("list_topics")
            for page in paginator.paginate():
                for t in page.get("Topics", []):
                    arn = t["TopicArn"]
                    resources.append({
                        "type": "sns-topic",
                        "name": arn.split(":")[-1],
                        "arn": arn,
                        "region": region,
                    })
        _safe("sns", _do_sns)

    # SQS queues
    if rt in ("sqs", "all"):
        def _do_sqs():
            sqs = boto3.client("sqs", region_name=region)
            urls = sqs.list_queues().get("QueueUrls", []) or []
            for url in urls:
                resources.append({
                    "type": "sqs-queue",
                    "name": url.split("/")[-1],
                    "url": url,
                    "region": region,
                })
        _safe("sqs", _do_sqs)

    # API Gateway REST APIs
    if rt in ("apigw", "all"):
        def _do_apigw():
            api = boto3.client("apigateway", region_name=region)
            paginator = api.get_paginator("get_rest_apis")
            for page in paginator.paginate():
                for r in page.get("items", []):
                    resources.append({
                        "type": "api-gateway-rest",
                        "name": r["name"],
                        "id": r["id"],
                        "endpoint_types": r.get("endpointConfiguration", {}).get("types", []),
                        "region": region,
                    })
        _safe("apigw", _do_apigw)

    out = {"resource_type": rt, "region": region,
           "count": len(resources), "resources": resources[:200]}
    if errors:
        out["errors"] = errors
    return out


@server.tool
def discover_alerts(severity: str = "all", service: str = "", limit: int = 20) -> dict[str, Any]:
    """Get active CloudWatch alarms.

    Args:
        severity: critical|warning|all
        service: filter alarm names containing this string
        limit: max records
    """
    if _is_mock():
        return {
            "severity_filter": severity, "service_filter": service, "count": 1,
            "alarms": [{
                "name": "payment-api-high-latency", "severity": "critical",
                "state": "ALARM", "metric": "TargetResponseTime",
                "namespace": "AWS/ApplicationELB", "threshold": 0.5,
                "updated": datetime.utcnow().isoformat(),
            }],
        }
    try:
        cw = _client("cloudwatch")
        alarms = []
        resp = cw.describe_alarms(StateValue="ALARM", MaxRecords=min(limit, 100))
        for alarm in resp.get("MetricAlarms", []):
            n = alarm["AlarmName"]
            sev = "critical" if any(k in n.lower() for k in ("critical", "high")) else "warning"
            if severity != "all" and sev != severity: continue
            if service and service.lower() not in n.lower(): continue
            ts = alarm.get("StateUpdatedTimestamp")
            alarms.append({
                "name": n, "severity": sev, "state": alarm["StateValue"],
                "metric": alarm.get("MetricName"), "namespace": alarm.get("Namespace"),
                "threshold": alarm.get("Threshold"),
                "updated": ts.isoformat() if ts else None,
            })
        return {"severity_filter": severity, "service_filter": service,
                "count": len(alarms), "alarms": alarms[:limit]}
    except Exception as exc:
        return {"error": str(exc), "alarms": []}


@server.tool
def discover_incidents(status: str = "open", time_range_hours: int = 24) -> dict[str, Any]:
    """Get recent incidents/outages.

    Args:
        status: open|resolved|all
        time_range_hours: lookback window in hours
    """
    if _is_mock():
        return {
            "status_filter": status, "time_range_hours": time_range_hours, "count": 2,
            "incidents": [
                {"id": "INC-001", "title": "payment-api 响应延迟", "status": "open",
                 "service": "payment-api",
                 "created": (datetime.utcnow() - timedelta(hours=2)).isoformat()},
                {"id": "INC-002", "title": "user-service 错误率上升", "status": "resolved",
                 "service": "user-service",
                 "created": (datetime.utcnow() - timedelta(hours=5)).isoformat()},
            ],
        }
    return _real_impl.discover_incidents(status=status, time_range_hours=time_range_hours)


# ============================================================
# 2. Knowledge Retrieval
# ============================================================

@server.tool
def query_knowledge_base(query: str, doc_type: str = "all") -> dict[str, Any]:
    """Query the ops knowledge base.

    Args:
        query: search keywords
        doc_type: runbook|architecture|faq|all
    """
    if _is_mock():
        return {
            "query": query, "doc_type": doc_type,
            "results": [
                {"title": "payment-api 故障排查指南", "type": "runbook",
                 "url": "https://wiki.internal/runbook/payment-api",
                 "excerpt": "常见问题包括：数据库连接超时、Redis 缓存失效...",
                 "relevance": 0.95},
                {"title": "支付服务架构说明", "type": "architecture",
                 "url": "https://wiki.internal/arch/payment",
                 "excerpt": "payment-api 是微服务架构中的支付网关...",
                 "relevance": 0.82},
            ],
        }
    return _real_impl.query_knowledge_base(query=query, doc_type=doc_type)


@server.tool
def search_runbooks(keywords: str, service: str = "") -> dict[str, Any]:
    """Search the runbook library.

    Args:
        keywords: search keywords
        service: optional service filter
    """
    if _is_mock():
        runbooks = [
            {"id": "RB-001", "title": "RDS 连接池耗尽处理", "service": "all",
             "tags": ["database", "rds"],
             "url": "https://wiki.internal/runbook/rds-connection-pool"},
            {"id": "RB-002", "title": "ECS 服务重启流程", "service": "all",
             "tags": ["ecs", "restart"],
             "url": "https://wiki.internal/runbook/ecs-restart"},
            {"id": "RB-003", "title": "API 响应延迟排查", "service": "api",
             "tags": ["latency"],
             "url": "https://wiki.internal/runbook/api-latency"},
        ]
        kw = keywords.lower()
        filtered = [rb for rb in runbooks
                    if kw in rb["title"].lower() or any(kw in t for t in rb["tags"])]
        if service:
            filtered = [rb for rb in filtered if service.lower() in rb["service"].lower()]
        return {"keywords": keywords, "service": service,
                "count": len(filtered), "runbooks": filtered}
    return _real_impl.search_runbooks(keywords=keywords, service=service)


@server.tool
def get_service_owner(service_name: str) -> dict[str, Any]:
    """Get the on-call team for a service.

    Args:
        service_name: service name
    """
    if _is_mock():
        catalog = {
            "payment-api": {"team": "payment-team", "on_call": "alice@example.com",
                            "slack": "#payment-alerts"},
            "user-service": {"team": "user-team", "on_call": "charlie@example.com",
                             "slack": "#user-alerts"},
            "order-service": {"team": "order-team", "on_call": "eve@example.com",
                              "slack": "#order-alerts"},
        }
        info = catalog.get(service_name, {"team": "unknown", "on_call": "oncall@example.com",
                                          "slack": "#general"})
        return {"service": service_name, **info,
                "runbook_url": f"https://wiki.internal/runbook/{service_name}"}
    return _real_impl.get_service_owner(service_name=service_name)


@server.tool
def get_service_dependencies(service_name: str) -> dict[str, Any]:
    """Get a service's upstream/downstream dependencies.

    Args:
        service_name: service name
    """
    if _is_mock():
        graph = {
            "payment-api": {"upstream": ["user-service", "order-service"],
                            "downstream": ["payment-gateway"],
                            "infrastructure": ["RDS-payment", "ElastiCache-payment"]},
            "user-service": {"upstream": ["auth-service"], "downstream": ["payment-api"],
                             "infrastructure": ["RDS-user"]},
            "order-service": {"upstream": ["user-service"], "downstream": ["payment-api"],
                              "infrastructure": ["RDS-order"]},
        }
        return {"service": service_name,
                **graph.get(service_name, {"upstream": [], "downstream": [],
                                            "infrastructure": []})}
    return _real_impl.get_service_dependencies(service_name=service_name)


# ============================================================
# 3. Analysis
# ============================================================

@server.tool
def analyze_logs(log_group: str, time_range_minutes: int = 30,
                 pattern: str = "", limit: int = 100) -> dict[str, Any]:
    """Analyze CloudWatch Logs (errors / patterns).

    Args:
        log_group: log group name
        time_range_minutes: lookback window in minutes
        pattern: optional CloudWatch Logs filter pattern
        limit: max events to inspect for top-error grouping
    """
    if _is_mock():
        return {
            "log_group": log_group, "time_range_minutes": time_range_minutes,
            "pattern": pattern, "total_lines": 1250,
            "error_count": 23, "error_rate": "1.84%",
            "top_errors": [
                {"count": 12, "message": "Connection timeout to RDS"},
                {"count": 8,  "message": "Redis connection refused"},
            ],
        }
    return _real_impl.analyze_logs(log_group=log_group,
                                   time_range_minutes=time_range_minutes,
                                   pattern=pattern, limit=limit)


@server.tool
def analyze_metrics(namespace: str, metric_name: str, dimensions: str = "",
                    period: int = 60, time_range_minutes: int = 30) -> dict[str, Any]:
    """Analyze CloudWatch metrics.

    Args:
        namespace: e.g. AWS/ApplicationELB
        metric_name: e.g. TargetResponseTime
        dimensions: comma-separated Name=Value pairs
        period: aggregation period in seconds (>=60)
        time_range_minutes: lookback window in minutes
    """
    if _is_mock():
        return {
            "namespace": namespace, "metric_name": metric_name,
            "statistics": {"avg": 45.2, "max": 89.3, "min": 12.1},
            "datapoints": [
                {"timestamp": "2026-05-18T02:00:00Z", "average": 45.2},
                {"timestamp": "2026-05-18T02:01:00Z", "average": 52.8},
            ],
        }
    return _real_impl.analyze_metrics(namespace=namespace, metric_name=metric_name,
                                      dimensions=dimensions, period=period,
                                      time_range_minutes=time_range_minutes)


@server.tool
def analyze_traces(service: str, trace_id: str = "",
                   time_range_minutes: int = 30) -> dict[str, Any]:
    """Analyze X-Ray traces (service summary or single trace).

    Args:
        service: service name (X-Ray service)
        trace_id: optional trace id for deep-dive
        time_range_minutes: lookback window
    """
    if _is_mock():
        return {
            "service": service, "total_traces": 156,
            "avg_duration_ms": 234, "p99_duration_ms": 1200,
            "error_rate": "2.3%",
            "slow_segments": [
                {"service": "RDS", "avg_duration_ms": 89},
                {"service": "Redis", "avg_duration_ms": 12},
            ],
        }
    return _real_impl.analyze_traces(service=service, trace_id=trace_id,
                                     time_range_minutes=time_range_minutes)


@server.tool
def analyze_root_cause(alert_id: str = "", service: str = "",
                       context: str = "") -> dict[str, Any]:
    """Root-cause analysis (LLM over collected evidence).

    Args:
        alert_id: optional alert id
        service: service name to focus on
        context: extra context to feed the LLM
    """
    if _is_mock():
        return {
            "alert_id": alert_id, "service": service,
            "root_cause": {"type": "database_connection_pool_exhaustion",
                           "confidence": 0.85,
                           "description": "RDS 连接池达到上限"},
            "evidence": [
                {"source": "logs", "finding": "大量 'Connection timeout' 错误"},
                {"source": "metrics", "finding": "数据库连接数达到 max_connections"},
            ],
            "recommendations": [
                {"priority": "high", "action": "增加 RDS max_connections 参数"},
                {"priority": "medium", "action": "检查是否有连接泄漏"},
            ],
        }
    return _real_impl.analyze_root_cause(alert_id=alert_id, service=service,
                                          context=context)


# ============================================================
# 4. Execution (write — confirm_token required)
# ============================================================

@server.tool
def execute_remediation(action_id: str, confirm_token: str) -> dict[str, Any]:
    """Execute a predefined remediation action.

    Args:
        action_id: ``<type>:<json-params>`` (e.g.
            ``ecs.update_service:{"cluster":"x","service":"y","desired_count":4}``)
        confirm_token: single-use token issued by L1 Orchestrator
    """
    if _is_mock():
        return {"action_id": action_id, "status": "executed",
                "executed_at": datetime.utcnow().isoformat()}
    return _real_impl.execute_remediation(action_id=action_id,
                                           confirm_token=confirm_token)


@server.tool
def restart_service(service_name: str, service_type: str = "ecs",
                    confirm_token: str = "") -> dict[str, Any]:
    """Restart a service.

    Args:
        service_name: ECS use ``<cluster>/<service>`` form
        service_type: ecs (currently the only supported type)
        confirm_token: single-use token issued by L1 Orchestrator
    """
    if _is_mock():
        return {"service": service_name, "action": "restart",
                "status": "initiated", "estimated_time": "2-5 minutes"}
    return _real_impl.restart_service(service_name=service_name,
                                       service_type=service_type,
                                       confirm_token=confirm_token)


@server.tool
def scale_service(service_name: str, desired_count: int,
                  confirm_token: str = "") -> dict[str, Any]:
    """Adjust an ECS service's desired count.

    Args:
        service_name: ``<cluster>/<service>``
        desired_count: target task count
        confirm_token: single-use token issued by L1 Orchestrator
    """
    if _is_mock():
        return {"service": service_name, "action": "scale",
                "desired_count": desired_count, "status": "initiated"}
    return _real_impl.scale_service(service_name=service_name,
                                     desired_count=desired_count,
                                     confirm_token=confirm_token)


@server.tool
def create_ticket(title: str, description: str, priority: str = "medium",
                  service: str = "") -> dict[str, Any]:
    """Create an ops ticket (publishes to NLOps SNS topic).

    Args:
        title: ticket title
        description: detailed description
        priority: critical|high|medium|low
        service: associated service
    """
    if _is_mock():
        ticket_id = f"OPS-{datetime.utcnow().strftime('%Y%m%d')}-{hash(title) % 10000:04d}"
        return {"ticket_id": ticket_id, "title": title, "priority": priority,
                "service": service, "status": "open",
                "url": f"https://jira.internal/browse/{ticket_id}"}
    return _real_impl.create_ticket(title=title, description=description,
                                     priority=priority, service=service)


# ============================================================
# 5. Reporting
# ============================================================

@server.tool
def generate_report(investigation_id: str, format: str = "html") -> dict[str, Any]:
    """Generate a diagnostic HTML report (writes to S3).

    Args:
        investigation_id: investigation id
        format: html|markdown|json
    """
    try:
        from report.generator import ReportGenerator

        finding = _get_investigation_finding(investigation_id)
        bucket = os.getenv("REPORT_BUCKET", "")
        if not bucket:
            return {"investigation_id": investigation_id, "format": format,
                    "status": "error", "error": "REPORT_BUCKET not configured"}

        generator = ReportGenerator(bucket=bucket)
        url = generator.render_and_upload(
            finding=finding, kind="diagnostic", trace_id=investigation_id,
        )
        return {
            "investigation_id": investigation_id,
            "report_id": f"rpt-{investigation_id}",
            "format": format, "status": "generated", "url": url,
            "summary": {
                "title": finding.get("title", ""),
                "root_cause": finding.get("root_cause", ""),
                "severity": finding.get("severity", "info"),
            },
        }
    except Exception as exc:
        report_id = f"RPT-{datetime.utcnow().strftime('%Y%m%d%H%M%S')}"
        return {"investigation_id": investigation_id, "report_id": report_id,
                "format": format, "status": "error", "error": str(exc)}


def _get_investigation_finding(investigation_id: str) -> dict[str, Any]:
    """Build the finding payload used by the report template."""
    if _is_mock():
        return {
            "title": f"调查报告 · {investigation_id}", "severity": "high",
            "investigation_id": investigation_id,
            "operator_portal_url":
                f"https://console.aws.amazon.com/aidevops/spaces/space-001/tasks/{investigation_id}",
            "timeline": [
                {"ts": "2026-05-18T02:00:00Z", "event": "问题触发"},
                {"ts": "2026-05-18T02:05:00Z", "event": "开始调查"},
                {"ts": "2026-05-18T02:15:00Z", "event": "定位根因"},
                {"ts": "2026-05-18T02:20:00Z", "event": "生成报告"},
            ],
            "root_cause": "RDS 连接池耗尽导致服务响应延迟",
            "fix_steps": [
                {"action": "增加 RDS max_connections 参数", "risk": "low", "auto": True},
                {"action": "检查是否有连接泄漏", "risk": "low", "auto": False},
            ],
            "evidence": {
                "trace_ids": ["1-66a01234-abc"],
                "log_snippets": [
                    "ERROR: ConnectionPoolExhausted",
                    "P99 latency: 200ms -> 3200ms",
                ],
            },
        }

    inv = _real_impl.get_investigation(investigation_id)
    return {
        "title": inv.get("title", f"investigation · {investigation_id}"),
        "severity": "high",
        "investigation_id": investigation_id,
        "operator_portal_url":
            f"https://console.aws.amazon.com/aidevops/spaces/{os.getenv('DOA_AGENT_SPACE_ID', 'unknown')}/tasks/{investigation_id}",
        "timeline": inv.get("timeline", []),
        "root_cause": inv.get("root_cause", ""),
        "fix_steps": [],
        "evidence": {"trace_ids": [], "log_snippets": []},
    }


@server.tool
def list_investigations(status: str = "all", limit: int = 20) -> dict[str, Any]:
    """List recent investigations.

    Args:
        status: open|in_progress|resolved|all
        limit: max records
    """
    if _is_mock():
        investigations = [
            {"id": "INV-001", "title": "payment-api 响应延迟",
             "service": "payment-api", "status": "resolved"},
            {"id": "INV-002", "title": "user-service 错误率上升",
             "service": "user-service", "status": "in_progress"},
        ]
        filtered = [i for i in investigations if status == "all" or i["status"] == status]
        return {"count": len(filtered), "investigations": filtered[:limit]}
    return _real_impl.list_investigations(status=status, limit=limit)


@server.tool
def get_investigation(investigation_id: str) -> dict[str, Any]:
    """Get a single investigation's detail.

    Args:
        investigation_id: investigation id
    """
    if _is_mock():
        return {
            "id": investigation_id, "title": "payment-api 响应延迟",
            "service": "payment-api", "status": "resolved",
            "root_cause": "数据库连接池耗尽",
            "timeline": [
                {"time": "01:00", "event": "告警触发"},
                {"time": "01:15", "event": "定位根因"},
                {"time": "01:45", "event": "问题解决"},
            ],
        }
    return _real_impl.get_investigation(investigation_id=investigation_id)


# ============================================================
# 6. Smart / High-level Tools (added in v3 — Strands + DOA)
# ============================================================

@server.tool
def smart_diagnose(query: str, user_id: str = "quick-desktop") -> dict[str, Any]:
    """One-stop SRE diagnosis: routes via Strands Agent → DOA → HTML report.

    Use this for high-level questions like "X 服务为什么慢" / "early-morning patrol".
    Internally drives the full L1 agent stack (Discovery + Analysis + Knowledge +
    Report) through the Strands Agents SDK, which calls AWS DevOps Agent under
    the hood and produces an HTML diagnostic page.

    Args:
        query: Natural-language SRE question.
        user_id: Caller identity (defaults to 'quick-desktop' when invoked via MCP).

    Returns:
        ``{text, html_url, engine, model, trace_id}``
    """
    import uuid as _uuid
    if _is_mock():
        return {
            "text": "已诊断完成（mock）。检测到 RDS 连接池耗尽。",
            "html_url": "https://s3.amazonaws.com/nlops-reports/mock-diagnostic.html",
            "engine": "strands-agents",
            "model": os.getenv("BEDROCK_MODEL_ID", "amazon.nova-pro-v1:0"),
            "trace_id": f"trc-mock-{_uuid.uuid4().hex[:8]}",
        }

    try:
        from agents.base import AgentContext
        from orchestrator.factory import build_default

        trace_id = f"trc-mcp-{_uuid.uuid4().hex[:12]}"
        ctx = AgentContext(
            trace_id=trace_id,
            user_id=user_id,
            session_id=f"sess-mcp-{_uuid.uuid4().hex[:8]}",
            channel="quick-desktop-mcp",
        )
        orch = build_default()
        result = orch.run(ctx, query)
        return {
            "text": result.get("text", ""),
            "engine": result.get("engine", "strands-agents"),
            "model": result.get("model"),
            "trace_id": trace_id,
            "html_url": _extract_url_from_text(result.get("text", "")),
        }
    except Exception as exc:
        return {"error": str(exc), "engine": "strands-agents", "text": ""}


def _extract_url_from_text(text: str) -> str:
    """Best-effort: extract first https URL from agent text reply."""
    import re
    m = re.search(r'https://\S+', text or "")
    return m.group(0) if m else ""


@server.tool
def consult_devops_agent(question: str, user_id: str = "quick-desktop") -> dict[str, Any]:
    """Direct one-shot chat with AWS DevOps Agent (5-30 seconds).

    Use this when you want DOA's expert opinion on AWS infrastructure but don't
    need a full investigation. Cheaper than smart_diagnose and faster.

    Args:
        question: Natural-language question for DOA.
        user_id: Caller identity (defaults to 'quick-desktop').
    """
    if _is_mock():
        return {
            "answer": "(mock DOA reply) The service appears healthy with normal latency.",
            "session_id": "mock-doa-session",
            "engine": "aws-devops-agent",
        }
    try:
        from tools.devops_agent import DevOpsAgentTool
        doa = DevOpsAgentTool()
        answer = doa.chat(question, user_id=user_id)
        return {
            "answer": answer,
            "engine": "aws-devops-agent",
            "agent_space_id": os.getenv("DOA_AGENT_SPACE_ID", ""),
        }
    except Exception as exc:
        return {"error": str(exc), "answer": "", "engine": "aws-devops-agent"}


@server.tool
def request_confirm_token(action_type: str, params_json: str = "{}",
                          risk: str = "medium",
                          user_id: str = "quick-desktop",
                          session_id: str = "") -> dict[str, Any]:
    """Issue a single-use confirmation token for a write action.

    The CALLER (Quick Desktop's LLM or the user) MUST:
      1. Show the user the action description and risk level.
      2. Wait for explicit user confirmation.
      3. Pass the returned ``confirm_token`` to write tools like
         ``scale_service`` / ``restart_service`` / ``execute_remediation``.

    Tokens are single-use, expire in 5 minutes, and are bound to ``user_id`` +
    ``session_id``. The L2 Execution Lambda re-validates the token before any
    AWS API write happens.

    Args:
        action_type: Like ``ecs.update_service`` / ``ec2.reboot_instances``.
        params_json: JSON of parameters (e.g. ``{"cluster":"x","service":"y","desired_count":4}``).
        risk: ``low | medium | high`` (display hint to user).
        user_id: Calling user (must match later write call).
        session_id: Session id (must match later write call).
    """
    import time as _time
    import uuid as _uuid

    token = f"ct-{_uuid.uuid4().hex}"
    issued_at = int(_time.time())
    expires_at = issued_at + 300  # 5 min

    if _is_mock():
        return {
            "confirm_token": token,
            "action_type": action_type,
            "params": params_json,
            "risk": risk,
            "expires_at": expires_at,
            "instructions": "Show the risk to the user and only call the write tool after explicit confirmation.",
            "_mock": True,
        }

    table_name = os.getenv("CONFIRM_TOKENS_TABLE", "")
    if not table_name:
        return {"error": "CONFIRM_TOKENS_TABLE not configured",
                "confirm_token": "", "expires_at": 0}

    try:
        ddb = boto3.resource("dynamodb", region_name=_REGION).Table(table_name)
        ddb.put_item(Item={
            "token": token,
            "user_id": user_id,
            "session_id": session_id or "mcp-stateless",
            "action_type": action_type,
            "params": params_json,
            "risk": risk,
            "issued_at": issued_at,
            "expires_at": expires_at,
            "ttl": expires_at + 300,  # DDB TTL slack
            "used": False,
        })
    except Exception as exc:
        return {"error": str(exc), "confirm_token": "", "expires_at": 0}

    return {
        "confirm_token": token,
        "action_type": action_type,
        "params": params_json,
        "risk": risk,
        "expires_at": expires_at,
        "instructions": (
            f"Action: {action_type} with params {params_json}. "
            f"Risk: {risk}. Show this to the user; only call the write tool "
            f"with confirm_token={token} after they confirm. Token expires in 5 minutes."
        ),
    }
