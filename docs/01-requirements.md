# NLOps 需求分析

> 版本: v3.0  ·  最后更新: 2026-05-19  ·  基于 PPT《自然语言驱动的 AI 运维平台》v3 重写
> v3 修订（vs v2 2026-05-17）：
> - **入口收窄到 Quick Desktop 主线**（飞书 / 企微 / Voice 移到 v4）
> - **经验沉淀方案调整**：DOA Custom Skill API 在 boto3 SDK 中不存在（实测 2026-05），改用 **Bedrock KB 双写 + AuditTable 历史检索** 实现，FR-2.5 / 3.2 / 3.4 narrative 同步调整
> - **Lambda 数 4 → 2**（方案 B 合并 L3+L4 入 L1）
> - **boto3 service name** `aidevops` → `devops-agent`（实测校正）

---

## 1. 项目背景

### 1.1 客户场景
某客户已将 100+ 微服务迁移到 AWS，由 SRE 团队负责日常运维。团队希望降低运维复杂度、提升故障响应效率，但当前面临以下问题：

| 维度 | 现状 | 问题 |
|------|------|------|
| 主动运维 | 每天打开 CloudWatch 逐一检查指标 | 重复劳动、漏检风险 |
| 被动运维 | 告警触发后切换 CloudWatch / Config / X-Ray 等多个控制台 | 上下文频繁丢失，定位耗时长 |
| 团队能力 | 故障处理依赖工程师经验 | 经验无法传承、无法沉淀复用 |
| 数据呈现 | 只有图表没有解读 | 需依赖个人经验解读 |

### 1.2 项目目标
在 **AWS DevOps Agent** 作为底层"自治型 SRE 引擎"的基础上，构建一个**面向中国客户、语音 / IM 驱动的智能闭环运维平台 (NLOps)**。让运维人员通过语音 / 文字即可完成"发现 → 定位 → 修复 → 沉淀"全流程，做到**随时随地、开口即运维**。

> **重要差异**：v1 版本设想从零自建 6 个 Agent；v2 版本采用 AWS DevOps Agent 作为引擎，NLOps 专注于语音入口 / 国内 IM / HTML 诊断书 / 写操作护栏等 4 类差异化能力。

---

## 2. 用户与角色

| 角色 | 描述 | 主要诉求 |
|------|------|---------|
| SRE 工程师 | 一线值班人员 | 快速发现异常、根因定位、执行修复 |
| 研发工程师 | 服务 owner | 接收事件通知、查看分析报告、复用历史经验 |
| 运维负责人 | 团队 leader | 全局健康概览、SLA 跟踪、成本控制 |
| 系统管理员 | 平台运维者 | 配置数据源、管理权限、维护知识库（含 DevOps Agent Skills 与 MCP 工具）|

---

## 3. 功能需求

按优先级（P0 必须 / P1 应该 / P2 可以）梳理。**6 个逻辑 Agent 作为业务概念保留**，物理实现见 `02-design.md`。

### 3.1 交互层 (P0)

| ID | 需求 | 优先级 | 验收标准 |
|----|------|--------|---------|
| FR-1.1 | 多入口接入：Amazon Quick (MCP)、企微 Bot、飞书 Bot | P0 | 三个入口均可发起运维请求并获得相同质量回复 |
| FR-1.2 | 支持语音输入与语音回复（中英文混合） | P0 | 端到端首响应 < 2s（含"我在分析中"的 placeholder TTS）|
| FR-1.3 | 支持文字输入与文字回复（含 Markdown / 卡片） | P0 | IM 卡片正常渲染，URL 可点击 |
| FR-1.4 | 输出 HTML 分析页 URL（30 天有效） | P0 | URL 可在浏览器和 IM 内打开，过期返回 403 |

### 3.2 智能编排（v3：1 Strands Agent + 5 Tool） (P0)

| 逻辑 Tool | 职责 | 物理实现 / 引擎 |
|---|---|---|
| **(Routing)** | 意图识别 → 选工具 | **Strands Agents 1.40 SDK 内置**（v2 的 RouterAgent 已删除） |
| **discover_service** | 拉指标 / 日志 / 拓扑 / 事件 | DOA on-demand chat（核心）+ CloudWatch 直连（fallback） |
| **deep_investigate** | 根因分析（只读） | DOA `CreateBacklogTask`（taskType=INVESTIGATION，94% 准确率） |
| **search_knowledge** | 经验沉淀 + 历史匹配 | **Bedrock KB + AuditTable scan**（DOA Custom Skill API 不在 SDK） |
| **request_execute** | 用户确认后执行修复 | NLOps 独立 ExecutionFn Lambda（写隔离 + Confirm Token + Policy Guard） |
| **render_report** | 生成 HTML 分析页 | Jinja2 + ECharts，写 S3（OrchestratorFn 内进程） |

| ID | 需求 | 优先级 | 验收标准 |
|----|------|--------|---------|
| FR-2.1 | Strands Agent 自动识别用户意图，分发到对应 Tool | P0 | 工具选择准确率 ≥ 95%（基于 Nova Pro 实测） |
| FR-2.2 | discover_service 通过 DOA on-demand chat 拉数据；DOA 不可达时降级到 CloudWatch 直连 | P0 | 双路径都能返回结构化结果 |
| FR-2.3 | deep_investigate 调用 DOA `CreateBacklogTask` API，返回 task_id；后续异步通过 EventBridge 取完整结果 | P0 | 输出 task_id / status / expected_minutes 三字段 |
| FR-2.4 | request_execute 必须有 confirm_token + Policy 检查方可写 AWS API | P0 | 缺 token 自动拒绝；越权资源被拦截；全部写操作进 audit log |
| FR-2.5 | search_knowledge 把客户私有 runbook / 故障手册 嵌入到 **Bedrock KB**（v3）。<br>~~原计划：注册为 DOA Custom Skill；实测 boto3 `devops-agent` 没有 CreateCustomSkill API，改走 KB 路径~~ | P0 | KB ingestion 成功率 ≥ 99%；retrieve top-5 相关性 ≥ 0.7 |
| FR-2.6 | render_report 把 DOA 输出转 HTML 诊断书（含图表 / 解读 / 建议 / 证据） | P0 | 报告 < 5s 生成，包含至少 1 图 + 文字解读 |
| FR-2.7 | 平台暴露 NLOps MCP Server，21 个工具（含 smart_diagnose / consult_devops_agent / request_confirm_token）给 Quick Desktop / DOA / 任意 MCP-aware AI | P0 | tools/list 返回 21；tools/call 全部能跑通（mock 或 real 模式） |
| FR-2.8 | EventBridge 订阅 DOA 自治调查事件（告警驱动场景），自动渲染 HTML + SES 发邮件 + KB 沉淀 | P0 | CW 告警 → DOA 自动调查 → 邮件落地 + 诊断书 URL，全程无人工 |

### 3.3 经验闭环 (P0)

| ID | 需求 | 优先级 | 验收标准 |
|----|------|--------|---------|
| FR-3.1 | 故障处理完成后自动生成结构化事件报告 | P0 | 含字段：时间线 / 根因 / 影响范围 / 修复步骤 / 验证结果 / 证据链 |
| FR-3.2 | 事件报告自动**写入 Bedrock KB**（v3 主路径，原 v2 计划的 DOA Custom Skill 因 SDK API 缺失改为通过 console UI 静态配置）| P0 | KB ingestion 成功率 ≥ 99%；KB 文档与 AuditTable 内容一致 |
| FR-3.3 | 同时双写 S3 + AuditTable（兼容客户已有知识库 / 历史事件检索） | P0 | S3 + AuditTable 均能查到同一 incident_id |
| FR-3.4 | **冷启动预置常见故障样例**（≥ 5 类，演示用；50 类为生产标准）| P1 | 部署完即可用 search_knowledge 命中常见 case |

### 3.4 分析页 / 报告 (P0)

| ID | 需求 | 优先级 | 验收标准 |
|----|------|--------|---------|
| FR-4.1 | 报告中包含数据图表（趋势 / 拓扑 / 火焰图） | P0 | 至少支持 ECharts 折线 / 柱状 / 热力 |
| FR-4.2 | 报告中包含 AI 文字解读 | P0 | 每个关键指标至少 1 句解读 |
| FR-4.3 | 报告中包含因果分析（时间线 + 关联事件） | P0 | 时间线按秒级排序 |
| FR-4.4 | 报告中包含可执行操作建议 | P0 | 按优先级排序，标注风险等级；可点击触发 Execution 流程 |
| FR-4.5 | 报告中包含证据链（日志片段 / Trace ID / DevOps Agent investigation ID）| P0 | 可点击跳转到原始数据源 / DevOps Agent Operator Portal |
| FR-4.6 | 支持对话式下钻（总览 → 聚焦 → 链路 → 代码） | P1 | 每次下钻生成独立 URL |

### 3.5 安全与合规 (P0)

| ID | 需求 | 优先级 | 验收标准 |
|----|------|--------|---------|
| FR-5.1 | Policy 护栏：Analysis 只读、Execution 写需确认 | P0 | 越权操作被拦截并审计 |
| FR-5.2 | 所有用户输入 / Agent 决策 / 执行动作 全链路日志 | P0 | 日志保留 ≥ 90 天 |
| FR-5.3 | S3 Presigned URL 默认 30 天过期 | P0 | URL 内不暴露明文凭证 |
| FR-5.4 | IAM 最小权限：Orchestrator Lambda 只读 + Execution Lambda 独立写权限 | P0 | 通过 IAM Access Analyzer 校验 |
| FR-5.5 | NLOps MCP Server 用 AWS SigV4 鉴权，DevOps Agent 服务主体 `aidevops.amazonaws.com` 可访问 | P0 | 验证 IAM trust policy 限定 sourceAccount + sourceArn |
| FR-5.6 | Confirm Token 单次使用、5 分钟过期、绑定原会话 | P0 | 重放 / 过期 / 跨会话使用均被拒绝 |

---

## 4. 非功能需求

| 维度 | 指标 | 说明 |
|------|------|------|
| 性能 - 语音 ASR 首响应 | < 500 ms | Nova Sonic 流式 |
| 性能 - 语音"分析中"placeholder | < 2 s | 用户开口后即返回提示音；真正答案随后到达 |
| 性能 - DevOps Agent investigation | 5-15 min | 由 DevOps Agent 自身决定，**不在 NLOps 控制范围**；用户期望需调整 |
| 性能 - DevOps Agent on-demand chat | 5-30 s | 简单查询场景，可接受 |
| 性能 - HTML 分析页生成 | < 5 s | 拿到 DevOps Agent 结果后渲染 |
| 性能 - Knowledge Skill 注册 | < 30 s | 通过 DevOps Agent API 注册 |
| 并发 | ≥ 50 并发用户 | Lambda 自动扩缩 |
| 可用性 | ≥ 99.5 % | 全 Serverless，无单点 |
| 可维护性 | Skills 可独立增减 | 通过 console 或 CLI 管理 |
| 成本 | ≤ $20 / 用户 / 月（不含 DevOps Agent）| **DevOps Agent 单独按使用量计费 ~$30-60/用户/月**，可被 AWS Support 抵扣 |
| 部署效率 | CDK 一键部署 ≤ 15 min | `cdk deploy` 全栈完成 |

---

## 5. 范围边界

### 5.1 包含 (In Scope)
- Orchestrator + Execution + EventBridge + MCP Server 4 Lambda
- 语音 / 文字交互 + HTML 分析页
- DevOps Agent on-demand chat / investigation API 集成
- DevOps Agent EventBridge 事件订阅
- DevOps Agent Custom Skills 自动注册
- NLOps 自暴露 MCP Server，提供客户内部工具
- CDK 基础设施代码
- 三个入口适配（Quick / 企微 / 飞书）

### 5.2 不包含 (Out of Scope)
- 取代 DevOps Agent 自身的根因分析能力（不重复造轮子）
- 跨云厂商支持（仅 AWS；DevOps Agent 自带的 Azure/on-prem 能力可用）
- 工单系统集成（v1 先打通推送即可）
- **AWS 中国区部署（DevOps Agent 不在中国区，方案 v1 仅 us-east-1 / ap-northeast-1，中国客户需走全球区路径）**

---

## 6. 关键假设与风险

| # | 假设 / 风险 | 影响 | 应对 |
|---|-------------|------|------|
| 1 | DevOps Agent 在 us-east-1 已 GA（确认） | 高 | 锁定 us-east-1 |
| 2 | Bedrock / Nova Sonic 在同 region GA | 高 | us-east-1 全部满足 |
| 3 | 客户已开启 CloudWatch 详细监控 | 中 | 部署时检查并提示开启 |
| 4 | 企微 / 飞书 webhook 配额 | 低 | 限流 + 异步推送 |
| 5 | DevOps Agent 调查耗时长（5-15 min） | 中 | 用 EventBridge 异步通知 + IM 卡片更新；用户体验需要预期管理 |
| 6 | DevOps Agent 调用费用累积快（$0.0083/s） | 高 | 区分 chat vs investigation；只在必要时调用 investigation |
| 7 | 写操作误执行 | 高 | Confirm Token + Policy + IAM 三重护栏 |
| 8 | NLOps MCP Server 被 Prompt Injection 攻击 | 中 | 只暴露只读 tool；按 DevOps Agent 安全指南做 input 净化 |
| 9 | 语音识别在嘈杂环境下准确率下降 | 中 | 提供"识别结果回显 + 文字纠正"路径 |
| 10 | 中国区客户数据合规 | 高 | 明示 v1 数据进出全球区，让客户评估；中国区方案待 DevOps Agent 入华 |

---

## 7. 验收标准（端到端 Demo 场景）

| 场景 | 输入 | 期望输出 | 涉及 Agent (逻辑) |
|------|------|---------|------|
| 1. 早晨巡检 | 语音："早上好，系统今天怎么样？" | 健康总览 HTML 分析页 + 语音摘要 | Router → Discovery → Report |
| 2. 故障下钻 | 语音："order-service 延迟为什么涨了？" | 聚焦分析页（含根因 + 证据 + 建议）| Router → Discovery → Analysis → Report |
| 3. 执行修复 | 语音："帮我扩容到 4 实例" | 风险确认卡片 → 用户确认 → 执行 → 结果回显 | Router → Execution（带 Confirm Token） |
| 4. 经验复用 | 语音："上次类似问题怎么解决的？" | DevOps Agent 自动应用 Custom Skill 给出方案 | Router → Knowledge (DevOps Agent Skills) |
| 5. 自动沉淀 | 修复完成后 | 事件报告自动注册为 Custom Skill；同时入 Bedrock KB（双写）| Knowledge |
| 6. 告警驱动闭环 | CW 告警触发 → DevOps Agent 自动调查 | EventBridge 事件 → NLOps 渲染 HTML → 推送 IM | EventBridge handler → Report |
| 7. 客户私有工具 | DevOps Agent 调查中需要查客户内部 CMDB | NLOps MCP Server 返回 CMDB 数据 | MCP Server (我们暴露的) |
