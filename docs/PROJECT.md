# NLOps v4 项目说明

> 自然语言驱动的 AI 运维平台，基于 AWS DevOps Agent 原生能力构建
> 
> **作者**: 陈朋辉（西云数据）  
> **版本**: v4.0  
> **演示**: 2026-06-02

---

## 📌 项目定位

**一句话**：NLOps v4 是 AWS DevOps Agent (DOA) 的"中国化体验层 + 可视化诊断书 + 自动经验沉淀 + 故障公告自动化"。

**核心价值**：
- DOA 是引擎（运维 AI），NLOps 是驾驶舱
- 不重复造轮子，让 DOA 做它擅长的（跨源关联分析）
- 我们补齐 DOA 不做的（中国 IM 入口、HTML 诊断书、经验自动沉淀）

---

## 🏗️ 架构设计

### 整体拓扑

```
┌──────────────────────────────────────────────────────────────────┐
│                      交互层 (Entry Points)                       │
│                                                                  │
│  飞书 @机器人 · Quick Desktop · SES 邮件 · CW Alarm · DOA EB     │
└──────────────────┬───────────────────────────────────────────────┘
                   ↓
        API Gateway (REST) / SNS Topic / EventBridge
                   ↓
┌──────────────────────────────────────────────────────────────────┐
│  Orchestrator Lambda  (1024MB · Python 3.12 · 4 路由)            │
│                                                                  │
│  • /chat /lark-event /mcp-quick /webhook-incoming                │
│  • EventBridge handler (DOA Investigation Completed)             │
│  • 5 MCP Tools                                                    │
└────────┬───────────────────┬───────────────────┬─────────────────┘
         ↓                   ↓                   ↓
   DevOps Agent       Bedrock Nova Pro    S3 / DDB / SSM Runbook
   (核心引擎)           (AI 增强)
```

### 技术分层

| 层 | 组件 | 职责 |
|----|------|------|
| 交互层 | 飞书 Custom App / Quick mcp-bridge / SES | 用户入口 |
| 编排层 | API Gateway + Orchestrator Lambda | 请求路由 + MCP 工具 |
| AI 层 | DevOps Agent + Bedrock Nova Pro | 核心分析 + 增强 |
| 数据层 | S3 + DynamoDB + SSM Document | 报告/会话/审计/Runbook |

### 关键设计决策

#### 1. 为什么只有 1 个 Lambda?

v3 用了 2 个 Lambda（OrchestratorFn + ExecutionFn）做"读写隔离"。v4 改成 1 个，理由：

- **写操作下沉到 SSM Runbook**：所有写操作都通过 SSM Automation Document 执行，IAM 边界由 SSM 自身管控（`assumeRole` + Document 权限）
- **代码量减少 25%**：去掉 L1 → L2 invoke 的样板代码 + Confirm Token 管理
- **冷启动减少**：少一次跨 Lambda invoke

#### 2. 为什么用 SNS 而不是 EventBridge 做 CW Alarm 路由?

CloudWatch Alarm 的 `AlarmAction` 原生支持 SNS Topic，**不直接支持 EventBridge** (需要绕一圈 EventBridge Rule)。所以告警链路是：

```
CW Alarm → SNS Topic → Lambda Subscription → DOA
```

而 EventBridge 用于 **DOA → NLOps** 方向（Investigation Completed 事件）。

#### 3. 为什么飞书事件用异步两段式?

飞书 webhook 要求 **3 秒内返回 200**，但 DOA chat 调用要 5-30 秒。所以：

```
Stage 1 (sync, < 1s):
  收到事件 → 去重 (event_id) → 自调用 InvocationType=Event → 返回 200

Stage 2 (async):
  另一个 Lambda 实例 → 处理消息 → 调 DOA → 用 Lark Reply API 回复
```

这样满足飞书 3s 限制，又能处理任意耗时的请求。

#### 4. 为什么 HTML 诊断书用公开 URL 而不是 Presigned?

Lambda 用 STS 临时凭证签的 Presigned URL，凭证轮换后 URL 失效。改成：

- S3 Bucket Policy 允许 `/reports/*` 公开读
- 直接生成虚拟主机式 URL（120 字符 vs 2000+ 字符的 presigned）
- URL 永久有效

安全权衡：URL 含时间戳 + UUID，外部猜不到，演示场景可接受。

### 核心序列图

#### 工作流 1：飞书 @机器人主动问诊

```
用户            飞书平台         API GW         Lambda(sync)    Lambda(async)    DOA
 │  @NLOps 调查  │                │                │                │              │
 │──────────────>│                │                │                │              │
 │               │   POST /lark-event              │                │              │
 │               │───────────────>│───────────────>│                │              │
 │               │                │                │  invoke Event  │              │
 │               │                │                │───────────────>│              │
 │               │                │  200 OK (<1s)  │                │              │
 │               │<───────────────│<───────────────│                │              │
 │               │                │                │                │  start_inv   │
 │               │                │                │                │─────────────>│
 │               │                │                │                │  task_id     │
 │               │                │                │                │<─────────────│
 │               │                │                │                │  Reply API   │
 │               │  机器人回复     │                │                │              │
 │<──────────────│<───────────────────────────────────────────────────│            │
 │                                                                                  │
 │  [5-15 分钟后,DOA 完成 Investigation]                                            │
 │                                                EventBridge        Lambda(EB)    │
 │                                                aws.devopsagent     │              │
 │                                                ───────────────────>│              │
 │                                                                    │  ListJournalRecords
 │                                                                    │─────────────>│
 │                                                                    │  AI 报告 md │
 │                                                                    │<─────────────│
 │                                                                    │  Nova Pro 增强
 │                                                                    │  生成公告/摘要/Skill
 │                                                                    │  S3 上传 HTML
 │               飞书卡片(红色)                                       │              │
 │<──────────────────────────────────────────────────────────────────│              │
 │  邮件(SES)                                                          │              │
 │<──────────────────────────────────────────────────────────────────│              │
```

#### 工作流 2：告警自动闭环

```
CW Alarm                SNS Topic       Lambda(webhook)    DOA          EventBridge      Lambda(EB)
   │  state=ALARM          │                  │              │              │                  │
   │─────────────────────>│                  │              │              │                  │
   │                       │   message        │              │              │                  │
   │                       │─────────────────>│              │              │                  │
   │                       │                  │ start_inv    │              │                  │
   │                       │                  │─────────────>│              │                  │
   │                       │                  │   task_id    │              │                  │
   │                       │                  │<─────────────│              │                  │
   │                       │                  │              │ DOA 自动调查 │                  │
   │                       │                  │              │ 5-15 分钟    │                  │
   │                       │                  │              │              │                  │
   │                       │                  │              │ Investigation Completed         │
   │                       │                  │              │─────────────>│                  │
   │                       │                  │              │              │ rule match       │
   │                       │                  │              │              │─────────────────>│
   │                       │                  │              │              │                  │
   │                       │                  │              │              │  ListJournalRecords
   │                       │                  │              │              │  Nova Pro 增强   │
   │                       │                  │              │              │  Jinja2 → S3     │
   │                       │                  │              │              │  飞书 + SES       │
```

---

## 📂 代码组织

### 目录结构

```
nlops/
├── README.md                     # v3 时代的简介（v4 部分见 docs/）
├── docs/
│   ├── design-v4.md              # v4 设计文档（最权威）
│   ├── 04-demo-script-v4.md      # Demo 演示脚本
│   ├── v6-overview.html          # 客户演示用 HTML 介绍页
│   └── PROJECT.md                # 本文件
│
├── infra/                        # CDK v2 (Python)
│   ├── app.py                    # CDK app entry
│   ├── nlops_v4_stack.py         # v4 Stack 定义（~280 行）
│   └── cdk.json
│
├── src/                          # Lambda 源码
│   ├── handlers/                 # 入口 handler
│   │   ├── api_handler.py        # 主入口路由（4 路由 + 异步分发）
│   │   └── lark_handler.py       # 飞书事件处理（异步两段式）
│   │
│   ├── tools/                    # 适配器
│   │   ├── devops_agent.py       # DOA boto3 client
│   │   ├── lark_app.py           # 飞书 Custom App API
│   │   ├── lark_bot.py           # 飞书 Custom Robot Webhook
│   │   ├── ssm_runbook.py        # SSM Automation 执行
│   │   └── ai_enhance.py         # Nova Pro 增强（公告/摘要/Skill/图表）
│   │
│   ├── mcp_server/               # MCP 工具实现
│   │   ├── server.py             # JSON-RPC 服务器
│   │   └── v4_tools.py           # 5 个 MCP 工具
│   │
│   ├── report/                   # HTML 诊断书生成
│   │   ├── generator.py          # Jinja2 + S3 上传
│   │   └── templates/
│   │       └── analysis.html     # 完整模板
│   │
│   └── common/                   # 工具
│       ├── audit.py              # DynamoDB 审计日志
│       └── logging_utils.py      # 结构化 JSON 日志
│
├── ssm-runbooks/                 # SSM Automation Documents
│   ├── ecs-scale.yaml            # ECS service 扩容
│   └── rds-proxy-expand.yaml     # RDS Proxy 连接池扩容
│
├── skills/                       # DOA Skills (Markdown)
│   ├── 01-ecs-troubleshooting.md
│   ├── 02-rds-connection-pool.md
│   ├── 03-lambda-throttling.md
│   └── zip/                      # 打包好的 zip（DOA 上传格式）
│
├── mcp-bridge/                   # Quick Desktop 的本地 stdio MCP 桥接
│   ├── index.js
│   └── package.json
│
└── assets/
    └── AB：自然语言驱动的 AI 运维平台-v6.pptx   # 22 页演示稿
```

### 代码量统计

| 模块 | 行数 |
|------|------|
| Orchestrator Lambda (api_handler.py) | ~430 |
| Lark @机器人 (lark_handler.py) | ~210 |
| 5 MCP 工具 (v4_tools.py) | ~270 |
| AI 增强 (ai_enhance.py) | ~260 |
| DOA 适配器 (devops_agent.py) | ~190 |
| 飞书适配器 (lark_app.py + lark_bot.py) | ~280 |
| SSM Runbook 适配器 (ssm_runbook.py) | ~90 |
| Report Generator + 模板 | ~250 |
| CDK Stack | ~290 |
| **合计** | **~2270 行** |

vs v3 ~3000 行，**减少 25%**，但功能更聚焦。

---

## 🔌 API 端点

部署后的 API URL：`https://0ij69qdk8c.execute-api.us-east-1.amazonaws.com/prod/`

| 端点 | 方法 | 认证 | 用途 |
|------|------|------|------|
| `/chat` | POST | None | 直连 DOA chat 的简单接口 |
| `/lark-event` | POST | None | 飞书事件订阅 webhook |
| `/mcp` | POST | IAM | DOA 的 MCP 集成 |
| `/mcp-quick` | POST | None | Quick Desktop MCP 接口（5 工具） |
| `/sse` | GET/POST | None | MCP SSE 模式（Quick Desktop） |
| `/message` | GET/POST | None | MCP SSE 消息端点 |
| `/webhook-incoming` | POST | None | CW Alarm Webhook 入口 |

---

## 🛠️ 5 个 MCP 工具

| 工具 | 用途 | 入参 | 出参 |
|------|------|------|------|
| `query_doa` | DOA Chat 一次性问答 | `question: str` | DOA 回答文本 |
| `start_investigation` | 启动 Investigation（异步） | `title, description, priority` | `task_id` + Operator URL |
| `get_html_report` | 生成 HTML 诊断书 | `task_id` | S3 永久 URL |
| `trigger_runbook` | 执行 SSM Automation | `document_name, parameters_json, dry_run` | execution_id |
| `notify_im` | 推送 IM 消息 | `channel, subject, body, html_url` | 状态 |

调用示例（curl）：

```bash
curl -X POST https://0ij69qdk8c.execute-api.us-east-1.amazonaws.com/prod/mcp-quick \
  -H "Content-Type: application/json" \
  -d '{
    "jsonrpc":"2.0","id":1,"method":"tools/call",
    "params":{
      "name":"start_investigation",
      "arguments":{
        "title":"demo-api 服务延迟告警",
        "description":"P99 从 200ms 升到 1200ms",
        "priority":"HIGH"
      }
    }
  }'
```

---

## 🔬 5 个 MCP 工具深度规范

### 1. `query_doa`

**输入 schema**：
```json
{
  "type": "object",
  "properties": {
    "question": {"type": "string"}
  },
  "required": ["question"]
}
```

**返回示例**：
```json
{
  "question": "demo-api 服务现在情况怎么样",
  "answer": "P99 延迟在过去 30 分钟从 200ms 升至 320ms。RDS proxy 连接池使用率 78%...",
  "engine": "aws-devops-agent",
  "agent_space_id": "52e43342-bbe2-4fb7-aadd-c072410509ba"
}
```

**实现要点**（`tools/devops_agent.py`）：
- 用 `boto3.client('devops-agent').create_chat()` + `send_message()`
- 25 秒硬超时（`ThreadPoolExecutor.submit(...).result(timeout=25)`）
- 超时返回 mock 字符串，不抛异常

**已知限制**：API Gateway 29s 超时，DOA 调用 5-30s，**有概率超时**。

---

### 2. `start_investigation`

**输入 schema**：
```json
{
  "type": "object",
  "properties": {
    "title":       {"type": "string"},
    "description": {"type": "string"},
    "priority":    {"type": "string", "enum": ["CRITICAL","HIGH","MEDIUM","LOW","MINIMAL"]}
  },
  "required": ["title"]
}
```

**返回示例**：
```json
{
  "task_id": "39a8dd51-3724-4e81-a190-4114d1593927",
  "title": "demo-api 服务为什么慢",
  "status": "in_progress",
  "expected_minutes": "5-15",
  "engine": "aws-devops-agent",
  "operator_console_url": "https://console.aws.amazon.com/devops-agent/spaces/.../tasks/..."
}
```

**实现要点**：用 `create_backlog_task(taskType='INVESTIGATION')`，**异步**，立即返回。

---

### 3. `get_html_report`

**输入 schema**：
```json
{
  "type": "object",
  "properties": {
    "task_id":  {"type": "string"},
    "title":    {"type": "string"},
    "summary":  {"type": "string"},
    "findings": {"type": "string"}
  }
}
```

**返回示例**：
```json
{
  "status": "ok",
  "html_url": "https://nlopsv4stack-...s3.us-east-1.amazonaws.com/reports/diagnostic/.../xxx.html",
  "title": "..."
}
```

**实现要点**：
1. 如果传 `task_id`，先调 `GetBacklogTask` + `ListJournalRecords` 拉 AI 报告
2. Nova Pro 增强：公告、摘要、自动 Skill
3. CloudWatch GetMetricData → ECharts option
4. Jinja2 渲染 → S3 上传 → 公开 URL

---

### 4. `trigger_runbook`

**输入 schema**：
```json
{
  "type": "object",
  "properties": {
    "document_name":   {"type": "string"},
    "parameters_json": {"type": "string"},
    "dry_run":         {"type": "boolean", "default": true}
  },
  "required": ["document_name"]
}
```

**dry_run 返回示例**：
```json
{
  "dry_run": true,
  "document_name": "nlops-ecs-scale",
  "parameters": {"ClusterName": ["demo"], "ServiceName": ["api"], "DesiredCount": ["4"]},
  "preview": "Would execute nlops-ecs-scale with {...}"
}
```

**真实执行返回**：
```json
{
  "status": "started",
  "execution_id": "abc-123-...",
  "document_name": "nlops-ecs-scale",
  "console_url": "https://console.aws.amazon.com/systems-manager/automation/execution/abc-123-..."
}
```

**安全设计**：默认 `dry_run=true`，必须显式 `false` 才执行。

---

### 5. `notify_im`

**输入 schema**：
```json
{
  "type": "object",
  "properties": {
    "channel":  {"type": "string", "enum": ["email", "lark", "wecom"]},
    "subject":  {"type": "string"},
    "body":     {"type": "string"},
    "html_url": {"type": "string"}
  },
  "required": ["channel", "subject", "body"]
}
```

**支持的 channel**：
- ✅ `email` (SES)
- ✅ `lark` (飞书 Custom Robot Webhook，发交互式卡片)
- ❌ `wecom` (Roadmap)

---

## 🔄 核心工作流

### 工作流 1：飞书 @机器人主动问诊

```
用户: @NLOps demo-api 为什么慢
   ↓
飞书 → /lark-event (Lambda 同步部分,< 1s 返回 200)
   ↓ (Lambda 自调用 InvocationType=Event)
异步 Lambda 处理:
  1. 解析 @ 提及，提取问题文本
  2. 意图识别:
     - 问候关键词 → 返回工具能力介绍
     - "调查/排查/为什么" → 调 start_investigation
     - 含 task_id 的"诊断书"请求 → 调 get_html_report
     - 其他 → 调 query_doa
  3. 用 LarkApp.reply_message 回复原消息
```

### 工作流 2：告警自动闭环

```
CloudWatch Alarm → ALARM
   ↓ Alarm Action: SNS Topic
SNS Topic → Lambda Subscription
   ↓
Lambda: _handle_alarm_webhook
  1. 解析 SNS 消息体
  2. 调 _doa.start_investigation()
   ↓
DOA 自动调查（5-15 min）
  - 应用相关 Skills (ECS/RDS/Lambda)
  - 跨源关联 CW + Logs + X-Ray
   ↓ EventBridge: aws.devopsagent
   ↓
EventBridge → Lambda: _handle_doa_event
  1. 解析嵌套事件结构 (metadata.task_id)
  2. ListJournalRecords 获取 AI 完整报告
  3. AI 增强：
     - generate_customer_announcement (公告)
     - generate_internal_summary (摘要)
     - generate_skill_markdown + sink_skill_to_s3
     - build_metrics_chart (CW 指标 → ECharts)
  4. Jinja2 渲染 HTML → S3 (公开 URL)
  5. 推飞书群（红色卡片 + 按钮）
  6. 发 SES 邮件
```

### 工作流 3：HTML 诊断书生成

```
finding 数据结构 → analysis.html (Jinja2 模板) → S3
                       ↓
                    渲染时:
                    - root_cause (根因)
                    - customer_announcement (蓝色卡片)
                    - internal_summary (橙色卡片)
                    - auto_skill (绿色卡片)
                    - metrics_chart (ECharts)
                    - report_md (marked.js 渲染)
                    - tool_uses (工具标签)
                    - operator_portal_url (链接)
```

---

## 💻 技术栈

### 核心服务

| 类别 | 服务 | 版本/规格 |
|------|------|----------|
| AI 引擎 | AWS DevOps Agent | 2026-03 GA |
| LLM | Amazon Bedrock Nova Pro | nova-pro-v1:0 |
| 计算 | AWS Lambda | Python 3.12, 1024MB |
| 网关 | API Gateway | REST API |
| 存储 | Amazon S3 | bucket policy 公开 /reports/* |
| 数据库 | DynamoDB | PAY_PER_REQUEST × 2 表 |
| 通知 | SES + SNS | SES 已 verified |
| 自动化 | SSM Automation | 2 个 Document |
| 事件 | EventBridge | aws.devopsagent rule |

### 第三方集成

| 集成 | 方式 | 用途 |
|------|------|------|
| 飞书 | Custom Robot Webhook | 推送告警/诊断书 |
| 飞书 | Custom App + Event Subscription | @机器人双向对话 |
| Quick Desktop | stdio MCP via mcp-bridge | 桌面端 AI 对话 |

### 关键库

| 库 | 用途 |
|----|------|
| boto3 1.42.97 | AWS SDK（含最新 devops-agent service） |
| Jinja2 3.1.6 | HTML 模板 |
| MarkupSafe 3.0.3 | Jinja2 依赖 |
| python-pptx | PPT 生成（演示前用） |
| marked.js | 浏览器端 markdown 渲染 |
| ECharts 5 | 浏览器端图表 |

---

## 🚀 部署

### 前置条件

- AWS 账号已 enable DevOps Agent
- Bedrock Nova Pro 模型访问权限
- SES 邮箱已 verify
- 飞书 Custom App 已创建（可选，用于 @机器人）

### CDK 部署

```bash
# 1. 构建 botocore Lambda Layer（含最新 devops-agent service）
mkdir -p /tmp/botocore-layer/python
pip install --target /tmp/botocore-layer/python --upgrade boto3 botocore jinja2 markupsafe
find /tmp/botocore-layer -name __pycache__ -type d -exec rm -rf {} +
cd /tmp/botocore-layer && zip -rq /tmp/botocore-layer.zip python/

# 2. 部署 Stack
cd nlops/infra
pip install -r requirements.txt
cdk deploy NLOpsV4Stack
```

### 部署后配置

1. **DOA Agent Space**：把 MCP API URL 注册到 DOA（IAM auth）
2. **CW Alarm Action**：把 alarm 的 SNS topic 设为 Stack 输出的 `AlarmTopicArn`
3. **飞书 Custom App**：事件订阅 URL 填 `<API_URL>/lark-event`
4. **飞书 Custom Robot**：在测试群创建机器人，把 webhook URL 设到 Lambda 环境变量

---

## 🧪 测试与验证

### 单元测试（演示前未实现）
TODO

### 端到端验证

| 场景 | 测试方法 | 预期 |
|------|---------|------|
| MCP 工具列表 | `curl /mcp-quick tools/list` | 返回 5 个工具 |
| 启动 Investigation | `curl /mcp-quick start_investigation` | 返回 task_id |
| 飞书 @机器人 | 群里 @NLOps 你好 | 3-5 秒回复能力介绍 |
| 告警闭环 | `aws cloudwatch set-alarm-state --state-value ALARM` | 飞书 + 邮件双通道 |
| HTML 诊断书 | 触发 Investigation 后等完成 | URL 永久可访问 |

---

## ⚠️ 已知限制与权衡

| 限制 | 原因 | 应对 |
|------|------|------|
| query_doa 偶尔超时 | API GW 29s 硬限制 vs DOA Chat 5-30s | 改用 start_investigation 异步 |
| HTML URL 公开读 | STS 临时凭证轮换问题 | 仅 /reports/* 路径公开 |
| Skills 手动上传 | DOA Skills API 不开放 | Investigation 后自动生成 markdown，但需手动上传到 DOA |
| Quick Desktop 工具调用不稳定 | Quick LLM 行为不可控 | 推荐用飞书替代 |
| Nova Sonic 语音未实现 | API GW 不支持 bidi-stream | Roadmap Phase 4，需 ECS WebSocket |

---

## 🔐 安全模型

### IAM 权限设计

#### Orchestrator Lambda Role 权限

| 权限组 | 资源 | 用途 |
|--------|------|------|
| `bedrock:InvokeModel*` | `*` | 调 Nova Pro 做 AI 增强 |
| `devops-agent:*` + `aidevops:*` | `*` | DOA chat/investigation/journal |
| `ssm:StartAutomationExecution` | `*` | 触发 SSM Runbook |
| `ses:SendEmail` | `*` | 发告警邮件 |
| `cloudwatch:GetMetricData` | `*` | 拉 ECharts 图表数据 |
| `dynamodb:*` | Sessions + Audit 表 | 会话/审计 |
| `s3:*` | ReportBucket | 上传 HTML 诊断书 + 自动 Skill |
| `lambda:InvokeFunction` | self | 飞书事件异步分发 |

**最小权限原则**：每个权限都精确到资源 ARN，不用 `*` 通配（除非服务不支持资源级权限）。

#### DOA Invoke Role（DOA 反向访问 NLOps MCP API）

```
{
  "AssumeRolePolicy": {
    "Service": "aidevops.amazonaws.com",
    "Conditions": {
      "StringEquals": {"aws:SourceAccount": "828414850215"}
    }
  },
  "Policy": {
    "Action": "execute-api:Invoke",
    "Resource": "arn:aws:execute-api:us-east-1:828414850215:.../prod/POST/mcp"
  }
}
```

### 敏感信息管理

| 敏感数据 | 当前方式 | 推荐方式（生产） |
|---------|---------|----------------|
| Lark App Secret | Lambda 环境变量 | AWS Secrets Manager |
| Lark Webhook URL | Lambda 环境变量 | AWS Secrets Manager（启用签名校验） |
| DOA Agent Space ID | Lambda 环境变量（公开） | 保持 |

### 数据保护

- **传输**：所有外部调用 HTTPS（Lark/SES/Bedrock）
- **存储**：S3 SSE-S3 加密；DDB 默认加密
- **公开 URL**：仅 `/reports/*` 路径公开，且 URL 含 UUID + 时间戳，外部猜不到
- **审计**：每个 Lambda 调用写 DynamoDB AuditTable，TTL 90 天

---

## 📊 监控与可观测

### CloudWatch Alarms

| Alarm | 监控对象 | 阈值 |
|-------|---------|------|
| `v4-orchestrator-errors` | Lambda Errors | ≥ 1 次 / 5min |
| `demo-api-high-cpu` | EC2 CPUUtilization | > 1% (演示用) |

### 关键日志查询（CloudWatch Logs Insights）

#### 1. 飞书事件处理统计
```sql
fields @timestamp, @message
| filter @message like /lark.message_parsed/
| parse @message /"preview":\s*"(?<preview>[^"]*)"/
| stats count() by preview
| sort count desc
```

#### 2. DOA Investigation 平均耗时
```sql
fields @timestamp, @message
| filter @message like /eb.received/
| parse @message /"task_id":\s*"(?<task_id>[^"]*)"/
| stats count() by bin(5m)
```

#### 3. AI 增强失败率
```sql
fields @timestamp, @message
| filter @message like /eb.ai_enhance_failed/
| stats count() by bin(1h)
```

### 关键指标

| 指标 | 期望值 | 告警阈值 |
|------|--------|---------|
| Lambda 冷启动时间 | < 1500ms | > 3000ms |
| Lambda 平均执行时间 | < 5s | > 20s (除 query_doa) |
| DOA Investigation 完成时间 | 5-15 min | > 20 min |
| HTML 诊断书上传成功率 | > 99% | < 95% |
| 飞书事件 ack 时间 | < 1s | > 2s |

---

## 🐛 故障排查指南

### 问题 1：飞书 @机器人不回复

**排查步骤**：

1. 查 Lambda 日志最近 5 分钟：
```bash
aws logs tail /aws/lambda/NLOpsV4Stack-OrchestratorFn... --since 5m | grep lark
```

2. 是否看到 `lark.event_received`？
   - ❌ 没看到：飞书事件没到 → 检查飞书 App 事件订阅 URL 配置
   - ✅ 看到：进入下一步

3. 是否看到 `lark.async_dispatched`？
   - ❌ 没看到：检查 IAM 是否有 `lambda:InvokeFunction` 权限
   - ✅ 看到：进入下一步

4. 是否看到 `lark.replied`？
   - ❌ 没看到：异步 Lambda 失败 → 看 ERROR 日志
   - ✅ 看到 `result_code: 0`：飞书已收到回复，检查飞书是否被风控屏蔽

### 问题 2：HTML 诊断书 URL 打开 InvalidAccessKeyId

**已修复**。如果出现：
- 重新生成 URL（旧 URL 用了过期的 STS 临时凭证）
- 现在的实现是直接公开 URL，不签名，永久有效

### 问题 3：CW Alarm 没触发 DOA Investigation

**排查**：

1. SNS Subscription 是否到 Lambda？
```bash
aws sns list-subscriptions-by-topic --topic-arn <NLOpsAlarmTopic>
```

2. CW Alarm 的 AlarmAction 是否设了 SNS Topic？
```bash
aws cloudwatch describe-alarms --alarm-names <name> | jq '.MetricAlarms[].AlarmActions'
```

3. Lambda 是否收到 SNS 事件？
```bash
aws logs tail /aws/lambda/... | grep webhook
```

### 问题 4：DOA Investigation 一直 IN_PROGRESS 不完成

- DOA 的调查时间确实可能长达 15+ 分钟，特别是 Agent Space 没关联实际 AWS 服务时
- 解决：在 DOA 控制台 Agent Space 里关联 AWS 账号 + 服务（CloudWatch / GitHub）
- Demo 临时：用 mock 数据或预录视频

---

## 🚀 部署运维手册

### 完整部署流程（首次）

```bash
# 1. Clone repo
git clone https://github.com/penghui1234/nlops.git
cd nlops
git checkout feat/v4-doa-native

# 2. 构建 botocore + jinja2 layer
mkdir -p /tmp/botocore-layer/python
pip install --target /tmp/botocore-layer/python --upgrade \
    boto3 botocore jinja2 markupsafe
find /tmp/botocore-layer -name __pycache__ -type d -exec rm -rf {} + 2>/dev/null
cd /tmp/botocore-layer && zip -rq /tmp/botocore-layer.zip python/

# 3. CDK bootstrap（首次部署）
cd nlops/infra
pip install -r requirements.txt
cdk bootstrap aws://828414850215/us-east-1

# 4. 部署 Stack
cdk deploy NLOpsV4Stack --require-approval never

# 5. 部署后配置（一次性）
# 5.1 SES 验证邮箱
aws ses verify-email-identity --email-address penghuichen@nwcdcloud.cn --region us-east-1

# 5.2 配置 CW Alarm 的 AlarmAction
aws cloudwatch put-metric-alarm \
  --alarm-name demo-api-high-cpu \
  --alarm-actions $(aws cloudformation describe-stacks --stack-name NLOpsV4Stack \
    --query 'Stacks[0].Outputs[?OutputKey==`AlarmTopicArn`].OutputValue' --output text) \
  ...

# 5.3 在 DOA 控制台:
#   - 创建 Agent Space "nlops-agent-space"
#   - 上传 3 个 Skills (skills/zip/*.zip)
#   - 注册 NLOps MCP Server (URL = McpUrl 输出, Role = DOAInvokeRoleArn)
```

### 增量部署（更新代码）

```bash
# 仅改 Lambda 代码
cdk deploy NLOpsV4Stack --hotswap

# 改 IAM/资源
cdk deploy NLOpsV4Stack --require-approval never
```

### 配置环境变量（不重新部署）

```bash
aws lambda update-function-configuration \
  --function-name NLOpsV4Stack-OrchestratorFn... \
  --environment "Variables={...}" \
  --region us-east-1
```

⚠️ 注意：手动改环境变量后，下次 `cdk deploy` 会被 CDK 配置覆盖。生产环境最好把变量写进 CDK 代码。

### 回滚

```bash
# 选项 A: 重新部署旧版本
git checkout <old-commit>
cdk deploy NLOpsV4Stack

# 选项 B: 直接回滚 CFN Stack
aws cloudformation cancel-update-stack --stack-name NLOpsV4Stack
# 或回滚到上一个 deployment
aws cloudformation continue-update-rollback --stack-name NLOpsV4Stack
```

---

## ❓ FAQ

### Q1: 为什么不用 Strands SDK?

v3 用过 Strands，但发现：
- DOA 自己已经做编排（跨源关联），Strands 多此一举
- Strands Layer 增加 30MB 部署包
- 调试 Strands 内部决策困难

v4 直接用 DOA + 简单 if/else 路由，代码更易懂。

### Q2: Quick Desktop 集成稳定吗?

不稳定。Quick LLM 决定调不调工具是黑盒，有时会"自己编"答案而不调真工具。

**建议**：演示主推飞书 @机器人，Quick Desktop 作为补充。

### Q3: 这能在中国区用吗?

DOA 当前不支持中国区。但已设计了降级路径：

| 场景 | 全球区 | 中国区 (Roadmap) |
|------|--------|----------------|
| 调查引擎 | DOA | CloudWatch Investigations |
| 经验沉淀 | DOA Skills | Bedrock KB |
| LLM | Bedrock Nova Pro | Bedrock Nova Pro（中国区也支持） |
| HTML 诊断书 | 一致 | 一致 |
| 飞书集成 | 一致 | 一致 |

### Q4: 月成本能再压缩吗?

主要成本是 DOA ($900/月)。优化方向：
- **Enterprise Support 抵扣**：DOA 75% 抵扣后 $300/月
- **限制 Investigation 频率**：用 SNS message dedup 避免重复触发
- **Bedrock Nova Pro 切 Lite**：$60 → $20，但准确率有影响

### Q5: 飞书加密事件订阅怎么做?

当前没启用 `Encrypt Key`（演示简化）。生产环境：
- 在飞书 App 配置 Encrypt Key
- 修改 lark_handler 解密 `body.encrypt` 字段
- 见 https://open.feishu.cn/document/server-docs/event-subscription-guide/encrypt-key-encrypt-and-decrypt-data

### Q6: 怎么扩展新的 MCP 工具?

在 `src/mcp_server/v4_tools.py` 加：

```python
@server.tool
def my_new_tool(param: str) -> dict:
    """工具描述（会成为 LLM 看到的 description）。
    
    Args:
        param: 参数说明
    """
    # 实现
    return {"result": "..."}
```

`@server.tool` 装饰器会自动：
- 注册到 MCP server
- 用 inspect 提取 schema
- 暴露给所有 MCP 客户端

### Q7: SSM Runbook 怎么扩展?

在 `ssm-runbooks/` 目录加 yaml 文件，CDK 自动加载：

```yaml
# ssm-runbooks/my-new-runbook.yaml
schemaVersion: "0.3"
description: "..."
parameters:
  ...
mainSteps:
  ...
```

然后修改 `infra/nlops_v4_stack.py` 的 `for rb_name, rb_file in [...]` 列表加一行。

---

## 🔄 v3 → v4 迁移指南

### 主要变化

| 项目 | v3 | v4 |
|------|----|----|
| Lambda 数量 | 2 (L1 + L2) | 1 (Orchestrator) |
| 写操作 | L2 Lambda + Confirm Token | SSM Runbook |
| MCP 工具 | 21 个 | 5 个 |
| Agent 框架 | Strands SDK | 无（DOA 原生） |
| 经验存储 | Bedrock KB | DOA Skills |
| IM | 无 | 飞书 @机器人 + Webhook |
| 默认模型 | Kimi K2.5 | Nova Pro |

### 迁移步骤

```bash
# 1. cdk destroy 旧 stack（保留 S3 数据）
cd nlops/infra
git checkout feat/v3-strands-merger
cdk destroy NLOpsStack
# S3 ReportBucket 设了 RemovalPolicy.RETAIN,会保留

# 2. checkout v4 分支
git checkout feat/v4-doa-native

# 3. 部署 v4
cd infra
cdk deploy NLOpsV4Stack
# 新 stack 名 NLOpsV4Stack,与 v3 NLOpsStack 不冲突

# 4. v3 数据迁移（可选）
# - S3 reports/ 已保留
# - DDB 旧表已被 destroy 删除
# - DOA Agent Space 保持不变
```

### 不向后兼容的变化

- **IAM Role ARN 变化**：DOA 注册的 MCP Server URL 和 Role 都换了，需重新注册
- **API URL 变化**：v3 `49y4ua4p1c.execute-api...` → v4 `0ij69qdk8c.execute-api...`
- **MCP 工具签名变化**：mcp-bridge 需要 npm install 重新握手

---

## 🗺️ Roadmap

| Phase | 内容 | 状态 |
|-------|------|------|
| **Phase 1** | 核心闭环：DOA + Webhook + Skills + 告警 | ✅ |
| **Phase 2** | 体验层：飞书 + HTML 诊断书 + ECharts | ✅ |
| **Phase 2.5** | AI 增强：故障公告 + 经验沉淀 | ✅ |
| Phase 3 | 自动修复：SSM 扩充 + Kiro 集成 | ⏳ |
| Phase 4 | 智能进阶：Nova Sonic 语音 + 多模态 | ⏳ |
| Phase 5 | 中国区：CW Investigations 降级 | ⏳ |

---

## 📚 参考博客

NLOps v4 设计参考了 AWS 官方实践：

1. [Building an end-to-end agentic SRE using AWS DevOps Agent](https://aws.amazon.com/blogs/devops/building-an-end-to-end-agentic-sre-using-aws-devops-agent/) (2026-05)
2. [Telkomsel CELYNA case study](https://aws.amazon.com/solutions/case-studies/telkomsel-case-study/) (2026)
3. [Reimagine AIOps with CloudWatch Investigations and Nova Sonic](https://aws.amazon.com/blogs/mt/reimagine-aiops-with-amazon-cloudwatch-investigations-and-amazon-nova-sonic/) (2025-10)
4. [Using Amazon Bedrock and Amazon Nova for AI-Powered Incident Response](https://aws.amazon.com/blogs/mt/using-amazon-bedrock-and-amazon-nova-for-ai-powered-incident-response/) (2025-07)

---

## 📄 许可

仅作内部方案验证使用。

---

## 联系方式

- **作者**: 陈朋辉
- **邮箱**: penghuichen@nwcdcloud.cn
- **GitHub**: https://github.com/penghui1234/nlops
