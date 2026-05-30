# NLOps v4 设计方案

> 基于 AWS DevOps Agent 的自然语言驱动智能运维平台（重构版）
> 
> 参考来源：
> - [End-to-End Agentic SRE using AWS DevOps Agent](https://aws.amazon.com/blogs/devops/building-an-end-to-end-agentic-sre-using-aws-devops-agent/) (2026-05)
> - [Telkomsel CELYNA](https://aws.amazon.com/solutions/case-studies/telkomsel-case-study/) (2026)
> - [CW Investigations + Nova Sonic](https://aws.amazon.com/blogs/mt/reimagine-aiops-with-amazon-cloudwatch-investigations-and-amazon-nova-sonic/) (2025-10)
> - [AI-Powered Incident Response with Nova Pro](https://aws.amazon.com/blogs/mt/using-amazon-bedrock-and-amazon-nova-for-ai-powered-incident-response/) (2025-07)

---

## 1. 设计原则（v4 vs v3 核心变化）

| 原则 | v3 做法 | v4 做法 | 理由 |
|------|---------|---------|------|
| 分析引擎 | 自建 Strands Agent 编排 5 个 Tool | **DevOps Agent 原生能力为主**，仅在体验层补充 | 避免重复造轮子，DOA 已内置 CW/X-Ray/Config 关联分析 |
| 经验沉淀 | 自建 Bedrock KB + S3 双写 | **DevOps Agent Skills** 为主 + KB 为辅 | Skills 是 DOA 原生经验封装，调查时自动匹配 |
| 告警触发 | EventBridge Rule 直连 Lambda | **Webhook** 触发 DOA Investigation | 官方推荐路径，支持多源（CW/Splunk/自定义） |
| 修复执行 | 自建 L2 Lambda + Confirm Token | **SSM Runbook** + Agent-ready Spec → Kiro | 标准化、可审计、支持代码级修复 |
| 语音交互 | placeholder（未实现） | **Nova Sonic** 语音 → 文字 → DOA → 语音回复 | 参考 CW Investigations + Nova Sonic 博客 |
| 可视化输出 | 自建 Jinja2 HTML 诊断书 | **保留并增强**（这是核心差异化） | DOA 原生输出偏文本，HTML 诊断书是我们的增量价值 |
| 通知通道 | SES 邮件 | **Slack/企微/飞书** + SES 邮件 | DOA 原生支持 Slack，IM 覆盖中国客户 |

---

## 2. 整体架构

```
┌──────────────────────────────────────────────────────────────────────────┐
│                          交互层 (Entry Points)                            │
│                                                                          │
│  📱 企微/飞书 Bot   🖥️ Quick Desktop   🎙️ Nova Sonic 语音   📧 SES邮件   │
│   (聊天/Webhook)   (本地MCP桥接)        (WebSocket)         (告警通知)    │
│       │                  │                    │                  ▲       │
│       │                  │                    │                  │       │
│       ▼                  ▼                    ▼                  │       │
│  ┌────────────┐   ┌─────────────────┐   ┌──────────────┐         │       │
│  │ POST /chat │   │ POST /mcp       │   │ WSS /voice   │         │       │
│  │ POST /hook │   │ (JSON-RPC 2.0)  │   │ (双向流)     │         │       │
│  └─────┬──────┘   └────────┬────────┘   └──────┬───────┘         │       │
│        └───────────────────┼───────────────────┘                 │       │
│                            ▼                                     │       │
│                    API Gateway (REST + WebSocket)                │       │
└────────────────────────────┼─────────────────────────────────────┼───────┘
                               ↓
┌──────────────────────────────────────────────────────────────────────────┐
│                     编排层 (Orchestration Lambda)                         │
│                                                                          │
│  ┌─────────────┐  ┌──────────────┐  ┌──────────────┐  ┌─────────────┐  │
│  │ Chat Router │  │ Webhook Fwd  │  │ Report Gen   │  │ Voice (ASR/ │  │
│  │ (Nova Pro)  │  │ → DOA        │  │ (HTML诊断书) │  │  TTS Sonic) │  │
│  └──────┬──────┘  └──────┬───────┘  └──────┬───────┘  └──────┬──────┘  │
│         │                │                  │                  │         │
│         └────────────────┼──────────────────┼──────────────────┘         │
└──────────────────────────┼──────────────────┼────────────────────────────┘
                           ↓                  ↓
┌──────────────────────────────────────────────────────────────────────────┐
│                    AWS DevOps Agent (核心引擎)                            │
│                                                                          │
│  ┌─────────────────────────────────────────────────────────────────┐    │
│  │ Agent Space                                                      │    │
│  │                                                                  │    │
│  │  📊 CloudWatch    📝 Splunk/CW Logs    🔗 GitHub (CI/CD)       │    │
│  │  🔍 X-Ray         📋 Config            🛠️ MCP Server (NLOps)   │    │
│  │                                                                  │    │
│  │  Skills:                                                         │    │
│  │    • ECS 故障排查指南                                             │    │
│  │    • RDS 连接池问题处理                                           │    │
│  │    • Lambda 限流修复流程                                          │    │
│  │    • 历史事件经验库                                               │    │
│  │                                                                  │    │
│  │  输出:                                                           │    │
│  │    • Root Cause Analysis                                         │    │
│  │    • Mitigation Plan (4 phases)                                  │    │
│  │    • Agent-ready Spec → Kiro                                     │    │
│  └─────────────────────────────────────────────────────────────────┘    │
│                                                                          │
│  Webhook ← CW Alarm / Splunk Alert / 自定义                            │
│  通知 → Slack Channel / 企微 / 飞书                                     │
└──────────────────────────────────────────────────────────────────────────┘
                           ↓
┌──────────────────────────────────────────────────────────────────────────┐
│                       执行层 (Remediation)                                │
│                                                                          │
│  ┌──────────────────┐  ┌──────────────────┐  ┌──────────────────────┐  │
│  │ SSM Runbook      │  │ Agent-ready Spec │  │ Manual Approval      │  │
│  │ (自动修复)       │  │ → Kiro (代码修复)│  │ (高风险操作)         │  │
│  └──────────────────┘  └──────────────────┘  └──────────────────────┘  │
└──────────────────────────────────────────────────────────────────────────┘
                           ↓
┌──────────────────────────────────────────────────────────────────────────┐
│                       存储层 (Persistence)                                │
│                                                                          │
│  S3 (HTML诊断书 + 架构图)  │  DynamoDB (Session + Audit)                │
└──────────────────────────────────────────────────────────────────────────┘
```

---

## 3. 核心流程

### 3.1 告警自动闭环（主流程）

```
CW Alarm ALARM
    │
    ▼ SNS → Lambda (webhook_forwarder)
    │
    ▼ POST DevOps Agent Webhook (HMAC 签名)
    │
    ▼ DOA 自动启动 Investigation
    │   ├── 查询 CloudWatch Metrics (异常时段)
    │   ├── 查询 CW Logs / Splunk (错误日志)
    │   ├── 查询 X-Ray (慢调用链)
    │   ├── 查询 GitHub (最近部署)
    │   ├── 匹配 Skills (历史经验)
    │   └── 调用 NLOps MCP Server (补充分析)
    │
    ▼ Investigation Completed (5-15 min)
    │
    ├──▶ Slack 通知 (根因 + 建议)
    │
    ├──▶ EventBridge → Report Lambda
    │       └── 渲染 HTML 诊断书 → S3 Presigned URL
    │       └── SES 邮件 (含诊断书链接)
    │
    ├──▶ Mitigation Plan 生成
    │       ├── Low Risk → SSM Runbook 自动执行
    │       └── High Risk → Agent-ready Spec → Kiro PR
    │
    └──▶ Skills 自动更新 (经验沉淀)
```

### 3.2 主动巡检（用户触发）

```
用户 (IM/语音/Q Desktop): "demo-api 服务怎么样？"
    │
    ▼ Orchestration Lambda
    │   ├── Nova Sonic ASR (语音→文字, 如适用)
    │   └── Nova Pro 意图识别
    │
    ▼ 路由决策:
    │   ├── 简单查询 → DOA Chat (5-30s)
    │   ├── 深度分析 → DOA Investigation (5-15min)
    │   └── 历史查询 → Skills 检索
    │
    ▼ 结果处理:
    │   ├── 文字回复 → IM/Q Desktop
    │   ├── HTML 诊断书 → S3 URL
    │   └── Nova Sonic TTS (文字→语音, 如适用)
```

### 3.3 代码级修复（Agent-ready Spec）

```
DOA Mitigation Plan
    │
    ▼ Agent-ready Spec 生成
    │   (结构化修复指令: 文件路径 + 变更内容 + 验证步骤)
    │
    ▼ 人工审批 (Slack 按钮 / IM 确认)
    │
    ▼ Kiro Agent 执行
    │   ├── 修改 IaC 模板 (CDK/Terraform/CloudFormation)
    │   ├── 提交 PR → GitHub
    │   └── 触发 CI/CD Pipeline
    │
    ▼ 部署完成 → DOA 验证 → 关闭 Investigation
```

#### Agent-ready Spec 示例

```yaml
spec_version: "1.0"
incident_id: "inv-xyz-001"
title: "RDS Proxy 连接池容量不足"

context:
  root_cause: "max_connections=200 不足以支撑当前流量"
  evidence:
    - "ConnectionPool 使用率峰值 95%"
    - "P99 延迟 200ms→320ms 与 Lambda 并发增长正相关"
  service: "demo-api"

target:
  repository: "github.com/penghui1234/demo-api-iac"
  files:
    - path: "lib/rds-stack.ts"
      reason: "RDS Proxy 连接池配置"

changes:
  - file: "lib/rds-stack.ts"
    operation: "modify"
    instruction: |
      在 RdsProxy 构造中,将 maxConnectionsPercent 从 100 提升到 150
    expected_diff: |
      - maxConnectionsPercent: 100,
      + maxConnectionsPercent: 150,

validation:
  pre_apply:
    - "运行 cdk diff 确认变更范围"
    - "检查 RDS 实例 max_connections 参数 ≥ 800"
  post_apply:
    - "等待部署完成 (~10min)"
    - "验证 ConnectionPool 使用率 < 70%"
    - "验证 P99 延迟 < 250ms"
  rollback:
    - "如指标恶化,git revert 该 commit"
```

#### 与 v3 的对比（修症状 vs 修病因）

| 维度 | v3 L2 Lambda 直接改 | v4 Agent-ready Spec → Kiro |
|------|-------------------|--------------------------|
| 修复内容 | AWS API（重启/扩容/改参数） | **代码 + IaC + 配置** 全栈 |
| 可审计 | DDB Audit | **Git history + PR review** 双重 |
| 可回滚 | 需要反向 API | **git revert** 一键 |
| 与 CI/CD 集成 | ❌ | ✅ 走 GitHub Actions |
| 高风险变更控制 | Confirm Token | **PR Review + CI 测试** 双层 |

#### Kiro 集成方式

NLOps Orchestrator Lambda 收到 Investigation Completed 事件后：
1. 解析 Mitigation Plan，提取 Agent-ready Spec
2. 推送到 IM/Quick Desktop（含 Spec 摘要 + 风险等级）
3. 用户点"批准" → Lambda 调 Kiro CLI/API
4. Kiro 自主完成：clone repo → 改代码 → 跑测试 → 提 PR
5. PR 描述里贴上 Agent-ready Spec 原文，便于 reviewer 理解
6. CI 通过 → reviewer 合并 → 自动部署
7. DOA 通过 `validation.post_apply` 验证修复效果

---

## 3.4 Quick Desktop 接入路径（核心入口之一）

Quick Desktop 是中国客户最常用的 AWS 工具入口，v4 仍作为一等公民支持。

```
┌─────────────────┐
│ Quick Desktop   │
│ (Mac/Win 客户端)│
│  内置 LLM:      │
│  Claude / Nova  │
└────────┬────────┘
         │ stdio (本地)
         ▼
┌──────────────────────────┐
│ mcp-bridge (Node.js)     │
│ • 翻译 stdio ↔ HTTP      │
│ • 转发 JSON-RPC 请求     │
└────────┬─────────────────┘
         │ HTTPS POST
         ▼
┌──────────────────────────────────────┐
│ API Gateway: /mcp-quick              │
│ (NoAuth, NLOps 专用)                  │
└────────┬─────────────────────────────┘
         ▼
┌──────────────────────────────────────┐
│ Orchestration Lambda → MCP Handler   │
│ 暴露 5 个精简后的 NLOps MCP 工具      │
└──────────────────────────────────────┘
```

### 与 v3 对比

| 维度 | v3 | v4 |
|------|----|----|
| MCP 工具数 | 21 个（自己造的"Agent"） | **5 个**（只补 DOA 不具备的） |
| 是否自建 LLM 编排 | 是（Strands Agent） | **否**（Quick 自己有 LLM） |
| 工具职责 | 涵盖发现/分析/修复/报告/知识 | **只做 DOA 的"补充层"** |
| 写操作护栏 | Confirm Token + L2 Lambda | **MCP 工具直接调 SSM Runbook**（SSM 自带审批） |

### v4 暴露的 5 个 MCP 工具

| 工具 | 用途 | 何时调用 |
|------|------|---------|
| `query_doa` | 通过 DOA Chat 一句话问诊 | "demo-api 怎么样？" |
| `start_investigation` | 启动 DOA 深度调查 | "为什么 demo-api 慢？" |
| `get_html_report` | 生成 HTML 诊断书 URL | 调查结束后给用户分享链接 |
| `trigger_runbook` | 调用 SSM Automation 修复 | "扩容到 4 个实例" |
| `notify_im` | 推送结果到企微/飞书频道 | 用户要求 "通知一下团队" |

### Quick Desktop 用户对话示例（v4）

```
用户 (Quick Desktop): 看下 demo-api 服务怎么样
Quick LLM (Claude): [调 query_doa("demo-api 当前健康状态")]
                    → DOA 返回：P99 320ms，RDS 连接池 78%
Quick LLM: demo-api 当前 P99 延迟 320ms 偏高，
           主要是 RDS Proxy 连接池使用率 78%。
           需要我深入调查吗？

用户: 调查下
Quick LLM: [调 start_investigation("demo-api latency", "RDS")]
           → 返回 inv-xyz，预计 5-15 分钟
Quick LLM: 已启动调查 inv-xyz，5-15 分钟后完成。
           完成后我会给你诊断书链接。

(15 分钟后用户回来)
用户: 调查好了吗？
Quick LLM: [调 get_html_report("inv-xyz")]
           → https://nlops-reports.s3.../inv-xyz.html
Quick LLM: 调查完成。根因是 RDS max_connections 不足。
           完整诊断书：[链接]
           建议执行 SSM Runbook: nlops-rds-proxy-expand。

用户: 帮我执行
Quick LLM: [调 trigger_runbook("nlops-rds-proxy-expand", {...}, dry_run=true)]
           → 显示风险卡片
Quick LLM: 这是写操作。计划：扩容 max_connections 200→400。
           风险：低（无需重启）。确认执行？

用户: 确认
Quick LLM: [调 trigger_runbook(... dry_run=false)]
           → SSM 执行成功
Quick LLM: ✅ 已扩容。已通过 SSM 审计日志记录。
```

### mcp-bridge 实现要点

`mcp-bridge/index.js` 保持 v3 实现不变（已成熟），只更新工具数量：

```javascript
// v3: 21 tools forwarded
// v4: 5 tools forwarded
const MCP_API_URL = process.env.NLOPS_MCP_URL  // 从环境变量读，不再硬编码
                  || 'https://xxx.execute-api.us-east-1.amazonaws.com/prod/mcp-quick';
```

修复 v3 已知问题：
- ✅ URL 改为环境变量（v3 是硬编码）
- ✅ 添加 30s 超时
- ✅ 错误信息透传到 Quick LLM

---

## 3.5 多源关联分析（Cross-source Correlation）

DOA 在调查过程中**自动跨数据源关联**，这是 v3 自建 Strands Agent 难以达到的：

```
告警发生时 DOA 自动关联：

CloudWatch Metrics ─┐
CloudWatch Logs    ─┤
X-Ray Traces       ─┼──▶ DOA Investigation Engine ──▶ 时间线 + 因果链
AWS Config         ─┤    (跨源时间对齐 + 异常检测)
GitHub Deployments ─┤
Splunk (可选)      ─┘

输出示例：
  "14:32 部署 commit abc123 引入未测试 SQL,
   导致 RDS CPU 30%→95%, P99 延迟 200ms→1200ms"
```

**关键差异**：DOA 原生支持时间对齐与因果推断，无需我们写编排代码；v3 是手动塞数据给 Strands，关联效果差。

---

## 3.6 多模态分析（Architecture Diagram Understanding）

参考 [AI-Powered Incident Response with Nova Pro](https://aws.amazon.com/blogs/mt/using-amazon-bedrock-and-amazon-nova-for-ai-powered-incident-response/) 博客：

```
HTML 诊断书生成时:
  1. 客户预上传服务架构图 (.png/.drawio) 到 S3
  2. Investigation 完成后,Nova Pro Vision 处理:
     ├── 识别架构图组件 (Lambda/RDS/ALB/SQS...)
     ├── 把 DOA 根因映射到架构图节点
     └── 在故障组件上自动标红 + 加箭头
  3. 输出图文并茂的诊断书:
     ┌────────────────────────────────────┐
     │ [架构图,RDS 节点标红 + ⚠️ 图标]    │
     │ "瓶颈在 RDS 实例 demo-db,        │
     │  ALB → ECS → RDS 链路上 RDS       │
     │  CPU 已达 95%"                    │
     └────────────────────────────────────┘
```

**为什么是关键差异化**：DOA 原生输出是文本，看不懂"哪一块出问题"；架构图标注是非技术人员（产品/老板）也能秒懂的。

---

## 3.7 故障通报自动化（Customer Communication）

事故处理中最耗时的环节之一 —— 写给客户的故障公告，由 Nova Pro 自动生成：

```
Investigation Completed
        │
        ▼ Nova Pro Prompt:
        "基于以下故障信息生成简体中文故障公告,
         面向最终用户,不透露内部技术细节,
         语气专业、致歉、给出预计恢复时间。"
        │
        ▼ 自动输出:
        ┌─────────────────────────────────────┐
        │ 服务公告 - 2026/05/30 14:30        │
        │ 我们注意到 demo-api 在 14:32 出现   │
        │ 访问缓慢。技术团队已定位问题,       │
        │ 预计 15:00 前完全恢复。             │
        │ 给您带来的不便,我们深表歉意。       │
        └─────────────────────────────────────┘
        │
        ▼ 推送渠道:
        ├── 客户状态页 (Status Page)
        ├── 企微 / 飞书群
        └── SES 邮件群发
```

**省时效果**：传统需要值班工程师写 + Manager review (15-30min)，自动化后 30 秒出稿，工程师只需审阅。

---

## 3.8 混合云 / 多云覆盖（Hybrid + Multi-cloud）

DOA 不止支持 AWS，NLOps 不需要额外开发即可继承这个能力：

```
Agent Space 可同时集成:
├── AWS                (CloudWatch / X-Ray / Config)  ← 原生
├── Azure Monitor       (via MCP Server)
├── GCP Cloud Logging   (via MCP Server)
├── Splunk on-prem      (via VPC peering, 参考 SRE 博客)
├── Datadog             (via integration)
├── Dynatrace           (via integration)
└── New Relic           (via integration)
```

**对客户的价值**：
- 一个 Agent Space 覆盖跨平台
- 中国客户通过 NLOps 的 IM 入口管理海外资产
- 避免在每个云平台重复部署 AIOps 工具

---

## 3.9 中国区降级路径（CloudWatch Investigations 备选）

DOA 当前不支持中国区，但 **CloudWatch Investigations** 在中国区可用。NLOps v4 设计支持运行时自动降级：

```
NLOps Orchestrator 启动:
├── 检测当前 region
├── if region in 全球区:
│       → 使用 DevOps Agent (主路径,完整能力)
└── elif region in [cn-north-1, cn-northwest-1]:
        → 降级到 CloudWatch Investigations
        → 功能子集:
            ✅ 告警自动调查
            ✅ 根因分析  
            ✅ SSM Runbook 修复
            ✅ HTML 诊断书 (NLOps 自建,与 region 无关)
            ✅ 企微 / 飞书 IM 通知
            ❌ Skills (用 Bedrock KB 替代)
            ❌ GitHub 集成 (需 PrivateLink)
            ❌ Multi-cloud (限于 AWS 中国)
```

**对客户的承诺**：
> "全球版用 DOA，中国版用 CW Investigations，**体验层（IM/Quick/HTML 诊断书）保持一致**"

---

## 4. 组件详细设计

### 4.1 Orchestration Lambda（唯一自建 Lambda）

**职责**：交互层入口 + HTML 诊断书渲染 + 语音处理

```python
# 路由逻辑
def handler(event, context):
    if is_eventbridge_doa_event(event):
        return handle_investigation_completed(event)  # → HTML + SES
    if is_webhook_from_alarm(event):
        return forward_to_doa_webhook(event)          # → DOA Investigation
    if is_chat_request(event):
        return handle_chat(event)                     # → DOA Chat + 格式化
    if is_voice_request(event):
        return handle_voice(event)                    # → Nova Sonic + DOA
```

**不再包含**：
- ❌ Strands Agent 编排（DOA 自己做）
- ❌ 5 个 Tool 的业务逻辑（DOA + Skills 替代）
- ❌ L2 Execution Lambda（SSM Runbook 替代）
- ❌ Bedrock KB 双写（Skills 替代）

### 4.2 NLOps MCP Server（注册到 DOA Agent Space）

**职责**：为 DOA 提供客户特定的补充能力

| MCP Tool | 用途 | 数据源 |
|----------|------|--------|
| `get_html_report` | 生成 HTML 诊断书 URL | Jinja2 + S3 |
| `get_architecture_diagram` | 返回服务架构图 | S3 (预上传) |
| `query_im_history` | 查询 IM 历史对话 | DynamoDB |
| `notify_im_channel` | 推送消息到企微/飞书 | 企微/飞书 API |
| `get_cost_impact` | 评估故障成本影响 | CUR + Nova Pro |

**精简原则**：只做 DOA 原生不支持的事情。DOA 已内置 CW/Logs/X-Ray/Config/GitHub 集成，不再重复封装。

### 4.3 DevOps Agent Skills（经验沉淀）

替代 v3 的 Bedrock KB，使用 DOA 原生 Skills 机制：

```markdown
# Skill: ECS 服务响应延迟排查

## 触发条件
- 告警包含 "TargetResponseTime" 或 "5xx"
- 服务类型为 ECS

## 调查步骤
1. 检查 ECS Service 的 running task count vs desired count
2. 检查 ALB Target Group 的 healthy host count
3. 查看最近 30 分钟的部署事件 (GitHub)
4. 分析 RDS/ElastiCache 连接池使用率
5. 检查 Lambda 并发限制 (如有下游 Lambda)

## 常见根因
- 部署后新版本 OOM → 回滚
- RDS 连接池耗尽 → 扩容 max_connections
- ElastiCache 节点故障 → failover

## 修复 Runbook
- SSM Document: nlops-ecs-scale-out
- SSM Document: nlops-rds-proxy-expand
```

**经验自动沉淀流程**：
1. Investigation 完成 → 提取根因 + 修复步骤
2. Nova Pro 格式化为 Skill Markdown
3. 调用 DOA API 创建/更新 Skill
4. 下次相似问题 → DOA 自动匹配该 Skill

### 4.4 HTML 诊断书（核心差异化，保留）

DOA 原生输出是文本/Slack 消息，缺乏可视化。HTML 诊断书是我们的核心增量：

```
Investigation Completed Event
    ↓
Report Lambda:
    1. GetBacklogTask → 获取完整调查结果
    2. 多模态增强:
       - 架构图标注故障点 (Nova Pro Vision)
       - ECharts 渲染指标趋势
       - 时间线可视化
    3. Jinja2 渲染 → S3 Presigned URL (30天)
    4. 推送: Slack卡片 / IM卡片 / SES邮件
```

**诊断书内容**：
- 📊 指标趋势图（ECharts 交互式）
- 🏗️ 架构图 + 故障点标注
- 📝 AI 根因解读（中文）
- ⏱️ 事件时间线
- 💡 修复建议 + 风险等级
- 📎 证据链（日志片段 + Trace ID）
- 🔗 DOA Operator Portal 链接

### 4.5 Nova Sonic 语音交互

参考 CW Investigations + Nova Sonic 博客的架构：

```
用户语音 (手机/电脑)
    ↓ WebSocket (API Gateway)
    ↓ Nova Sonic (speech-to-speech, 双向流式)
    ↓
Nova Sonic System Prompt:
    "你是 NLOps 运维助手。用户会用语音描述问题。
     你可以调用以下工具：
     - query_doa_chat(question) → 查询 DevOps Agent
     - get_investigation_status(inv_id) → 查看调查进度
     - trigger_runbook(doc_name, params) → 执行修复
     请用简洁中文回复，适合语音播报。"
    ↓
用户: "demo-api 现在什么情况？"
Nova Sonic → DOA Chat → "P99 延迟 320ms，RDS 连接池 78%"
Nova Sonic → 语音回复: "demo-api 的 P99 延迟升到了 320 毫秒，
    主要原因是 RDS 连接池使用率达到 78%。需要我启动深度调查吗？"
```

---

## 5. 部署架构

```
┌─────────────────────────────────────────────────────┐
│ AWS Account (us-east-1)                             │
│                                                     │
│  ┌─────────────────────────────────────────────┐   │
│  │ DevOps Agent Space: "NLOps-Production"      │   │
│  │                                              │   │
│  │  Integrations:                               │   │
│  │    ✅ CloudWatch (alarms + metrics + logs)   │   │
│  │    ✅ GitHub (deployments + PRs)             │   │
│  │    ✅ Slack (notifications)                  │   │
│  │    ✅ NLOps MCP Server (custom tools)        │   │
│  │                                              │   │
│  │  Skills: 10+ 运维经验包                      │   │
│  │  Webhook: CW Alarm → SNS → Lambda → DOA     │   │
│  └─────────────────────────────────────────────┘   │
│                                                     │
│  ┌─────────────────────────────────────────────┐   │
│  │ Lambda: NLOps-Orchestrator (1536MB, 120s)   │   │
│  │   • POST /chat      → DOA Chat + 格式化     │   │
│  │   • POST /voice     → Nova Sonic 双向流     │   │
│  │   • POST /webhook   → Forward to DOA        │   │
│  │   • EventBridge     → HTML Report + Notify  │   │
│  │   • POST /mcp       → MCP Server (5 tools)  │   │
│  └─────────────────────────────────────────────┘   │
│                                                     │
│  ┌──────────┐ ┌──────────┐ ┌──────────────────┐   │
│  │ S3       │ │ DynamoDB │ │ SSM Documents    │   │
│  │ Reports  │ │ Sessions │ │ (Runbooks)       │   │
│  │ + Diagrams│ │ + Audit  │ │ nlops-ecs-scale │   │
│  └──────────┘ └──────────┘ │ nlops-rds-expand │   │
│                             │ nlops-lambda-fix │   │
│                             └──────────────────┘   │
└─────────────────────────────────────────────────────┘
```

---

## 6. v3 → v4 精简对比

| 组件 | v3 | v4 | 变化 |
|------|----|----|------|
| Lambda 数量 | 2 (L1 + L2) | **1** | L2 被 SSM Runbook 替代 |
| 自建代码行数 | ~3000 行 | **~800 行** | 大量逻辑下沉到 DOA |
| MCP 工具数 | 21 | **5** | 只保留 DOA 不具备的 |
| Agent 框架 | Strands SDK | **无**（DOA 自带） | 不再自建编排 |
| 经验存储 | Bedrock KB + S3 | **DOA Skills** | 原生集成，调查时自动匹配 |
| 修复执行 | L2 Lambda + Confirm Token | **SSM Runbook + Kiro** | 标准化、可审计 |
| 语音 | placeholder | **Nova Sonic 实现** | 真正可用 |
| 告警触发 | EventBridge Rule | **Webhook (HMAC)** | 官方推荐，支持多源 |

---

## 7. 成本估算（50 用户/月）

| 服务 | 用途 | 月费用 | 占比 |
|------|------|--------|------|
| DevOps Agent | Chat + Investigation (~40h) | $1,200 | 74% |
| Nova Pro | Chat Router + Report 增强 | $80 | 5% |
| Nova Sonic | 语音交互 (~10h) | $50 | 3% |
| Lambda × 1 | Orchestrator | $8 | <1% |
| S3 + DDB + API GW | 存储 + 会话 + 入口 | $15 | 1% |
| SSM | Runbook 执行 | $0 | 0% |
| SES + SNS | 通知 | $2 | <1% |
| **合计** | | **~$1,355/月** | |
| Enterprise Support 抵扣 (DOA 75%) | | -$900 | |
| **净成本** | | **~$455/月 (~$9/人)** | |

vs v3: 月成本降低 ~$240（去掉 Bedrock KB OpenSearch $150 + L2 Lambda + Strands 调用）

---

## 8. 实施路线

### Phase 1: 核心闭环（2 周）
- [ ] 创建 DevOps Agent Space，配置 CW + GitHub 集成
- [ ] 编写 Webhook Forwarder Lambda（CW Alarm → DOA）
- [ ] 编写 3 个初始 Skills（ECS/RDS/Lambda 故障）
- [ ] 配置 Slack 通知通道
- [ ] 验证：告警 → 自动调查 → Slack 通知

### Phase 2: 体验层（1 周）
- [ ] 实现 HTML 诊断书渲染（EventBridge → Report）
- [ ] 注册 NLOps MCP Server 到 Agent Space（5 tools）
- [ ] **Quick Desktop 接入**：复用 v3 mcp-bridge，改用 5 个新工具
- [ ] 接入企微/飞书 Bot
- [ ] 验证：Quick Desktop 完整对话流 + 告警闭环 + HTML 诊断书 + IM 通知

### Phase 3: 语音 + 修复（1 周）
- [ ] Nova Sonic 语音交互实现
- [ ] SSM Runbook 编写（3 个常见修复）
- [ ] Agent-ready Spec → Kiro 集成验证
- [ ] 验证：语音巡检 + 自动修复

### Phase 4: 经验沉淀（持续）
- [ ] Investigation 完成后自动生成 Skill
- [ ] Skills 版本管理 + 团队共享
- [ ] 效果度量：MTTR 对比

---

## 9. 风险与缓解

| 风险 | 影响 | 缓解 |
|------|------|------|
| DOA Investigation 耗时 5-15min | 用户等待焦虑 | Slack 实时进度推送 + 先返回初步发现 |
| DOA 不支持中国区 | 中国客户无法使用 | 跨境方案：中国 IM → Global API GW → us-east-1 DOA |
| Skills 数量有限时匹配不准 | 早期效果不佳 | 冷启动期用 Nova Pro 兜底分析 |
| SSM Runbook 覆盖不全 | 部分修复无法自动化 | 降级为 Agent-ready Spec → 人工执行 |
| Nova Sonic 中文识别率 | 语音体验差 | 提供文字输入 fallback |

---

## 10. 核心差异化总结

**为什么不直接用 DevOps Agent？**

DevOps Agent 是引擎，NLOps 是驾驶舱：

| 维度 | DevOps Agent 原生 | NLOps v4 增量 |
|------|-------------------|---------------|
| 入口 | Operator Console / Slack | + Quick Desktop / 企微/飞书 / Nova Sonic 语音 |
| 输出 | 文本 + Slack 消息 | + **HTML 诊断书**（图表 + 解读 + 证据链 + 架构图标注） |
| 经验 | Skills（手动创建） | + **自动从 Investigation 生成 Skill** |
| 修复 | Mitigation Plan（建议） | + SSM 自动执行 + **Kiro 代码级修复（PR）** |
| 语音 | ❌ | **Nova Sonic 随时随地运维** |
| 多模态 | 文本输出 | + **架构图理解 + 故障点标注** (Nova Pro Vision) |
| 客户沟通 | ❌ | **自动生成故障公告**（Nova Pro 中文化） |
| 中国区支持 | ❌ DOA 不可用 | **CloudWatch Investigations 降级路径** |
| 中国 IM | ❌ 仅 Slack | 企微/飞书原生集成 |
| 多云 | ✅ DOA 支持 | NLOps 把多云能力暴露到 IM 入口 |

**一句话定位**：
> NLOps = DevOps Agent 的**中国化体验层** + **多模态可视化诊断书** + **代码级闭环修复** + **自动经验沉淀** + **语音运维** + **中国区降级保障**

---

## 附录 A: 参考博客核心要点提炼

### A.1 End-to-End Agentic SRE (2026-05)
- **Webhook 触发**：CW Alarm → SNS → Lambda → DOA Webhook (HMAC)
- **Skills 封装经验**：Markdown 格式，包含调查步骤 + 常见根因 + Runbook 引用
- **Mitigation Plan 4 阶段**：Prepare → Pre-Validate → Apply → Post-Validate
- **Agent-ready Spec**：结构化指令，可直接交给 Kiro 执行代码修复
- **多源集成**：CW + Splunk + GitHub + Slack 同时接入一个 Agent Space

### A.2 Telkomsel CELYNA (2026)
- **效果量化**：MTTR -83%，根因识别 1h→1min，复杂事件从 20 人会议→AI 自动
- **Serverless 架构**：Lambda 为核心，按事件量自动伸缩
- **统一日志池**：DB + App + K8s + Network → 集中分析
- **自愈能力**：低于 99% SLA 阈值自动触发修复

### A.3 CW Investigations + Nova Sonic (2025-10)
- **语音闭环**：语音提问 → CW Investigation 分析 → 语音回答 → 语音指令修复
- **SSM Runbook 执行**：Investigation 发现问题后，直接执行 SSM Automation 修复
- **Anywhere Ops**：不在电脑旁也能通过语音完成运维
- **S3 中转**：Investigation insights → S3 → Nova Sonic 上下文

### A.4 AI-Powered Incident Response (2025-07)
- **多模态分析**：架构图 + 文本日志 + 指标 → Nova Pro 综合分析
- **概率排序根因**：输出 ranked list of probable causes
- **自动生成客户沟通**：故障通报邮件自动生成
- **数据采集脚本化**：fetch-obsv-data.sh 一键采集 CW + Config + X-Ray
