# NLOps 实现方案设计

> 版本: v3.0  ·  最后更新: 2026-05-19  ·  对应需求: `01-requirements.md`
>
> v3 修订（vs v2，2026-05-17）：
> - **Strands Agents SDK 1.40 真用**（替代 v2 的"Strands-style"自研编排）
> - **方案 B 合并**：L3 EventBridge Subscriber + L4 MCP Server 合并入 L1，4 Lambda → 2 Lambda
> - **Bedrock 默认模型** Claude → `amazon.nova-pro-v1:0`（演示账号无 Claude 权限）
> - **DOA boto3 service name** 实测校正为 `devops-agent`（v2 推测的 `aidevops` 错误）
> - **Email 告警**：SES HTML 邮件作为主推送通道（替代 IM 卡片，因为 v3 demo 收窄到 Quick Desktop）
> - **MCP 工具数** 18 → 21（新增 `smart_diagnose` / `consult_devops_agent` / `request_confirm_token`）
> - **MOCK_MODE 开关**：演示彩排 vs 真实模式切换不需 redeploy
> - 锁定 region：`us-east-1`，**不支持 AWS 中国区**

---

## 1. 总体架构

### 1.1 逻辑视图（PPT 卖点：1 Strands Agent + 5 Tool）

```
┌──────────────── 用户 / AI Caller ─────────────────┐
│  Quick Desktop (MCP) │ 飞书 / 企微 (webhook, Phase 2) │
└──────────────────────────┬───────────────────────┘
                           │
                ┌──────────▼──────────┐
                │  NLOps Strands Agent │  Bedrock Nova Pro 自动 routing
                │  (system prompt 中文)│
                └──────────┬───────────┘
   ┌─────────┬─────────────┼─────────────┬────────────┐
   ▼         ▼             ▼             ▼            ▼
@discover  @deep_         @search_      @render_    @request_
 _service  investigate    knowledge     report      execute
   │         │             │             │            │
   ▼         ▼             ▼             ▼            ▼
DOA chat  DOA Create    Bedrock KB    Jinja2+S3   invoke L2
          BacklogTask                              (写隔离)
```

**v3 关键变化**：
- 删除独立的 RouterAgent —— Strands LLM 自动根据工具 description 路由
- 5 个 @tool 函数包装原 agents/* 的业务逻辑（DiscoveryAgent / AnalysisAgent / KnowledgeAgent / ReportAgent / ExecutionAgent）
- AgentContext 通过 `contextvars` 在工具间传递，不需要每请求重建 Strands Agent

### 1.2 物理视图（v3 实际部署：2 Lambda）

```
┌─────────────────────── Caller layer ──────────────────────┐
│ Quick Desktop / 飞书 / 企微 / 邮件订阅                    │
│                                                           │
│   stdio MCP (mcp-bridge)        webhook                   │
│         │                         │                        │
│         ▼                         ▼                        │
│  McpApi (REST + SigV4/NoAuth)   CallerApi (REST)          │
│  /mcp /sse /message /mcp-quick   /chat /webhook /voice    │
└──────────────────────────┬───────────────────────────────┘
                           │ all routes target L1
                           ▼
┌──────────────────────────────────────────────────────────┐
│ L1 OrchestratorFn (1536MB / 120s, Python 3.12 + Strands) │
│ ─────────────────────────────────────────────────────── │
│  api_handler.handler() 内部分发：                          │
│   • event.source == aws.aidevops → eventbridge_handler   │
│   • path startsWith /mcp or /sse → mcp_handler           │
│   • else (chat/webhook/voice)    → _chat_flow            │
│                                                          │
│  Strands Agents SDK (1.40) 编排 5 个 @tool                │
│                                                          │
│  21 个 MCP 工具直接暴露给 Quick Desktop 等外部 AI         │
└────┬──────────────────┬────┴──────────────────┬──────────┘
     │ confirm_token    │ DOA / Bedrock /        │ EventBridge
     │ + invoke L2      │ KB / SES / CloudWatch  │ Pub/Sub
     ▼                  ▼                        ▼
┌──────────────┐  ┌──────────────────┐  ┌────────────────────┐
│ L2           │  │  AWS DevOps Agent│  │ EventBridge        │
│ ExecutionFn  │  │  (devops-agent)  │  │ source=aws.aidevops│
│ (写隔离 IAM) │  │  CreateChat /    │  │ DOA Investigation  │
│              │  │  CreateBacklog   │  │ Completed          │
│              │  │  Task            │  │  ↓                 │
│              │  │                  │  │  (target: L1)      │
│              │  │  Bedrock Nova    │  │                    │
│              │  │  Pro (LLM)       │  │                    │
└──────┬───────┘  │                  │  └────────────────────┘
       │ AWS API  │  Bedrock KB      │
       ▼          │  SES SendEmail   │
   AWS resources  │  CW / Logs /     │
   (ECS/EC2/RDS)  │  X-Ray / Tag     │
                  └──────────────────┘
```

**2 个 Lambda 的职责**：

| 编号 | 名称 | 职责 | IAM 关键权限 |
|------|------|------|--------------|
| L1 | **OrchestratorFn** | 所有 chat/MCP/EventBridge 入口；Strands Agent 编排 5 Tools；DOA / Bedrock / KB / SES 调用；HTML 报告生成 | `bedrock:InvokeModel*`、`devops-agent:CreateChat/SendMessage/CreateBacklogTask*`、`ses:SendEmail`、`s3:*`、`lambda:InvokeFunction` (调 L2)、`cloudwatch:Get*` / `logs:StartQuery` / `xray:Get*` / `tag:GetResources` 等只读观测 |
| L2 | **ExecutionFn** | 写操作隔离；只此 Lambda 有 ECS/EC2/RDS 写权限 | `ecs:UpdateService`、`autoscaling:Set*`、`rds:Reboot*`、tag 边界 `aws:ResourceTag/nlops:managed=true` |

**为什么不全合到 1 个 Lambda**：L2 独立的真正价值是**减少 blast radius**。L1 跑 LLM 推理 / 21 个 MCP 工具 / EventBridge 处理；任何一处出 prompt injection / 代码 bug，**只要 L1 没有写权限，攻击面就被收住**。Confirm Token 是软护栏（DDB 校验），真正硬护栏是 IAM。

---

## 2. 4 个集成路径（DOA ↔ NLOps）

| 路径 | 方向 | 触发场景 | 用到的服务 |
|---|---|---|---|
| **call-down** (主动调用) | NLOps → DOA | smart_diagnose 工具 / 用户主动问 | `devops-agent:CreateChat` + `SendMessage`（v2 设计写的 `aidevops:StartChatSession` 已校正） |
| **event-up** (告警闭环) | DOA → NLOps | CloudWatch alarm 触发 DOA 自动调查后 | EventBridge `aws.aidevops` event source |
| **mcp-out** (暴露工具) | DOA → NLOps MCP | DOA 调查时需要客户私有数据 + Quick Desktop 等 AI 调用 | NLOps MCP Server（API GW + Lambda + SigV4 / NoAuth） |
| **mcp-in** (使用 AWS MCP) | NLOps → AWS MCP | NLOps 自身需要标准化访问 CW / X-Ray | (v3 未实现，留 v4) |

详见 `docs/03-devops-agent-integration.md`。

---

## 3. 模块划分

| 模块 | 职责 | 实现 |
|------|------|------|
| **交互入口** | 接收用户请求、做协议适配 | API Gateway × 2（CallerApi + McpApi） |
| **路由分发** | 单 L1 入口判断 source / path | `handlers/api_handler.handler` |
| **会话管理** | 多轮对话上下文、用户身份 | DynamoDB SessionsTable（TTL = 1h） |
| **Strands Orchestrator** | 5 Tool 编排 + LLM 路由 | `orchestrator/engine.py` (NLOpsStrandsAgent) + `strands-agents 1.40` |
| **DevOps Agent Tool** | 调用 chat / investigation API；解析返回 | `tools/devops_agent.py` (boto3 `devops-agent`) |
| **MCP Server** | 暴露 21 个工具给 Quick / DOA | `mcp_server/server.py` + `private_tools.py` (mock/real) + `_real_impl.py` |
| **EventBridge handler** | 接收 DOA 自治调查事件，渲染 HTML + 发邮件 + 写 KB | `handlers/eventbridge_handler.py` |
| **Execution (L2)** | 写操作隔离；confirm_token 校验 | `handlers/execution_handler.py` (独立 Lambda) |
| **Report Tool** | DOA 输出 → JSON → HTML | `report/generator.py` + Jinja2 + ECharts |
| **Alert Email** | DOA 完成后 SES HTML 邮件 | `report/templates/alert_email.html` |
| **Knowledge KB** | 双写 Bedrock KB | `tools/bedrock_kb.py` |
| **Voice 适配** (v4) | Nova Sonic ASR / TTS | `voice/nova_sonic.py`（v3 暂未启用） |
| **Policy Guard** | 软护栏（早拦截、可读错误、审计） | `common/policy.py` |
| **审计日志** | 全链路 trace | DynamoDB AuditTable + CloudWatch Logs |

---

## 4. 核心数据模型（同 v2，未变）

### 4.1 会话 Session
```json
{
  "session_id": "sess-2026-05-19-uuid",
  "user_id": "alice@corp",
  "channel": "quick-desktop-mcp | wecom | feishu",
  "messages": [
    {"role": "user", "content": "...", "ts": 1747488000},
    {"role": "assistant", "content": "...", "ts": 1747488003}
  ],
  "context": {
    "current_service": "demo-api",
    "doa_session_id": "do-...",
    "pending_confirm_token": "ct-..."
  },
  "ttl": 1747491600
}
```

### 4.2 事件报告 Incident Report
```json
{
  "incident_id": "inv-2026-05-19-001",
  "title": "demo-api P99 latency spike",
  "severity": "high",
  "service": "demo-api",
  "devops_agent": {
    "task_id": "inv-...",
    "operator_portal_url": "https://us-east-1.console.aws.amazon.com/aidevops/...",
    "score": 0.94
  },
  "timeline": [...],
  "root_cause": "RDS proxy connection pool exhaustion",
  "fix_steps": [...],
  "evidence": {...}
}
```

### 4.3 Confirm Token
```json
{
  "token": "ct-uuid",
  "session_id": "sess-...",
  "user_id": "alice@corp",
  "action_type": "ecs.update_service",
  "params": "{...}",
  "risk": "low | medium | high",
  "issued_at": 1747488003,
  "expires_at": 1747488303,
  "used": false
}
```

存 DynamoDB ConfirmTokensTable；L2 ExecutionFn 验证：未过期 + 未使用 + session 匹配 + user 匹配。

---

## 5. Strands Agent 编排（v3 替换自研引擎）

### 5.1 定义工具

```python
# src/orchestrator/engine.py
from strands import Agent, tool
from strands.models import BedrockModel

@tool
def discover_service(service: str, window_minutes: int = 30) -> str:
    """Fetch current metrics, logs, and topology for an AWS service.
    Use this when the user asks 'how is X service' / 'X 服务怎么样'.
    """
    ctx = _ctx()  # contextvar
    return DiscoveryAgent().run(ctx, service=service, window_minutes=window_minutes)

# ...其他 4 个 @tool ...
```

### 5.2 创建 Strands Agent

```python
model = BedrockModel(model_id="amazon.nova-pro-v1:0", temperature=0.2)
agent = Agent(
    model=model,
    tools=[discover_service, deep_investigate, search_knowledge,
           render_report, request_execute],
    system_prompt=_SYSTEM_PROMPT,
)
result = agent("payment-api 为什么慢")
# Strands 自动: LLM 路由 → 调 discover_service → 调 deep_investigate → 调 render_report
```

### 5.3 contextvar 传递 ctx

每个工具被 Strands 调用时不传 ctx 参数，但需要访问 user_id / trace_id 等。通过 `contextvars.ContextVar` 在 `NLOpsStrandsAgent.run()` 入口设置，工具内 `_ctx()` 读取。

---

## 6. 关键流程

### 6.1 路径 A：Quick Desktop 主动排障（v3 主路径）

```
1. 用户在 Quick Desktop 说: "demo-api 为什么慢"
2. Quick LLM 看 21 个工具 → 选 smart_diagnose
3. mcp-bridge 转发到 /mcp-quick
4. McpApi → L1.api_handler → mcp_handler → smart_diagnose
5. smart_diagnose 内部:
   - 创建 AgentContext
   - 调 NLOpsStrandsAgent.run(ctx, "demo-api 为什么慢")
   - Strands LLM 决定: 先 discover_service → 再 deep_investigate → 再 render_report
   - 调 DOA chat / CreateBacklogTask
   - Jinja2 渲染 HTML → S3
6. 返回 MCP response: {text, html_url, engine="strands-agents", model="nova-pro"}
7. Quick Desktop 渲染给用户
```

### 6.2 路径 B：告警驱动闭环（event-up）

```
1. CloudWatch Alarm 触发
2. DOA 自动 investigation
3. DOA 完成 → EventBridge 发布事件 source=aws.aidevops
4. L1.api_handler 识别 source 是 aidevops → 路由到 eventbridge_handler
5. L1.eventbridge_handler:
   - DOA GetBacklogTask 拉详情
   - Jinja2 渲染 HTML 诊断书 → S3
   - SES SendEmail (HTML + plain text) → 收件人邮箱
   - tools/bedrock_kb.sink_incident → KB 双写
   - SNS Publish (legacy fan-out)
6. 用户邮箱 / Quick Suite Email Connector 看到告警
7. 用户在 Quick Desktop 问 "刚才什么告警" → smart_diagnose 给完整故事
```

### 6.3 路径 C：写操作（Confirm Token UX）

```
用户在 Quick Desktop: "scale demo-api to 4"
   ↓
Quick LLM 自动两步:
  Step 1: 调 request_confirm_token(action_type="ecs.update_service", 
                                   params_json='{"cluster":"demo","service":"demo-api","desired_count":4}',
                                   risk="low",
                                   user_id="penghui",
                                   session_id="sess-xxx")
       → L1 写 ConfirmTokensTable, 返回 token + 风险描述
       → Quick LLM 把风险卡片显示给用户:
         "Action: ecs.update_service desired_count=4
          Risk: low. Show this to the user; only call write tool 
          with confirm_token=ct-xxx after they confirm."
       → 用户回 "确认"
  Step 2: 调 scale_service(service_name="demo/demo-api", 
                          desired_count=4, 
                          confirm_token="ct-xxx")
       → L1 → invoke L2 ExecutionFn
       → L2: ConfirmTokensTable.get → 校验 token 未过期 / 未使用 / session 匹配
       → L2: ecs.update_service (受 nlops:managed=true tag 边界限制)
       → 返回结果
   ↓
Quick Desktop 显示 "已扩容成功"
```

---

## 7. 关键技术选型（v3 更新）

| 维度 | 选型 | 理由 |
|------|------|------|
| 语言 | Python 3.12 | Strands SDK / boto3 / Lambda 原生 |
| Agent 框架 | **strands-agents 1.40 SDK** + AWS DevOps Agent（底层 RCA 引擎） | v2 自研已淘汰，真用 AWS 官方 SDK |
| LLM 默认 | **`amazon.nova-pro-v1:0`** (us-east-1 on-demand) | Claude 在演示账号无权限；Nova Pro 性价比高、JSON 输出可靠 |
| LLM 备选 | Claude 3.5 Sonnet（账号开通后切） / Mistral Large / DeepSeek V3 / GLM 4.7 | 通过 `BEDROCK_MODEL_ID` env 切换，LLM wrapper 已支持 6 种 family |
| Embedding | Bedrock Titan Embed v2 | 与 Bedrock KB 默认一致 |
| 语音 | Nova Sonic（v3 暂未启用，v4 计划） | 端到端流式，中英文 |
| Knowledge | **Bedrock KB 双写**（v3 主路径） | DOA Custom Skill API 不在 boto3 SDK，仅 console UI 可配；KB 双写自我闭环 |
| 数据源 | DOA 内置集成（CW / Datadog / Dynatrace 等） | 不重复造轮子 |
| MCP | mcp Python SDK + Streamable HTTP / NoAuth | 暴露 21 工具给 DOA + Quick Desktop |
| 基础设施 | CDK v2 (Python) + StrandsLayer | 一键部署 |
| 报告渲染 | Jinja2 + ECharts (CDN) | 静态 HTML，零前端构建 |
| 告警通道 | **SES HTML 邮件 (v3 主)** + SNS fan-out | Email 是 universal 通道，Quick Suite Email Connector 原生支持 |
| 存储 | S3（报告 + KB sink）+ DynamoDB（会话/审计/Confirm Token） | Serverless 标配 |

---

## 8. 部署拓扑（v3 单 region）

| 资源 | 数量 | 说明 |
|------|------|------|
| API Gateway (REST) — Caller | 1 | /chat /voice /webhook |
| API Gateway (REST) — MCP | 1 | /mcp (SigV4) /mcp-public /mcp-quick /sse /message |
| Lambda L1 - OrchestratorFn | 1 | 1536MB / 120s（Strands SDK + 21 工具） |
| Lambda L2 - ExecutionFn | 1 | 512MB / 60s（写隔离） |
| Lambda Layer - StrandsLayer | 1 | 12MB（strands-agents 1.40 + jinja2 + 依赖） |
| EventBridge Rule | 1 | source=`aws.aidevops`, target=L1 |
| AWS DevOps Agent | 共享托管 | Agent Space `52e43342-...` |
| Bedrock | 共享 | Nova Pro / Titan Embed |
| Bedrock KB | 1（可选 v3 未配） | 双写沉淀 |
| S3 - reports | 1 bucket | 30 天 IA, 1 年 Glacier |
| DynamoDB - sessions | 1 表 | TTL = 1h |
| DynamoDB - audit | 1 表 | TTL = 90d |
| DynamoDB - confirm-tokens | 1 表 | TTL = 5min |
| SNS - notifications | 1 topic | 邮件 / 飞书 / 企微订阅 |
| SES - email identity | 1 | `penghuichen@nwcdcloud.cn`（sandbox 模式 verified） |
| CloudWatch Logs | 共享 | 每 Lambda 一个 log group |

**Lambda 数从 v2 的 4 个减到 v3 的 2 个**。

---

## 9. 成本重算（v3, 50 用户/月）

### 9.1 用量假设
- 每用户每天 5 次 on-demand chat（每次 30s）
- 每团队每天 2 次 investigation（每次 8 min）
- 每月 5 次 evaluation（每次 15 min）
- 月活跃 22 工作日

### 9.2 明细
| 项 | 计算 | 月成本 |
|---|---|---|
| **DOA - Chat** | 50 × 5 × 22 × 30s × $0.0083 | **$1,369** |
| **DOA - Investigation** | 22 × 2 × 8min × 60s × $0.0083 | **$175** |
| **DOA - Evaluation** | 5 × 15min × 60s × $0.0083 | **$37** |
| Bedrock Nova Pro (Strands routing + analyze_root_cause) | 估 50 × 22 × 5 × 5k tok × ($0.0008+$0.0032)/2/1k | **~$80** |
| Lambda × 2（L1 1536MB + L2 512MB） | 调用量低，Free Tier 内 | **~$5** |
| API Gateway × 2 | 50 × 22 × 10 = 11k 请求 | **~$5** |
| S3 | 报告 + KB sink，约 1GB | **~$1** |
| DynamoDB × 3 | PAY_PER_REQUEST | **~$5** |
| SNS + SES（< 1k 邮件） | | **~$2** |
| CloudWatch Logs | 2 Lambda 总日志 | **~$3** |
| **小计** | | **~$1,682/月** |
| **AWS Support 抵扣** | Enterprise Support 75% × DOA 部分 | **−$1,186** |
| **净成本** | | **~$496/月**（Enterprise Support）|
| **每用户每月** | | **~$10/用户**（Enterprise Support）|

**v3 比 v2 月成本降 ~$248**：
- Bedrock Claude → Nova Pro：节省 ~$168/月
- 4 Lambda → 2 Lambda：节省 ~$3-8/月
- 其他细节优化：~$72/月

### 9.3 与 PPT v2 估算的差异
| 项 | PPT v1 | 设计 v2 | 设计 v3 |
|---|---|---|---|
| 月度合计 | $975 | $1,930 (无抵扣) / $744 (抵扣) | $1,682 (无抵扣) / $496 (抵扣) |
| 每用户 | $19.5 | $39 / $15 | $34 / $10 |
| 主要驱动 | Bedrock $500 | DOA + Claude | DOA + Nova Pro |

---

## 10. Region 与中国区策略（同 v2）

### 10.1 v3 部署 region
- **首选**: `us-east-1`（DOA + Nova Pro + Bedrock 全部 GA）
- **备选**: `ap-northeast-1` 东京（亚太低延迟）

### 10.2 中国区
- **AWS 中国区当前不支持 DOA / Bedrock / Nova Sonic**
- **方案不可直接落地中国区**
- 中国客户的可选路径：
  1. **数据出境模式**：客户接受指标 / 日志通过专线 / VPN 同步到 us-east-1
  2. **降级模式**（v4 路径）：用 SageMaker 自建小模型 + Strands SDK + 自研 RCA 替代 DOA
  3. **等待**：等 AWS 中国区 GA（无明确时间表）

---

## 11. 项目结构（v3）

```
nlops/
├── docs/
│   ├── 01-requirements.md           # v3 已写
│   ├── 02-design.md                 # 本文档
│   ├── 03-devops-agent-integration.md
│   └── 04-demo-script.md
├── infra/                           # CDK v2
│   ├── app.py
│   ├── cdk.json
│   └── nlops_stack.py               # v3: 2 Lambda + StrandsLayer
├── src/
│   ├── handlers/                    # 单 L1 内多 entry point
│   │   ├── api_handler.py           # 路由分发：EB / MCP / chat
│   │   ├── execution_handler.py     # L2 Execution
│   │   ├── eventbridge_handler.py   # DOA 事件 → HTML + SES + KB
│   │   └── mcp_handler.py           # MCP JSON-RPC
│   ├── orchestrator/                # Strands SDK 集成
│   │   ├── engine.py                # NLOpsStrandsAgent (320 行)
│   │   └── factory.py               # build_default singleton
│   ├── agents/                      # 5 Tool 业务实现 + AgentContext
│   │   ├── base.py
│   │   ├── router.py                # 兼容保留，Strands 自动 routing 后实际不用
│   │   ├── discovery.py / analysis.py / knowledge.py /
│   │   ├── execution.py / report.py
│   ├── tools/                       # 外部服务适配
│   │   ├── devops_agent.py          # boto3('devops-agent')
│   │   ├── cloudwatch_mcp.py
│   │   └── bedrock_kb.py
│   ├── mcp_server/                  # 21 个 MCP 工具
│   │   ├── server.py
│   │   ├── private_tools.py         # 工具入口（含 MOCK_MODE 分支）
│   │   └── _real_impl.py            # 真实 AWS API 实现 (~750 行)
│   ├── report/
│   │   ├── generator.py
│   │   └── templates/
│   │       ├── analysis.html        # 完整诊断书
│   │       └── alert_email.html     # 告警邮件 (内联 CSS)
│   ├── voice/
│   │   └── nova_sonic.py            # v3 暂未启用
│   └── common/                      # llm / policy / session / audit / log
├── tests/
│   ├── conftest.py
│   └── test_smoke.py                # 9 项基础测试
├── mcp-bridge/                      # Quick Desktop stdio 桥接
│   ├── index.js
│   └── package.json
├── requirements.txt
└── README.md
```

---

## 12. 与 PPT 的差异（v3）

| 项 | PPT v2 | 设计 v3 | 原因 |
|---|---|---|---|
| Lambda 数量 | 4（L1+L2+L3+L4） | **2（L1+L2）** | 方案 B 合并 L3/L4 入 L1，写隔离保留 L2 |
| Agent 数量 | 6 个 Agent | **1 Strands Agent + 5 Tool** | Strands 自动 routing 替代独立 RouterAgent |
| Agent 框架 | "Strands SDK" | **真用 strands-agents 1.40 SDK** | v2 是自研 95 行 mimics，v3 真用官方 |
| 默认 LLM | Claude / Nova 可切换 | **Nova Pro 默认**（账号无 Claude） | 演示账号现状 |
| boto3 service name | `aidevops` | **`devops-agent`**（实测校正） | v2 设计文档错 |
| 告警通道 | IM 卡片 (飞书 / 企微) | **SES 邮件 (v3 主)** + SNS fan-out | v3 demo 收窄到 Quick Desktop，飞书/企微 v4 加 |
| Voice (Nova Sonic) | ✅ 已通过验证 | ⏸️ v3 暂不启用，v4 加 | 演示收窄优先级 |
| Custom Skill | 自动注册 (P0) | KB 双写沉淀 (P0)，Skill 待 GA UI 配置 | DOA boto3 SDK 没有 CreateCustomSkill API |
| 多入口 | Quick + 飞书 + 企微 | **v3 仅 Quick Desktop**，飞书/企微 v4 | demo 收窄 |
| 月度成本 | $1,930 (无抵扣) / $744 (抵扣) | **$1,682 / $496** | Nova Pro 比 Claude 便宜 ~$168 |

---

## 13. 运行模式（MOCK_MODE 开关）

NLOps 支持两种运行模式，通过 `MOCK_MODE` 环境变量切换，**不需要 redeploy**：

| 模式 | 适用场景 | 行为 |
|---|---|---|
| `MOCK_MODE=false`（默认） | 客户验收 / 真实运维 | 调真实 AWS API |
| `MOCK_MODE=true` | 演示彩排 | 返回故事性 demo 数据（payment-api 案例） |

**21 个 MCP 工具的 mock vs real 行为**：
- 工具入口（`private_tools.py`）首先检查 `_is_mock()`，true 则返回内联 demo 数据（保留可读性）
- false 则委托给 `_real_impl.py` 真调 AWS API
- 缺少必要环境变量（如 `BEDROCK_KB_ID`）时，real 路径返回明确的 `"error": "XXX not configured"` 而不是崩溃

**切换命令**：
```bash
aws lambda update-function-configuration \
  --region us-east-1 \
  --function-name NLOpsStack-OrchestratorFn6F7CE538-fDx1bctLRCvy \
  --environment "Variables={MOCK_MODE=true,...其他保留}"
```

---

## 14. 已知限制 / v4 计划

| # | 限制 | v4 计划 |
|---|------|---------|
| 1 | DOA Custom Skill 自动注册 — boto3 SDK 没有 API | 等 AWS 暴露 SDK，或保持 KB 双写方案 |
| 2 | 飞书 / 企微 webhook — v3 仅骨架 | v4 加签名校验 + 卡片回复 |
| 3 | Nova Sonic 语音 — v3 未启用 | v4 重新启用，含中英文测试 |
| 4 | mcp-in (NLOps → AWS 官方 CW MCP) | v4 加 fallback 路径 |
| 5 | Bedrock KB ID 未配 | v4 创建 KB + ingestion + 测试 retrieve |
| 6 | X-Ray 未启用 | v4 给所有 Lambda 启用 + 看 service map |
| 7 | SES sandbox | demo 前申请退出 sandbox（24-48h 审批）|
| 8 | Strands SDK Lambda cold start | v4 测实际数据，决定是否开 Provisioned Concurrency |
| 9 | 对话式下钻（FR-4.6 总览→聚焦→链路→代码） | v4 在 Quick Desktop 内实现多轮 |
