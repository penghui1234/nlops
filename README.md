# NLOps · 自然语言驱动的 AI 运维平台

> 在 **AWS DevOps Agent** 之上构建的语音 / IM 驱动智能闭环运维平台
> 让 SRE 用语音 / 文字完成"发现 → 定位 → 修复 → 沉淀"全流程

[![region](https://img.shields.io/badge/region-us--east--1-blue)]()
[![status](https://img.shields.io/badge/status-PoC-orange)]()

---

## 架构一览

**逻辑视图**（PPT 卖点保留）：6 个 Agent

```
Router → Discovery / Knowledge / Analysis / Execution / Report
```

**物理视图**（实际部署）：4 个 Lambda + AWS DevOps Agent 引擎

```
入口 (Quick / 企微 / 飞书)
    │
    ▼  /chat /voice /webhook
┌──────────────────────────┐         ┌──────────────────────┐
│ L1 Orchestrator Lambda   │ chat()  │                      │
│ (Strands SDK 内 5 Tools) │◀──────▶ │  AWS DevOps Agent    │
└──────────┬───────────────┘ invest()│  (engine, 6 region)  │
           │ confirm_token            │                      │
           ▼                          └─────────┬────────────┘
┌──────────────────────────┐                    │ EventBridge
│ L2 Execution Lambda      │                    ▼
│ (write IAM + tag bound)  │          ┌──────────────────────┐
└──────────────────────────┘          │ L3 EB Subscriber     │
                                      │ (alert-driven HTML)  │
                                      └──────────────────────┘
                                             ▲
                                             │ MCP HTTP+SigV4
                                      ┌──────┴───────────────┐
                                      │ L4 NLOps MCP Server  │
                                      │ (customer's tools)   │
                                      └──────────────────────┘
```

详见 [`docs/02-design.md`](docs/02-design.md)。

---

## 文档

| 文件 | 行数 | 用途 |
|---|---:|---|
| [`docs/01-requirements.md`](docs/01-requirements.md) | 171 | **需求分析** — P0/P1/P2 / 验收 / 风险 |
| [`docs/02-design.md`](docs/02-design.md) | 504 | **实现方案** — 架构 / 流程 / 成本 / Region |
| [`docs/03-devops-agent-integration.md`](docs/03-devops-agent-integration.md) | 679 | **DevOps Agent 集成** — 4 路径 / IAM / MCP |
| [`docs/04-demo-script.md`](docs/04-demo-script.md) | 572 | **演示脚本** — 5-6 场景 / Q&A / 翻车预案 |
| [`assets/AB-NLOps-v2.pptx`](assets/AB-NLOps-v2.pptx) | 17 页 | **客户/老板 PPT v2** |

---

## 项目结构

```
nlops/
├── README.md                  # 本文件
├── requirements.txt           # 运行时依赖
├── .gitignore
├── assets/
│   └── AB-NLOps-v2.pptx       # 17 页演示稿
├── docs/                      # 4 份文档（见上）
├── infra/                     # CDK v2
│   ├── app.py
│   ├── cdk.json
│   ├── requirements.txt
│   └── nlops_stack.py         # 4 Lambda + DDB×3 + S3 + SNS + EB
├── mcp-bridge/              # Quick Desktop MCP 桥接器
│   ├── index.js                     # stdio MCP server
│   └── package.json
├── src/
│   ├── handlers/              # 4 Lambda 入口
│   │   ├── api_handler.py             # L1 Orchestrator
│   │   ├── execution_handler.py       # L2 Execution
│   │   ├── eventbridge_handler.py     # L3 EB Subscriber
│   │   └── mcp_handler.py             # L4 MCP Server
│   ├── orchestrator/          # Strands 风格 in-process 编排
│   │   ├── engine.py
│   │   └── factory.py
│   ├── agents/                # 6 个逻辑 Agent (Tool)
│   │   ├── base.py
│   │   ├── router.py / discovery.py / analysis.py
│   │   ├── knowledge.py / execution.py / report.py
│   ├── tools/                 # 外部服务适配
│   │   ├── devops_agent.py            # 真实 DOA 调用
│   │   ├── cloudwatch_mcp.py          # fallback
│   │   └── bedrock_kb.py
│   ├── mcp_server/            # NLOps as MCP Server
│   │   ├── server.py
│   │   └── private_tools.py
│   ├── report/                # HTML 诊断书
│   │   ├── generator.py
│   │   └── templates/analysis.html
│   ├── voice/                 # Nova Sonic
│   │   └── nova_sonic.py
│   └── common/                # 共享：LLM / Policy / Session / Audit / Log
└── tests/
    ├── conftest.py
    └── test_smoke.py          # 5 项基础测试
```

---

## 快速开始

### 前置条件
- AWS 账户在 6 个支持 region 之一（推荐 `us-east-1`）
- AWS Support plan（推荐 Enterprise，可抵扣 75% DevOps Agent 成本）
- Python 3.12 + pip
- AWS CDK v2 (`npm i -g aws-cdk`)

### 部署

```bash
git clone https://github.com/penghui1234/nlops
cd nlops/infra
pip install -r requirements.txt
pip install -r ../requirements.txt
cdk bootstrap
cdk deploy
```

部署后输出：
- `CallerApiUrl` — 给 IM Bot / Quick 配的 webhook
- `McpApiUrl` — 注册到 DevOps Agent Agent Space 的 MCP Server endpoint
- `McpInvokeRoleArn` — DevOps Agent 假装的 IAM Role ARN

### 配置 DevOps Agent
1. AWS Console → DevOps Agent → 创建 Agent Space
2. Capabilities → MCP Servers → Register → 填 `McpApiUrl` + `McpInvokeRoleArn`
3. Capabilities → CloudWatch alarms → 关联自动 investigation
4. NLOps Lambda 环境变量：`DOA_AGENT_SPACE_ID` 设为新 Space ID

### 本地测试

```bash
pip install -r requirements.txt
pytest tests/ -q
```

---

## Quick Desktop 集成

NLOps 提供 MCP Bridge，支持 Quick Desktop 本地连接：

### 配置方式

1. **安装依赖**：
```bash
cd mcp-bridge
npm install
```

2. **Quick Desktop 配置**：
   - 模式：Local
   - Command：`node`
   - Arguments：`<项目路径>/mcp-bridge/index.js`

### 可用工具（18个）

| 类别 | 工具 | 功能 |
|------|------|------|
| 发现 | `discover_resources` / `discover_alerts` / `discover_incidents` | 资源/告警/事件发现 |
| 知识 | `query_knowledge_base` / `search_runbooks` / `get_service_owner` / `get_service_dependencies` | 知识检索 |
| 分析 | `analyze_logs` / `analyze_metrics` / `analyze_traces` / `analyze_root_cause` | 日志/指标/追踪/根因分析 |
| 执行 | `execute_remediation` / `restart_service` / `scale_service` / `create_ticket` | 修复/重启/扩缩容/工单 |
| 报告 | `generate_report` / `list_investigations` / `get_investigation` | 报告生成 |

### 示例对话

```
用户: order-service 延迟为什么涨了？
NLOps: [调用 analyze_metrics + analyze_logs]
       发现 order-service 在 10:30 后延迟从 50ms 涨到 500ms，
       原因是数据库连接池耗尽...

用户: 帮我扩容到 400
NLOps: 已生成确认令牌，请确认后执行...
```

---

## 环境变量

部署后需在 Lambda 环境变量中配置：

| 变量 | 说明 | 示例 |
|------|------|------|
| `BEDROCK_MODEL_ID` | Bedrock LLM 模型 | `moonshotai.kimi-k2.5` |
| `BEDROCK_EMBED_MODEL` | 嵌入模型 | `amazon.titan-embed-text-v2:0` |
| `DOA_AGENT_SPACE_ID` | DevOps Agent Space | `774d6ebc-...` |
| `REPORT_BUCKET` | 报告存储桶 | `nlopsstack-reportbucket...` |

---

## 成本（50 用户 / 月）

| 项 | 月度 |
|---|---:|
| AWS DevOps Agent (chat + investigation) | ~$1,581 |
| Bedrock LLM (Router / Report) | ~$248 |
| Nova Sonic | ~$79 |
| 其他（Lambda / API GW / S3 / DDB / SNS） | ~$22 |
| **小计** | **~$1,930** |
| Enterprise Support 抵扣 | -$1,186 |
| **净** | **~$744 (~$15/用户)** |

详见 [`docs/02-design.md` §9](docs/02-design.md)。

---

## 真实差异化（vs 直接用 DevOps Agent）

| # | NLOps 做的 | DevOps Agent 默认 |
|---|---|---|
| 1 | 语音入口 (Nova Sonic) | ❌ |
| 2 | 国内 IM 覆盖 (Quick / 企微 / 飞书) | ❌ (Slack/ServiceNow only) |
| 3 | HTML 诊断书 (面向非技术干系人) | ⚠️ Operator Portal 偏技术 |
| 4 | 写操作护栏 (Confirm Token + 独立 Lambda) | ❌ 仅给建议 |
| 5 | 客户私有工具 MCP 暴露 | ❌ 需自行实现 |

---

## Region & 中国区

- **支持 region**: us-east-1 / us-west-2 / eu-central-1 / eu-west-1 / ap-southeast-2 / ap-northeast-1
- **AWS 中国区**: ❌ DevOps Agent / Bedrock / Nova Sonic 当前不支持
- 中国客户 3 条路径详见 [`docs/02-design.md` §10](docs/02-design.md)

---

## 许可

仅作内部方案验证使用。
