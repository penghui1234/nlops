# NLOps 实现方案设计

> 版本: v2.0  ·  最后更新: 2026-05-17  ·  对应需求: `01-requirements.md` v2
>
> v2 修订：
> - **AWS DevOps Agent 作为底层引擎**（GA 2026-03-31，$0.0083/agent-second）
> - **6 个 Agent 仍作为逻辑分层**（PPT 卖点保留），但物理上合并为 4 个 Lambda
> - 新增 4 个集成路径：`call-down` / `event-up` / `mcp-out` / `mcp-in`
> - 重算成本（含 DevOps Agent 用量）
> - 锁定 region：`us-east-1`（备选 `ap-northeast-1`），**不支持 AWS 中国区**

---

## 1. 总体架构

### 1.1 逻辑视图（保留 PPT 6 Agent 卖点）

```
┌──────────────────────── 用户 ────────────────────────┐
│   Amazon Quick (MCP)  │  企微 Bot  │  飞书 Bot         │
└────────────────────────┬─────────────────────────────┘
                         │ 语音 / 文字
                ┌────────▼──────────┐
                │   Router Agent    │  意图识别
                └────────┬──────────┘
        ┌────────────────┼─────────────────┐
        ▼                ▼                 ▼
┌──────────────┐ ┌──────────────┐ ┌──────────────┐
│  Discovery   │ │  Knowledge   │ │  Execution   │
│  Agent       │ │  Agent       │ │  Agent       │
└──────┬───────┘ └──────┬───────┘ └──────┬───────┘
       │                │                 │
       └────────┬───────┘                 │
                ▼                         │
        ┌──────────────┐                  │
        │  Analysis    │                  │
        │  Agent       │                  │
        └──────┬───────┘                  │
               │                          │
               └────────┬─────────────────┘
                        ▼
               ┌──────────────┐
               │  Report      │
               │  Agent       │
               └──────────────┘
```

### 1.2 物理视图（实际部署的 Lambda）

```
┌─────────────────────── Caller layer ──────────────────────┐
│ Quick / 企微 / 飞书  →  API Gateway (REST)                │
└──────────────────────────┬───────────────────────────────┘
                           │
┌──────────────────────────▼───────────────────────────────┐
│ Lambda L1: Orchestrator                                  │
│ ─────────────────────────────────────────────────────── │
│  Strands SDK 内部编排 5 个逻辑 Agent (Tool)：             │
│   • Router (intent classify, Bedrock LLM)                │
│   • Discovery  ─┐                                        │
│   • Analysis   ─┼──→  AWS DevOps Agent (chat / invest.) │
│   • Knowledge  ─┘     + Custom Skills + MCP Server       │
│   • Report     ─────→  Bedrock LLM + Jinja2 + S3         │
│   • Execution  ─────→  invoke L2 (cross-Lambda)          │
└────┬──────────────────────┬──────────────────┬───────────┘
     │ confirm_token        │ chat / invest.   │ EventBridge
     │ + Policy             │                  │ Pub
     ▼                      ▼                  ▼
┌──────────────┐  ┌──────────────────┐  ┌────────────────────┐
│ L2: Execution│  │  AWS DevOps Agent│  │ EventBridge        │
│ Lambda       │  │  (managed)       │  │ "DevOps Agent      │
│ (write IAM   │  │                  │  │  Investigation"    │
│  isolated)   │  │  ↑ MCP tools     │  └─────────┬──────────┘
└──────┬───────┘  │  ↑ Custom Skills │            │
       │ AWS API  │                  │            │
       ▼          └────────┬─────────┘            │
   AWS resources           │                      ▼
   (ECS / EC2 / RDS)       │ MCP HTTP        ┌──────────────────────┐
                           │ + SigV4         │ L3: EventBridge      │
                           ▼                 │     Subscriber Lambda│
                    ┌──────────────┐         │ 渲染 HTML、推送 IM   │
                    │ L4: NLOps    │         └──────────────────────┘
                    │ MCP Server   │
                    │ Lambda       │  暴露客户内部工具
                    │ (API Gateway │  (CMDB / 工单 / 自研 APM)
                    │  + IAM SigV4)│
                    └──────┬───────┘
                           ▼
                客户私有 endpoint（VPC / 内网）
```

**4 个 Lambda 的职责**：

| 编号 | 名称 | 职责 | IAM 关键权限 |
|------|------|------|--------------|
| L1 | **Orchestrator** | 入口；Strands SDK 内编排 Router/Discovery/Analysis/Knowledge/Report 5 个逻辑 Agent | `bedrock:Invoke*`、`aidevops:StartChat*`、`aidevops:CreateInvestigation*`、`s3:PutObject` (报告)、`lambda:InvokeFunction` (调 L2)、`dynamodb:*` (会话/审计) |
| L2 | **Execution** | 写操作隔离；只此 Lambda 有 ECS/EC2/RDS 写权限 | `ecs:UpdateService`、`autoscaling:Set*`、`rds:Reboot*`、tag 边界 `aws:ResourceTag/nlops:managed=true` |
| L3 | **EventBridge Subscriber** | 订阅 DevOps Agent 自治调查结果，渲染 HTML 推送 IM | EventBridge target；`s3:PutObject`、`sns:Publish` |
| L4 | **MCP Server** | 暴露客户内部工具给 DevOps Agent；Streamable HTTP + SigV4 鉴权 | 调用客户私有 endpoint；不直接访问 AWS 资源（受最小权限） |

**逻辑 ↔ 物理映射**：

| 逻辑 Agent | 实现方式 | Lambda |
|---|---|---|
| Router | in-process Tool（Bedrock LLM） | L1 |
| Discovery | in-process Tool → DevOps Agent on-demand chat | L1 |
| Analysis | in-process Tool → DevOps Agent investigation | L1 |
| Knowledge | in-process Tool → DevOps Agent Custom Skills（+ Bedrock KB 双写） | L1 |
| Report | in-process Tool → Jinja2 → S3 | L1 |
| **Execution** | **跨 Lambda 调用（最关键的物理隔离）** | L2 |

> 设计原则：**只有 Execution 因为权限边界单独拆 Lambda**；其他 5 个逻辑 Agent 在 L1 内做 in-process Tool 调用，避免 Lambda → Lambda 跳转累加冷启动。

---

## 2. 4 个集成路径（DevOps Agent ↔ NLOps）

| 路径 | 方向 | 触发场景 | 用到的服务 |
|---|---|---|---|
| **call-down** (主动调用) | NLOps → DevOps Agent | 用户主动问"系统怎么样" | `aidevops:StartChat*` API（同步） |
| **event-up** (告警闭环) | DevOps Agent → NLOps | CloudWatch alarm 触发 DevOps Agent 自动调查后 | EventBridge `aws.aidevops` event source |
| **mcp-out** (暴露工具) | DevOps Agent → NLOps MCP Server | DevOps Agent 调查时需要客户私有数据 | NLOps MCP Server（API GW + Lambda + SigV4） |
| **mcp-in** (使用 AWS MCP) | NLOps Orchestrator → AWS MCP Server | NLOps 自身需要标准化访问 CW / X-Ray | AWS 官方 MCP Server (CloudWatch / X-Ray) |

详见 `docs/03-devops-agent-integration.md`。

---

## 3. 模块划分

| 模块 | 职责 | 实现 |
|------|------|------|
| **交互入口** | 接收用户请求、做协议适配 | API Gateway + 三个 Adapter（Quick / WeCom / Feishu） |
| **会话管理** | 多轮对话上下文、用户身份 | DynamoDB（`session_id` 分区键，TTL = 1h） |
| **Orchestrator (L1)** | Router/Discovery/Analysis/Knowledge/Report 5 个逻辑 Agent in-process 编排 | Strands SDK 风格 Tool 注册 |
| **DevOps Agent Tool** | 调用 chat / investigation API；解析返回 | boto3 `aidevops` client（GA 后正式 SDK） |
| **MCP Client** | NLOps 调用 AWS 官方 MCP Server (CloudWatch / X-Ray) | mcp Python SDK |
| **MCP Server (L4)** | 反向：把客户工具暴露给 DevOps Agent | Streamable HTTP + Lambda Web Adapter / API GW |
| **Execution (L2)** | 写操作隔离 | 独立 Lambda + 独立 IAM Role |
| **EventBridge Sub (L3)** | 接收 DevOps Agent 自治调查事件 | EventBridge rule pattern + Lambda target |
| **Report Tool** | DevOps Agent 输出 → JSON → HTML | Jinja2 + ECharts (CDN) |
| **Voice 适配** | Nova Sonic ASR / TTS | Bedrock streaming，封装在 L1 |
| **Policy Guard** | 软护栏（早拦截、可读错误、审计） | `src/common/policy.py`（已实现） |
| **审计日志** | 全链路 trace | DynamoDB audit 表 + CloudWatch Logs（JSON） |

---

## 4. 核心数据模型

### 4.1 会话 Session
```json
{
  "session_id": "sess-2026-05-17-uuid",
  "user_id": "alice@corp",
  "channel": "quick | wecom | feishu",
  "messages": [
    {"role": "user", "content": "...", "ts": 1747488000},
    {"role": "assistant", "content": "...", "ts": 1747488003}
  ],
  "context": {
    "current_service": "order-service",
    "current_incident_id": "inc-xxx",
    "devops_agent_session_id": "do-...",
    "pending_confirm_token": "ct-..."
  },
  "ttl": 1747491600
}
```

### 4.2 Orchestrator 内部 Plan（Strands 风格）
```json
{
  "intent": "troubleshoot",
  "confidence": 0.93,
  "tools_to_call": [
    {"tool": "discovery", "args": {"service": "order-service", "window": "30m"}},
    {"tool": "analysis",  "args": {"depends_on": ["discovery"]}},
    {"tool": "report",    "args": {"depends_on": ["analysis"]}}
  ]
}
```

### 4.3 事件报告 Incident Report
```json
{
  "incident_id": "inc-2026-05-17-001",
  "title": "order-service P99 延迟突增",
  "severity": "high",
  "devops_agent": {
    "investigation_id": "inv-...",
    "operator_portal_url": "https://us-east-1.console.aws.amazon.com/aidevops/...",
    "score": 0.94
  },
  "timeline": [
    {"ts": "2026-05-17T14:30:00Z", "event": "P99 latency rose from 200ms to 2s"},
    {"ts": "2026-05-17T14:32:10Z", "event": "DB CPU reached 95%"}
  ],
  "root_cause": "RDS proxy 连接池耗尽，慢查询堆积",
  "impact": {"services": ["order-service"], "users_affected": "~2%"},
  "fix_steps": [
    {"action": "扩容 RDS proxy 连接数 200 → 400", "risk": "low", "auto": true},
    {"action": "重启 order-service Pod", "risk": "medium", "auto": false}
  ],
  "verification": "P99 恢复至 250ms",
  "evidence": {
    "trace_ids": ["1-66...."],
    "log_snippets": ["ERROR ConnectionPoolExhausted"],
    "metrics": ["RDSProxy.DatabaseConnections"]
  }
}
```

### 4.4 Confirm Token
```json
{
  "token": "ct-uuid",
  "session_id": "sess-...",
  "user_id": "alice@corp",
  "intent": "execute_action",
  "action_payload": {
    "service": "order-service",
    "action": "scale",
    "params": {"desired": 4}
  },
  "issued_at": 1747488003,
  "expires_at": 1747488303,   // 5 分钟
  "used": false
}
```

存 DynamoDB；Execution Lambda 验证：未过期 + 未使用 + session 匹配 + user 匹配。

---

## 5. Agent 协作机制（v2 简化版）

### 5.1 in-process Tool 编排（L1 内）
```python
# 伪码
@tool("router")
def router(query: str) -> Plan: ...

@tool("discovery")
def discovery(service: str, window: str) -> Findings:
    # 优先 DevOps Agent on-demand chat
    return devops_agent.chat(f"give me metrics of {service} last {window}")

@tool("analysis")
def analysis(findings: Findings) -> RootCause:
    return devops_agent.investigate(findings)

@tool("execution")
def execution(action: dict, confirm_token: str):
    # 跨 Lambda invoke L2
    return lambda_client.invoke("nlops-execution", payload={...})

# Orchestrator
plan = router(user_query)
if plan.intent == "troubleshoot":
    findings = discovery(...)
    rca = analysis(findings)
    report_url = report(rca)
    return report_url
```

### 5.2 Policy Guard
仍保留 `src/common/policy.py`，**作为软护栏**（早拦截、可读错误、产生审计）。**真正的硬边界仍是 IAM**：
- L1 Orchestrator IAM：无写权限
- L2 Execution IAM：写权限有 tag 边界
- L4 MCP Server IAM：无 AWS 资源权限，只能 fetch 客户内部 endpoint

### 5.3 跨 Lambda 调用（L1 → L2）
```python
import boto3, json
lambda_client = boto3.client("lambda")

resp = lambda_client.invoke(
    FunctionName="nlops-execution",
    InvocationType="RequestResponse",  # 同步等结果
    Payload=json.dumps({
        "session_id": session_id,
        "confirm_token": token,
        "action": action_payload,
    }).encode(),
)
```

---

## 6. 关键流程

### 6.1 路径 A：用户主动排障（call-down）
```
1. 用户在企微说: "order-service 延迟为什么涨了"
2. WeCom Adapter → API Gateway /chat → L1 Orchestrator
3. L1: Nova Sonic ASR (若是语音消息)
4. L1: 加载/创建 session
5. L1: Router(query) → intent=troubleshoot, plan=[discovery, analysis, report]
6. L1: Discovery → DevOps Agent on-demand chat ("metrics of order-service 30m")
7. L1: Analysis → DevOps Agent CreateInvestigation → 长时任务，立刻返回 investigation_id
8. L1: 给用户立即回复"我在调查中，5-10 分钟内会发完整报告"（语音 placeholder）
9. L1: 同步轮询 1 次 chat 摘要 → Report 渲染初版 HTML → S3 → IM 卡片推送
10. 后续：DevOps Agent 调查完成 → EventBridge → L3 → 更新 HTML + 通知用户
11. 用户点"扩容" → L1 issue confirm_token → 推风险卡片
12. 用户点确认 → L1 校验 token → invoke L2 → AWS API 写
13. L2 完成 → audit log → 通知 L1 → 用户回显
14. Knowledge：把整个 incident 注册为 DevOps Agent Custom Skill
```

### 6.2 路径 B：告警驱动闭环（event-up）
```
1. CloudWatch Alarm 触发
2. DevOps Agent 自动开始 investigation（已配置 alarm → DevOps Agent 关联）
3. DevOps Agent 完成 investigation → 发布事件到 EventBridge
   { "source": "aws.aidevops", "detail-type": "Investigation Completed", ... }
4. L3 EventBridge Subscriber Lambda 被触发
5. L3 拉 investigation 详情 → 渲染 HTML → S3
6. L3 推送 IM 卡片（值班群组）→ 包含分析页 URL + 一键复用按钮
7. 若卡片"一键执行"被点击 → 走路径 A 第 11 步以后
```

### 6.3 路径 C：DevOps Agent 调用客户私有工具（mcp-out）
```
1. DevOps Agent 在调查 order-service 时，发现需要查 CMDB
2. DevOps Agent 通过已注册的 NLOps MCP Server endpoint 发起 HTTPS + SigV4 请求
   GET https://api.example.com/mcp  (API Gateway → L4)
3. L4 验证 SigV4 (来自 aidevops.amazonaws.com)
4. L4 fetch 客户 CMDB（通过 Private Connections / VPC Link）
5. L4 返回 MCP 协议格式的 tool 结果
6. DevOps Agent 用结果继续调查
```

### 6.4 路径 D：NLOps 调 AWS 官方 MCP（mcp-in）
仅作 fallback：当 DevOps Agent 不可达时，L1 直接通过 AWS 官方 CloudWatch MCP Server 拉数据。详见 `03-devops-agent-integration.md` §4。

---

## 7. 关键技术选型

| 维度 | 选型 | 理由 |
|------|------|------|
| 语言 | Python 3.12 | Strands SDK / boto3 / Lambda 原生 |
| Agent 框架 | Strands SDK（主）+ AWS DevOps Agent（底层引擎） | 双层：Strands 在 L1 内做 6 逻辑 Agent；DevOps Agent 是真正的 RCA 引擎 |
| LLM | Bedrock Claude 3.5 Sonnet (主) / Nova Pro (备) | 用于 Router 意图识别、Report 文本生成 |
| Embedding | Bedrock Titan Embed v2 | 与 Bedrock KB 默认一致 |
| 语音 | Nova Sonic | 端到端流式，中英文 |
| Knowledge | DevOps Agent Custom Skills（主）+ Bedrock KB（双写）| Skills 在 DevOps Agent 调查时直接生效；KB 兼容客户已有知识库 |
| 数据源 | DevOps Agent 内置集成（CW / Datadog / Dynatrace 等）| 不重复造轮子 |
| MCP | mcp Python SDK + Streamable HTTP | 暴露 NLOps 自有工具给 DevOps Agent |
| 基础设施 | CDK v2 (Python) | 一键部署 |
| 报告渲染 | Jinja2 + ECharts (CDN) | 静态 HTML，零前端构建 |
| 存储 | S3（报告）+ DynamoDB（会话/审计/Confirm Token）| Serverless 标配 |

---

## 8. 部署拓扑（单 region）

| 资源 | 数量 | 说明 |
|------|------|------|
| API Gateway (REST) — Caller | 1 | 三个路由：/voice /chat /webhook |
| API Gateway (REST) — MCP Server | 1 | 单路由 /mcp，SigV4 鉴权 |
| Lambda L1 - Orchestrator | 1 | 1024MB / 60s（含 Bedrock 调用） |
| Lambda L2 - Execution | 1 | 512MB / 60s |
| Lambda L3 - EventBridge Subscriber | 1 | 512MB / 60s |
| Lambda L4 - MCP Server | 1 | 256MB / 30s |
| EventBridge Rule | 1 | source=`aws.aidevops` |
| AWS DevOps Agent | 共享托管 | 一个 Agent Space |
| Bedrock | 共享 | Claude / Nova / Titan Embed |
| Bedrock KB | 1（可选） | 双写沉淀 |
| S3 - reports | 1 bucket | 30 天 IA, 1 年 Glacier |
| DynamoDB - sessions | 1 表 | TTL = 1h |
| DynamoDB - audit | 1 表 | TTL = 90d |
| DynamoDB - confirm-tokens | 1 表 | TTL = 5min |
| SNS - notifications | 1 topic | 飞书 / 企微 / 邮件订阅 |
| CloudWatch Logs | 共享 | 每 Lambda 一个 log group |

**Lambda 数从 v1 的 7 个减到 v2 的 4 个。**

---

## 9. 成本重算（50 用户 / 月）

### 9.1 用量假设
- 每用户每天 5 次 on-demand chat（每次 30s）
- 每团队每天 2 次 investigation（每次 8 min）
- 每月 5 次 evaluation（每次 15 min）
- 月活跃 22 工作日

### 9.2 明细
| 项 | 计算 | 月成本 |
|---|---|---|
| **DevOps Agent - Chat** | 50 × 5 × 22 × 30s × $0.0083 | **$1,369** |
| **DevOps Agent - Investigation** | 22 × 2 × 8min × 60s × $0.0083 | **$175** |
| **DevOps Agent - Evaluation** | 5 × 15min × 60s × $0.0083 | **$37** |
| Bedrock Claude (Router/Report) | 估 50 × 22 × 5 × 5k tok × ($3+$15)/2/M | **$248** |
| Nova Sonic | 50 × 22 × 10min × $0.012/min×60s | **$79** |
| Lambda × 4 | 调用量低，Free Tier 内 | **~$5** |
| API Gateway | 50 × 22 × 10 = 11k 请求 | **~$5** |
| S3 | 报告 + KB sink，约 1GB | **~$1** |
| DynamoDB | 3 表 PAY_PER_REQUEST | **~$5** |
| CloudWatch Logs | 4 Lambda 总日志 | **~$5** |
| **小计** | | **~$1,930/月** |
| **AWS Support 抵扣** | Enterprise Support 75% × DevOps Agent 部分 | **−$1,186** |
| **净成本** | | **~$744/月**（Enterprise Support）|
| **每用户每月** | | **~$15/用户**（Enterprise Support）|

**注**：
- 不含 Enterprise Support 时净成本 ~$1,930/月，~$39/用户
- Unified Operations 客户 100% 抵扣，净成本 ~$370/月（仅 Bedrock + Nova Sonic + 基础设施）
- **比 PPT 原估的 $19.5/用户 偏高**，但仍优于 Datadog+PagerDuty 的 $44-118/host/月，且我们是 per-user 不是 per-host

### 9.3 与 PPT 估算的差异
| 项 | PPT v1 | 设计 v2 | 原因 |
|---|---|---|---|
| 月度合计 | $975 | $1,930 (无抵扣) / $744 (Enterprise Support) | DevOps Agent 是按秒计费，PPT 没把它单独算 |
| 每用户 | $19.5 | $39 / $15 (Enterprise Support) | 同上 |
| 主要驱动 | Bedrock $500 | DevOps Agent on-demand chat | DevOps Agent 调用累积快 |

---

## 10. Region 与中国区策略

### 10.1 v1 部署 region
- **首选**: `us-east-1`（DevOps Agent + Nova Sonic + Bedrock 全部 GA）
- **备选**: `ap-northeast-1` 东京（亚太低延迟）

### 10.2 中国区
- **AWS 中国区当前不支持 DevOps Agent / Bedrock / Nova Sonic**
- **方案不可直接落地中国区**
- 中国客户的可选路径：
  1. **数据出境模式**：客户接受指标 / 日志通过专线 / VPN 同步到 us-east-1，使用全球区 NLOps（合规需评估）
  2. **降级模式**（v3 路径）：用 SageMaker 自建小模型 + Strands SDK + 自研 RCA 替代 DevOps Agent，损失能力但满足合规
  3. **等待**：等 AWS 中国区 GA（无明确时间表）
- **PPT 中宣传"中国区可用"会被拆穿**，建议改成"全球区可用，中国区 v3 路径规划中"

---

## 11. 项目结构（v2）

```
nlops/
├── docs/
│   ├── 01-requirements.md           # v2 已写
│   ├── 02-design.md                 # 本文档
│   └── 03-devops-agent-integration.md # 待写
├── infra/                           # CDK
│   ├── app.py
│   ├── cdk.json
│   └── nlops_stack.py               # 待重构（4 Lambda）
├── src/
│   ├── handlers/                    # 4 个 Lambda 入口
│   │   ├── api_handler.py           # L1 Orchestrator
│   │   ├── execution_handler.py     # L2 Execution
│   │   ├── eventbridge_handler.py   # L3
│   │   └── mcp_handler.py           # L4 MCP Server
│   ├── orchestrator/                # 新增：Strands 风格编排引擎
│   │   ├── engine.py
│   │   └── tools.py
│   ├── agents/                      # 6 个逻辑 Agent（作为 Tool）
│   │   ├── router.py
│   │   ├── discovery.py
│   │   ├── analysis.py
│   │   ├── execution.py             # 这里只是 Tool stub，真正写在 L2
│   │   ├── knowledge.py
│   │   └── report.py
│   ├── tools/                       # 外部服务适配
│   │   ├── devops_agent.py          # 重写：真实 chat / investigate API
│   │   ├── cloudwatch_mcp.py        # MCP Client（fallback）
│   │   └── bedrock_kb.py            # 双写 KB（可选）
│   ├── mcp_server/                  # 新增：暴露给 DevOps Agent 的 MCP
│   │   ├── server.py
│   │   └── private_tools.py
│   ├── report/
│   │   ├── generator.py
│   │   └── templates/analysis.html
│   ├── voice/
│   │   └── nova_sonic.py
│   └── common/                      # 已写
│       ├── llm.py
│       ├── policy.py
│       ├── session.py
│       ├── audit.py
│       └── logging_utils.py
├── tests/
│   └── test_orchestrator.py
├── requirements.txt
└── README.md
```

---

## 12. 与 PPT 的差异（v2 版本）

| 项 | PPT 描述 | v2 设计 | 原因 |
|---|---|---|---|
| Agent 数量 | 6 个 Agent，独立部署 | **6 个逻辑 Agent，物理 4 Lambda** | DevOps Agent 替代 Discovery/Analysis/Knowledge 重活 |
| 根因分析引擎 | 自研多 Agent | **AWS DevOps Agent**（GA 服务） | 不重复造轮子，94% 准确率即开即用 |
| 知识库 | 自建 Bedrock KB | **DevOps Agent Custom Skills + KB 双写** | Skills 在调查时自动生效；KB 兼容客户已有 |
| 平台与 DevOps Agent 关系 | 未提 | **4 个集成路径**：call-down / event-up / mcp-out / mcp-in | 是 v2 核心架构 |
| 成本 | $975/月 (50 用户) | **$1,930/月 无抵扣 / $744 Enterprise Support** | DevOps Agent 按秒计费 |
| Region | "us-east-1" | **明确 us-east-1，标注中国区不支持** | DevOps Agent 6 region GA |
| 流式语音 | "边分析边播报" | **placeholder TTS + 完成后回复** | DevOps Agent investigation 5-15min，不可能边分析边播 |
| 写操作护栏 | "Policy 护栏 + 用户确认" | **Confirm Token + Policy + IAM 三重 + Lambda 物理隔离** | 落地具体 |
| MCP | "CloudWatch MCP" | **NLOps 既是 MCP Client（消费 AWS MCP）也是 MCP Server（暴露给 DevOps Agent）** | 双向 |
