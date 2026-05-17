# NLOps × AWS DevOps Agent 集成方案

> 版本: v1.0  ·  最后更新: 2026-05-17
> 适用：开发团队实施参考；客户 PoC 联调清单
> 对应需求: `01-requirements.md` FR-2.2/2.3/2.4/2.7/2.8、FR-5.5
> 对应设计: `02-design.md` §2

---

## 0. 前提与术语

### 0.1 服务边界
- **AWS DevOps Agent**（简称 **DOA**）：AWS 官方 GA 服务（2026-03-31），提供自治型 SRE 智能体能力
- **NLOps**：本项目的 Lambda 集合（Orchestrator / Execution / EventBridge Subscriber / MCP Server）
- **Agent Space**：DOA 的工作空间概念，类似 tenant；一个 AWS 账户下可创建多个

### 0.2 关键 IAM 标识
- DOA 服务主体（Service Principal）: `aidevops.amazonaws.com`
- DOA 主要 IAM action prefix: `aidevops:*`
- DOA 资源 ARN 模式: `arn:aws:aidevops:{region}:{account}:agent-space/{space-id}` / `:investigation/{inv-id}`
- EventBridge 事件 source: `aws.aidevops`

### 0.3 region 限制
DOA GA 仅在 6 个 region：`us-east-1` / `us-west-2` / `eu-central-1` / `eu-west-1` / `ap-southeast-2` / `ap-northeast-1`。
**v1 部署锁定 `us-east-1`**；备选 `ap-northeast-1`（亚太低延迟）。

---

## 1. 4 个集成路径概览

```
                       ┌────────────────────────────────────┐
                       │       AWS DevOps Agent             │
                       │       (Agent Space)                │
                       │                                    │
                       │  ◀── ② event-up (EventBridge)      │
                       │  ▶── ③ mcp-out (HTTP+SigV4)        │
                       │  ◀── ① call-down (boto3 invoke)    │
                       └────────────────────────────────────┘
                              ▲             │             ▲
                              │             ▼             │
   ┌──────────────────────────┴─────────────────────────────┴──┐
   │                          NLOps                            │
   │                                                           │
   │  L1 Orchestrator  ── ① call-down ──→ DOA chat/invest    │
   │                                                           │
   │  L3 EventBridge   ←── ② event-up   ── DOA inv events     │
   │                                                           │
   │  L4 MCP Server    ←── ③ mcp-out    ── DOA queries        │
   │                                                           │
   │  L1 Orchestrator  ──── ④ mcp-in   ──→ AWS 官方 MCP      │
   │                       (CW / X-Ray, fallback only)        │
   └───────────────────────────────────────────────────────────┘
```

| # | 路径 | 方向 | 触发场景 | NLOps 端 | DOA 端 |
|---|------|------|---------|---------|--------|
| ① | **call-down** | NLOps → DOA | 用户主动查询 / 排障 | Orchestrator Lambda | DOA chat / investigation API |
| ② | **event-up** | DOA → NLOps | 告警驱动闭环 | EventBridge Subscriber Lambda | DOA 完成调查后发事件 |
| ③ | **mcp-out** | DOA → NLOps | DOA 调查时需要客户私有数据 | MCP Server Lambda（API GW） | DOA 注册 MCP server 并调用 |
| ④ | **mcp-in** | NLOps → AWS MCP | DOA 不可达时 fallback | Orchestrator Lambda | （目标是 AWS 官方 CW MCP） |

---

## 2. 路径 ① call-down：NLOps 主动调用 DOA

### 2.1 使用场景
- 用户语音/文字主动查询："系统怎么样" → on-demand chat
- 用户主动排障："X 服务为什么慢" → investigation

### 2.2 SDK 调用

```python
import boto3
from typing import Any

# DevOps Agent uses 'aidevops' service name in boto3 (GA)
agent_rt = boto3.client("aidevops", region_name="us-east-1")

# --- 2.2.1 On-demand chat (5-30s, 同步) ---------------------- #
def ask_chat(agent_space_id: str, prompt: str, session_id: str) -> str:
    resp = agent_rt.start_chat_session(
        agentSpaceId=agent_space_id,
        sessionId=session_id,                # 复用会话上下文
        inputText=prompt,
    )
    # streaming response: aggregate chunks
    chunks: list[str] = []
    for evt in resp["completion"]:
        if "chunk" in evt:
            chunks.append(evt["chunk"]["bytes"].decode("utf-8"))
    return "".join(chunks)


# --- 2.2.2 Investigation (5-15min, 异步) ---------------------- #
def start_investigation(
    agent_space_id: str,
    title: str,
    context: dict[str, Any],
) -> str:
    """Returns investigation_id. Poll or subscribe via EventBridge for completion."""
    resp = agent_rt.create_investigation(
        agentSpaceId=agent_space_id,
        title=title,
        context=context,                     # service / window / signals
    )
    return resp["investigationId"]


def get_investigation(investigation_id: str) -> dict[str, Any]:
    """Read current state. Useful for polling fallback."""
    resp = agent_rt.get_investigation(investigationId=investigation_id)
    return resp["investigation"]
```

> ⚠️ **注**：DOA 的 boto3 service name 在 GA 后才稳定。本文按 `aidevops` 命名。
> 如果实际 SDK 名称不同（例如 `aws-devops-agent` / `bedrock-aidevops`），需要替换。
> **联调阶段必须先用 `aws devops-agent help` 确认 CLI 命令名，再 mirror 到 SDK**。

### 2.3 IAM 调用方权限（Orchestrator Lambda）

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "DOAReadAndChat",
      "Effect": "Allow",
      "Action": [
        "aidevops:StartChatSession",
        "aidevops:GetChatSession",
        "aidevops:ListChatSessions",
        "aidevops:GetInvestigation",
        "aidevops:ListInvestigations"
      ],
      "Resource": [
        "arn:aws:aidevops:us-east-1:123456789012:agent-space/*"
      ]
    },
    {
      "Sid": "DOAWriteInvestigation",
      "Effect": "Allow",
      "Action": [
        "aidevops:CreateInvestigation",
        "aidevops:UpdateInvestigation"
      ],
      "Resource": [
        "arn:aws:aidevops:us-east-1:123456789012:agent-space/*"
      ]
    }
  ]
}
```

### 2.4 调用模式选择

| 用户意图 | 选用 API | 预期延迟 | 后续动作 |
|---|---|---|---|
| "系统怎么样" 简单巡检 | `start_chat_session` | 5-30 s | 同步等结果 → 渲染 HTML |
| "X 服务为什么慢" 复杂排障 | `create_investigation` | 5-15 min | 立刻回 placeholder TTS；订阅 EventBridge 等结果 |
| "上次类似问题怎么解决" | `start_chat_session`（DOA 会自动应用 Custom Skill） | 5-15 s | 同步等结果 |

**经验法则**：能用 `chat` 就别用 `investigation`，因为定价相同但 chat 平均 30s vs investigation 8min → 节省 **15× 成本**。

---

## 3. 路径 ② event-up：DOA 通过 EventBridge 通知 NLOps

### 3.1 使用场景
- CloudWatch alarm 触发 → DOA 自动调查 → 完成后通知 NLOps 渲染 HTML 推送 IM
- DOA 主动发现的预防性建议（evaluation）→ 通知值班群组

### 3.2 EventBridge 事件样例

DOA 发布的事件 schema（参考官方文档）：

```json
{
  "version": "0",
  "id": "abc123-...",
  "detail-type": "Investigation Completed",
  "source": "aws.aidevops",
  "account": "123456789012",
  "time": "2026-05-17T14:42:00Z",
  "region": "us-east-1",
  "resources": [
    "arn:aws:aidevops:us-east-1:123456789012:agent-space/space-001"
  ],
  "detail": {
    "investigationId": "inv-2026-05-17-...",
    "status": "COMPLETED",
    "title": "order-service P99 latency spike",
    "severity": "high",
    "rootCause": {
      "summary": "RDS proxy 连接池耗尽",
      "score": 0.94
    },
    "triggerSource": "cloudwatch-alarm",
    "triggerArn": "arn:aws:cloudwatch:us-east-1:123456789012:alarm:order-p99-high",
    "operatorPortalUrl": "https://us-east-1.console.aws.amazon.com/aidevops/...",
    "completedAt": "2026-05-17T14:42:00Z"
  }
}
```

可能的 `detail-type`：
- `Investigation Started`
- `Investigation Updated`（中间步骤）
- `Investigation Completed`
- `Evaluation Completed`（预防性评估）

### 3.3 EventBridge Rule（CDK 写法）

```python
from aws_cdk import aws_events as events
from aws_cdk import aws_events_targets as targets

events.Rule(
    self,
    "DOAInvestigationCompletedRule",
    event_pattern=events.EventPattern(
        source=["aws.aidevops"],
        detail_type=["Investigation Completed"],
        detail={
            "status": ["COMPLETED"],
            "severity": ["high", "critical"],   # 只关心高/严重
        },
    ),
    targets=[targets.LambdaFunction(eventbridge_subscriber_fn)],
)
```

### 3.4 EventBridge Subscriber Lambda（L3）伪码

```python
def handler(event: dict, context):
    detail = event["detail"]
    inv_id = detail["investigationId"]

    # 1. 拉完整调查详情
    investigation = doa.get_investigation(inv_id)

    # 2. 渲染 HTML 诊断书
    html_url = report.render_and_upload(investigation, channel="alert")

    # 3. 推送 IM 卡片到值班群组
    notifier.push_alert_card(
        title=detail["title"],
        severity=detail["severity"],
        root_cause=detail["rootCause"]["summary"],
        html_url=html_url,
        operator_portal_url=detail["operatorPortalUrl"],
    )

    # 4. 写审计日志
    audit.log(
        trace_id=inv_id,
        agent="EventBridgeSubscriber",
        action="alert_pushed",
        status="ok",
        payload={"detail_type": event["detail-type"]},
    )
```

### 3.5 IAM —— L3 需要的权限

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": [
        "aidevops:GetInvestigation",
        "aidevops:GetEvaluation"
      ],
      "Resource": "*"
    },
    {
      "Effect": "Allow",
      "Action": ["s3:PutObject"],
      "Resource": "arn:aws:s3:::nlops-reports/*"
    },
    {
      "Effect": "Allow",
      "Action": ["sns:Publish"],
      "Resource": "arn:aws:sns:us-east-1:123456789012:nlops-notify"
    }
  ]
}
```

EventBridge 调用 Lambda 不需要 NLOps 这边显式授权——CDK 的 `targets.LambdaFunction` 会自动加上 `events.amazonaws.com` 的 invoke permission。

### 3.6 联调清单
- [ ] DOA Agent Space 已创建
- [ ] CloudWatch alarm 与 DOA 关联（在 alarm 详情页配 "Auto-investigate with DevOps Agent"）
- [ ] EventBridge rule 已部署，pattern 匹配上面 §3.3 的 source/detail-type
- [ ] L3 Lambda 已部署，CloudWatch Logs 可见调用记录
- [ ] 端到端：手动触发 alarm → DOA 调查 → IM 群收到卡片（耗时 5-15 min）

---

## 4. 路径 ③ mcp-out：DOA 调用 NLOps MCP Server（暴露客户私有工具）

### 4.1 使用场景
DOA 调查时需要的数据**不在它内置集成里**：
- 客户内部 CMDB（按服务名查 owner team / on-call 名单）
- 客户自研 APM（特殊指标）
- 客户的 Jira / Wiki / 内部 runbook
- 客户私有 GitHub Enterprise

### 4.2 协议要求（DOA 官方约束）

引用 DOA 官方文档（[Connecting MCP Servers](https://docs.aws.amazon.com/devopsagent/latest/userguide/configuring-capabilities-for-aws-devops-agent-connecting-mcp-servers.html)）：

| 项 | 要求 |
|---|---|
| 传输协议 | **Streamable HTTP**（不是 stdio / WebSocket） |
| 鉴权 | OAuth 2.0 Client Credentials / OAuth 3LO / API Key / **AWS SigV4** ←推荐 |
| 工具名称长度 | ≤ 64 字符 |
| 安全 | 仅暴露**只读** tool；防 prompt injection |
| 私网 | 支持 Private Connection（VPC Endpoint） |

### 4.3 NLOps MCP Server 架构（L4）

```
DOA Agent Space
   │ HTTPS + SigV4
   ▼
┌──────────────────────────────────┐
│ API Gateway (REST)               │
│  Path: /mcp                      │
│  Auth: AWS_IAM (SigV4)           │
└─────────────┬────────────────────┘
              │
              ▼
┌──────────────────────────────────┐
│ L4 Lambda: MCP Server            │
│   - validate MCP request schema  │
│   - dispatch to tool registry    │
│   - return MCP-compliant response│
└─────────────┬────────────────────┘
              │ optionally via VPC Link
              ▼
   客户内部 endpoint
   (CMDB / Jira / 内部 APM)
```

### 4.4 IAM 配置：DOA 假装客户角色

DOA 调用客户的 MCP Server 时，**会先 AssumeRole** 到客户账户里的一个 IAM Role，再用那个 role 的凭证去签 SigV4。所以客户账户里必须有这个 trust policy：

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Principal": {
        "Service": "aidevops.amazonaws.com"
      },
      "Action": "sts:AssumeRole",
      "Condition": {
        "StringEquals": {
          "aws:SourceAccount": "123456789012"
        },
        "ArnLike": {
          "aws:SourceArn": "arn:aws:aidevops:us-east-1:123456789012:agent-space/*"
        }
      }
    }
  ]
}
```

> ⚠️ **`aws:SourceAccount` 和 `aws:SourceArn` 必须有**——防止 confused deputy 问题。
> 这是 DOA 官方文档明确要求的安全条件。

### 4.5 该 Role 的 permission policy（最小化）

只允许调用这个 API Gateway 的特定 method：

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": "execute-api:Invoke",
      "Resource": "arn:aws:execute-api:us-east-1:123456789012:abcd1234/prod/POST/mcp"
    }
  ]
}
```

### 4.6 MCP 工具实现示例

L4 Lambda 处理 MCP 请求：

```python
from typing import Any

# 工具注册表 — 每个 tool 是一个只读函数
TOOL_REGISTRY = {
    "get_service_owner": get_service_owner,
    "get_recent_jira_tickets": get_recent_jira_tickets,
    "get_internal_apm_metric": get_internal_apm_metric,
}


def get_service_owner(service_name: str) -> dict[str, Any]:
    """Look up service owner team and on-call from internal CMDB."""
    # call into customer's internal CMDB API (via VPC link)
    return cmdb_client.lookup(service_name)


def get_recent_jira_tickets(service: str, limit: int = 5) -> list[dict]:
    """Recent open Jira tickets for a service."""
    return jira_client.search(
        f'project = OPS AND component = "{service}" AND status != Done',
        limit=limit,
    )


def get_internal_apm_metric(metric: str, window_minutes: int = 30) -> dict:
    """Custom APM metric (only available in customer's private network)."""
    return apm_client.query(metric, window_minutes)


def handler(event: dict, context):
    """MCP Streamable HTTP request handler."""
    body = json.loads(event["body"])
    method = body["method"]               # 'tools/list' or 'tools/call'

    if method == "tools/list":
        return mcp_response(
            id=body["id"],
            result={"tools": [tool_schema(name, fn) for name, fn in TOOL_REGISTRY.items()]},
        )

    if method == "tools/call":
        tool_name = body["params"]["name"]
        args = body["params"].get("arguments", {})
        if tool_name not in TOOL_REGISTRY:
            return mcp_error(body["id"], code=-32601, message=f"unknown tool: {tool_name}")
        try:
            result = TOOL_REGISTRY[tool_name](**args)
            return mcp_response(
                id=body["id"],
                result={"content": [{"type": "text", "text": json.dumps(result)}]},
            )
        except Exception as exc:
            return mcp_error(body["id"], code=-32603, message=str(exc))

    return mcp_error(body["id"], code=-32601, message=f"unknown method: {method}")


def tool_schema(name: str, fn) -> dict:
    """Auto-generate MCP tool schema from function signature."""
    import inspect
    sig = inspect.signature(fn)
    params = {
        p.name: {"type": "string"}
        for p in sig.parameters.values()
        if p.name != "self"
    }
    return {
        "name": name,
        "description": (fn.__doc__ or "").strip().split("\n")[0],
        "inputSchema": {"type": "object", "properties": params, "required": list(params)},
    }


def mcp_response(id, result):
    return {
        "statusCode": 200,
        "headers": {"Content-Type": "application/json"},
        "body": json.dumps({"jsonrpc": "2.0", "id": id, "result": result}),
    }


def mcp_error(id, code, message):
    return {
        "statusCode": 200,        # MCP error 仍是 200，错误信息在 body
        "headers": {"Content-Type": "application/json"},
        "body": json.dumps({"jsonrpc": "2.0", "id": id, "error": {"code": code, "message": message}}),
    }
```

### 4.7 注册 NLOps MCP Server 到 DOA Agent Space

通过 AWS Console 或 CLI（GA 后 SDK 也支持）：

```bash
aws aidevops register-mcp-server \
  --agent-space-id space-001 \
  --name "NLOps Private Tools" \
  --endpoint-url "https://abcd1234.execute-api.us-east-1.amazonaws.com/prod/mcp" \
  --auth-method AWS_SIGV4 \
  --signing-region us-east-1 \
  --signing-service execute-api \
  --iam-role-arn arn:aws:iam::123456789012:role/NLOpsMcpInvokeRole
```

注册成功后，DOA 调查时会**自动发现** `tools/list` 返回的工具，并按需调用。

### 4.8 安全注意事项（来自 DOA 官方文档）

1. **只暴露只读 tool**——绝不要把 `delete_*` / `update_*` 通过 MCP 暴露
2. **Tool allowlist**——在 Agent Space 里只 allowlist 必要的 tool，不要 "Allow all"
3. **Prompt injection 防御**——MCP 返回的内容 = 用户输入，必须做 sanitize
4. **审计**——L4 Lambda 必须记录每次调用，含 tool 名 / 参数 / DOA 来源 ARN

---

## 5. 路径 ④ mcp-in：NLOps 调用 AWS 官方 MCP（fallback）

### 5.1 使用场景
- DOA 不可达（不太可能，但作为 fallback）
- 简单查询不想付 $0.0083/agent-second

### 5.2 AWS 官方 MCP Server 列表

按 2026-05 当前公开的：
- **CloudWatch MCP Server**（社区/AWS Lab 实现，非完全官方 GA）
- **X-Ray MCP Server**（同上）

> ⚠️ AWS 官方 MCP 当前在快速演进，**联调时务必查最新文档** [AWS MCP Servers](https://github.com/awslabs/mcp)

### 5.3 使用方式（mcp Python SDK）

```python
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

# 假设 AWS CW MCP Server 通过 docker / 本地进程运行
params = StdioServerParameters(
    command="aws-mcp-cloudwatch",
    args=["--region", "us-east-1"],
)

async with stdio_client(params) as (read, write):
    async with ClientSession(read, write) as session:
        await session.initialize()
        tools = await session.list_tools()

        # 调用 cloudwatch.get_metric_data
        result = await session.call_tool(
            "get_metric_data",
            arguments={
                "namespace": "AWS/RDS",
                "metric_name": "DatabaseConnections",
                "dimensions": {"DBInstanceIdentifier": "prod-orders"},
                "window_minutes": 30,
            },
        )
```

### 5.4 何时用路径 ④

| 场景 | 用 ① call-down | 用 ④ mcp-in |
|---|---|---|
| 简单读 1 个指标 | ❌ 杀鸡用牛刀（$） | ✅ |
| 多源数据综合分析 | ✅ DOA 内置 | ❌ 需自己写编排 |
| 需要 RCA / 根因 | ✅ DOA 投资 | ❌ 不会 |
| 经验匹配 / Skills | ✅ DOA 内置 | ❌ |

**结论**：路径 ④ 只用于"我就要 1 个指标，不需要 DOA 来分析"——少用。日常 95% 都走路径 ①。

---

## 6. 端到端时序图：故障排查（路径 ①+② 组合）

```
User                NLOps L1            AWS DevOps Agent      EventBridge          NLOps L3
  │                    │                       │                  │                   │
  │ "X 为什么慢"       │                       │                  │                   │
  ├───────────────────▶│                       │                  │                   │
  │                    │ start_chat_session    │                  │                   │
  │                    ├──────────────────────▶│                  │                   │
  │                    │  (5-30s, 初步发现)     │                  │                   │
  │                    │◀──────────────────────┤                  │                   │
  │ "正在调查..." TTS  │                       │                  │                   │
  │◀───────────────────┤                       │                  │                   │
  │ 初步卡片 (HTML v1) │                       │                  │                   │
  │◀───────────────────┤                       │                  │                   │
  │                    │ create_investigation  │                  │                   │
  │                    ├──────────────────────▶│                  │                   │
  │                    │  (returns inv_id)     │                  │                   │
  │                    │◀──────────────────────┤                  │                   │
  │                    │                       │                  │                   │
  │                    │  ----- 等待 5-15 min -----              │                   │
  │                    │                       │                  │                   │
  │                    │                       │ inv 完成事件      │                   │
  │                    │                       ├─────────────────▶│                   │
  │                    │                       │                  │ trigger Lambda    │
  │                    │                       │                  ├──────────────────▶│
  │                    │                       │ get_investigation│                   │
  │                    │                       │◀─────────────────────────────────────┤
  │                    │                       ├─────────────────────────────────────▶│
  │                    │                       │                  │ render HTML v2    │
  │                    │                       │                  │ (full diagnosis)  │
  │ 完整诊断书 IM 卡    │                       │                  │                   │
  │◀───────────────────────────────────────────────────────────────────────────────────┤
  │                    │                       │                  │                   │
```

---

## 7. 错误处理与降级

| 错误 | 检测方式 | 降级策略 |
|---|---|---|
| DOA chat 超时 (>60s) | boto3 timeout | 路径 ④ 拉 CW 指标 + Bedrock 自己解读（次优） |
| DOA investigation 卡死 (>30 min) | 轮询 `get_investigation` 仍在 IN_PROGRESS | 通知用户"调查异常长，建议手动查看 Operator Portal" |
| DOA 服务整体不可用 | `ServiceUnavailable` / 5xx | Circuit breaker 30s；fallback 到路径 ④ + 简化 HTML 诊断书 |
| EventBridge 事件丢失 | L3 没收到事件 | 定时轮询 `list_investigations` 补漏（每 10 min） |
| MCP Server 被恶意调用 | DOA 来源 ARN 不在白名单 | API GW 直接 403 |

---

## 8. 成本控制

### 8.1 用量监控
配 CloudWatch alarm：
- DOA chat / investigation / evaluation 月用量分别报警
- alarm 阈值参考成本预算（设计文档 §9）

### 8.2 经验法则
| 场景 | 推荐 API | 月开销（50 用户） |
|---|---|---|
| 80% 简单查询 | `chat`（30s 平均） | ~$1,000 |
| 15% 复杂排障 | `investigation`（8min 平均） | ~$500 |
| 5% 评估建议 | `evaluation`（15min 平均） | ~$50 |
| **合计 DOA** | | **~$1,550** |

### 8.3 降本套路
1. **预热 Custom Skills**：第二次同类故障 → DOA 直接命中 Skill，不开新调查
2. **alarm severity 过滤**：EventBridge rule 只订阅 `severity in [high, critical]`
3. **chat 多轮复用 session**：同一 user 短时间内复用 `sessionId`，省 context 重建
4. **Enterprise Support 抵扣**：75% credit 实质把 DOA 费用减 3/4

---

## 9. 实施检查表

### 9.1 客户准备
- [ ] AWS 账户在 6 个支持 region 之一
- [ ] AWS Support plan 选定（影响成本抵扣比例）
- [ ] CloudWatch 详细监控已开
- [ ] DOA Agent Space 创建（建议每环境 1 个：dev / staging / prod）
- [ ] 内部工具的 endpoint 已就绪（CMDB / Jira / 自研 APM）

### 9.2 联调
- [ ] 路径 ① call-down：用 CLI 测试 `aws aidevops start-chat-session` 成功
- [ ] 路径 ② event-up：手动触发 alarm，L3 Lambda CloudWatch Logs 看到 invoke
- [ ] 路径 ③ mcp-out：DOA Agent Space → Capabilities 看到 NLOps MCP Server 已注册并 health=OK
- [ ] 路径 ④ mcp-in：本地 mcp client 能成功调 AWS CW MCP Server

### 9.3 安全审查
- [ ] L4 MCP Server 只暴露只读 tool（grep `def ` 确认）
- [ ] DOA trust policy 含 `aws:SourceAccount` + `aws:SourceArn` 双条件
- [ ] L1 Orchestrator IAM 不含任何 `aidevops:Delete*`
- [ ] L2 Execution IAM 用 tag 边界 `aws:ResourceTag/nlops:managed=true`
- [ ] 全部 Lambda 启用 CloudWatch Logs，retention ≥ 90 天

---

## 10. 参考资料

- [AWS DevOps Agent 官方主页](https://aws.amazon.com/devops-agent/)
- [AWS DevOps Agent User Guide](https://docs.aws.amazon.com/devopsagent/latest/userguide/)
- [Connecting MCP Servers (DOA)](https://docs.aws.amazon.com/devopsagent/latest/userguide/configuring-capabilities-for-aws-devops-agent-connecting-mcp-servers.html)
- [Private connections for DOA](https://aws.amazon.com/blogs/devops/securely-connect-aws-devops-agent-to-private-services-in-your-vpcs/)
- [DOA pricing](https://aws.amazon.com/devops-agent/pricing/)
- [Model Context Protocol spec](https://spec.modelcontextprotocol.io/)
- [AWS MCP Servers (awslabs/mcp)](https://github.com/awslabs/mcp)
- 本项目: `docs/01-requirements.md` · `docs/02-design.md` · `docs/04-demo-script.md`
