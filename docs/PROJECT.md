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
