# NLOps · 自然语言驱动的 AI 运维平台 (v4)

> 在 **AWS DevOps Agent** 之上构建的飞书 / Quick Desktop 驱动智能闭环运维平台
> 让 SRE 用文字（v4 暂不含语音）完成"发现 → 定位 → 修复 → 沉淀"全流程

[![region](https://img.shields.io/badge/region-us--east--1-blue)]() [![status](https://img.shields.io/badge/status-v4.0-green)]() [![lambda](https://img.shields.io/badge/Lambda-1-orange)]() [![doa](https://img.shields.io/badge/DOA-native-blueviolet)]()

---

## ✨ v4 亮点

- 🚀 **DOA 原生为主**: 不再自建 Strands Agent 编排，直接用 DOA 跨源关联分析
- 🎨 **HTML 诊断书**: 仪表盘式 7-Tab 诊断报告（AI 解读 + ECharts + Mermaid + 工具标签）
- 📱 **飞书 @机器人**: 双向对话，3 秒内异步 ack，自动调用 DOA
- 🚨 **告警自动闭环**: CW Alarm → DOA → 飞书+邮件 + 自动公告
- 🧬 **经验自动沉淀**: 每次 Investigation 后 Nova Pro 自动生成 Skill
- 📣 **故障公告自动化**: AI 同时生成"用户公告"+"SRE 摘要"两版文案
- ⚙️ **5 个精简 MCP 工具**: 比 v3 减少 76%，更聚焦实用

---

## 架构总览（v4，2026-05-30）

```
┌──────────────────────────────────────────────────────────────────┐
│  入口: 飞书 @机器人 · Quick Desktop · CW Alarm · DOA EventBridge │
└────────────────────────────┬─────────────────────────────────────┘
                             ↓  API Gateway (REST) / SNS
┌──────────────────────────────────────────────────────────────────┐
│  Orchestrator Lambda (1024MB · Python 3.12 · 4 路由)             │
│   ├── /chat                  — 直连 DOA chat                      │
│   ├── /lark-event            — 飞书事件 (异步两段式)              │
│   ├── /mcp-quick /mcp        — 5 MCP 工具                          │
│   ├── /webhook-incoming      — CW Alarm 转发                       │
│   └── EventBridge handler    — Investigation 完成 → HTML+IM       │
└────┬───────────┬───────────┬─────────────────────────────────────┘
     ↓           ↓           ↓
   DOA      Bedrock     S3 / DDB / SSM Runbook
 (核心引擎) Nova Pro    (报告 / 会话 / 自动修复)
 (3 Skills) (AI 增强)
```

详见 [`docs/design-v4.md`](docs/design-v4.md) · [`docs/PROJECT.md`](docs/PROJECT.md)

---

## v3 → v4 主要变化

| 项 | v3 | v4 |
|---|---|---|
| Lambda 数 | 2 (L1+L2) | **1** L2 → SSM Runbook |
| Agent 框架 | Strands SDK | **无**（DOA 自带编排） |
| MCP 工具数 | 21 | **5** |
| 经验存储 | Bedrock KB + S3 | **DOA Skills** 原生 |
| 写操作 | L2 Lambda + Confirm Token | **SSM Automation** |
| IM | 无 | **飞书 @机器人 + 群消息卡片** |
| HTML 诊断书 | 简单模板 | **7-Tab 仪表盘 + ECharts + Mermaid** |
| AI 增强 | 无 | **故障公告 + SRE 摘要 + 自动 Skill** |
| 代码行数 | ~3000 | **~2270 (-25%)** |
| 月成本 (50 用户) | $1,682 | **$452 (-73%)** |

---

## 文档

| 文件 | 用途 |
|---|---|
| [`docs/design-v4.md`](docs/design-v4.md) | **设计文档** — 架构 / 工作流 / 设计决策 |
| [`docs/PROJECT.md`](docs/PROJECT.md) | **工程师手册** — 部署 / 运维 / 故障排查 / FAQ |
| [`docs/04-demo-script-v4.md`](docs/04-demo-script-v4.md) | **演示脚本** — 4 段 Demo 详细流程 |
| [`docs/v6-overview.html`](docs/v6-overview.html) | **客户介绍页** — 一页式可视化总览 |
| [`assets/AB：自然语言驱动的 AI 运维平台-v7.pptx`](assets/) | **演示 PPT** — 23 页 |

---

## 项目结构

```
nlops/
├── README.md                         # 本文件
├── requirements.txt                  # Python 运行时依赖
│
├── docs/                             # 4 份文档
│   ├── design-v4.md
│   ├── PROJECT.md
│   ├── 04-demo-script-v4.md
│   └── v6-overview.html
│
├── infra/                            # CDK v2 (Python)
│   ├── app.py
│   ├── cdk.json
│   └── nlops_v4_stack.py             # 1 Lambda + DDB×2 + S3 + APIGW + EB Rule
│
├── src/                              # Lambda 源码
│   ├── handlers/
│   │   ├── api_handler.py            # 主入口路由（4 路由 + 异步分发）
│   │   └── lark_handler.py           # 飞书事件处理（异步两段式）
│   ├── tools/
│   │   ├── devops_agent.py           # DOA boto3 client
│   │   ├── lark_app.py               # 飞书 Custom App API
│   │   ├── lark_bot.py               # 飞书 Custom Robot Webhook
│   │   ├── ssm_runbook.py            # SSM Automation
│   │   └── ai_enhance.py             # Nova Pro 增强
│   ├── mcp_server/
│   │   ├── server.py                 # JSON-RPC 服务器
│   │   └── v4_tools.py               # 5 个 MCP 工具
│   ├── report/
│   │   ├── generator.py              # Jinja2 + S3 上传
│   │   └── templates/
│   │       └── analysis.html         # 7-Tab 诊断书模板
│   └── common/
│       ├── audit.py
│       └── logging_utils.py
│
├── ssm-runbooks/                     # SSM Automation Documents
│   ├── ecs-scale.yaml
│   └── rds-proxy-expand.yaml
│
├── skills/                           # DOA Skills 内容
│   ├── 01-ecs-troubleshooting.md
│   ├── 02-rds-connection-pool.md
│   ├── 03-lambda-throttling.md
│   └── zip/                          # 打包好的 zip (DOA 上传用)
│
├── mcp-bridge/                       # Quick Desktop MCP stdio bridge
│   ├── index.js
│   └── package.json
│
└── assets/                           # 演示资料
    └── AB：自然语言驱动的 AI 运维平台-v7.pptx
```

---

## 快速开始

### 前置条件
- AWS 账户在 6 个支持 region 之一（推荐 `us-east-1`）
- AWS DevOps Agent 已 GA 且账号已 enable
- Bedrock 模型访问：`amazon.nova-pro-v1:0`
- SES：发件邮箱已 verify
- 飞书 Custom App 已创建（用于 @机器人）+ Custom Robot Webhook（用于群推送）
- Python 3.12 + pip + AWS CDK v2

### 构建 Lambda Layer

```bash
mkdir -p /tmp/botocore-layer/python
pip install \
  --target /tmp/botocore-layer/python \
  --upgrade boto3 botocore jinja2 markupsafe
find /tmp/botocore-layer -name __pycache__ -type d -exec rm -rf {} + 2>/dev/null
cd /tmp/botocore-layer && zip -rq /tmp/botocore-layer.zip python/
```

### 部署

```bash
git clone https://github.com/penghui1234/nlops
cd nlops/infra
pip install -r requirements.txt
cdk bootstrap   # 首次部署
cdk deploy NLOpsV4Stack
```

部署后输出（CFN Outputs）：
- `ApiUrl` — API Gateway 根 URL
- `ChatUrl` / `WebhookUrl` / `McpUrl` / `McpQuickUrl` — 各路由
- `AlarmTopicArn` — SNS Topic（CW Alarm 设为 AlarmAction）
- `DOAInvokeRoleArn` — DOA 反向调用 MCP API 的 Role
- `ReportBucketName` — HTML 诊断书 S3 bucket

### 配置 DevOps Agent
1. AWS Console → DevOps Agent → 创建 Agent Space（记下 ID）
2. Capabilities → MCP Servers → Register → 填 `McpUrl` + `DOAInvokeRoleArn`
3. Skills → Upload skill → 依次上传 `skills/zip/*.zip`
4. CDK env `DOA_AGENT_SPACE_ID` 改为新 Space ID 重新部署

### 配置 SES + 飞书
```bash
# SES verify
aws ses verify-email-identity --email-address <你的邮箱> --region us-east-1

# Lambda 环境变量（飞书 Custom App + Custom Robot）
aws lambda update-function-configuration \
  --function-name <NLOpsV4Stack-OrchestratorFn...> \
  --environment "Variables={
    LARK_APP_ID=cli_xxx,
    LARK_APP_SECRET=xxx,
    LARK_WEBHOOK_URL=https://open.feishu.cn/open-apis/bot/v2/hook/xxx
  }"
```

详细步骤见 [`docs/PROJECT.md` § 部署运维手册](docs/PROJECT.md#-部署运维手册)。

---

## 5 个 MCP 工具

| 工具 | 用途 | 异步? |
|------|------|------|
| `query_doa` | 一次性问诊 (DOA Chat) | 同步 5-30s |
| `start_investigation` | 启动深度调查 | 异步,立即返回 |
| `get_html_report` | 生成 HTML 诊断书 | 同步 3-5s |
| `trigger_runbook` | 执行 SSM Runbook | 默认 dry-run |
| `notify_im` | 推送到 IM (email/lark) | 同步 1-2s |

调用示例：

```bash
curl -X POST $ApiUrl/mcp-quick \
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

详细规范见 [`docs/PROJECT.md` § MCP 工具深度规范](docs/PROJECT.md#-5-个-mcp-工具深度规范)。

---

## 核心工作流

### 飞书 @机器人主动问诊
```
@NLOps 帮我调查 demo-api 为什么慢
   ↓ Lark webhook → Lambda (sync ack <1s) → 异步处理
   ↓ DOA start_investigation → task_id
   → 飞书回复 "已启动调查 task_id: xxx"
   ↓ 5-15 分钟后 DOA 完成
EventBridge → Lambda (EB handler):
   ├── ListJournalRecords 抓 AI 报告
   ├── Nova Pro 生成公告 / 摘要 / 自动 Skill
   ├── ECharts 指标图 + Jinja2 渲染 → S3
   ├── 飞书群红色卡片 (含按钮)
   └── SES HTML 邮件
```

### 告警自动闭环
```
CW Alarm → SNS Topic → Lambda → DOA → ...（同上 EB handler 流程）
```

详见 [`docs/PROJECT.md` § 核心工作流](docs/PROJECT.md#-核心工作流)。

---

## 成本（50 用户/月）

| 项 | 月度 |
|---|---:|
| AWS DevOps Agent | $900 |
| Bedrock Nova Pro | $60 |
| Lambda × 1 + API GW + DDB + S3 + SES + SNS | $17 |
| **合计** | **$977** |
| Enterprise Support 抵扣 (DOA 75%) | -$525 |
| **净** | **$452 (~$9/用户/月)** |

---

## 真实差异化（vs 直接用 DevOps Agent）

| # | NLOps v4 增量 | DOA 默认 |
|---|---|---|
| 1 | 飞书 @机器人 + 邮件 + Quick Desktop | ❌ 仅 Slack |
| 2 | 7-Tab HTML 诊断书 (图表+解读+证据) | ⚠️ Operator Portal 偏技术 |
| 3 | 故障公告自动生成 (中文公告 + SRE 摘要) | ❌ |
| 4 | 经验自动沉淀 (Investigation → Skill) | ⚠️ 手动创建 |
| 5 | SSM Runbook 自动修复 | ⚠️ 仅给建议 |
| 6 | 5 个 MCP 工具盒 (任何 MCP-aware AI 可调用) | ❌ |

---

## Region & 中国区
- **支持 region**: us-east-1 / us-west-2 / eu-central-1 / eu-west-1 / ap-southeast-2 / ap-northeast-1
- **AWS 中国区**: ❌ DevOps Agent 不支持，已设计降级路径（Phase 5 用 CloudWatch Investigations）

---

## Branch 说明

- `feat/v4-doa-native` (当前) — v4 主分支
- `feat/v3-strands-merger` — v3 backup（卸载前的最后状态）
- `main` — 暂未发布到 main

---

## 许可

仅作内部方案验证使用。

## 联系方式

- **作者**: 陈朋辉（西云数据 · 解决方案架构师）
- **邮箱**: penghuichen@nwcdcloud.cn
- **演示**: 2026-06-02
