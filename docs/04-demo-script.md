# NLOps Demo 演示脚本

> 版本: v1.0  ·  最后更新: 2026-05-17
> 适用：客户演示 / 老板汇报 / 售前 PoC / 内部团队对齐
> 时长: 8-10 分钟主体 + 2 分钟 Q&A
> 对应需求: `01-requirements.md` §7 · 对应设计: `02-design.md` §6

---

## 0. 演讲者准备清单

### 0.1 物料
- [ ] 手机 1 部，企微 / 飞书 已登录
- [ ] 演示笔记本 + 投屏（双屏：左 PPT，右浏览器/AWS 控制台）
- [ ] AWS 控制台已登录 us-east-1，DevOps Agent Operator Portal 打开备用
- [ ] 浏览器标签预备：HTML 诊断书 demo URL（场景 1）
- [ ] 备用网络（4G 热点），防演示场地 wifi 抽风

### 0.2 演讲前 1 周准备
- [ ] DevOps Agent Agent Space 创建并关联到 demo AWS 账号
- [ ] 客户业务模拟环境部署（建议 ECS + RDS proxy + order-service / payment-service）
- [ ] 故障注入脚本就绪（场景 2 的慢查询 / 场景 5 的证书过期）
- [ ] 预制 5 个 Custom Skill（场景 4 经验匹配演示用），全程跑过至少 1 次
- [ ] 企微 / 飞书 Bot webhook 联调通过
- [ ] Nova Sonic 中文测试 5 次以上（覆盖普通话 + 演讲者口音）
- [ ] HTML 诊断书模板美化定稿（截图过 2 轮设计 review）
- [ ] **完整跑通 1 次**：从场景 1 到场景 5 端到端，用秒表卡时间

### 0.3 演讲前 1 天
- [ ] 重新跑 1 遍场景 1+2，确保 DevOps Agent 接入正常
- [ ] 重置一次 demo 环境（清空 Custom Skills 中的本次记录）
- [ ] 备份"故障预录视频" 1 份（场景 2 投资过长时降级用）
- [ ] 检查所有 Presigned URL 仍有效（默认 30 天）

### 0.4 演讲前 30 min
- [ ] 手机静音、关闭其他通知
- [ ] 重启企微 / 飞书 App（避免 token 过期）
- [ ] 浏览器关闭无关 tab
- [ ] 投屏分辨率确认；字体放大到 18pt+

---

## 1. 开场（30 秒）

> "各位好。今天给大家演示 NLOps —— 一个把 AWS DevOps Agent 包装成**语音驱动 + 国内 IM 友好 + 带写操作护栏**的智能闭环运维平台。
>
> 我会用 5 个真实场景演示完整闭环，从早巡到自动修复，**全程不打开任何 Dashboard**。"

**节奏控制**：不要开场就放 PPT 架构图。**先放 demo，再讲架构**。客户对架构的兴趣远不如对体验的兴趣。

---

## 2. 场景 1：早晨巡检（1 min）

### 2.1 演示动作

1. 演讲者拿起手机，打开企微对话窗（NLOps Bot）
2. 按住语音键，对手机说：
   > 🎙 **"早上好，系统今天怎么样？"**
3. 松开。

### 2.2 用户感知

| 时间 | 用户体验 |
|------|---------|
| ~2 s | 🔊 *"早上好。我正在巡检 12 个核心服务，分析报告稍等就好。"* |
| ~10 s | 📱 企微弹出**早晨巡检报告卡片**（见下） |
| 演讲者 | 点 [📄 查看完整诊断书] → 投屏切到浏览器 |

**早晨巡检报告卡片**（背记下来）：
```
📊 早晨巡检报告 · 5 月 17 日
─────────────────────────
✅ 核心服务 11/12 健康
⚠️ order-service P99 略高 (320ms)

🎯 重点观察
• RDS 连接池使用率 78% ↗
• payment-service 错误率 0.2%

[📄 查看完整诊断书]  [🔍 下钻]
```

**HTML 诊断书页面**（投屏展示）：
- 顶部：12 个服务的**健康灯**（红/黄/绿色块阵列）
- 中部：4 张 ECharts 图（CPU / 内存 / QPS / 错误率，过去 24h）
- **每张图下面有 AI 解读**：
  > "*order-service P99 在 7:30 出现毛刺，与 cron job 时间吻合，建议关注 batch job 的 DB 占用..."

### 2.3 演讲点（背词）

> "注意三件事：
> **第一，这是一句话**——不是看 12 个 Dashboard，是听一句话。
> **第二，回复有 AI 解读**——传统 Dashboard 给数字，我们给医生写的诊断书。
> **第三，全程在手机上**——值班 SRE 不用打开 IDE，不用打开浏览器。"

### 2.4 背后逻辑（被问到时简短解释）

- 调用 AWS DevOps Agent on-demand chat（**5-10 秒**）拉所有服务概况
- Bedrock Claude 把结果转成 HTML 诊断书 JSON
- Jinja2 渲染 → S3 → Presigned URL（30 天有效）

---

## 3. 场景 2：故障下钻（2 min）

### 3.1 演示动作

1. 在同一个会话里继续语音：
   > 🎙 **"order-service 延迟为什么涨了？"**
2. 松开。
3. 切回投屏到企微。

### 3.2 用户感知

| 时间 | 用户体验 |
|------|---------|
| ~2 s | 🔊 *"我正在调用 AWS DevOps Agent 做深度调查，预计 5-10 分钟出完整报告。先看初步发现：…RDS proxy 连接池使用率 78%，疑似数据库慢查询堆积。已发卡片到群里。"* |
| ~15 s | 📱 弹**初步诊断卡片**（见下） |
| ~5-10 min | 📱 推送**完整诊断书更新通知** |

**初步诊断卡片**：
```
🔍 order-service 延迟调查 · 初步发现
─────────────────────────────────
🟡 状态：调查中 (DevOps Agent inv-abc)

📌 已确认
• P99 14:30 起从 200ms → 320ms
• 期间 RDS CPU 升至 85%
• 同时段无新部署

🔎 深度调查中 (~5-10 min)
→ 慢查询日志分析
→ 连接池配置审查
→ 关联微服务调用链

[📄 初步分析页]  [⏰ 完成后通知]
```

### 3.3 ⚠️ 关键决策点：等还是剪？

DevOps Agent investigation **真的要 5-10 分钟**。演讲不能干等。两条路：

**Plan A（推荐）**：**预先把这次调查跑过**，演讲时直接放预录的"完成卡片"
- 故事线：*"我们在演讲前 2 小时启动了这次调查，刚才那条等待消息是真的，但完整报告这会儿已经到了，我现在打开看看"*
- 这是**诚实**的做法，不是欺骗

**Plan B**：剪辑跳过等待，直接展示 5 分钟后的状态
- 故事线：*"我们快进 5 分钟看结果"*
- 演讲者按 PPT 切到下一页（中间放占位"调查中..."一帧）

**绝对不要**：现场启动 + 现场等 5 分钟。会冷场。

### 3.4 完整诊断书（投屏展示）

打开 HTML 完整诊断书：

```
order-service P99 延迟突增 · 完整诊断
═══════════════════════════════════════════════
DevOps Agent investigation: inv-abc-2026-05-17
准确率得分: 0.94

【时间线】
14:30 P99 latency rose 200ms → 320ms
14:32 RDS CPU reached 85%
14:34 ConnectionPoolExhausted 错误开始出现
14:35 错误率从 0.05% 升至 0.4%

【根因分析】
RDS Proxy 连接池配置过小（max=200），结合 14:30 触发的
batch job 大量并发写入造成连接饥饿。getUserOrders() 
等待连接平均 1.8s，导致请求堆积。

【火焰图】(Trace ID: 1-66...)
[投屏播放火焰图，明确指出 getUserOrders 等待 connection]

【证据链】
- 慢查询 #1: SELECT * FROM orders WHERE created_at > ... (耗时 2.3s, 14:31:08)
- 慢查询 #2: ...
- ConnectionPoolExhausted 日志片段 × 18 条
- 关联 commit: feat: batch job for order archive (deploy 03:00)

【修复建议】
┌────────────────────────────────────────┬──────┬─────────┐
│ 建议                                   │ 风险 │ 自动可执行│
├────────────────────────────────────────┼──────┼─────────┤
│ 扩容 RDS Proxy 连接池 200 → 400        │ 🟢 Low│ ✅       │
│ 给 orders 表加索引 (created_at, user_id)│ 🟡 Medium│ ❌ 需评审│
│ 重启 order-service Pod 清连接          │ 🟢 Low│ ✅       │
└────────────────────────────────────────┴──────┴─────────┘
```

### 3.5 演讲点

> "这是 **AI 诊断书 vs 传统 Dashboard 的关键差距**：
> Dashboard 告诉你 P99 涨了 → 你自己想为什么。
> 诊断书告诉你 P99 涨了 + **为什么** + **怎么办** + **风险等级** + **能不能自动**。
>
> 而且时间线、火焰图、证据链全部链回 X-Ray、CloudWatch Logs，**敢点的每个链接都能跳到原始数据**。"

---

## 4. 场景 3：执行修复（Confirm Token · 1 min）

### 4.1 演示动作

1. 在诊断书卡片上点 **[执行：扩容 RDS proxy 200→400]**

### 4.2 用户感知

**先弹风险确认卡片**：
```
⚠️  执行确认
─────────────
操作：扩容 RDS proxy 连接池 200 → 400
资源：rds-proxy-prod-orders
风险：🟢 Low
影响：无中断，1 秒内生效
撤销：可立即恢复

Token: ct-2026-05-17-abc (5 min 内有效)

[✓ 确认执行]   [✗ 取消]
```

2. 演讲者点 **[✓ 确认执行]**
3. ~3 秒后回复：

```
✅ 执行成功
─────────
• RDS proxy 连接池已扩容至 400
• 操作时间: 14:42:08
• AWS API: ModifyDBProxy
• 审计: audit-2026-05-17-...
• P99 已恢复到 195ms

[📄 后续观察 5 min]
```

### 4.3 演示越权拦截（重点环节，30 秒）

**这一步是体现"我们不是普通 chatbot"的关键演示**。

演讲者再发一条：
> 🎙 **"帮我扩容到 4000"**

系统拒绝（**演练好这个反应必须 < 5 秒返回**）：
```
🚫 操作被拦截
─────────────
原因：扩容上限超出 Policy 边界（max=500）
建议：超过限制需走变更评审流程
审计: audit-2026-05-17-...

[📋 申请变更评审]
```

### 4.4 演讲点

> "看，写操作护栏不是说说：
> **第一道**：Bedrock LLM 把意图先翻成结构化 action
> **第二道**：Policy Guard 软拦截（毫秒级）
> **第三道**：Confirm Token（5 分钟单次有效）
> **第四道**：Execution Lambda 独立 IAM Role + 资源 tag 边界
> **第五道**：审计日志（90 天）
>
> AWS DevOps Agent 自己只给建议，**真正写 AWS API 的是我们这层**。这是合规要求高的客户必备能力。"

---

## 5. 场景 4：经验复用（Skills · 1.5 min）

### 5.1 故事铺垫（讲台词）

> "刚才那次故障已经处理完，事件报告自动注册成 DevOps Agent 的 Custom Skill。
> 现在我们假设**3 周后**，类似故障再次发生。"

（演讲者切换到"3 周后"的模拟会话）

### 5.2 演示动作

> 🎙 **"上次 order-service 延迟是怎么解决的？"**

### 5.3 用户感知

| 时间 | 用户体验 |
|------|---------|
| ~3 s | 🔊 *"3 周前 5 月 17 日发生过同款故障，相似度 92%，当时通过扩容 RDS proxy 解决。要直接执行同样方案吗？"* |
| ~5 s | 📱 历史方案匹配卡片 |

**历史方案匹配卡片**：
```
🧠 历史方案匹配
─────────────
📌 案例 inc-2026-05-17-001
相似度: 92%
─────────────
📊 当时根因
RDS proxy 连接池耗尽

🛠️  当时处理方案
扩容连接池 200 → 400 + 重启 Pod

✅ 验证结果
P99 从 320ms 恢复至 195ms
─────────────
[⚡ 一键复用]  [🔍 走完整流程]
```

演讲者点 **[⚡ 一键复用]** → 直接进入场景 3 的确认流程，30 秒完成修复。

### 5.4 演讲点

> "**故障平均处理时间 30 min → 2 min。**
>
> 第一次发生：DevOps Agent 全调查 7 分钟。
> 第二次发生：Custom Skill 自动匹配 + 一键复用 30 秒。
>
> 这就是我们说的'经验闭环'。**团队的每一次故障处理都在让系统变聪明**，而不是知识沉淀在某个工程师的脑子里。"

### 5.5 ⚠️ 演练注意

第一次跑场景 3 后，要确认 Custom Skill **真的注册成功**。可在 AWS DevOps Agent Operator Portal 检查：
- 进入 Agent Space → Capabilities → Custom Skills
- 应看到名为 `nlops-incident-{incident_id}` 的 Skill
- 状态: Active

如果没注册成功，场景 4 就跑不通。**必须在 demo 前一天演练阶段确认**。

---

## 6. 场景 5：告警自动闭环（1.5 min）

### 6.1 故事铺垫

> "前面 4 个场景都是 SRE 主动问。最后这个场景是**SRE 什么都不做**，比如他在睡觉。"

### 6.2 演示动作

演讲者**手动触发** payment-service 的 5xx 错误率告警（演讲前预备的脚本）。

> 在终端执行：`./demo/inject-payment-failure.sh`

或者：
> 在 PPT 上播放预录的"告警 → 调查 → 推送" 30 秒视频（保险起见）

### 6.3 用户感知

约 **3-5 分钟后**（这次必须用 Plan B 剪辑或预录），SRE 群里弹出：

```
🚨 自动调查完成
─────────────────
告警: payment-service 5xx 飙升
调查: DevOps Agent (automatic, no human)
─────────────────
根因: 上游证书过期 (cert-mgr-* expired 2 min ago)
影响: 0.8% 支付请求失败
建议: 替换证书 (有 Skill 可复用，3 个月前同样故障)

[📄 完整诊断书]  [⚡ 一键修复]
```

**全程 SRE 没有任何操作 — 告警来 + 调查 + 推送 + 一键修复就绪。**

### 6.4 背后逻辑

```
1. CW alarm 触发
2. CW alarm → DevOps Agent (alarm 已配置 association)
3. DevOps Agent 自动 investigation (5 min)
4. 完成 → 发布事件到 EventBridge (source=aws.aidevops)
5. NLOps EventBridge Subscriber Lambda (L3) 触发
6. L3 拉调查详情 → 渲染 HTML → 推 IM 群组
```

### 6.5 演讲点

> "这就是真·智能闭环：
>
> **2 AM 告警响时，**SRE 醒来抓起手机，**完整诊断方案已经躺在 IM 里**。
> 一键修复，回去接着睡。MTTR 从 30 分钟降到 5 分钟。
>
> 这一段全程没有人工，是 **AWS DevOps Agent + EventBridge + NLOps** 三方协同自动跑出来的。"

---

## 7. 场景 6（可选高阶）：客户私有工具集成（1 min）

> 如果客户问 *"我们公司内部还有 CMDB / 工单系统，能不能集成？"* 才放这一段。
> 否则跳过，节省时间。

### 7.1 演示动作

切到 AWS 控制台 → DevOps Agent Operator Portal → 打开任意一个最近的 investigation，进**调查日志**界面。

### 7.2 用户感知

```
DevOps Agent 调查 inv-xyz · 步骤详情
────────────────────────────────────
✅ Step 1: 拉 CloudWatch metrics (built-in)
✅ Step 2: 拉 X-Ray traces (built-in)
✅ Step 3: 查 GitHub 最近 commit (built-in)
🆕 Step 4: 调用 NLOps MCP Server 查 CMDB
   → tool: get_service_owner
   → response: { team: "order-team", on-call: "alice@" }
🆕 Step 5: 调用 NLOps MCP Server 查 Jira
   → tool: get_recent_tickets(service="order-service")
   → response: [{ key: "OPS-123", title: "RDS proxy upgrade plan" }]
✅ Step 6: 关联到 owner team 的内部 runbook
✅ Step 7: 综合得出根因
```

### 7.3 演讲点

> "DevOps Agent 默认不知道你的 CMDB、Jira、内部 runbook 在哪。
>
> 我们做了什么？**NLOps 自身实现了一个 MCP Server**，把客户内部工具暴露给 DevOps Agent，DevOps Agent 调查时**当作自己的 tool 调用**。
>
> 这是一般 SaaS 工具做不到的客户深度定制 — 因为我们用的是 AWS 官方协议（Streamable HTTP + SigV4），是**正向集成**而不是反向爬数据。"

---

## 8. 收尾（30 秒）

> "刚才看到的，**今天全部都是真的**：
> - DevOps Agent 是 AWS 2026-03-31 GA 的服务
> - Nova Sonic 中文支持现已 GA
> - 我们这一层（NLOps）大概 1500 行代码 + CDK 部署
>
> **总成本**：50 用户 / 月 大约 $744（Enterprise Support）到 $1,930（无抵扣）
> **部署时间**：CDK 一键 ≤ 15 分钟
> **首批落地**：3-4 周完成 PoC
>
> 谢谢，问题环节。"

---

## 9. Q&A 弹药库（高频问题预备答案）

### Q1: "为什么不直接用 DevOps Agent？我们也是 AWS 客户。"

A: "好问题。直接用 DevOps Agent 你能拿到 70% 的能力，但少这 5 件：
1. **语音入口**：Nova Sonic，DevOps Agent 没有
2. **国内 IM**：我们直连企微 / 飞书，DevOps Agent 主流是 Slack / ServiceNow
3. **HTML 诊断书**：DevOps Agent 自己的 Operator Portal 是给工程师的，我们的诊断书是给团队/客户/管理层看的
4. **写操作护栏**：DevOps Agent 给建议，我们做 Confirm Token + 独立 IAM 的执行层
5. **客户私有工具**：通过 MCP Server 把您内部的 CMDB / Jira 暴露给 DevOps Agent

如果您只是给工程师内部用且只在 Slack 里，确实直接 DevOps Agent 就够了。如果您要给非技术干系人看、要在企微飞书里、要严格合规，就需要我们这一层。"

### Q2: "中国客户能用吗？"

A: "**不能**直接落地中国区。DevOps Agent / Bedrock / Nova Sonic 都没有中国区版本。

中国客户有 3 条路：
1. **数据出境**：通过专线 / VPN，把指标日志同步到 us-east-1，使用全球区 NLOps（合规需评估）
2. **降级版本（v3 路径）**：用 SageMaker 自建中文小模型 + Strands SDK，损失能力但满足合规
3. **等待**：等 AWS 中国区 GA，无明确时间表

我们诚实地把这写在了设计文档里，没在 PPT 上忽悠。"

### Q3: "DevOps Agent 调查要 5-15 分钟，太慢了。"

A: "这是 DevOps Agent 自身的 SLA，我们改不了。但有 3 种缓解：
1. **on-demand chat（5-30 秒）** 用于巡检 / 简单查询场景
2. **investigation（5-15 分钟）** 用于真正复杂的根因分析
3. **Custom Skills 命中** → 30 秒（场景 4 演示）

实际生产环境中，80% 是 on-demand chat 或 Skill 命中，**剩下 20% 才走完整 investigation**。所以平均下来不慢。"

### Q4: "成本能再低吗？$1,930 太贵。"

A: "三个方向降本：
1. **AWS Support 抵扣**：Enterprise Support 75% 抵扣 → ~$744；Unified Operations 100% 抵扣 → ~$370
2. **Bedrock 切 Nova**：Claude 3.5 Sonnet 换成 Nova Pro，Bedrock 费用 -60%
3. **限制 investigation 触发**：把 alarm 和 investigation 关联得更精准，减少误触发

**最低可到**：$370/月（50 用户，~$7.4/用户）— 当然前提是您是 Unified Operations 客户。"

### Q5: "你们和 Datadog / PagerDuty 比怎么样？"

A: "Datadog/PagerDuty 是观测+告警工具，不做 RCA、不做执行修复、不沉淀经验。我们做完整闭环。

具体差异（您可以看 PPT slide 14）：
- 语音交互、HTML 诊断书、写操作护栏、经验闭环、国内 IM —— 这 5 项他们都没有
- 价格：Datadog $44-118/host，我们 $15-39/user。
- **不是替代关系**，是补充：Datadog 做观测，我们做闭环。"

### Q6: "为什么 6 个 Agent？多吗？"

A: "**6 个是逻辑分层，物理上只有 4 个 Lambda**。
- Router / Discovery / Analysis / Knowledge / Report 5 个逻辑 Agent 在 Orchestrator 单 Lambda 内通过 Strands SDK 做 in-process Tool 调用，**没有跨 Lambda 跳转开销**
- 只有 Execution 因为写权限隔离需求，单独一个 Lambda
- 加上 EventBridge Subscriber 和 MCP Server，总共 4 个

6 这个数字是业务概念（让 PPT 更清晰），不是物理 Lambda 数量。"

### Q7: "Demo 里那个 5 分钟等待，真实环境也这样吗？"

A: "**真实的，DevOps Agent investigation 平均 8 分钟，准确率 94%。** 但这是 5xx 飙升、根因复杂的场景。

日常 80% 的查询是 on-demand chat（5-30 秒）或 Custom Skill 命中（< 5 秒）。所以**平均响应 15 秒以内**。Demo 演示的是最复杂场景，让大家看到 worst case 也是可控的。"

### Q8: "代码开源吗？"

A: "（按团队/公司政策回答）当前是**内部私有仓库**。如果客户付费 PoC，我们可以提供完整代码和部署支持。"

---

## 10. 演讲常见翻车 & 应对预案

| 翻车场景 | 触发条件 | 应对预案 |
|---|---|---|
| Nova Sonic 没识别出来 | 演讲场地嘈杂 / 演讲者口音 | **降级文字输入**：手机切换到键盘输入同样问题 |
| DevOps Agent 调查超时 | 网络问题 / DevOps Agent 抖动 | **切预录视频**：场景 2/5 都准备好预录视频 |
| 企微卡片渲染异常 | 企微 App 版本老 / webhook 延迟 | **切到飞书**：双 IM 各准备一份 |
| HTML 诊断书 URL 失效 | Presigned URL 过期 | **切到本地预渲染版**：硬盘里存一份 HTML 副本 |
| 网络断了 | 4G/Wifi 都不行 | **切纯 PPT 模式**：跳过 demo 直接讲架构图 |
| 观众打断问问题 | 客户太活跃 | **承诺 Q&A 环节回答**：不要中断 demo 节奏 |
| AWS 控制台需要 MFA | 切到 console 时被拦 | **提前登录并保持会话活跃** |

---

## 11. Demo 后续动作（演讲完成 ≤ 24 h）

- [ ] 整理客户的关键问题清单（哪几条 Q 没在弹药库里？）
- [ ] 把演讲录像剪辑成 3-5 分钟精华版（截掉等待环节）
- [ ] 把客户提到的需求转成 GitHub Issue
- [ ] 把演讲反馈写入 `docs/demo-retro-{date}.md`
- [ ] 如果客户感兴趣 → 启动 PoC，3 周交付
- [ ] 如果客户犹豫 → 发送跟进材料：本脚本 + PPT v2 + 设计文档

---

## 12. 附：演讲者背词卡（对折装口袋）

```
开场 30s：
"NLOps = AWS DevOps Agent + 语音 + 国内 IM + 写护栏"

场景 1 - 早晨巡检：
"一句话完成，不是 12 个 Dashboard"

场景 2 - 故障下钻：
"Dashboard 给数字，诊断书给医生写的报告"

场景 3 - 执行修复：
"五道护栏：意图→Policy→Token→IAM→审计"

场景 4 - 经验复用：
"30min → 2min，团队越用越聪明"

场景 5 - 告警自动闭环：
"2 AM 告警，方案在手机里等你"

场景 6 - 私有 MCP（可选）：
"DevOps Agent 加上你的 CMDB 和 Jira"

收尾：
"今天看到的全部都是真的。
 50 用户 ~$15-39/月。
 PoC 3-4 周交付。"
```

---

> 演讲愉快。**节奏 > 完美**：宁可跳过一个场景，不要冷场超过 5 秒。
