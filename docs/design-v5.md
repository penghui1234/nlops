# NLOps v5 设计方案

> 在 **Amazon Bedrock AgentCore + AWS DevOps Agent** 之上构建的生产级自然语言运维平台
>
> **文档状态**: 设计提案（Proposal） · 创建 2026-06-08
> **作者**: 陈朋辉（西云数据 · 解决方案架构师）
> **GitHub**: https://github.com/penghui1234/nlops/tree/feat/v5
> **承接**: [`docs/design-v4.md`](design-v4.md)（v4 已实施完成）

> 参考来源（全部为 AWS 官方，2026-06-08 联网核实，完整清单见附录 B）：
> - [Amazon Bedrock AgentCore is now generally available](https://aws.amazon.com/about-aws/whats-new/2025/10/amazon-bedrock-agentcore-available/) — **AgentCore 已 GA（2025-10）**
> - [Amazon Bedrock AgentCore FAQs](https://aws.amazon.com/bedrock/agentcore/faqs/) — 模块总览：Runtime / Memory / Gateway / Identity / Observability / Code Interpreter / Browser
> - [Announcing General Availability of AWS DevOps Agent](https://aws.amazon.com/blogs/mt/announcing-general-availability-of-aws-devops-agent/) — **DevOps Agent GA（2026-03-31），预览期 MTTR↓75% / 调查↑80% / 根因准确率 94%**
> - [Building an end-to-end agentic SRE using AWS DevOps Agent](https://aws.amazon.com/blogs/devops/building-an-end-to-end-agentic-sre-using-aws-devops-agent/)
> - [Amazon Bedrock Guardrails](https://aws.amazon.com/bedrock/guardrails/) — 六大安全防护

---

## 0. v5 的由来：来自评委的三个灵魂拷问

v4 已经把"自然语言驱动运维"的**闭环跑通了**（飞书 → DOA → HTML 诊断书 → 自动公告 → 经验沉淀）。但评委在 v4 评审时提出了三个尖锐问题，它们都不是"场景对不对"，而是"**这套东西能不能从 Demo 变成产品**"：

| # | 评委原话 | 本质 | v4 现状 |
|---|---------|------|---------|
| 1 | **多轮对话** | 会话状态 / 上下文记忆 | ❌ `chat()` 是 one-shot，每次新会话，无跨轮记忆 |
| 2 | **准确理解问题并准确提取关键参数** | 意图识别 + 结构化参数抽取 | ⚠️ 靠 LLM 一步到位，写操作参数无强校验 |
| 3 | **控制问答的范围**（"只能回答 100 个问题，拒绝第 101 个"） | 用量配额 + 领域边界 + 安全护栏 | ❌ 无配额、无边界控制、无 Guardrails |

**v5 的核心目标，就是用 `AgentCore` 把这三个问题逐一解掉**，把 NLOps 从"能演示的闭环"升级为"可治理的产品"。

---

## 1. 设计原则（v5 vs v4 核心变化）

| 原则 | v4 做法 | v5 做法 | 理由 |
|------|---------|---------|------|
| Agent 运行时 | 自建单 Lambda（形状路由） | **AgentCore Runtime** 托管对话 Agent，Lambda 降级为工具后端 | 会话隔离、自动伸缩、生产级运行时 |
| 会话记忆 | 无（DDB 只存审计） | **AgentCore Memory**（短期 + 长期） | 解决评委难点 1：多轮对话 |
| 意图与参数 | LLM 直接调工具 | **两段式：意图分类 → 结构化 Slot Filling** | 解决评委难点 2：参数提取准确性 |
| 用量治理 | 无 | **AgentCore Identity + QuotaManager（DDB 原子计数）** | 解决评委难点 3a：配额（答 N 拒第 N+1） |
| 安全边界 | 无 | **Bedrock Guardrails + 领域意图分类** | 解决评委难点 3b：拒绝越界/有害请求 |
| 工具暴露 | API GW + 自写 JSON-RPC MCP server | **AgentCore Gateway**（API/Lambda/MCP → 统一工具） | 标准化、自带鉴权、减少胶水代码 |
| 可观测 | 自写 `common/audit.py` + CloudWatch Logs | **AgentCore Observability**（OpenTelemetry trace）+ 保留审计 | 端到端追踪、会话级可视 |
| 分析引擎 | DevOps Agent 原生 | **保持不变** —— DOA 仍是"大脑" | v4 已验证，不重造 |
| 交付层 | 飞书 / HTML 诊断书 / 公告 / Skill | **保持不变** —— NLOps 的"最后一公里" | v4 核心差异化，继续保留 |

**一句话总结 v5 的定位**：
> **DevOps Agent 提供诊断深度，AgentCore 提供治理能力，NLOps 提供交付体验** —— 三层叠加，缺一不可。

---

## 2. 整体架构

```
┌────────────────────────────────────────────────────────────────────────────┐
│                          交互层 (Entry Points)                              │
│   📱 飞书 @机器人      🖥️ Quick Desktop      📧 SES 邮件      🚨 CW Alarm   │
└───────────────────────────────┬────────────────────────────────────────────┘
                                ↓
┌────────────────────────────────────────────────────────────────────────────┐
│                  治理层 (Amazon Bedrock AgentCore)  ★ v5 新增                │
│                                                                            │
│  ┌────────────┐  ┌────────────┐  ┌────────────┐  ┌────────────┐          │
│  │ Identity   │  │  Memory    │  │  Gateway   │  │Observability│          │
│  │ 鉴权+配额  │  │ 短期/长期  │  │ 工具网关   │  │  OTel 追踪 │          │
│  │ (难点 3a)  │  │ (难点 1)   │  │            │  │            │          │
│  └─────┬──────┘  └─────┬──────┘  └─────┬──────┘  └─────┬──────┘          │
│        └───────────────┴───────┬───────┴───────────────┘                 │
│                                ▼                                          │
│  ┌──────────────────────────────────────────────────────────────────┐   │
│  │                  AgentCore Runtime (对话 Agent)                    │   │
│  │   ① Guardrails 安全护栏 (难点 3b)                                  │   │
│  │   ② 意图分类 Intent Router (难点 2)                                │   │
│  │   ③ 结构化 Slot Filling 参数抽取 (难点 2)                          │   │
│  │   ④ 多轮编排 (调 Memory 取上下文)                                  │   │
│  └──────────────────────────────────────────────────────────────────┘   │
└───────────────┬──────────────────────────────────────┬─────────────────────┘
                ↓ (深度诊断)                            ↓ (交付动作)
┌───────────────────────────────┐      ┌───────────────────────────────────────┐
│   AWS DevOps Agent (大脑)     │      │   NLOps 工具后端 (Lambda, v4 复用)      │
│   • 跨源关联 CW/X-Ray/Config  │      │   • get_html_report  (7-Tab 诊断书)     │
│   • Investigation 根因定位    │      │   • trigger_runbook  (SSM, dry-run)     │
│   • Skills 经验匹配           │      │   • notify_im        (飞书/邮件)         │
└───────────────────────────────┘      └───────────────────────────────────────┘
                                                       ↓
┌────────────────────────────────────────────────────────────────────────────┐
│             存储层: S3(诊断书) · DynamoDB(Quota 计数 + 审计) · Memory Store  │
└────────────────────────────────────────────────────────────────────────────┘
```

**与 v4 的关键差异**：v4 的"单 Lambda 形状路由"被拆成两部分——**对话理解/治理上移到 AgentCore Runtime**，**具体动作（HTML/IM/Runbook）下沉为 Gateway 后面的工具**。DOA 与交付层逻辑基本复用 v4。

---

## 3. 难点逐个击破（v5 核心设计决策）

### 3.1 难点 1：多轮对话 → AgentCore Memory

**问题**：v4 的 `tools/devops_agent.py::chat()` 每次都 `create_chat()` 开新会话，用户问"demo-api 为什么慢"，再追问"那它的 RDS 连接数呢"，第二句完全丢失上下文。

**v5 方案**：引入 AgentCore Memory 的双层记忆。

| 记忆类型 | 存什么 | 生命周期 | 用途 |
|---------|--------|---------|------|
| **短期记忆 (Short-term)** | 当前会话的对话历史、已抽取的 slot、当前 incident 上下文 | 会话级（如 30 分钟 TTL） | 多轮追问、参数补全 |
| **长期记忆 (Long-term)** | 用户偏好、服务历史故障、常用集群/服务名 | 跨会话持久 | "上次那个服务"、个性化、加速参数抽取 |

**会话标识设计**：
- 飞书入口：`session_id = lark_open_id + chat_id`
- Quick Desktop：`session_id = mcp_session_id`（v4 已有 `Mcp-Session-Id` header）

**多轮编排伪代码**：
```python
def handle_turn(session_id, user_text):
    history = memory.get_short_term(session_id)        # 取上下文
    intent, slots = understand(user_text, history)     # 见 3.2
    if missing := required_slots(intent) - slots.keys():
        memory.append(session_id, user_text, partial=slots)
        return reprompt(missing)                        # 反问缺失参数 → 又一轮
    result = dispatch(intent, slots, history)
    memory.append(session_id, user_text, result)        # 写回记忆
    return result
```

> **关键点**：多轮不只是"记住聊天记录"，而是"**记住已抽取的参数**"——这样追问时能增量补全 slot，而不是从头再问。

> 📎 **核实**：AgentCore Memory 官方明确支持「short-term memory for multi-turn conversations」与「long-term memory that persists across sessions」，并可跨 Agent 共享记忆库。来源：[What is Amazon Bedrock AgentCore](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/what-is-bedrock-agentcore.html)。

---

### 3.2 难点 2：准确理解 + 准确提取参数 → 两段式 NLU

**问题**：运维的写操作（`trigger_runbook`）对参数准确性是零容忍的——把"demo 集群"听成别的集群就是生产事故。靠一个大 prompt 一步到位既不稳定也不可控。

**v5 方案**：拆成**意图分类**和**结构化 Slot Filling**两段，并对写操作强制 dry-run 二次确认。

**第一段：意图分类（Intent Router）**
用轻量模型（Nova Lite/Pro）把输入归类到有限意图集，顺带挡掉越界请求（接 3.3）：

| 意图 | 示例 | 目标工具 | 风险 |
|------|------|---------|------|
| `query` | "demo-api 现在健康吗" | `query_doa` | 只读 |
| `investigate` | "查一下为什么 demo-api 变慢" | `start_investigation` | 只读 |
| `report` | "把刚才那个调查生成诊断书" | `get_html_report` | 只读 |
| `remediate` | "把 demo 集群 api 服务扩到 4 个" | `trigger_runbook` | **写** |
| `notify` | "把结果发到运维群" | `notify_im` | 低 |
| `out_of_scope` | "帮我写首诗" | （拒绝，见 3.3） | — |

**第二段：结构化 Slot Filling**
每个意图绑定一个 **JSON Schema**，用模型的结构化输出（tool-use / structured output）抽参，缺参数就反问（回到多轮）：

```python
REMEDIATE_SCHEMA = {
  "document_name": {"type": "string", "enum": [
      "nlops-ecs-scale", "nlops-rds-proxy-expand", "nlops-ec2-reboot"]},
  "ClusterName":   {"type": "string", "required": True},
  "ServiceName":   {"type": "string", "required": True},
  "DesiredCount":  {"type": "integer", "minimum": 1, "maximum": 20, "required": True},
}
```

**写操作三道闸**（在 v4 `trigger_runbook` dry-run 基础上强化）：
1. **Schema 校验**：参数类型/范围不合法直接拒绝（如 DesiredCount=200）
2. **dry-run 回显**：执行前把"将对 X 集群 Y 服务从 2 扩到 4"用自然语言回显给用户
3. **显式确认**：用户必须回复确认（多轮的又一次往返）才以 `dry_run=false` 真正执行

> v4 的 `trigger_runbook` 已经默认 `dry_run=True` 且注释要求确认——v5 把这个"君子约定"变成**运行时强制的状态机**。

---

### 3.3 难点 3：控制问答范围 → 配额 + 边界双控

评委的"答 100 个拒第 101 个"其实包含两层，v5 都做：

#### 3.3a 用量配额（Quota）—— 评委原话的直接落地

**目标**：每个用户/租户在时间窗内最多 N 次调用，超出明确拒绝。

**实现**：DynamoDB 原子计数器（条件写防并发绕过），通过 AgentCore Identity 拿到调用方身份。

```python
class QuotaManager:
    """按 (principal, window) 计数，原子递增，超限拒绝。"""
    def check_and_incr(self, principal: str, limit: int = 100,
                       window: str = "2026-06") -> dict:
        key = {"pk": f"quota#{principal}", "sk": window}
        try:
            resp = ddb.update_item(
                Key=key,
                UpdateExpression="SET cnt = if_not_exists(cnt, :z) + :one",
                ConditionExpression="attribute_not_exists(cnt) OR cnt < :lim",
                ExpressionAttributeValues={":z": 0, ":one": 1, ":lim": limit},
                ReturnValues="UPDATED_NEW",
            )
            used = int(resp["Attributes"]["cnt"])
            return {"allowed": True, "used": used, "remaining": limit - used}
        except ddb.exceptions.ConditionalCheckFailedException:
            # 第 101 个 → 条件失败 → 拒绝
            return {"allowed": False, "used": limit, "remaining": 0,
                    "reason": f"已达本周期配额上限 {limit} 次"}
```

设计要点：
- **原子性**：用 `ConditionExpression` 保证并发下也不会突破 limit（不能先读后写）
- **多维配额**：principal 可以是 `user` / `team` / `tenant`，window 可按天/周/月
- **优雅拒绝**：返回明确话术 + 剩余额度，而不是静默失败
- **可配置**：limit 走环境变量/参数表，不同租户不同额度

> "拒绝第 101 个"看似简单，做对要解决：持久计数、并发原子性、明确话术、可配置阈值——这正是产品化意识的体现。

> 📎 **核实与落地点**：纯计数（有状态）必须自建，Cedar 这类策略语言是无状态授权、无法计数。但 **AgentCore Gateway 的 Policy（Cedar）+ Lambda 拦截器（interceptors）** 正是把 QuotaManager 挂上去的**原生执行点**——在工具调用进入前用 Lambda 拦截器调一次 `check_and_incr`，超限即拒。来源：[Secure AI agents with Policy and Lambda interceptors in AgentCore Gateway](https://aws.amazon.com/blogs/machine-learning/secure-ai-agents-with-policy-and-lambda-interceptors-in-amazon-bedrock-agentcore-gateway/)。

#### 3.3b 领域边界 + 安全护栏（Guardrails）

**目标**：只回答运维相关问题，拒绝越界（写诗）、有害（生成恶意脚本）、敏感（套取凭据）请求。

**实现**：
1. **意图分类前置过滤**（3.2 第一段）：归类到 `out_of_scope` 直接礼貌拒绝
2. **Amazon Bedrock Guardrails**（独立 Bedrock 特性，可作用于 Agent）：六大防护中本场景重点用 **denied topics**（屏蔽非运维话题，如"写诗"）、**sensitive information filters**（PII/凭据脱敏，不回显密钥）、**content filters + prompt attack**（拦截有害内容与提示注入）
3. **工具白名单**：Agent 只能调注册的 5 个工具，无法执行任意命令

> 📎 **核实**：Bedrock Guardrails 提供六类防护：content filters、denied topics、word filters、sensitive information filters、contextual grounding、Automated Reasoning checks。"denied topics" 官方示例正是"银行助手屏蔽非法投资建议"，与本场景"只答运维"同构。来源：[Amazon Bedrock Guardrails](https://aws.amazon.com/bedrock/guardrails/) · [Guardrails components](https://docs.aws.amazon.com/bedrock/latest/userguide/guardrails-components.html)。

---

## 4. 组件详细设计

### 4.1 AgentCore Runtime —— 对话 Agent
- 托管对话 Agent（替代 v4 单 Lambda 的 `/chat` `/lark-event` 理解部分）
- 内置 Guardrails、意图路由、Slot Filling、多轮编排
- 会话隔离：每个 `session_id` 独立运行时上下文

### 4.2 AgentCore Memory —— 会话记忆
- 短期：会话历史 + 已抽取 slot（TTL 30 min）
- 长期：用户偏好 + 服务故障史（跨会话）
- 替代 v4 DDB 中"会话"用途，审计表保留

### 4.3 AgentCore Gateway —— 工具网关
- 把 v4 的 5 个 MCP 工具（`query_doa` / `start_investigation` / `get_html_report` / `trigger_runbook` / `notify_im`）通过 Gateway 暴露
- **Gateway 原生托管现有 MCP server**（把 MCP server 当作 native target，自动发现工具定义），也能把 Lambda / REST API / API Gateway 直接转成 MCP 工具——v4 的 `mcp_server/server.py` 自写 JSON-RPC 可被 Gateway 接管或替代
- 自带 inbound 鉴权、Cedar Policy、Lambda 拦截器（QuotaManager 的挂载点，见 3.3a）
- DevOps Agent 本身也作为一个"诊断工具"被 Agent 调用

> 📎 **核实**：Gateway 可「convert APIs, Lambda functions, and existing services into MCP-compatible tools」，并「natively connects to MCP servers with no protocol translation」。来源：[AgentCore Gateway 文档](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/gateway.html) · [Extending MCP support for AgentCore Gateway](https://aws.amazon.com/blogs/machine-learning/extending-mcp-support-for-amazon-bedrock-agentcore-gateway-2/)。

### 4.4 QuotaManager + DynamoDB —— 配额（v5 新增自建）
- 新增 DDB 表 `nlops-quota`（pk=`quota#{principal}`, sk=`window`）
- 在每次工具调用入口处 `check_and_incr`
- CFN 输出配额表名，可在 Console 调整阈值

### 4.5 AgentCore Identity —— 身份与鉴权
- 解析调用方身份（飞书 open_id / Quick Desktop session / IAM）作为 QuotaManager 的 principal
- inbound/outbound 鉴权，DOA 反向调用工具时的 OAuth

### 4.6 保留 v4 资产（不重造）
- DevOps Agent + 3 Skills + 2 SSM Runbook
- HTML 诊断书（`report/`）+ AI 增强（`tools/ai_enhance.py`）
- 飞书集成（`tools/lark_*.py`）+ 告警闭环（`_handle_alarm_webhook`）

---

## 5. v4 → v5 对比

| 项 | v4 | v5 |
|---|---|---|
| 对话运行时 | 自建 Lambda | **AgentCore Runtime** |
| 多轮对话 | ❌ one-shot | ✅ **AgentCore Memory** |
| 意图理解 | LLM 直调 | ✅ **意图分类 + Slot Filling** |
| 参数校验 | 弱 | ✅ **JSON Schema + dry-run 状态机** |
| 用量配额 | ❌ | ✅ **QuotaManager（答 N 拒 N+1）** |
| 安全边界 | ❌ | ✅ **Guardrails + 领域分类** |
| 工具暴露 | 自写 JSON-RPC | **AgentCore Gateway** |
| 可观测 | 自写审计 | **AgentCore Observability** + 审计 |
| 分析引擎 | DOA | DOA（不变） |
| 交付层 | 飞书/HTML/公告/Skill | 同 v4（不变） |

---

## 6. 实施路线

### Phase 1: 治理底座（核心，回应评委）
- [ ] QuotaManager + DDB 表（难点 3a，**最有说服力，优先做**）
- [ ] 意图分类 Intent Router（难点 2）
- [ ] 结构化 Slot Filling + 写操作确认状态机（难点 2）
- [ ] Guardrails 接入（难点 3b）

### Phase 2: AgentCore 接入
- [ ] AgentCore Memory 接入，改造 `devops_agent.chat()` 支持多轮（难点 1）
- [ ] AgentCore Gateway 注册 5 工具
- [ ] AgentCore Identity 身份解析

### Phase 3: 运行时迁移
- [ ] 对话理解逻辑迁到 AgentCore Runtime
- [ ] AgentCore Observability 端到端追踪
- [ ] Lambda 收敛为纯工具后端

---

## 7. 风险与缓解

| 风险 | 缓解 |
|------|------|
| AgentCore 区域可用性 / GA 状态 | AgentCore 已于 **2025-10 GA**、DevOps Agent **2026-03-31 GA**（均已核实），主要风险转为**目标 region 是否同时支持二者**；Phase 1 的配额+意图+Guardrails 可**先在现有 Lambda 内实现**，不强依赖 AgentCore，AgentCore 接入作为 Phase 2/3 |
| 意图分类误判导致拒绝正常请求 | 设置 `fallback=query`（拿不准时走只读问诊，永不误触发写操作） |
| 配额并发绕过 | DDB 条件写保证原子性（已在 3.3a 设计） |
| 多轮记忆膨胀 | 短期记忆设 TTL + 轮数上限，超出做摘要压缩 |

---

## 8. 核心差异化总结（v5 对外话术）

> **v4 证明了"自然语言能驱动运维闭环"，v5 证明了"它能成为一个可治理、可上线的产品"。**

回应评委的一句话总结：
- **多轮对话** → AgentCore Memory 双层记忆，记住的不只是聊天记录，更是已抽取的参数
- **准确理解与参数提取** → 意图分类 + JSON Schema Slot Filling + 写操作 dry-run 确认状态机
- **控制问答范围** → QuotaManager 原子配额（答 N 拒 N+1）+ Guardrails 领域边界双控

---

## 附录：与 v4 文档的关系
- 架构演进、流程细节、成本模型的基线见 [`docs/design-v4.md`](design-v4.md)
- v5 仅描述**增量**（治理层 + 三大难点解法），未重述 v4 已实现部分

---

## 附录 B: 联网核实记录与参考链接（2026-06-08）

本文档所有技术声明均经联网核实，来源为 AWS 官方（whats-new / 博客 / 文档）。

### B.1 Amazon Bedrock AgentCore
| 声明 | 核实结果 | 来源 |
|------|---------|------|
| AgentCore 已 GA | ✅ 2025-10 GA（先于 2025-07 preview） | [AgentCore is now GA](https://aws.amazon.com/about-aws/whats-new/2025/10/amazon-bedrock-agentcore-available/) · [Preview 公告](https://aws.amazon.com/about-aws/whats-new/2025/07/amazon-bedrock-agentcore-preview/) |
| 模块：Runtime/Memory/Gateway/Identity/Observability/Code Interpreter/Browser | ✅ 一致 | [PoC→Production 博客](https://aws.amazon.com/blogs/machine-learning/move-your-ai-agents-from-proof-of-concept-to-production-with-amazon-bedrock-agentcore/) · [FAQs](https://aws.amazon.com/bedrock/agentcore/faqs/) |
| Memory：短期(多轮)+长期(跨会话) | ✅ 一致 | [What is AgentCore](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/what-is-bedrock-agentcore.html) |
| Gateway：API/Lambda/MCP → MCP 工具，原生托管 MCP server | ✅ 一致 | [Gateway 文档](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/gateway.html) · [Extending MCP support](https://aws.amazon.com/blogs/machine-learning/extending-mcp-support-for-amazon-bedrock-agentcore-gateway-2/) |
| Gateway：Cedar Policy + Lambda 拦截器做工具级鉴权 | ✅ 一致（QuotaManager 挂载点） | [Policy and Lambda interceptors](https://aws.amazon.com/blogs/machine-learning/secure-ai-agents-with-policy-and-lambda-interceptors-in-amazon-bedrock-agentcore-gateway/) |
| Identity：identity-aware 授权 + OAuth + token vault | ✅ 一致 | [GA 公告](https://aws.amazon.com/about-aws/whats-new/2025/10/amazon-bedrock-agentcore-available/) |
| Observability：OpenTelemetry 兼容 + CloudWatch | ✅ 一致 | [Add observability 文档](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/observability-configure.html) |

### B.2 AWS DevOps Agent
| 声明 | 核实结果 | 来源 |
|------|---------|------|
| 预览 2025-12-02（re:Invent），GA 2026-03-31 | ✅ 一致 | [re:Post: included with Support plans](https://repost.aws/articles/ARt2t2FDNiRZSbCJqg-UlM_A/accelerate-incident-resolution-with-aws-devops-agent-now-included-with-aws-support-plans) |
| 预览期 MTTR↓75% / 调查↑80% / 根因准确率 94% | ✅ 一致 | [GA 公告](https://aws.amazon.com/blogs/mt/announcing-general-availability-of-aws-devops-agent/) |
| 多 Agent 推理做根因定位、跨源关联 | ✅ 一致 | [Multi-agent reasoning 博客](https://aws.amazon.com/blogs/devops/how-aws-devops-agent-uses-multi-agent-reasoning-to-find-root-causes/) |
| 现已包含在 AWS Support plans（印证 v4 成本模型抵扣） | ✅ 一致 | [re:Post 文章](https://repost.aws/articles/ARt2t2FDNiRZSbCJqg-UlM_A/accelerate-incident-resolution-with-aws-devops-agent-now-included-with-aws-support-plans) |

### B.3 Amazon Bedrock Guardrails
| 声明 | 核实结果 | 来源 |
|------|---------|------|
| 六大防护：content filters / denied topics / word filters / sensitive info(PII) / contextual grounding / Automated Reasoning | ✅ 一致 | [Guardrails 产品页](https://aws.amazon.com/bedrock/guardrails/) · [Safeguard tiers 博客](https://aws.amazon.com/blogs/machine-learning/tailor-responsible-ai-with-new-safeguard-tiers-in-amazon-bedrock-guardrails/) |
| denied topics 可限定领域（官方例：银行助手屏蔽非法投资建议） | ✅ 一致 | [Guardrails components 文档](https://docs.aws.amazon.com/bedrock/latest/userguide/guardrails-components.html) |

### B.4 需要使用者自行二次确认的点
- **目标 region 同时支持 AgentCore + DevOps Agent**：两者 GA region 列表可能不同，落地前请在 AWS Console / 文档确认所选 region（如 us-east-1）二者均可用。
- **DynamoDB 条件写原子计数**：属 AWS 通用能力（`ConditionExpression` 防并发），未单列链接，参见 DynamoDB 官方文档「Condition expressions」。
- **AgentCore 具体 API 形态**：本文档给出的是架构与机制设计，具体 SDK/API 调用方式以实现阶段的官方 API Reference 为准。
