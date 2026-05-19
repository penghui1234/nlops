# NLOps Demo 演示脚本（v3 — Quick Desktop 主线）

> 版本: v3.0 · 最后更新: 2026-05-19
> 适用：客户演示 / 老板汇报 / 售前 PoC / AB 评审
> 时长: 8-10 分钟主体 + 2 分钟 Q&A
> 对应需求: `01-requirements.md` §7 · 对应设计: `02-design.md` §6
>
> v3 vs v2 改动：
> - **入口收窄到 Quick Desktop**（IM 飞书/企微留 v4，Voice 留 v4）
> - **6 场景 → 5 场景**（砍语音/IM/Custom Skill 故事，加邮件告警和写操作护栏 UX 强调）
> - **演示数据真实化**：用真账号 EC2 / Lambda / AuditTable，而不是 PPT 上的虚构 payment-api

---

## 0. 演讲者准备清单

### 0.1 物料
- [ ] 演示笔记本 + 投屏
  - 左屏：PPT（17 页）
  - 右屏：Quick Desktop 窗口 + 浏览器（备用 AWS 控制台 + 手机邮箱）
- [ ] 手机一部，已安装 outlook / 邮件 App，登录 `penghuichen@nwcdcloud.cn`
- [ ] 备用网络（4G 热点），防演示场地 Wi-Fi 抽风
- [ ] AWS 控制台已登录 us-east-1

### 0.2 演讲前 1 周准备
- [ ] **彩排 5 个场景全跑通**（用秒表卡时间，5 分钟内覆盖完）
- [ ] AWS DevOps Agent Agent Space `52e43342-bbe2-4fb7-aadd-c072410509ba` 关联：
  - 至少 1 个 Service registered
  - CloudWatch alarm 与 DOA 关联（自动 investigation）
- [ ] Demo 数据已到位：
  - EC2 `i-0257069e2402a0fbc` 打 `Service=demo-api / Owner=penghuichen@... / nlops:managed=true` tag
  - DDB AuditTable 至少 5 条 sample incident
  - CloudWatch alarm `demo-api-high-cpu` 强制 ALARM 状态
- [ ] HTML 诊断书 + 邮件模板美化定稿
- [ ] **完整跑通 1 次**：场景 1 → 5 端到端，记录耗时

### 0.3 演讲前 1 天
- [ ] 重置 demo 环境：
  - 清掉演示用 ConfirmTokensTable 内残留 token
  - 重新触发 demo-api-high-cpu alarm 确认进 ALARM 状态
- [ ] 确认 SES `penghuichen@nwcdcloud.cn` 邮箱仍 verified（发一封测试邮件试）
- [ ] 备份"故障预录视频" 1 份（场景 5 投资过长时降级用）
- [ ] 检查所有 S3 Presigned URL 仍有效（默认 30 天）

### 0.4 演讲前 30 min
- [ ] 手机静音、关其他通知
- [ ] 重启 Quick Desktop（避免缓存的 MCP tools 列表与服务端不一致）
  - **断开 NLOps MCP connection → 等 3 秒 → 重连**
  - 应该看到 21 个工具（discover_resources / smart_diagnose / ...）
- [ ] 浏览器关无关 tab
- [ ] 投屏分辨率确认；字体放大 18pt+
- [ ] 测一次：在 Quick Desktop 问"看一下 EC2"，应返回真实 1 台 t3.micro

---

## 1. 开场（30 秒）

> "各位好。今天给大家演示 NLOps —— 一个把 AWS DevOps Agent 和 21 个 MCP 工具包装成**任何 MCP-aware AI 都能调用**的智能闭环运维平台。
>
> 我用 5 个真实场景演示完整闭环，全程在 **Quick Desktop** 一个窗口里完成。**今天演示走真实模式，所有数据都来自我自己的 AWS 账号**，没有提前彩排的故事。"

**节奏控制**：不要开场就放 PPT 架构图。**先放 demo，再讲架构**。客户对体验的兴趣远大于对架构。

---

## 2. 场景 1：资源盘点（1 分钟） — 真实数据 ✅

### 2.1 演示动作
在 Quick Desktop 输入：
> 💬 **"看一下当前账号下所有的 AWS 资源"**

### 2.2 用户感知
| 时间 | 用户体验 |
|------|---------|
| ~3 s | Quick Desktop AI 调用 `discover_resources(resource_type="all")` |
| ~5 s | 返回真实数据：1 台 EC2（t3.micro running） + 4 个 Lambda（NLOps 自己的） |

**Quick Desktop 显示**:
```
✅ 找到 5 个资源:

EC2 实例 (1):
- test (i-0257069e2402a0fbc, t3.micro, running)
  AZ: us-east-1c, 公网 IP: 3.89.49.81
  Tags: Service=demo-api, Owner=penghuichen@nwcdcloud.cn

Lambda 函数 (4):
- NLOpsStack-OrchestratorFn (python3.12, 1536MB)
- NLOpsStack-ExecutionFn (python3.12, 512MB)
- ...
```

### 2.3 演讲点
> "注意这是**真实的盘点**，不是预设数据。我账号里就 1 台 EC2 + 4 个 Lambda（这 4 个就是 NLOps 自己跑在的 Lambda）。
>
> Quick Desktop 自己的 LLM 看到我们注册的 21 个 MCP 工具，自动选了 `discover_resources` 调用。这就是 MCP 协议的威力 —— **NLOps 提供工具盒，调用方的 AI 自由组合**。"

---

## 3. 场景 2：服务负责人查询（45 秒） — Tag 路径

### 3.1 演示动作
> 💬 **"demo-api 这个服务的负责人是谁，怎么联系？"**

### 3.2 Quick Desktop 显示
```
✅ demo-api 服务信息:

负责团队: demo-team
On-call: penghuichen@nwcdcloud.cn
Slack: #nlops-demo
Runbook: https://wiki.internal/runbook/demo-api
匹配资源数: 2

(基于 AWS Resource Tagging API 真实查询，
通过 Service=demo-api tag 反查到打了这个 tag 的资源)
```

### 3.3 演讲点
> "这是通过 AWS 资源标签实时查的。客户给资源打 `Service=xxx` 和 `Owner=xxx` tag，NLOps 自动建立服务到负责人的映射。
>
> 这一条对**值班场景**特别重要 —— 凌晨告警来了，Quick Desktop 让 AI 帮你 @ 到对的人，不需要查 wiki / 找文档 / 翻历史 PR。"

---

## 4. 场景 3：智能诊断（2 分钟） — Strands Agent + DOA + Bedrock 联动 ⭐ 旗舰场景

### 4.1 故事铺垫（讲台词）
> "前两个是简单查询。下面演示**真正的智能闭环**：用户用一句话问'X 服务为什么慢'，NLOps 后台启动一系列 Agent + DOA 协作，最后给一份完整诊断书。"

### 4.2 演示动作
> 💬 **"OrchestratorFn 这个 Lambda 调用越来越少，帮我深度分析一下原因"**

### 4.3 用户感知
| 时间 | 用户体验 |
|------|---------|
| ~3 s | Quick Desktop AI 看 21 个工具 → **选 `smart_diagnose`** |
| ~10-30 s | NLOps L1 进程内 Strands Agent 启动 5 个 Tool 协作 |
| | 1. `discover_service` → 调 DOA chat 拉 OrchestratorFn 健康概况 |
| | 2. `deep_investigate` → 调 DOA CreateBacklogTask 启动 RCA |
| | 3. `search_knowledge` → 查 AuditTable 历史 incident |
| | 4. `render_report` → Jinja2 渲染 HTML → S3 |
| ~35 s | Quick Desktop 渲染 Strands Agent 返回的中文摘要 + HTML 诊断书 URL |

**Quick Desktop 返回**:
```
✅ 智能诊断完成

引擎: Strands Agents 1.40 SDK
LLM: amazon.nova-pro-v1:0
Trace ID: trc-mcp-abc123

📊 初步分析:
OrchestratorFn 在过去 24 小时调用次数从 23 次/天降至 3 次/天，
- 不太像故障（错误率 0%）
- 更可能是: 业务流量减少 / 上游调用方下线 / Demo 数据
- 历史相似事件: inv-2026-05-15-002 (Lambda cold start)

🔬 深度调查 (Backlog Task ID: inv-xyz):
已通过 AWS DevOps Agent 启动，预计 5-15 分钟出 RCA 完整结果。

📄 完整诊断书: 
https://nlopsstack-reportbucket.s3.amazonaws.com/reports/diagnostic/abc123.html
(30 天有效)

🔗 DevOps Agent Operator Portal:
https://us-east-1.console.aws.amazon.com/aidevops/spaces/52e43342.../tasks/inv-xyz
```

### 4.4 投屏切换
**演讲者点 HTML URL → 投屏切到浏览器**
- 上方：服务健康灯 + 严重度
- 中部：时间线 / 根因 / 关联 alarm
- 底部：修复建议（带风险等级 / 是否可自动）+ 证据链

### 4.5 演讲点（背词）
> "刚才发生了什么？
>
> **第一**：Quick Desktop 自己的 LLM 决定调 `smart_diagnose`，因为它看到这是个'why X is slow'类问题。
>
> **第二**：`smart_diagnose` 工具内部启动 **Strands Agents 1.40 SDK**（AWS 官方开源框架）。Strands 的 LLM 看到我们 5 个 Tool 的 description，自动决定调用顺序：先发现 → 再调查 → 再渲染。
>
> **第三**：Strands 的 `deep_investigate` 工具调到 **AWS DevOps Agent** —— 这是 AWS 2026-03 GA 的自治型 SRE 智能体，94% 准确率。**真正的 RCA 在 DOA 跑，我们做编排和呈现。**
>
> **第四**：`render_report` 把结构化结果转成 HTML，写到 S3，给一个 Presigned URL。
>
> 全程**没有 NLOps 的工程师写一行 if-else 决定该调哪个工具** —— 都是 LLM-driven。这就是 Strands SDK 的核心价值。"

### 4.6 ⚠️ 关键决策点：等还是剪？

DOA `CreateBacklogTask` 真要 5-15 分钟出深度结果。**演讲不能干等**。两条路：

**Plan A（推荐）**：**预先把这次调查跑过**，演讲时初步分析 30 秒返回足够；如果有人问"完整调查呢"再带他看 Operator Portal 上跑完的结果（"我们演讲前 30 分钟启动了，刚好出来"）

**Plan B**：演讲只展示初步分析（30 秒就有），完整调查告诉听众"会异步推完整诊断书 + 邮件"，连接到场景 5

我推荐 Plan B。

---

## 5. 场景 4：写操作护栏（1.5 分钟） — Confirm Token + L2 隔离 ⭐ 合规要点

### 5.1 故事铺垫
> "前面都是只读。现在演示**写操作**。这是合规客户最关心的：**LLM 不能直接调 ECS scale**，要有护栏。"

### 5.2 演示动作
> 💬 **"帮我把 demo-api 实例数扩到 4"**

### 5.3 Quick Desktop 自动两步走

**Step 1**: AI 看到这是写操作，**先调 `request_confirm_token`**：
```
🔒 写操作请求确认
─────────────────────
Action: ecs.update_service
Params: {"cluster":"demo","service":"demo-api","desired_count":4}
Risk: low
Token: ct-9b3e4a1f... (5 分钟内有效)

⚠️ 这是真实的写操作。请你显式确认后我才会调 scale_service。
```

**Step 2**: 演讲者输入：
> 💬 **"确认"**

Quick Desktop 调 `scale_service(service_name="demo/demo-api", desired_count=4, confirm_token="ct-9b3e4a1f...")`

返回（如果 ECS 真存在的话）：
```
❌ 执行失败: 
"NoSuchService" - cluster 'demo' or service 'demo-api' does not exist

(这是预期：演示账号没真实 ECS service。
但 Confirm Token 校验通过 ✅，IAM 检查通过 ✅，
说明护栏链路是对的。)
```

### 5.4 演示越权拦截（30 秒，可选）

演讲者再发：
> 💬 **"帮我直接 scale 不要 token"**

Quick LLM 应该会拒绝（它的 system prompt 看到 description 说 "REQUIRES confirm_token"）。如果它没拒绝，scale_service 会因为 `confirm_token=""` 在 L2 ConfirmTokensTable 校验失败。

### 5.5 演讲点
> "**写操作的 4 道护栏**：
>
> 1. **Quick LLM 看到 tool description 强调 'REQUIRES confirm_token'** —— 软护栏 1
> 2. **`request_confirm_token`** 把 token 写 DDB（5 分钟单次有效，绑定 user + session）—— 软护栏 2
> 3. **用户必须显式回 '确认'** —— 软护栏 3，但这是关键的**人在回路**
> 4. **L2 ExecutionFn 独立 IAM Role** 做 token 校验 + 跑真 AWS API —— 硬护栏
>
> 即使 Quick LLM / NLOps 任何一处出 prompt injection 漏洞，**只要绕不过 L2 的 IAM 隔离 + tag 边界（`nlops:managed=true`）**，写操作就走不了。
>
> 这就是 v3 用的'读全在 L1，写隔离 L2'架构。"

---

## 6. 场景 5：自动告警闭环（2 分钟） — EventBridge + SES + KB 沉淀 ⭐ 闭环演示

### 6.1 故事铺垫
> "前面 4 个场景都是 SRE 主动问。这个场景演示**SRE 什么都不做**，比如他在睡觉。"

### 6.2 演示动作
演讲者**手动触发** EventBridge 模拟事件（演讲前预备）：

```bash
aws events put-events \
  --entries '[{
    "Source":"aws.aidevops",
    "DetailType":"Investigation Completed",
    "Detail":"{\"investigationId\":\"inv-demo-live\",\"status\":\"COMPLETED\",\"title\":\"Live demo: demo-api memory pressure\",\"severity\":\"high\",\"service\":\"demo-api\",\"rootCause\":{\"summary\":\"Memory utilization climbing past 85%\"},\"operatorPortalUrl\":\"https://...\"}",
    "Resources":["arn:aws:aidevops:us-east-1:828414850215:agent-space/52e43342-bbe2-4fb7-aadd-c072410509ba"]
  }]'
```

或者，**直接对真账号上已有的 alarm 切换状态**：
```bash
aws cloudwatch set-alarm-state \
  --alarm-name demo-api-high-cpu \
  --state-value ALARM \
  --state-reason "Live demo trigger"
```

### 6.3 用户感知

约 **5-10 秒后**：

**演讲者手机弹通知**（投屏切到手机）：
```
📧 [HIGH] Live demo: demo-api memory pressure
来自: nlops-alerts@... → penghuichen@nwcdcloud.cn

🚨 NLOps Alert · HIGH
─────────────────────
服务: demo-api
根因: Memory utilization climbing past 85%
时间: 2026-05-19 ...
来源: AWS DevOps Agent

修复建议:
- Restart demo-api process [low risk · 可自动]
- Investigate memory leak in v1.2.3 [medium risk]

[📄 查看完整诊断书 →]
[🔗 DevOps Agent Portal →]
```

**演讲者打开 Quick Desktop 问**：
> 💬 **"刚才那个告警是什么情况？给我总结"**

Quick LLM 调 `discover_incidents` 或 `get_investigation`，返回 AuditTable 里刚刚 EventBridge handler 沉淀的记录。

### 6.4 演讲点
> "这一段全程**没有人工**：
>
> 1. CloudWatch alarm 触发 → AWS DevOps Agent 自动 investigation
> 2. DOA 完成调查 → 发布事件到 EventBridge
> 3. NLOps L1 OrchestratorFn 收到事件，**在同一进程内**：
>    - 调 DOA `GetBacklogTask` 拉详情
>    - **Bedrock Nova Pro** 写'非技术干系人'摘要
>    - **Jinja2** 渲染 HTML 诊断书 → S3
>    - **SES** 发 HTML 邮件到 `penghuichen@nwcdcloud.cn`
>    - **Bedrock KB 双写**：把 incident JSON 推到 KB，下次类似问题可以语义检索召回
> 4. **手机邮件 push 实时到达** —— 跨设备 universal 通道
> 5. SRE 醒来抓手机看邮件 → 完整诊断 + 一键修复 URL 已经躺在邮箱里
> 6. 想深问？打开 Quick Desktop，AI 用 `discover_incidents` 调 AuditTable 给你完整故事
>
> **MTTR 从 30 分钟降到 5 分钟。**"

### 6.5 ⚠️ 演练注意

- 邮件投递可能受 SES sandbox 限制：必须 verify `penghuichen@nwcdcloud.cn`（发件 + 收件双向 verify）
- 演讲前一天发一封测试邮件确认到达
- 备用方案：如果邮件没到，直接打开 S3 上的 HTML 诊断书 URL 演示

---

## 7. 收尾（30 秒）

> "刚才看到的，**今天全部都是真的**：
> - **AWS DevOps Agent** 是 AWS 2026-03 GA 的服务，service 名 `devops-agent`
> - **Strands Agents** 是 AWS 开源的多 Agent 编排框架，1.40 是当前稳定版
> - **Bedrock Nova Pro** 是 Amazon 自家 LLM，演示账号能直接用
> - 我们这一层（NLOps）大概 **2500 行 Python + 1 份 CDK 文件**
>
> **架构亮点**：
> - **2 个 Lambda**：读全在 L1，写隔离 L2（合规底线）
> - **21 个 MCP 工具**：任何 MCP-aware AI（Quick / DOA / Cursor / Claude Desktop）都能调用
> - **MOCK_MODE 开关**：演示彩排 vs 真实模式不需 redeploy
>
> **总成本**：50 用户 / 月 大约 **$496**（Enterprise Support 抵扣后），人均 $10/月
>
> **部署**：CDK 一键 ≤ 15 分钟
> **首批落地**：3-4 周完成 PoC
>
> 谢谢，问题环节。"

---

## 8. Q&A 弹药库（v3 高频问题预备答案）

### Q1: "为什么不直接用 DevOps Agent？"

A: "好问题。直接用 DOA 你能拿到 70% 的能力，但少这 5 件：
1. **Quick Desktop / 任意 MCP 客户端入口** —— DOA 主推 Slack / ServiceNow，不支持 MCP-as-tool 模式
2. **HTML 诊断书 + SES 邮件双通道** —— DOA 自带 Operator Portal 是给工程师的，邮件是 universal 通道
3. **写操作护栏 (Confirm Token + L2 IAM 隔离)** —— DOA 给建议，我们做执行层
4. **smart_diagnose 一站式工具** —— 1 句话触发完整 RCA 闭环，不需要客户自己组装多步
5. **客户私有 MCP 工具** —— v4 加 CMDB / Jira / 内部 APM 接入

如果您只是给工程师内部用且只在 Slack 里，确实直接 DOA 就够了。如果您要严格合规、跨设备触达、客户深度定制，就需要 NLOps 这一层。"

### Q2: "Strands SDK 是什么？为什么要用它？"

A: "Strands Agents 是 **AWS 2025 开源的 Agent 框架**（github.com/strands-agents/sdk-python，5.9k stars）。
- 模型无关：Bedrock / Anthropic / Gemini / OpenAI / Ollama 都支持
- 工具用 `@tool` 装饰器，LLM 自动 routing
- 内置 MCP server 支持

我们用它的好处：
1. **替代自研 routing** —— v2 我们写了 95 行自研编排，v3 直接 import strands
2. **AWS 官方背书** —— 给客户看不会说'你这是自研框架可信吗'
3. **生态兼容** —— Strands 生态有 multi-agent / hot-reload / OpenTelemetry 等高级特性，未来扩展不用换框架"

### Q3: "中国客户能用吗？"

A: "**当前全球区可用，中国区暂不支持**。
- DOA / Bedrock / Nova Sonic 都没有中国区版本
- 中国客户有 3 条路：
  1. **数据出境**：通过专线 / VPN 同步指标到 us-east-1（合规需评估）
  2. **降级版本**：用 SageMaker 自建中文模型 + Strands SDK，损失 RCA 能力但合规
  3. **等待 AWS 中国区 GA**

我们诚实地把这写在了设计文档里，没在 PPT 上忽悠。"

### Q4: "DOA investigation 真要 5-15 分钟，太慢了"

A: "这是 DOA 自身的 SLA。但有 3 种缓解：
1. **chat (5-30s)** 用于巡检 / 简单查询场景
2. **investigation (5-15min)** 用于真正复杂的根因分析
3. **smart_diagnose 内部并行**：先 chat 出初步分析（用户立刻能看到），同时启动 investigation 异步给完整结果

实际生产 80% 是 chat 或缓存命中，**剩下 20% 才走完整 investigation**。"

### Q5: "成本能再低吗？$496 /月"

A: "三个方向降本：
1. **AWS Support 抵扣**：Enterprise Support 75% → ~$496；Unified Operations 100% → ~$200
2. **限制 investigation 触发**：精准 alarm 关联，减少误触发
3. **Bedrock 切换到 Nova Lite**：从 Pro 降到 Lite，可再省 ~$50/月

**最低可到 $200/月（50 用户，~$4/用户）**。"

### Q6: "你们怎么和 Datadog / PagerDuty / NewRelic 比？"

A: "Datadog/PagerDuty 是观测+告警工具，**不做 RCA、不做执行修复、不沉淀经验**。我们做完整闭环。

具体差异：
- **MCP 工具盒** —— 任何 AI 调用方（Quick / Cursor / Claude）都能用，他们没有
- **写操作护栏** —— 我们有 Confirm Token + L2 IAM 隔离，他们要么不写要么粗放写
- **价格**：Datadog $44-118/host，我们 $10/user
- **不是替代**：他们做观测我们做闭环，可以叠加用"

### Q7: "为什么 Lambda 数从 4 降到 2？是不是把功能砍了？"

A: "**没砍功能**，反而扩了（21 工具 vs v2 的 18）。
- v2 的 4 Lambda 中，L3 (EventBridge) 和 L4 (MCP) 都是只读 + 调外部服务，权限模型一样
- v3 把它们 in-process import 到 L1，**减少 Lambda 间冷启动叠加**
- L2 (Execution) 仍独立 —— **写权限隔离是 IAM 硬护栏，绝不合并**

这是'读全在一处，写隔离一处'的清晰架构。"

### Q8: "21 个 MCP 工具，AI 选不对怎么办？"

A: "三层保护：
1. **Tool description 写得明确**：每个工具说清 'use this when X' 让 LLM 准确选
2. **Strands Agent system prompt** 给指引（'写操作必须先 request_confirm_token'）
3. **MOCK_MODE=true 演示彩排**：返回故事性数据，让客户先建立信任，再切真实模式

实测 Nova Pro 选工具准确率 95%+。"

---

## 9. 演讲常见翻车 & 应对预案

| 翻车场景 | 触发条件 | 应对预案 |
|---|---|---|
| Quick Desktop MCP connection 没拉到 21 工具 | 缓存陈旧 | **重启 Quick Desktop**，或断开 NLOps connection 再连 |
| smart_diagnose 调用超时 | DOA chat 慢 | 第一次问简短问题预热，或切到 `discover_resources` 等不依赖 DOA 的工具 |
| Bedrock Nova Pro 返回 throttling | 区域级速率限制 | 重试一次；或临时切到 `us.amazon.nova-lite-v1:0` |
| SES 邮件没到 | sandbox 限制 / 验证 expired | 直接打开 S3 上的 HTML 诊断书 URL；或切到飞书 / 短信备用通道 |
| HTML 诊断书 URL 失效 | Presigned URL 过期 | **演讲前重新生成一次**，或切到本地预渲染的 HTML 副本 |
| 网络断了 | 4G/Wi-Fi 都不行 | 切纯 PPT 模式 + 之前录的演示视频 |
| 观众打断问问题 | 客户太活跃 | 承诺 Q&A 答；不要中断 demo 节奏 |
| AWS 控制台 MFA 卡住 | 切到 console 时被拦 | **提前登录并保持会话**，或不切控制台仅展示 Quick Desktop |

---

## 10. Demo 后续动作（演讲完成 ≤ 24 h）

- [ ] 给客户发**完整 PPT + 4 份 docs + GitHub 链接**（feat/v3-strands-merger 分支）
- [ ] 收集 Q&A 中没答好的问题，更新本文 §8
- [ ] 如果有客户报告"邮件到我们企业邮箱被拦了"，准备 SES 退 sandbox 流程
- [ ] 整理客户 ROI 计算表（按客户实际用户数 / SLA 要求 / 现有工具栈）

---

## 11. v3 vs v2 演讲脚本主要差异

| 项 | v2 脚本 (6 场景) | v3 脚本 (5 场景) |
|---|---|---|
| 场景 1 早巡 | 语音"早上好" → IM 卡片 | Quick Desktop 文字"看一下资源" |
| 场景 2 排障 | 语音"X 为什么慢" → 5min 等 | Quick Desktop 文字 → smart_diagnose → 30s 初步 + 异步完整 |
| 场景 3 修复 | IM 风险卡片 + 按钮 | Quick Desktop 文字 + 显式"确认" |
| 场景 4 经验复用 | DOA Custom Skill 自动匹配 | **砍掉**（Custom Skill API 不存在）；改为场景 5 的 KB 沉淀演示 |
| 场景 5 告警闭环 | DOA → EventBridge → IM 卡片 | DOA → EventBridge → SES 邮件（手机端 push）→ Quick Desktop 跟问 |
| 场景 6 客户私有 MCP | 假设展示 CMDB / Jira | **砍掉**（v3 暂未集成客户内部系统） |

总时长：v2 ~10 min，v3 ~7 min（更紧凑）。
