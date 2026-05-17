# NLOps 实现方案设计

> 版本: v1.0  ·  最后更新: 2026-05-17  ·  对应需求文档: `01-requirements.md`

## 1. 总体架构

```
┌────────────────────────────────────────────────────────────────────┐
│  交互层  Amazon Quick (MCP)  │  企微 Bot (Webhook)  │  飞书 Bot     │
│         语音 / 文字输入           输出: 语音 + HTML 分析页 URL       │
└──────────────────────────┬─────────────────────────────────────────┘
                           │ HTTPS
                  ┌────────▼────────┐
                  │   API Gateway   │   /voice  /chat  /webhook
                  └────────┬────────┘
                           │
                  ┌────────▼─────────┐
                  │ Lambda: Entry    │   会话管理 / 鉴权 / 限流
                  └────────┬─────────┘
                           │
        ┌──────────────────▼──────────────────┐
        │  AgentCore  +  Strands SDK          │
        │  ┌────────────────────────────────┐ │
        │  │  Router Agent (意图识别 / DAG)  │ │
        │  └─────┬──────┬───────┬──────┬────┘ │
        │        ▼      ▼       ▼      ▼      │
        │  Discovery  Knowledge  Analysis  Execution
        │     │          │          │         │  │
        │     └────┬─────┴────┬─────┴────┬────┘  │
        │          ▼          ▼          ▼       │
        │              Report Agent (HTML)       │
        └────────┬───────────────┬───────────────┘
                 │               │
        ┌────────▼─────┐ ┌──────▼──────┐
        │ AWS 服务层   │ │ 数据/存储层 │
        │ - CW MCP     │ │ - Bedrock KB │
        │ - DevOps Agt │ │ - S3 (报告)  │
        │ - SNS / SES  │ │ - DynamoDB   │
        │ - Bedrock LLM│ │   (会话/审计)│
        │ - Nova Sonic │ │              │
        └──────────────┘ └──────────────┘
```

---

## 2. 模块划分

| 模块 | 职责 | 实现 |
|------|------|------|
| **交互入口** | 接收用户请求、做协议适配 | API Gateway + 三个 Adapter（Quick / WeCom / Feishu） |
| **会话管理** | 维护多轮对话上下文、用户身份 | DynamoDB（`session_id` 为分区键，TTL = 1h） |
| **Router Agent** | 意图识别 + 子 Agent 调度 | Bedrock LLM (Claude 3.5 Sonnet)，输出结构化 plan |
| **Discovery Agent** | 拉取指标 / 日志 / 事件 / 拓扑 | 调用 CloudWatch MCP Server |
| **Analysis Agent** | 根因分析（只读） | 调用 DevOps Agent + LLM 综合 |
| **Execution Agent** | 执行修复（写） | 调用 DevOps Agent + Policy Guard |
| **Knowledge Agent** | 经验检索 + 沉淀 | Bedrock Knowledge Base + Embedding |
| **Report Agent** | 生成 HTML 分析页 | LLM 生成结构化 JSON → Jinja2 模板 → ECharts |
| **Policy Guard** | Agent 调用权限拦截 | AgentCore Policy + 自研 PolicyEngine |
| **审计日志** | 全链路追踪 | CloudWatch Logs + Embedded Metric Format |

---

## 3. 核心数据模型

### 3.1 会话 Session
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
    "current_incident_id": "inc-xxx"
  },
  "ttl": 1747491600
}
```

### 3.2 Agent 调度 Plan
```json
{
  "intent": "troubleshoot",
  "confidence": 0.93,
  "steps": [
    {"agent": "Discovery", "input": {"service": "order-service", "window": "30m"}, "parallel_group": "A"},
    {"agent": "Knowledge", "input": {"query": "order latency spike"}, "parallel_group": "A"},
    {"agent": "Analysis", "input": {"depends_on": ["Discovery", "Knowledge"]}},
    {"agent": "Report",   "input": {"depends_on": ["Analysis"]}}
  ]
}
```

### 3.3 事件报告 Incident Report
```json
{
  "incident_id": "inc-2026-05-17-001",
  "title": "order-service P99 延迟突增",
  "severity": "high",
  "timeline": [
    {"ts": "2026-05-17T14:30:00Z", "event": "P99 latency rose from 200ms to 2s"},
    {"ts": "2026-05-17T14:32:10Z", "event": "DB CPU reached 95%"}
  ],
  "root_cause": "RDS proxy 连接池耗尽，慢查询堆积",
  "impact": {"services": ["order-service"], "users_affected": "~2%"},
  "fix_steps": ["扩容 RDS proxy 连接数 200 → 400", "重启 order-service Pod"],
  "verification": "P99 恢复至 250ms",
  "evidence": {
    "trace_ids": ["1-66...."],
    "log_snippets": ["ERROR ConnectionPoolExhausted"],
    "metrics": ["RDSProxy.DatabaseConnections"]
  },
  "embedding": [0.12, -0.45, ...]
}
```

---

## 4. Agent 协作机制

### 4.1 Agent-as-Tool
每个 Agent 既是独立 Lambda，也注册为可被其他 Agent 调用的 Tool（OpenAPI 风格签名）。
例：`Analysis.invoke({"task": "find similar incidents"})` 内部会调用 `Knowledge` Agent。

### 4.2 Policy Guard
| Agent | 默认权限 | 写操作策略 |
|-------|---------|------------|
| Router      | 读 LLM、读 Session    | 无写权 |
| Discovery   | 读 CW / X-Ray / EC2 元数据 | 无写权 |
| Analysis    | 读 + 调用 DevOps Agent (read-only) | 无写权 |
| Knowledge   | 读 / 写 Bedrock KB     | 仅写 KB |
| Report      | 写 S3 (报告 bucket)    | 仅写报告 |
| **Execution** | **读 + 写 EC2/RDS/ECS** | **必须有用户 confirm token** |

伪代码：
```python
def guard(agent_name: str, action: dict, ctx: Context):
    policy = POLICIES[agent_name]
    if action["type"] in policy["write_ops"] and not ctx.user_confirmed:
        raise PolicyDenied("write requires user confirmation")
    if not policy.allows(action["resource"]):
        raise PolicyDenied(f"{agent_name} cannot touch {action['resource']}")
```

### 4.3 并行调度
Router 输出的 plan 中相同 `parallel_group` 的 step 用 `asyncio.gather` 并发执行；不同 group 串行。

---

## 5. 关键技术选型

| 维度 | 选型 | 理由 |
|------|------|------|
| 语言 | Python 3.12 | Strands SDK 原生支持，AWS SDK 完整 |
| Agent 框架 | AgentCore + Strands SDK | 官方推荐，支持 Tool / Policy / Memory |
| LLM | Bedrock - Claude 3.5 Sonnet (主) / Nova Pro (备) | 模型无关设计，可切换 |
| Embedding | Bedrock - Titan Embed v2 | 与 KB 默认模型一致 |
| 语音 | Nova Sonic (Speech-to-Speech) | 端到端流式，中英文混合 |
| Knowledge | Bedrock Knowledge Base + OpenSearch Serverless | 托管，免运维 |
| 数据源 | CloudWatch MCP Server + DevOps Agent | 官方 MCP，统一协议 |
| 基础设施 | CDK v2 (Python) | 一键部署，与业务代码同语言 |
| 报告渲染 | Jinja2 + ECharts (CDN) | 静态 HTML 即可，零前端构建 |
| 存储 | S3（报告）+ DynamoDB（会话/审计） | Serverless 标配 |

---

## 6. 关键流程

### 6.1 端到端故障排查（语音入口）
```
1. 用户在企微说: "order-service 延迟为什么涨了"
2. WeCom Adapter → API Gateway /voice
3. Lambda Entry:
   3.1 Nova Sonic ASR → "order-service 延迟为什么涨了"
   3.2 加载/创建 session
   3.3 调用 Router Agent
4. Router Agent (LLM) → Plan:
   - parallel: [Discovery(order-service, 30m), Knowledge("latency spike")]
   - serial:   [Analysis, Report]
5. 并行执行 Discovery + Knowledge
6. Analysis Agent 综合两者 + 调 DevOps Agent → 根因
7. Report Agent → JSON → HTML → S3 → Presigned URL
8. Lambda Entry:
   8.1 Nova Sonic TTS 流式播报摘要（边生成边播）
   8.2 同步推送 HTML URL 卡片到企微
9. 用户确认修复 → Execution Agent
10. 完成后 Knowledge Agent 自动沉淀报告
```

### 6.2 经验匹配优先策略
```
用户请求 → Knowledge.search(query) → Top-K
   ├── score > 85% → 直接推荐历史方案 + 一键复用
   ├── 60-85%      → 作为参考，仍走完整 Analysis
   └── < 60%       → 完整流程，结束后 sink 入库
```

---

## 7. 部署拓扑（单 region）

| 资源 | 数量 | 说明 |
|------|------|------|
| API Gateway (REST) | 1 | 三个路由：/voice /chat /webhook |
| Lambda - Entry | 1 | 256MB / 30s |
| Lambda - Agent (六个) | 6 | 512MB / 60s，独立 Role |
| Bedrock | 共享 | Claude / Nova / Titan Embed |
| AgentCore | 1 实例 | 注册 6 Agent |
| Bedrock KB | 1 | OpenSearch Serverless backend |
| S3 - reports | 1 bucket | 30 天 lifecycle 转 IA, 1 年转 Glacier |
| DynamoDB - sessions | 1 表 | TTL 启用 |
| DynamoDB - audit | 1 表 | 90 天 TTL |
| SNS - notifications | 1 topic | 飞书 / 企微 / 邮件订阅 |
| CloudWatch Logs | 共享 | 每个 Lambda 独立 log group |

---

## 8. 项目结构

```
nlops/
├── docs/
│   ├── 01-requirements.md    # 需求分析（已写）
│   └── 02-design.md          # 本文档
├── infra/                    # CDK
│   ├── app.py
│   ├── cdk.json
│   └── nlops_stack.py
├── src/
│   ├── handlers/             # Lambda 入口
│   │   └── api_handler.py
│   ├── agents/               # 6 个 Agent
│   │   ├── base.py
│   │   ├── router.py
│   │   ├── discovery.py
│   │   ├── analysis.py
│   │   ├── execution.py
│   │   ├── knowledge.py
│   │   └── report.py
│   ├── tools/                # 工具适配器
│   │   ├── cloudwatch_mcp.py
│   │   ├── devops_agent.py
│   │   └── bedrock_kb.py
│   ├── report/
│   │   ├── generator.py
│   │   └── templates/analysis.html
│   ├── voice/
│   │   └── nova_sonic.py
│   └── common/
│       ├── policy.py         # Policy Guard
│       ├── session.py        # 会话存取
│       └── llm.py            # Bedrock LLM 封装
├── tests/
│   └── test_router.py
├── requirements.txt
└── README.md
```

---

## 9. 与 PPT 方案的差异

| 项 | PPT | 本设计 | 原因 |
|----|-----|--------|------|
| 会话存储 | 未明确 | DynamoDB + TTL | 多轮对话必须持久化 |
| 审计 | 未明确 | DynamoDB audit 表 | Policy 拦截需要审计依据 |
| 写操作确认 | "用户确认" | confirm token + Policy 双重 | 避免误触 / 重放攻击 |
| 报告渲染 | "HTML 模板引擎" | Jinja2 + ECharts CDN | 选定具体方案 |
| 模型切换 | "模型无关" | LLM 适配层 + 主备配置 | 可灰度切换降本 |
| 经验冷启动 | 50 条预置 | 提供 seed-knowledge.jsonl + 自动加载 | 部署即可用 |
