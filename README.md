# NLOps · 自然语言驱动的 AI 运维平台

> 在 **AWS DevOps Agent** 之上构建的 IM / Quick Desktop 驱动智能闭环运维平台
> 让 SRE 用文字（v3 暂不含语音）完成"发现 → 定位 → 修复 → 沉淀"全流程

[![region](https://img.shields.io/badge/region-us--east--1-blue)]() [![status](https://img.shields.io/badge/status-v3.0%20Beta-green)]() [![lambda](https://img.shields.io/badge/Lambda-2%20%28L1%2BL2%29-orange)]() [![strands](https://img.shields.io/badge/Strands_SDK-1.40-blueviolet)]()

---

## 架构总览（v3, 2026-05-19 起）

**逻辑视图**（PPT 卖点）：1 Strands Agent + 5 Tool + DOA 引擎

```
NLOps Strands Agent
  ├── @tool discover_service     → DevOps Agent on-demand chat
  ├── @tool deep_investigate     → DevOps Agent CreateBacklogTask (investigation)
  ├── @tool search_knowledge     → Bedrock Knowledge Base
  ├── @tool render_report        → Jinja2 + S3 (HTML 诊断书)
  └── @tool request_execute      → invoke L2 Execution Lambda (写隔离)
```

**物理视图**（实际部署）：2 个 Lambda（"读全在 L1，写隔离 L2"）

```
入口 (Quick Desktop / 飞书 / 企微 / 邮件订阅)
    │
    ▼  /chat /webhook  /mcp /sse /message
┌──────────────────────────────────────────────┐
│ L1 OrchestratorFn (1536MB, Python 3.12)      │
│ • api_handler  (chat/webhook 入口)            │
│ • mcp_handler  (MCP JSON-RPC, 21 工具)        │
│ • eventbridge_handler (DOA Investigation     │
│   Completed → HTML + SES 邮件 + KB 沉淀)     │
│ • Strands SDK 在进程内驱动 5 个 Tool          │
└──────┬─────────────┬────────────────┬─────────┘
       │ confirm     │ Bedrock /      │ EventBridge
       │ + invoke    │ DOA / KB / SES │ aws.aidevops
       ▼             ▼                ▼
┌──────────────┐ ┌────────────────┐ (订阅 DOA 事件)
│ L2           │ │  AWS DevOps    │
│ ExecutionFn  │ │  Agent (引擎)  │
│ (写隔离 IAM) │ │                │
│  ECS / RDS / │ │  Bedrock Nova  │
│  EC2 reboot  │ │  Pro (LLM)     │
└──────────────┘ └────────────────┘
```

详见 [`docs/02-design.md`](docs/02-design.md)。

---

## v3 主要更新（vs v2）

| 项 | v2 | v3 (当前) |
|---|---|---|
| Lambda 数 | 4 (L1+L2+L3+L4) | **2 (L1+L2)** L3/L4 合并入 L1 |
| Agent 框架 | "Strands-style" 自研 95 行 | **真用 strands-agents 1.40 SDK** |
| LLM 默认 | `moonshotai.kimi-k2.5` | `amazon.nova-pro-v1:0` |
| MOCK_MODE 开关 | 无 | **有**（Lambda env 切换 demo / 真实模式） |
| MCP 工具数 | 18 | **21**（新增 smart_diagnose / consult_devops_agent / request_confirm_token） |
| EventBridge → 告警通道 | SNS only | **SES HTML 邮件** + SNS fan-out + KB 双写 |
| DOA boto3 service name | 假设 `aidevops` | **实测 `devops-agent`**（已校正） |
| 写操作护栏 | Confirm Token + L2 隔离 | 同 + Quick Desktop 通过 `request_confirm_token` 工具显式两阶段确认 |

---

## 文档

| 文件 | 行数 | 用途 |
|---|---:|---|
| [`docs/01-requirements.md`](docs/01-requirements.md) | 171 | **需求分析** — P0/P1/P2 / 验收 / 风险 |
| [`docs/02-design.md`](docs/02-design.md) | ~500 | **实现方案** — v3 架构 / Strands / 数据模型 / 成本 / Region |
| [`docs/03-devops-agent-integration.md`](docs/03-devops-agent-integration.md) | ~680 | **DevOps Agent 集成** — 4 路径 / IAM / MCP |
| [`docs/04-demo-script.md`](docs/04-demo-script.md) | ~570 | **演示脚本** — Quick Desktop 5 场景 / Q&A / 翻车预案 |
| [`assets/AB-NLOps-v2.pptx`](assets/AB-NLOps-v2.pptx) | 17 页 | **客户/老板 PPT** |

---

## 项目结构

```
nlops/
├── README.md                      # 本文件
├── requirements.txt               # 运行时依赖
├── .gitignore
├── assets/
│   └── AB-NLOps-v2.pptx           # 17 页演示稿
├── docs/                          # 4 份文档（见上）
├── infra/                         # CDK v2
│   ├── app.py
│   ├── cdk.json
│   └── nlops_stack.py             # 2 Lambda + DDB×3 + S3 + SNS + EventBridge + StrandsLayer
├── mcp-bridge/                    # Quick Desktop MCP 桥接器
│   ├── index.js                   # stdio MCP server (转发到 McpApi)
│   └── package.json
├── src/
│   ├── handlers/                  # 单 L1 Lambda 内多 entry point
│   │   ├── api_handler.py             # 路由分发：EB / MCP / chat
│   │   ├── execution_handler.py       # L2 Execution
│   │   ├── eventbridge_handler.py     # DOA 事件 → HTML + SES + KB
│   │   └── mcp_handler.py             # MCP JSON-RPC
│   ├── orchestrator/              # Strands SDK 集成
│   │   ├── engine.py                  # NLOpsStrandsAgent
│   │   └── factory.py
│   ├── agents/                    # 5 个 Tool 业务实现 + AgentContext
│   │   ├── base.py
│   │   ├── discovery.py / analysis.py / knowledge.py /
│   │   ├── execution.py / report.py
│   │   └── router.py              # 兼容保留（v3 由 Strands 自动路由）
│   ├── tools/                     # 外部服务适配
│   │   ├── devops_agent.py        # boto3('devops-agent') 真调
│   │   ├── cloudwatch_mcp.py      # CW 直连 fallback
│   │   └── bedrock_kb.py          # KB 双写
│   ├── mcp_server/
│   │   ├── server.py
│   │   ├── private_tools.py       # 21 个 MCP 工具入口（含 MOCK_MODE 分支）
│   │   └── _real_impl.py          # 真实 AWS API 实现 (~750 行)
│   ├── report/
│   │   ├── generator.py           # Jinja2 渲染 → S3
│   │   └── templates/
│   │       ├── analysis.html      # 完整诊断书
│   │       └── alert_email.html   # 告警邮件 (内联 CSS)
│   ├── voice/                     # Nova Sonic（v3 暂不演示）
│   │   └── nova_sonic.py
│   └── common/                    # llm / policy / session / audit / log
└── tests/
    └── test_smoke.py              # 9 项基础测试
```

---

## 快速开始

### 前置条件
- AWS 账户在 6 个支持 region 之一（推荐 `us-east-1`）
- AWS DevOps Agent 已 GA 且账号已 enable
- Bedrock 模型访问：`amazon.nova-pro-v1:0` + `amazon.titan-embed-text-v2:0`
- SES：发件邮箱已 verify（sandbox 模式 from + to 都需 verify）
- Python 3.12 + pip
- AWS CDK v2 (`npm i -g aws-cdk`)
- Strands Agents Lambda Layer（CDK 自动从 `/tmp/strands-layer/strands-layer.zip` 上传，本地需先构建）

### 构建 Strands Lambda Layer

```bash
mkdir -p /tmp/strands-layer/python
pip install \
  --platform manylinux2014_x86_64 \
  --python-version 3.12 \
  --target /tmp/strands-layer/python \
  --only-binary=:all: \
  strands-agents jinja2 markupsafe

# 删除 Lambda runtime 已有的 boto3
rm -rf /tmp/strands-layer/python/boto3* /tmp/strands-layer/python/botocore*

cd /tmp/strands-layer && zip -rq strands-layer.zip python/
```

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
- `CallerApiUrl` — IM Bot / Quick / 邮件订阅 webhook
- `McpApiUrl` — MCP server endpoint（DOA / Quick Desktop）
- `McpInvokeRoleArn` — DOA AssumeRole
- `StrandsLayerArn` — strands-agents Layer 引用

### 配置 DevOps Agent
1. AWS Console → DevOps Agent → 创建 Agent Space（记下 ID）
2. Capabilities → MCP Servers → Register → 填 `McpApiUrl/mcp` + `McpInvokeRoleArn`
3. Capabilities → CloudWatch alarms → 关联自动 investigation
4. CDK env 里 `DOA_AGENT_SPACE_ID` 改为新 Space ID 重新部署（或 `aws lambda update-function-configuration`）

### 配置 SES 邮箱（sandbox 模式必做）
```bash
aws ses verify-email-identity --email-address penghuichen@nwcdcloud.cn --region us-east-1
# 收到验证邮件后点击链接确认；或申请退出 sandbox
```

### 本地测试

```bash
pip install -r requirements.txt
pytest tests/ -q   # 9 passed
```

---

## Quick Desktop 集成

### 配置方式

1. **本地安装 mcp-bridge**：
```bash
cd mcp-bridge && npm install
```

2. **Quick Desktop 配置**：
   - 模式：Local
   - Command：`node`
   - Arguments：`<项目路径>/mcp-bridge/index.js`

3. **重新握手**：在 Quick Desktop MCP 设置里禁用 → 启用 NLOps，强制重新拉 21 个工具

### 21 个 MCP 工具

| 类别 | 工具 | 数据源 |
|---|---|---|
| **发现** (3) | `discover_resources` / `discover_alerts` / `discover_incidents` | EC2/ECS/RDS/ELB/Lambda describe + CW alarms + DDB Audit |
| **知识** (4) | `query_knowledge_base` / `search_runbooks` / `get_service_owner` / `get_service_dependencies` | Bedrock KB + Resource Tagging API + X-Ray service map |
| **分析** (4) | `analyze_logs` / `analyze_metrics` / `analyze_traces` / `analyze_root_cause` | CW Logs Insights + GetMetricStatistics + X-Ray + LLM (Nova Pro) |
| **执行** (4) | `execute_remediation` / `restart_service` / `scale_service` / `create_ticket` | invoke L2（confirm_token 校验）+ SNS publish |
| **报告** (3) | `generate_report` / `list_investigations` / `get_investigation` | Jinja2 + S3 + DDB AuditTable |
| **智能** (3) | `smart_diagnose` / `consult_devops_agent` / `request_confirm_token` | Strands Agent + DOA chat + ConfirmTokens 表 |

### 示例对话

```
用户: 看一下当前有哪些 EC2
NLOps: 找到 1 台真实 EC2: i-0257069e2402a0fbc (test, t3.micro, running)
       Service=demo-api, OnCall=penghuichen@nwcdcloud.cn
       
用户: demo-api 为什么慢？
NLOps (调 smart_diagnose → Strands → 5 tool 串联 → DOA):
       已启动深度调查 inv-xyz，初步发现 RDS proxy 连接池 78%。
       完整诊断书 → https://s3.amazonaws.com/.../report.html
       
用户: 帮我把 demo-api 实例数扩到 4
NLOps: 这是写操作。我先调 request_confirm_token 给你看风险卡片：
       Action: ecs.update_service desired_count=4
       Risk: low
       Token: ct-xxx (5 min 有效)
       请确认后我再执行。
用户: 确认
NLOps (调 scale_service with token): 已通过 L2 写隔离执行成功，已审计。
```

---

## 运行模式（Mock vs Real）

| 模式 | 适用场景 | 行为 |
|---|---|---|
| `MOCK_MODE=false`（默认） | 客户验收 / 真实运维 | 调真实 AWS API |
| `MOCK_MODE=true` | 演示彩排 | 返回故事性 demo 数据（payment-api 案例） |

切换不需 redeploy，改 `OrchestratorFn` 环境变量即可：

```bash
aws lambda update-function-configuration \
  --region us-east-1 \
  --function-name NLOpsStack-OrchestratorFn6F7CE538-fDx1bctLRCvy \
  --environment "Variables={MOCK_MODE=true,...其他保留}"
```

---

## 关键环境变量

| 变量 | 说明 | 默认 |
|---|---|---|
| `BEDROCK_MODEL_ID` | Bedrock LLM | `amazon.nova-pro-v1:0` |
| `BEDROCK_EMBED_MODEL` | 嵌入模型 | `amazon.titan-embed-text-v2:0` |
| `BEDROCK_KB_ID` | KB ID（空则知识工具返回 not configured） | `""` |
| `DOA_AGENT_SPACE_ID` | DevOps Agent Space | 占位，需替换 |
| `DOA_BOTO3_SERVICE` | boto3 service name | `devops-agent` |
| `MOCK_MODE` | mock / real 切换 | `false` |
| `ALERT_EMAIL_FROM` / `ALERT_EMAIL_TO` | SES 告警邮箱 | `penghuichen@nwcdcloud.cn` |
| `EXECUTION_FN_NAME` | L2 Lambda 名（自动注入） | — |

---

## 成本（50 用户 / 月，v3 重算）

| 项 | 月度 |
|---|---:|
| AWS DevOps Agent (chat + investigation) | ~$1,581 |
| Bedrock Nova Pro (Strands routing + analyze_root_cause) | ~$80 |
| Lambda × 2（L1 + L2） | ~$5 |
| 其他（API GW + S3 + DDB + SNS + SES） | ~$15 |
| **小计** | **~$1,681** |
| Enterprise Support 抵扣 (DOA 75%) | -$1,186 |
| **净** | **~$495** (~$10/用户) |

v3 比 v2 月成本降 **~$249**（Bedrock 切 Nova Pro 省 ~$168 + Lambda 减少 ~$8 + 其他优化）。

---

## 真实差异化（vs 直接用 DevOps Agent）

| # | NLOps 做的 | DevOps Agent 默认 |
|---|---|---|
| 1 | Quick Desktop / IM 入口（v3 文字优先，语音 v4 加） | ❌ Slack/ServiceNow only |
| 2 | HTML 诊断书 + SES 邮件双通道 | ⚠️ Operator Portal 偏技术 |
| 3 | 写操作护栏 (Confirm Token + L2 隔离 IAM) | ❌ 仅给建议 |
| 4 | smart_diagnose 工具：1 句话触发完整 RCA 闭环 | ❌ 需用户自己组装 |
| 5 | 21 个 MCP 工具盒，任何 MCP-aware AI 都可调用 | ❌ 需自行实现 |

---

## Region & 中国区
- **支持 region**: us-east-1 / us-west-2 / eu-central-1 / eu-west-1 / ap-southeast-2 / ap-northeast-1
- **AWS 中国区**: ❌ DevOps Agent / Bedrock / Nova Sonic 当前不支持
- 中国客户 3 条路径详见 [`docs/02-design.md` §10](docs/02-design.md)

---

## 许可

仅作内部方案验证使用。
