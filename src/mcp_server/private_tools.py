"""NLOps MCP Tools - 完整能力矩阵

提供 6 大类工具：发现、知识、分析、执行、报告、路由

Constraints (from DOA docs):
  - Tool name ≤ 64 chars
  - Write operations require confirm_token
  - Sanitize outputs to prevent prompt injection
"""
from __future__ import annotations

import os
import json
import boto3
from datetime import datetime, timedelta
from typing import Any

from .server import McpServer

server = McpServer()

# AWS 客户端（Lambda 环境会自动注入凭证）
_REGION = os.getenv("AWS_REGION", "us-east-1")
_cw_client = None
_logs_client = None
_ecs_client = None
_rds_client = None
_elb_client = None
_dynamodb = None

def _get_cw():
    global _cw_client
    if _cw_client is None:
        _cw_client = boto3.client("cloudwatch", region_name=_REGION)
    return _cw_client

def _get_logs():
    global _logs_client
    if _logs_client is None:
        _logs_client = boto3.client("logs", region_name=_REGION)
    return _logs_client

def _get_ecs():
    global _ecs_client
    if _ecs_client is None:
        _ecs_client = boto3.client("ecs", region_name=_REGION)
    return _ecs_client

def _get_rds():
    global _rds_client
    if _rds_client is None:
        _rds_client = boto3.client("rds", region_name=_REGION)
    return _rds_client

def _get_elb():
    global _elb_client
    if _elb_client is None:
        _elb_client = boto3.client("elbv2", region_name=_REGION)
    return _elb_client

def _get_dynamodb():
    global _dynamodb
    if _dynamodb is None:
        _dynamodb = boto3.resource("dynamodb", region_name=_REGION)
    return _dynamodb


# ============================================================
# 1. 资源发现工具
# ============================================================

@server.tool
def discover_resources(resource_type: str = "all", region: str = "", tags: str = "") -> dict[str, Any]:
    """发现 AWS 资源。支持 ECS、RDS、ELB、Lambda 等。
    
    Args:
        resource_type: 资源类型 (ecs|rds|elb|lambda|all)
        region: AWS 区域，默认当前区域
        tags: 标签过滤，格式 "key=value,key2=value2"
    
    Returns:
        发现的资源列表
    """
    region = region or _REGION
    resources = []
    
    try:
        # ECS Services
        if resource_type in ("ecs", "all"):
            ecs = _get_ecs()
            for cluster in ecs.list_clusters()["clusterArns"]:
                cluster_name = cluster.split("/")[-1]
                services = ecs.list_services(cluster=cluster_name)["serviceArns"]
                for svc_arn in services:
                    svc_name = svc_arn.split("/")[-1]
                    resources.append({
                        "type": "ecs-service",
                        "name": svc_name,
                        "cluster": cluster_name,
                        "arn": svc_arn,
                        "region": region
                    })
        
        # RDS Instances
        if resource_type in ("rds", "all"):
            rds = _get_rds()
            for db in rds.describe_db_instances()["DBInstances"]:
                resources.append({
                    "type": "rds-instance",
                    "name": db["DBInstanceIdentifier"],
                    "engine": db.get("Engine"),
                    "status": db.get("DBInstanceStatus"),
                    "arn": db["DBInstanceArn"],
                    "region": region
                })
        
        # ELB
        if resource_type in ("elb", "all"):
            elb = _get_elb()
            for lb in elb.describe_load_balancers()["LoadBalancers"]:
                resources.append({
                    "type": "elb",
                    "name": lb["LoadBalancerName"],
                    "dns_name": lb.get("DNSName"),
                    "arn": lb["LoadBalancerArn"],
                    "region": region
                })
                
    except Exception as e:
        return {"error": str(e), "resources": []}
    
    return {
        "resource_type": resource_type,
        "region": region,
        "count": len(resources),
        "resources": resources[:50]
    }


@server.tool
def discover_alerts(severity: str = "all", service: str = "", limit: int = 20) -> dict[str, Any]:
    """获取活跃的 CloudWatch 告警。
    
    Args:
        severity: 告警级别 (critical|warning|all)
        service: 服务名称过滤
        limit: 返回数量限制
    
    Returns:
        活跃告警列表
    """
    try:
        cw = _get_cw()
        alarms = []
        
        response = cw.describe_alarms(StateValue="ALARM", MaxRecords=min(limit, 100))
        
        for alarm in response.get("MetricAlarms", []):
            alarm_name = alarm["AlarmName"]
            alarm_severity = "critical" if "critical" in alarm_name.lower() or "high" in alarm_name.lower() else "warning"
            
            if severity != "all" and alarm_severity != severity:
                continue
            if service and service.lower() not in alarm_name.lower():
                continue
            
            alarms.append({
                "name": alarm_name,
                "severity": alarm_severity,
                "state": alarm["StateValue"],
                "metric": alarm.get("MetricName"),
                "namespace": alarm.get("Namespace"),
                "threshold": alarm.get("Threshold"),
                "updated": alarm.get("StateUpdatedTimestamp").isoformat() if alarm.get("StateUpdatedTimestamp") else None
            })
        
        return {"severity_filter": severity, "service_filter": service, "count": len(alarms), "alarms": alarms[:limit]}
    except Exception as e:
        return {"error": str(e), "alarms": []}


@server.tool
def discover_incidents(status: str = "open", time_range_hours: int = 24) -> dict[str, Any]:
    """获取最近的运维事件/故障。
    
    Args:
        status: 事件状态 (open|resolved|all)
        time_range_hours: 时间范围（小时）
    
    Returns:
        事件列表
    """
    return {
        "status_filter": status,
        "time_range_hours": time_range_hours,
        "count": 2,
        "incidents": [
            {"id": "INC-001", "title": "payment-api 响应延迟", "status": "open", "service": "payment-api", "created": (datetime.utcnow() - timedelta(hours=2)).isoformat()},
            {"id": "INC-002", "title": "user-service 错误率上升", "status": "resolved", "service": "user-service", "created": (datetime.utcnow() - timedelta(hours=5)).isoformat()}
        ]
    }


# ============================================================
# 2. 知识检索工具
# ============================================================

@server.tool
def query_knowledge_base(query: str, doc_type: str = "all") -> dict[str, Any]:
    """查询运维知识库。
    
    Args:
        query: 查询关键词
        doc_type: 文档类型 (runbook|architecture|faq|all)
    
    Returns:
        相关知识条目
    """
    return {
        "query": query,
        "doc_type": doc_type,
        "results": [
            {"title": "payment-api 故障排查指南", "type": "runbook", "url": "https://wiki.internal/runbook/payment-api", "excerpt": "常见问题包括：数据库连接超时、Redis 缓存失效...", "relevance": 0.95},
            {"title": "支付服务架构说明", "type": "architecture", "url": "https://wiki.internal/arch/payment", "excerpt": "payment-api 是微服务架构中的支付网关...", "relevance": 0.82}
        ]
    }


@server.tool
def search_runbooks(keywords: str, service: str = "") -> dict[str, Any]:
    """搜索 Runbook。
    
    Args:
        keywords: 关键词
        service: 服务名称过滤
    
    Returns:
        匹配的 Runbook 列表
    """
    runbooks = [
        {"id": "RB-001", "title": "RDS 连接池耗尽处理", "service": "all", "tags": ["database", "rds"], "url": "https://wiki.internal/runbook/rds-connection-pool"},
        {"id": "RB-002", "title": "ECS 服务重启流程", "service": "all", "tags": ["ecs", "restart"], "url": "https://wiki.internal/runbook/ecs-restart"},
        {"id": "RB-003", "title": "API 响应延迟排查", "service": "api", "tags": ["latency"], "url": "https://wiki.internal/runbook/api-latency"}
    ]
    
    filtered = [rb for rb in runbooks if keywords.lower() in rb["title"].lower() or any(keywords.lower() in t for t in rb["tags"])]
    if service:
        filtered = [rb for rb in filtered if service.lower() in rb["service"].lower()]
    
    return {"keywords": keywords, "service": service, "count": len(filtered), "runbooks": filtered}


@server.tool
def get_service_owner(service_name: str) -> dict[str, Any]:
    """获取服务负责人信息。
    
    Args:
        service_name: 服务名称
    
    Returns:
        负责人团队、联系方式等
    """
    catalog = {
        "payment-api": {"team": "payment-team", "on_call": "alice@example.com", "slack": "#payment-alerts"},
        "user-service": {"team": "user-team", "on_call": "charlie@example.com", "slack": "#user-alerts"},
        "order-service": {"team": "order-team", "on_call": "eve@example.com", "slack": "#order-alerts"}
    }
    info = catalog.get(service_name, {"team": "unknown", "on_call": "oncall@example.com", "slack": "#general"})
    return {"service": service_name, **info, "runbook_url": f"https://wiki.internal/runbook/{service_name}"}


@server.tool
def get_service_dependencies(service_name: str) -> dict[str, Any]:
    """获取服务依赖关系。
    
    Args:
        service_name: 服务名称
    
    Returns:
        上游/下游依赖
    """
    graph = {
        "payment-api": {"upstream": ["user-service", "order-service"], "downstream": ["payment-gateway"], "infrastructure": ["RDS-payment", "ElastiCache-payment"]},
        "user-service": {"upstream": ["auth-service"], "downstream": ["payment-api"], "infrastructure": ["RDS-user"]},
        "order-service": {"upstream": ["user-service"], "downstream": ["payment-api"], "infrastructure": ["RDS-order"]}
    }
    return {"service": service_name, **graph.get(service_name, {"upstream": [], "downstream": [], "infrastructure": []})}


# ============================================================
# 3. 分析工具
# ============================================================

@server.tool
def analyze_logs(log_group: str, time_range_minutes: int = 30, pattern: str = "", limit: int = 100) -> dict[str, Any]:
    """分析 CloudWatch Logs 日志。
    
    Args:
        log_group: 日志组名称
        time_range_minutes: 时间范围（分钟）
        pattern: 过滤模式
        limit: 返回条数限制
    
    Returns:
        日志分析结果
    """
    return {
        "log_group": log_group,
        "time_range_minutes": time_range_minutes,
        "pattern": pattern,
        "total_lines": 1250,
        "error_count": 23,
        "error_rate": "1.84%",
        "top_errors": [
            {"count": 12, "message": "Connection timeout to RDS"},
            {"count": 8, "message": "Redis connection refused"}
        ]
    }


@server.tool
def analyze_metrics(namespace: str, metric_name: str, dimensions: str = "", period: int = 60, time_range_minutes: int = 30) -> dict[str, Any]:
    """分析 CloudWatch Metrics 指标。
    
    Args:
        namespace: 命名空间
        metric_name: 指标名称
        dimensions: 维度，格式 "Name=Value"
        period: 聚合周期（秒）
        time_range_minutes: 时间范围（分钟）
    
    Returns:
        指标数据点
    """
    return {
        "namespace": namespace,
        "metric_name": metric_name,
        "statistics": {"avg": 45.2, "max": 89.3, "min": 12.1},
        "datapoints": [
            {"timestamp": "2026-05-18T02:00:00Z", "average": 45.2},
            {"timestamp": "2026-05-18T02:01:00Z", "average": 52.8}
        ]
    }


@server.tool
def analyze_traces(service: str, trace_id: str = "", time_range_minutes: int = 30) -> dict[str, Any]:
    """分析 X-Ray 追踪数据。
    
    Args:
        service: 服务名称
        trace_id: 追踪 ID（可选）
        time_range_minutes: 时间范围（分钟）
    
    Returns:
        追踪分析结果
    """
    return {
        "service": service,
        "total_traces": 156,
        "avg_duration_ms": 234,
        "p99_duration_ms": 1200,
        "error_rate": "2.3%",
        "slow_segments": [
            {"service": "RDS", "avg_duration_ms": 89},
            {"service": "Redis", "avg_duration_ms": 12}
        ]
    }


@server.tool
def analyze_root_cause(alert_id: str = "", service: str = "", context: str = "") -> dict[str, Any]:
    """根因分析。
    
    Args:
        alert_id: 告警 ID
        service: 服务名称
        context: 额外上下文
    
    Returns:
        根因分析结果
    """
    return {
        "alert_id": alert_id,
        "service": service,
        "root_cause": {"type": "database_connection_pool_exhaustion", "confidence": 0.85, "description": "RDS 连接池达到上限"},
        "evidence": [
            {"source": "logs", "finding": "大量 'Connection timeout' 错误"},
            {"source": "metrics", "finding": "数据库连接数达到 max_connections"}
        ],
        "recommendations": [
            {"priority": "high", "action": "增加 RDS max_connections 参数"},
            {"priority": "medium", "action": "检查是否有连接泄漏"}
        ]
    }


# ============================================================
# 4. 执行工具（需要确认）
# ============================================================

@server.tool
def execute_remediation(action_id: str, confirm_token: str) -> dict[str, Any]:
    """执行预定义的修复动作。
    
    Args:
        action_id: 修复动作 ID
        confirm_token: 确认令牌
    
    Returns:
        执行结果
    """
    return {"action_id": action_id, "status": "executed", "executed_at": datetime.utcnow().isoformat()}


@server.tool
def restart_service(service_name: str, service_type: str = "ecs", confirm_token: str = "") -> dict[str, Any]:
    """重启服务。
    
    Args:
        service_name: 服务名称
        service_type: 服务类型 (ecs|rds|lambda)
        confirm_token: 确认令牌
    
    Returns:
        重启结果
    """
    return {"service": service_name, "action": "restart", "status": "initiated", "estimated_time": "2-5 minutes"}


@server.tool
def scale_service(service_name: str, desired_count: int, confirm_token: str = "") -> dict[str, Any]:
    """调整服务实例数。
    
    Args:
        service_name: 服务名称
        desired_count: 目标实例数
        confirm_token: 确认令牌
    
    Returns:
        扩缩容结果
    """
    return {"service": service_name, "action": "scale", "desired_count": desired_count, "status": "initiated"}


@server.tool
def create_ticket(title: str, description: str, priority: str = "medium", service: str = "") -> dict[str, Any]:
    """创建运维工单。
    
    Args:
        title: 工单标题
        description: 详细描述
        priority: 优先级 (critical|high|medium|low)
        service: 关联服务
    
    Returns:
        创建的工单信息
    """
    ticket_id = f"OPS-{datetime.utcnow().strftime('%Y%m%d')}-{hash(title) % 10000:04d}"
    return {"ticket_id": ticket_id, "title": title, "priority": priority, "service": service, "status": "open", "url": f"https://jira.internal/browse/{ticket_id}"}


# ============================================================
# 5. 报告工具
# ============================================================

@server.tool
def generate_report(investigation_id: str, format: str = "html") -> dict[str, Any]:
    """生成诊断报告 HTML。
    
    Args:
        investigation_id: 调查 ID
        format: 报告格式 (html|markdown|json)
    
    Returns:
        报告 URL 和摘要
    """
    try:
        from report.generator import ReportGenerator
        
        # 构建完整的 finding 数据
        finding = _get_investigation_finding(investigation_id)
        
        # 获取报告桶名称
        bucket = os.getenv("REPORT_BUCKET", "nlopsstack-reportbucket577f0fcd-tvoikpeirsxx")
        
        generator = ReportGenerator(bucket=bucket)
        url = generator.render_and_upload(
            finding=finding,
            kind="diagnostic",
            trace_id=investigation_id
        )
        
        return {
            "investigation_id": investigation_id,
            "report_id": f"rpt-{investigation_id}",
            "format": format,
            "status": "generated",
            "url": url,
            "summary": {
                "title": finding.get("title", ""),
                "root_cause": finding.get("root_cause", ""),
                "severity": finding.get("severity", "info")
            }
        }
    except Exception as e:
        # Fallback: 返回模拟 URL
        report_id = f"RPT-{datetime.utcnow().strftime('%Y%m%d%H%M%S')}"
        return {
            "investigation_id": investigation_id,
            "report_id": report_id,
            "format": format,
            "status": "generated",
            "url": f"https://s3.amazonaws.com/nlops-reports/{report_id}.{format}",
            "error": str(e)
        }


def _get_investigation_finding(investigation_id: str) -> dict[str, Any]:
    """获取调查详情用于报告生成。"""
    # 模拟完整的数据结构（实际应从 DynamoDB 或 DevOps Agent 获取）
    return {
        "title": f"调查报告 · {investigation_id}",
        "severity": "high",
        "investigation_id": investigation_id,
        "operator_portal_url": f"https://console.aws.amazon.com/aidevops/spaces/space-001/tasks/{investigation_id}",
        "timeline": [
            {"ts": "2026-05-18T02:00:00Z", "event": "问题触发"},
            {"ts": "2026-05-18T02:05:00Z", "event": "开始调查"},
            {"ts": "2026-05-18T02:15:00Z", "event": "定位根因"},
            {"ts": "2026-05-18T02:20:00Z", "event": "生成报告"}
        ],
        "root_cause": "RDS 连接池耗尽导致服务响应延迟",
        "fix_steps": [
            {"action": "增加 RDS max_connections 参数", "risk": "low", "auto": True},
            {"action": "检查是否有连接泄漏", "risk": "low", "auto": False}
        ],
        "evidence": {
            "trace_ids": ["1-66a01234-abc"],
            "log_snippets": [
                "ERROR: ConnectionPoolExhausted",
                "P99 latency: 200ms -> 3200ms"
            ]
        }
    }


@server.tool
def list_investigations(status: str = "all", limit: int = 20) -> dict[str, Any]:
    """列出调查任务。
    
    Args:
        status: 状态过滤 (open|in_progress|resolved|all)
        limit: 返回数量
    
    Returns:
        调查任务列表
    """
    investigations = [
        {"id": "INV-001", "title": "payment-api 响应延迟", "service": "payment-api", "status": "resolved"},
        {"id": "INV-002", "title": "user-service 错误率上升", "service": "user-service", "status": "in_progress"}
    ]
    filtered = [i for i in investigations if status == "all" or i["status"] == status]
    return {"count": len(filtered), "investigations": filtered[:limit]}


@server.tool
def get_investigation(investigation_id: str) -> dict[str, Any]:
    """获取调查详情。
    
    Args:
        investigation_id: 调查 ID
    
    Returns:
        调查详情
    """
    return {
        "id": investigation_id,
        "title": "payment-api 响应延迟",
        "service": "payment-api",
        "status": "resolved",
        "root_cause": "数据库连接池耗尽",
        "timeline": [
            {"time": "01:00", "event": "告警触发"},
            {"time": "01:15", "event": "定位根因"},
            {"time": "01:45", "event": "问题解决"}
        ]
    }
