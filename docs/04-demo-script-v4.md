# NLOps v4 演示脚本

> 演示日期: 2026-06-02
> 演示者: 陈朋辉 / 西云数据 解决方案架构师
> 时长: 30 分钟（含 Q&A）

## 演示总体结构

| # | 内容 | 时长 | 形式 |
|---|------|------|------|
| 1 | 客户场景 + 痛点 | 3 min | PPT |
| 2 | 业界方案对比 | 2 min | PPT |
| 3 | NLOps v4 整体架构 | 4 min | PPT 架构图 |
| 4 | **Demo 1: Quick Desktop 智能诊断** | 5 min | 实时演示 + 视频 backup |
| 5 | **Demo 2: 告警自动闭环** | 4 min | 实时演示 + 视频 backup |
| 6 | **Demo 3: HTML 诊断书 + 经验沉淀** | 3 min | 实时演示 |
| 7 | 性能 / 成本 / 路线图 | 4 min | PPT |
| 8 | Q&A | 5 min | 互动 |

---

## Demo 1: Quick Desktop 智能诊断（5 分钟）

### 目标场景
> "用户在 Quick Desktop 用一句话发起诊断，NLOps 调用 DOA 完成全链路分析，给出 HTML 诊断书"

### 演示前置准备（演示前 5 分钟）

```bash
# 1. 确认 v4 Stack 健康
curl -sS https://0ij69qdk8c.execute-api.us-east-1.amazonaws.com/prod/mcp-quick \
  -X POST -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/list"}' | jq '.result.tools | length'
# 期望返回: 5

# 2. 确认 Quick Desktop 已重新握手（5 个工具可见）
# 3. 提前打开 DOA Operator Console 标签页
# 4. 提前打开 SES 邮箱 (penghuichen@nwcdcloud.cn)
```

### 演示脚本

**[00:00] 开场**
> "下面演示 Demo 1：用 Quick Desktop 一句话完成生产问题诊断。注意整个过程中我没有打开任何 AWS 控制台。"

**[00:30] Step 1 — 一句话发起诊断**

打开 Quick Desktop，输入：
```
demo-api 服务现在情况怎么样？最近 30 分钟有没有异常？
```

预期 Quick LLM 行为：
- 自动调用 `query_doa` 工具
- 提示词送到 DOA，5-15s 内返回

**[01:30] Step 2 — 启动深度调查**

接着输入：
```
不太对劲，帮我启动深度调查
```

预期：
- Quick LLM 调用 `start_investigation`
- 返回 `task_id` + Operator Console 链接

**话术要点**：
> "注意这里返回的速度——只用了 2 秒。因为 DOA Investigation 是异步的，5-15 分钟后完成，结果通过 EventBridge 自动推送给我们的诊断书生成器。我们不阻塞用户。"

**[02:30] Step 3 — 切到 Operator Console**

打开提前准备好的 DOA Operator Console 标签：
- 看到刚创建的 Investigation 进度条
- 展开 "Telemetry sources" — 显示 DOA 自动关联了 CW / Logs / X-Ray / GitHub

**话术要点**：
> "DOA 在背后做了什么？看右侧——它自动查询了 CloudWatch、CloudWatch Logs、X-Ray、GitHub。这就是 v4 比 v3 的最大升级：我们不再用 Strands SDK 自己写编排，DOA 原生就能做跨源关联分析。"

**[03:30] Step 4 — 调用 HTML 诊断书**

回到 Quick Desktop：
```
帮我把这次调查生成一份 HTML 诊断书发给我
```

预期：
- Quick LLM 调用 `get_html_report` 工具
- 返回 S3 Presigned URL（30 天有效）

点击 URL，浏览器打开诊断书：
- 顶部：标题 + 严重度 + Investigation ID
- 中部：根因摘要（中文）+ 时间线
- 底部：DOA Operator Portal 链接

**话术要点**：
> "这是我们 v4 的核心差异化之一 —— DOA 原生输出是文本，而我们生成图文并茂的 HTML 诊断书。URL 30 天有效，可以分享给老板、客户、团队。"

**[04:30] Step 5 — 收尾**

> "5 分钟之内，从一句话到诊断书，全程不需要打开 AWS 控制台。这就是 NLOps v4 给 SRE 团队带来的体验：自然语言驱动 + 智能闭环。"

### 翻车预案

| 问题 | 应对 |
|------|------|
| `query_doa` 超时（API GW 29s 硬限制） | 改用 `start_investigation`，说"DOA Chat 适合短问题，深度问题用 Investigation" |
| DOA Investigation 创建失败 | 切到 backup 视频；说 "AWS DOA 自身偶发抖动，下面用录制的视频继续" |
| Quick Desktop 未握手 | 现场 `cd mcp-bridge && npm install`，1-2 分钟可恢复 |
| HTML 诊断书 URL 打不开 | 切 backup 视频中预渲染的诊断书截图 |

---

## Demo 2: 告警自动闭环（4 分钟）

### 目标场景
> "凌晨告警触发，无人值守。DOA 自动调查 → 生成诊断书 → 邮件通知 SRE。"

### 演示前置准备

```bash
# 确保告警当前在 OK 状态（否则 set-alarm-state 不会触发新事件）
aws cloudwatch set-alarm-state \
  --alarm-name demo-api-high-cpu \
  --state-value OK --state-reason "demo reset" \
  --region us-east-1
```

### 演示脚本

**[00:00] 开场**
> "Demo 2 模拟凌晨告警。我现在按一个按钮触发 ALARM，然后我们看自动闭环。"

**[00:30] Step 1 — 触发告警**

```bash
aws cloudwatch set-alarm-state \
  --alarm-name demo-api-high-cpu \
  --state-value ALARM \
  --state-reason "[demo] CPU surge on demo-api EC2 i-0257069e2402a0fbc, sustained 95% utilization" \
  --region us-east-1
```

**话术**：
> "实际生产中这是 CW 自动判断，我们演示模拟手动触发。告警一旦进入 ALARM 状态，会发一条消息到 SNS，触发我们的 Lambda。"

**[01:00] Step 2 — 查看 Lambda 日志（实时）**

打开 CloudWatch Logs Insights，搜索 NLOpsV4Stack-OrchestratorFn 最近 1 分钟的日志：

```
fields @timestamp, @message
| filter @message like /webhook|investigation/
| sort @timestamp desc
| limit 5
```

应看到：
- `webhook.no_doa_url_creating_investigation_directly`（fallback 路径）
- 或 `webhook.forwarded`（如果 DOA Webhook 已配置）

**话术**：
> "Lambda 已经把告警转发给 DOA。这条 fallback 提示是因为我们演示账号还没配 DOA Webhook URL，正式部署是直接调 DOA Webhook 走 HMAC 签名验证。功能完全等价。"

**[01:30] Step 3 — 切到 DOA Operator Console**

刷新 Backlog Tasks 列表：
- 看到 `[ALARM] demo-api-high-cpu` 任务，状态 `IN_PROGRESS`

**话术**：
> "DOA 已经接收告警，正在自动调查。注意标题——它自动从告警名 demo-api-high-cpu 关联到了 demo-api 服务。"

**[02:00] Step 4 — 等待完成（演示中等不到 5-15 min，用预录视频展示）**

切到 backup 视频，展示：
- DOA Investigation 完成
- EventBridge 触发 NLOps Lambda
- HTML 诊断书生成 + S3 上传
- SES 邮件发送

**[03:00] Step 5 — 切到邮箱**

打开提前准备好的邮箱标签（penghuichen@nwcdcloud.cn）：
- 看到主题：`🚨 [HIGH] [ALARM] demo-api-high-cpu`
- 内容：根因摘要（中文）+ 诊断书链接 + Operator Portal 链接

**话术要点**：
> "凌晨告警，SRE 在睡觉。早上起来打开邮箱看到这封邮件 —— 不是冷冰冰的 'ALARM threshold breached'，而是 AI 写好的中文诊断报告，含修复建议。这就是 v4 的价值：值班体验从'被吵醒'变成'醒来时已知'。"

### 翻车预案

| 问题 | 应对 |
|------|------|
| Lambda 日志不及时（CW 索引延迟） | 等 30s 再刷新；或切预录视频 |
| DOA Investigation 5-15min 太久 | 演示中用预录视频展示完成状态 |
| SES 邮件没收到 | 检查垃圾邮件；或展示 Lambda log 中 `ses.send_email` 成功记录 |

---

## Demo 3: HTML 诊断书 + 经验沉淀（3 分钟）

### 目标场景
> "诊断书不只是图表，还能自动沉淀为团队 Skill。下次类似问题，DOA 直接复用。"

### 演示脚本

**[00:00] 展示一份完整的 HTML 诊断书**

打开 Demo 1 生成的诊断书 URL：
- 滚动展示：标题、根因、时间线、证据链、Operator Portal 链接
- 强调可分享、移动端友好、30 天有效

**[01:00] 展示 Skills 文件**

打开 GitHub repo 的 `skills/` 目录：
- `01-ecs-troubleshooting.md`
- `02-rds-connection-pool.md`
- `03-lambda-throttling.md`

打开任意一个，展示结构：
- 触发条件
- 调查步骤
- 常见根因（带百分比）
- 修复 Runbook 引用

**话术要点**：
> "DOA 的 Skills 是它的'经验记忆'。我们把团队的 Runbook 和故障经验封装成 Markdown，DOA 在调查时自动匹配。比如 ECS 服务延迟告警 → DOA 自动应用 Skill 01 → 按预设步骤检查 ECS、ALB、RDS、GitHub 部署。"

**[02:00] 自动经验沉淀（展示概念）**

> "更进一步：每次 Investigation 完成后，NLOps 可以让 Nova Pro 自动从结果生成新的 Skill 版本。下次类似问题 → DOA 匹配到这个 Skill → 秒级出方案。"
> 
> "这是我们规划的 Phase 4 能力，目前 Markdown 是手动维护，但已有 3 个开箱即用的 Skill。"

### 翻车预案

| 问题 | 应对 |
|------|------|
| 诊断书 URL 过期 | 重新调用 `get_html_report` 生成新 URL |
| GitHub 网络不通 | 切到本地代码仓库展示 |

---

## Q&A 准备

### 高频问题

**Q1: 这和 AWS 官方 DevOps Agent 有什么区别？**
> 我们是 DOA 的"驾驶舱"。DOA 是引擎（运维 AI），NLOps 提供：
> 1. **中国化体验层**: Quick Desktop / 企微 / 飞书入口（DOA 原生只支持 Slack）
> 2. **可视化诊断书**: HTML 图文报告（DOA 是文本输出）
> 3. **自动经验沉淀**: 每次故障自动生成 Skill（DOA 需手动）
> 4. **代码级修复**: 集成 Kiro 自动提 PR（DOA 只生成 Spec）

**Q2: 中国区能用吗？**
> DOA 当前不支持中国区。我们设计了降级路径：
> - 全球区: DOA 主路径
> - 中国区: CloudWatch Investigations 备选 + Bedrock KB（本地经验库）
> - 体验层一致：IM/Quick Desktop/HTML 诊断书都不变

**Q3: 数据安全吗？日志会不会出账户？**
> 不会。DOA 通过 IAM Role 反向访问客户账户的 CW/Logs/X-Ray，数据不离开客户 region。
> NLOps 自身全部在 us-east-1（或客户指定 region）部署，IAM 最小权限。
> SSM Runbook 走客户账户内 IAM，可审计。

**Q4: 月成本多少？**
> 50 用户场景 ~$455/月（净），约 $9/人。详细分解：
> - DOA: $1,200（Enterprise Support 抵扣 75% 后 $300）
> - Bedrock Nova Pro: $80
> - Lambda + API GW + S3 + DDB: $30
> - 其他: ~$45

**Q5: v3 vs v4 改了什么？为什么重做？**
> v3 自建了大量代理层（Strands Agent + 21 个 MCP 工具 + L2 写 Lambda）。v4 参考了 AWS 官方博客（End-to-End Agentic SRE, Telkomsel CELYNA）后做了减法：
> - Lambda 从 2 个减到 1 个
> - MCP 工具从 21 个减到 5 个
> - 代码从 ~3000 行降到 ~800 行
> - 用 DOA 原生 Skills 替代自建 Bedrock KB
> - 用 SSM Runbook 替代自建写 Lambda
> 减法的好处：维护成本降低、可信度提高（更多 AWS 原生）。

**Q6: 演示中 query_doa 偶尔超时是不是产品问题？**
> 不是。DOA Chat 5-30s 是正常范围，超过 API Gateway 29s 硬限制时会超时。生产场景我们用 `start_investigation`（异步），用户问完立刻得到 task_id，结果通过 EventBridge 推送，不阻塞。Demo 中演示这两种模式各有适用场景。

### 翻车专项 Q&A

**Q: 演示中 Investigation 卡在 IN_PROGRESS 一直不动？**
> "DOA 调查需要 5-15 分钟，演示时间不够。我们准备了预录视频展示完成态，效果完全一致。"

**Q: 为什么用 fallback 路径而不是 DOA Webhook？**
> "DOA Webhook 创建必须在 Operator Console 手动操作，演示账号还没做。功能上 fallback 路径（直接调 CreateBacklogTask）和 Webhook 路径完全等价，只是 Webhook 多了 HMAC 签名安全层。"

---

## Demo 录制清单（演示前要准备的视频文件）

| # | 文件 | 时长 | 内容 |
|---|------|------|------|
| 1 | `demo1-quick-desktop.mp4` | 5 min | Quick Desktop 完整对话流 |
| 2 | `demo2-alarm-loop.mp4` | 4 min | 告警 → DOA → 邮件完整闭环（含 5-15min 加速） |
| 3 | `demo3-html-skills.mp4` | 3 min | HTML 诊断书 + Skills 展示 |

录制规范：
- 屏幕分辨率: 1920×1080
- 音频: 静音（演示时讲解）
- 格式: MP4 H.264
- 后期: 加 1.5x 速度（DOA 等待部分）

---

## 检查清单（演示前 30 分钟）

- [ ] v4 Stack 健康（curl tools/list 返回 5）
- [ ] DOA Agent Space 在线
- [ ] test EC2 i-0257069e2402a0fbc 在 running 状态
- [ ] CW Alarm `demo-api-high-cpu` 在 OK 状态（避免误触发）
- [ ] SES 邮箱 penghuichen@nwcdcloud.cn 验证状态 = Success
- [ ] Quick Desktop 已重新握手，能看到 5 个工具
- [ ] 浏览器打开标签：DOA Operator Console / SES 邮箱 / GitHub repo / 备用诊断书 URL
- [ ] backup 视频已就位
- [ ] PPT 已切到 v6（含 v4 架构）
