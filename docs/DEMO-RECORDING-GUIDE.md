# 🎬 NLOps v4 Demo 录制指南

> **演示日期**: 2026-06-02  
> **总录制时长**: 约 15 分钟（4 个 Demo）  
> **录制工具**: QuickTime (Mac) / OBS Studio (Win) / Snagit  
> **分辨率**: 1920×1080 · 30fps  
> **音频**: 麦克风开启（同步录音）

---

## 📋 总览

| Demo | 名称 | 时长 | 场景 | 关键演示点 |
|------|------|------|------|----------|
| **1** | 飞书 @机器人智能问诊 | 4-5 min | 主动 | 一句话调查 + AI 跨源关联 |
| **2** | 凌晨告警自动闭环 | 3-4 min | 被动 | 全自动 + 双通道通知 |
| **3** | HTML 诊断书走查 | 3 min | 展示 | 7-Tab + 故障公告复制 |
| **4** | 经验沉淀闭环 | 2-3 min | 演进 | Skill 自动生成 + 复用 |

---

## 🛠️ 录制前一次性准备

### 环境配置
```bash
# 1. 确保关闭所有通知（避免微信、Slack 等弹窗）
# 2. 关闭无关浏览器标签
# 3. 设置屏幕分辨率 1920×1080
# 4. 麦克风测试: 录 10 秒读"测试 1 2 3"
```

### 关键 URL 收藏
```
飞书 PC 客户端     - 直接打开
demo-api 主页      - http://3.89.49.81/
DOA Operator       - https://52e43342-bbe2-4fb7-aadd-c072410509ba.aidevops.global.app.aws/
SES 邮箱           - https://mail.nwcdcloud.cn (penghuichen@nwcdcloud.cn)
HTML 诊断书 (备用) - https://nlopsv4stack-reportbucket577f0fcd-xwmgrghecgja.s3.us-east-1.amazonaws.com/reports/diagnostic/[最新URL]
GitHub Repo        - https://github.com/penghui1234/nlops/tree/feat/v4-doa-native
```

### 备用 task_id（应急用）
```
推荐:    39a8dd51-3724-4e81-a190-4114d1593927  (AI 增强测试)
备用 1:  68fdf7d8-4c55-4cee-ad59-00fc3d48046b  (修复后验证)
备用 2:  92d519cc-7aeb-4384-93ad-21f833b8c927  (ECS 服务延迟)
备用 3:  1660387b-892f-4012-9e03-884c9b19fa71  (飞书闭环测试)
```

---

# 🎬 Demo 1: 飞书 @机器人智能问诊（主动场景）

> **时长**: 4-5 分钟  
> **核心**: SRE 一句话发起调查 → AI 自主跨源关联 → HTML 诊断书

## 录制前准备（5 分钟）

### Step 1.1 启动 CPU 压测（让 demo-api 真"慢"）
```bash
# 让 EC2 CPU 涨到 100%，持续 10 分钟
aws ssm send-command \
  --document-name AWS-RunShellScript \
  --instance-ids i-0257069e2402a0fbc \
  --parameters 'commands=["nohup sudo /usr/local/bin/demo-cpu-spike.sh 600 > /tmp/spike.log 2>&1 &"]' \
  --region us-east-1
```

### Step 1.2 等 1 分钟，验证 CPU 已上升
```bash
aws cloudwatch get-metric-statistics \
  --namespace AWS/EC2 \
  --metric-name CPUUtilization \
  --dimensions Name=InstanceId,Value=i-0257069e2402a0fbc \
  --start-time $(date -u -d '5 minutes ago' '+%Y-%m-%dT%H:%M:%S') \
  --end-time $(date -u '+%Y-%m-%dT%H:%M:%S') \
  --period 60 --statistics Average \
  --region us-east-1
```
**期望**: CPU > 30%

### Step 1.3 验证飞书机器人在线
飞书群发：`@NLOps 你好`  
**期望**: 3-5 秒收到能力介绍卡片

### Step 1.4 准备屏幕（4 个 Tab）
| Tab | 内容 |
|-----|------|
| 1 | 飞书 PC 客户端（NLOps 测试群） |
| 2 | Chrome - http://3.89.49.81/ |
| 3 | Chrome - DOA Operator Console |
| 4 | Chrome - HTML 诊断书 backup URL |

## 录制脚本

### 【0:00-0:30】开场
**画面**: 飞书群

> "下面演示 NLOps v4 第一个场景 —— 飞书 @机器人智能问诊。
> 
> 这是真实的 demo-api 服务（**切到 Tab 2** http://3.89.49.81/）—— 部署在 EC2 上的 Web 服务。**现在它的 CPU 飙到了 100%**。
> 
> 传统做法 SRE 要切到 CloudWatch 控制台逐项排查。我们看 NLOps 怎么做。"

### 【0:30-1:30】Step 1: 飞书发问 → 收到 ack
**画面**: 切回 Tab 1 飞书群

**输入**（慢慢打字让观众看清）:
```
@NLOps 帮我调查一下 demo-api 服务为什么变慢了
```

**等 3-5 秒**，机器人回复:
```
🔍 已启动深度调查
任务 ID: <new-task-id>
预计 5-15 分钟完成
```

> "看，机器人 3 秒内 ack。
> 
> 关键设计：飞书要求 webhook 3 秒内 ack，但 DOA 调查需要 5-15 分钟。我们用了**异步两段式** —— Lambda 收到事件立即返回 200，然后异步处理。"

### 【1:30-2:30】Step 2: 切到 DOA Operator 看后台
**画面**: 切到 Tab 3 DOA Operator Console

**操作**: 刷新 Investigations 列表，找到刚创建的任务

**指着 Telemetry sources**:
- ✅ CloudWatch Metrics
- ✅ CloudWatch Logs
- ✅ X-Ray Traces
- ✅ Skills 应用（ecs-troubleshooting）

> "DOA 自主决定调用这些数据源，跨源关联分析。这是 v4 的核心：我们不再像 v3 一样自建 Strands Agent 编排，DOA 原生就能做。
> 
> 完整调查需要 5-15 分钟。为节省演示时间，我直接打开一个之前完成的调查给大家看。"

### 【2:30-3:30】Step 3: 让机器人生成已完成调查的诊断书
**画面**: 切回 Tab 1 飞书群

**输入**:
```
@NLOps 帮我生成 task_id 39a8dd51-3724-4e81-a190-4114d1593927 的诊断书
```

机器人回复 HTML 诊断书 URL。**点击 URL** → 浏览器打开。

### 【3:30-4:30】Step 4: 演示 7-Tab HTML 诊断书

**逐 Tab 快速过（每 Tab 5-10 秒）**:

1. **📊 概览**
   > "ECharts CPU 趋势图（注意阈值线）、**Mermaid 拓扑图（Nova Pro 根据 DOA 实际调用的工具动态生成**）、DOA 用过的 AWS 工具标签"

2. **🔬 根因**
   > "AI 提取的核心结论 + SRE 内部摘要 + **经验已自动沉淀为 Skill**（v4 新增）"

3. **🤖 完整报告**
   > "DOA 自主调查产出的 markdown 完整报告"

4. **📣 通报**（**重点演示**）
   > "**这是 v4 杀手锏**：AI 自动生成的中文用户公告"
   
   **点 "复制故障公告" 按钮** → 弹出 alert
   
   > "一键复制，SRE 直接粘贴到状态页 / 微博 / 邮件群发，节省 15-30 分钟人工写公告。"

5-7. **简单提一下**（行动 / 证据 / 原始数据）

### 【4:30-5:00】总结

> "刚才 5 分钟里发生了什么？
> 1. SRE 一句话 → @NLOps
> 2. 机器人 3 秒 ack（异步两段式）
> 3. DOA 自主跨源关联
> 4. HTML 7-Tab 诊断书 + AI 增强（公告 + 摘要 + 自动 Skill）
> 5. **全程不打开 AWS 控制台**
> 
> 下面看 Demo 2：凌晨告警自动闭环。"

## 录制后清理
```bash
# 停止 CPU 压测
aws ssm send-command \
  --document-name AWS-RunShellScript \
  --instance-ids i-0257069e2402a0fbc \
  --parameters 'commands=["sudo pkill stress-ng || true"]' \
  --region us-east-1

# 重置告警
aws cloudwatch set-alarm-state \
  --alarm-name demo-api-high-cpu \
  --state-value OK --state-reason "demo 1 done" \
  --region us-east-1
```

---

# 🎬 Demo 2: 凌晨告警自动闭环（被动场景）

> **时长**: 3-4 分钟  
> **核心**: SRE 在睡觉时，AI 已经把活干完了

## 录制前准备（3 分钟）

### Step 2.1 重置告警状态
```bash
aws cloudwatch set-alarm-state \
  --alarm-name demo-api-high-cpu \
  --state-value OK --state-reason "demo 2 prep" \
  --region us-east-1
sleep 5
```

### Step 2.2 验证关键资源
```bash
# demo-api 在线
curl -sS -m 5 -o /dev/null -w "demo-api: HTTP %{http_code}\n" http://3.89.49.81/

# 飞书机器人在线（@NLOps 你好）
# SES 邮箱可访问
```

### Step 2.3 屏幕准备（4 个 Tab）
| Tab | 内容 |
|-----|------|
| 1 | **终端**（触发命令 + 看日志） |
| 2 | 飞书 PC 客户端（NLOps 测试群） |
| 3 | SES 邮箱（penghuichen@nwcdcloud.cn） |
| 4 | DOA Operator Console |

## 录制脚本

### 【0:00-0:30】开场 + 设置场景
**画面**: 飞书群（清空状态）+ 邮箱

> "下面是 Demo 2 —— 凌晨告警自动闭环。
> 
> 想象凌晨 2 点，demo-api 服务的 CPU 飙到 100%。SRE 在睡觉，没人看告警。
> 
> 传统做法 SRE 早上来才发现，故障已经持续 6 小时。
> 
> 我们看 NLOps 怎么处理 —— **注意，我接下来不会做任何操作，全程自动**。"

### 【0:30-1:00】Step 1: 触发告警
**画面**: 终端

```bash
aws cloudwatch set-alarm-state \
  --alarm-name demo-api-high-cpu \
  --state-value ALARM \
  --state-reason "[demo] CPU spike on demo-api EC2 i-0257069e2402a0fbc, 95% sustained" \
  --region us-east-1
```

执行后画面静止 5 秒：

> "我现在按下告警按钮 —— 这模拟 CPU 真的飙起来时 CloudWatch 自动触发的效果。
> 
> 现在告警已经触发。**从这一刻开始，全程没有人工干预**。"

### 【1:00-2:00】Step 2: 看 Lambda 日志
**画面**: 终端

```bash
aws logs tail /aws/lambda/NLOpsV4Stack-OrchestratorFn6F7CE538-8CQbnN8zYC4C \
  --follow --region us-east-1 | grep -E "webhook|investigation|eb\."
```

**期望**: 看到 `webhook.no_doa_url_creating_investigation_directly`

> "看 Lambda 日志：CW Alarm → SNS → 我们的 Lambda → DOA。Lambda 已经调用 DOA start_investigation，task_id 已经生成。"

### 【2:00-2:30】Step 3: 切到 DOA Operator
**画面**: Tab 4 DOA Operator Console

> "DOA 正在自主调查。**调查需要 5-15 分钟**。在生产环境，SRE 早上 7 点起床时，调查已经完成多次。
> 
> 演示时间有限，我们直接看一个之前完成的调查会发什么。"

### 【2:30-3:30】Step 4: 看到飞书 + 邮件到达（高潮）

**画面**: Tab 2 飞书群

如果飞书群里有之前测试的红色卡片，直接拉到那条：

> "看，飞书群里的红色卡片就是 NLOps 发的。包含：
> - 🚨 严重度徽章 [HIGH]
> - 服务名 demo-api
> - **Nova Pro 自动生成的中文根因摘要**
> - DOA 调用工具列表
> - 两个按钮：📊 查看完整诊断书 + 🔍 DOA Operator"

切到 Tab 3 邮箱：

> "同时邮箱也收到了 HTML 邮件 —— 跟飞书是双通道，确保 SRE 看到。"

**指着邮件中的故障公告草稿**:

> "这一段 —— Nova Pro 自动生成的故障公告草稿。SRE 早上起来不需要写公告，**直接复制粘贴到状态页就行**。"

### 【3:30-4:00】总结

> "凌晨 2 点告警 → 早上 SRE 起床看到：
> 1. 飞书群红色卡片（团队广播）
> 2. 邮箱完整诊断书（个人值班）
> 3. **故障公告草稿就绪**（直接发布）
> 4. 经验已自动沉淀为新 Skill
> 
> 整个过程**不需要任何人**。这就是 NLOps v4 给 SRE 团队的'值班解放'。
> 
> 下面是 Demo 3：HTML 诊断书走查。"

## 录制加速技巧（演示等不及 5-15 分钟时）

**手动触发 EB 事件，30 秒内看到飞书 + 邮件**:
```bash
aws lambda invoke \
  --function-name NLOpsV4Stack-OrchestratorFn6F7CE538-8CQbnN8zYC4C \
  --payload '{
    "source": "aws.devopsagent",
    "detail-type": "Investigation Completed",
    "detail": {
      "metadata": {
        "task_id": "39a8dd51-3724-4e81-a190-4114d1593927",
        "agent_space_id": "52e43342-bbe2-4fb7-aadd-c072410509ba",
        "execution_id": "exe-ops1-7ead971e-4e9a-46ed-ac66-7717c989c2f2"
      },
      "data": {"status": "COMPLETED", "priority": "HIGH"}
    }
  }' \
  --cli-binary-format raw-in-base64-out \
  /tmp/lambda-response.json --region us-east-1
```

执行后约 30 秒：
- 飞书群收到红色卡片
- 邮箱收到 HTML 邮件

## 录制后清理
```bash
aws cloudwatch set-alarm-state \
  --alarm-name demo-api-high-cpu \
  --state-value OK --state-reason "demo 2 done" \
  --region us-east-1
```

---

# 🎬 Demo 3: HTML 诊断书走查

> **时长**: 3 分钟  
> **核心**: 7-Tab 仪表盘式报告 + AI 增强能力展示

## 录制前准备（1 分钟）

### Step 3.1 准备一个完整的诊断书 URL
直接用之前生成的最新诊断书：
```bash
# 重新生成确保 URL 有效
URL=$(curl -sS -X POST https://0ij69qdk8c.execute-api.us-east-1.amazonaws.com/prod/mcp-quick \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"get_html_report","arguments":{"task_id":"39a8dd51-3724-4e81-a190-4114d1593927"}}}' \
  | python3 -c "
import sys, json, re
d = json.load(sys.stdin)
t = d.get('result', {}).get('content', [{}])[0].get('text', '')
m = re.search(r'\{.*\}', t, re.DOTALL)
if m: print(json.loads(m.group(0)).get('html_url', ''))")
echo "URL: $URL"
# 复制到剪贴板
echo "$URL" | xclip -selection clipboard 2>/dev/null || echo "$URL" | pbcopy 2>/dev/null
```

### Step 3.2 屏幕准备
| Tab | 内容 |
|-----|------|
| 1 | 浏览器 - HTML 诊断书 |
| 2 | GitHub Repo（备用展示 Skills 来源） |
| 3 | 邮箱（展示故障公告复制目标） |

## 录制脚本

### 【0:00-0:30】开场
**画面**: 浏览器打开诊断书 URL

> "Demo 3 是 HTML 诊断书走查。这是 v4 的核心差异化 —— **不是 Dashboard，是 AI 诊断书**。
> 
> 顶部 Hero 区：标题、严重度徽章、4 个 Quick Stats、4 个操作按钮。
> 
> 下面是 7 个 Tab，逐个看。"

### 【0:30-2:30】Step 1: 逐 Tab 演示

#### Tab 1: 📊 概览（30 秒）
> "**ECharts CPU 趋势图**（带告警阈值线）、**Mermaid 服务拓扑**（Nova Pro 根据 DOA 实际调用的工具动态生成）、**DOA 用过的 AWS 工具标签**。"

#### Tab 2: 🔬 根因（30 秒）
> "**核心根因**（一句话提炼）、**SRE 内部摘要**（含 3 条行动项）、**自动 Skill 沉淀**（v4 新增）。
> 
> 注意根因这一段 —— 这是 Nova Pro 从 DOA 完整报告里提取的核心结论，跟 DOA Operator Console 显示的内容一致。"

#### Tab 3: 🤖 完整报告（30 秒）
> "DOA 自主调查产出的完整 markdown 报告，含表格、列表、代码块。这是 ListJournalRecords API 抓出来的原始 AI 输出。"

**滚动几秒展示报告内容**

#### Tab 4: 📣 通报（**重点 30 秒**）
> "这是 v4 的杀手锏 —— AI 自动生成的中文用户公告。"

**滚动展示公告内容**:
> "200 字左右，专业、致歉、给出预计恢复时间。"

**点 "📋 复制故障公告" 按钮** → 弹出 alert "✅ 故障公告已复制到剪贴板"

> "一键复制。"

**切到 Tab 3 邮箱**，新建邮件，**Cmd+V 粘贴** → 公告内容出现

> "直接粘贴到状态页 / 微博 / 邮件群发。**节省 SRE 15-30 分钟手写公告的时间**。"

#### Tab 5: 🛠️ 行动（15 秒）
> "推荐的 SSM Runbook：nlops-ecs-scale、nlops-rds-proxy-expand。点 'DOA Operator' 按钮可以查看 DOA 自动生成的 Mitigation Plan。"

#### Tab 6: 📎 证据（15 秒）
> "Trace IDs + 日志片段。给开发者深入查的入口。"

#### Tab 7: 🗂️ 原始数据（5 秒）
> "finding 的 raw JSON，给开发者二次集成用。"

### 【2:30-3:00】总结

回到 Hero 顶部 + 操作按钮：

> "**HTML 诊断书的几个亮点：**
> - 🔗 URL 永久有效（S3 公开读，跟 STS 临时凭证无关）
> - 📱 手机/电脑双端友好（响应式设计）
> - 🖨️ 可一键打印为 PDF
> - 🔍 直接跳转 DOA Operator Console（深度运维用户）
> 
> 这就是把 DOA 的文本输出变成**图文并茂的诊断报告**的关键。
> 
> 下面是最后 Demo 4：经验沉淀闭环。"

---

# 🎬 Demo 4: 经验沉淀闭环

> **时长**: 2-3 分钟  
> **核心**: 第 1 次故障 → 自动生成 Skill → 第 N 次相似故障秒级匹配

## 录制前准备（1 分钟）

### Step 4.1 准备需要展示的内容

| 内容 | 来源 |
|------|------|
| HTML 诊断书的 "🧬 自动 Skill" 卡片 | `https://...html#root-cause` |
| GitHub Skills 文件夹 | https://github.com/penghui1234/nlops/tree/feat/v4-doa-native/skills |
| 自动生成的 Skill markdown URL | 从诊断书中点击查看 |

### Step 4.2 屏幕准备
| Tab | 内容 |
|-----|------|
| 1 | HTML 诊断书（在 Tab 2 根因页） |
| 2 | GitHub `skills/` 文件夹 |
| 3 | 飞书群（或 PPT） |

## 录制脚本

### 【0:00-0:30】开场
**画面**: HTML 诊断书 → Tab 2 "根因"

> "最后是 Demo 4 —— 经验沉淀闭环。这是 v4 v3 升级后的核心新增能力。
> 
> 先看现状 —— DOA 调查完成后，**经验默认是丢失的**。下次相似问题，DOA 还要从头查一遍。"

### 【0:30-1:30】Step 1: 展示自动 Skill 沉淀

**画面**: 诊断书的 "🧬 经验已自动沉淀为 Skill" 绿色卡片

> "看 v4 怎么做 —— 每次 Investigation 完成后，**Nova Pro 自动从 AI 报告里提取根因 + 调查步骤 + 修复建议**，生成一份新的 Skill markdown，上传到 S3。"

**点击卡片中的 "查看 →" 链接** → 浏览器打开 markdown

> "这是自动生成的 Skill 内容："

**滚动展示**:
- 触发条件
- 调查步骤
- 常见根因
- 修复 Runbook 引用

> "**完全符合 DOA Skill 模板格式**，可以直接上传到 DOA Web App。"

### 【1:30-2:00】Step 2: 对比手工 Skill

**切到 Tab 2 GitHub** → 打开 `skills/01-ecs-troubleshooting.md`

> "对比看 —— 这是我们演示前**手工编写**的 3 个 Skill 之一。
> 
> 自动生成的 Skill 跟手工写的**结构完全一致**，可以直接互换。"

### 【2:00-2:30】Step 3: 复用效果对比

**切到 Tab 3 PPT 或终端**

```
第 1 次故障 (无经验)         第 N 次相似故障 (经验匹配)
    ↓ MTTR ~ 15 min                ↓ MTTR ~ 2-3 min
    ↓ DOA 全量探索                  ↓ DOA 应用历史 Skill
    ↓ 自动生成 Skill                ↓ 跳过通用探索阶段
    ↓ 同步到 DOA                    ↓
                          减少 80-87%
```

> "MTTR 从 **15 分钟降到 2-3 分钟**，减少 80-87%。
> 
> 这就是经验沉淀的价值 —— **每次故障处理完，团队的 AWS 运维经验自动增长一点**。
> 
> 知识不再依赖个人，而是沉淀在系统里。新 SRE 加入团队，第一天就能用上历史经验。"

### 【2:30-3:00】总结全部 4 个 Demo

> "总结 4 个 Demo：
> 
> 1. **Demo 1 主动问诊** —— SRE 一句话调查
> 2. **Demo 2 凌晨闭环** —— 全自动，不用人
> 3. **Demo 3 诊断书** —— 7-Tab + AI 公告
> 4. **Demo 4 经验沉淀** —— Skill 自动生成 + 复用
> 
> NLOps v4 = DevOps Agent 的**中国化驾驶舱** + **AI 增强体验** + **自动经验沉淀**。
> 
> 谢谢大家，欢迎提问。"

---

# 🎬 后期处理（4 个视频通用）

## 剪辑要点

1. **剪掉等待时间** - 等机器人回复的 5-15 秒可以快进 2-3x
2. **加字幕** - 关键话术用大字幕（"3 秒 ack" / "Nova Pro 自动生成" / "MTTR 减少 87%"）
3. **节奏控制** - DOA 调查那段 5-15 分钟肯定要剪掉，用 "5-15 分钟后..." 字幕过渡
4. **黑屏过渡** - 每个 Demo 之间黑屏 1 秒，加 "Demo X 完" 字样
5. **音频** - 后期可以降噪 / 拉响麦克风

## 推荐工具
- **Mac**: iMovie / Final Cut Pro / Screenflow
- **Win**: Camtasia / DaVinci Resolve（免费）
- **跨平台**: Davinci Resolve / Kdenlive

---

# ⚠️ 录制中通用翻车应对

## 问题 1: 飞书机器人不回复
**应对步骤**:
1. 等 30 秒（飞书可能延迟）
2. 查 Lambda 日志: `aws logs tail .../OrchestratorFn... --since 2m | grep lark`
3. 如果看到 `lark.replied`，说明发出去了，飞书显示延迟，等等就行
4. 如果没看到，**停止录制**，调试后重录

## 问题 2: DOA Investigation 卡在 IN_PROGRESS
**应对**:
- 切到 backup task_id 演示
- 或用方案 B 手动触发 EB 事件
- 不要在录制中等 5-15 分钟

## 问题 3: HTML 诊断书 URL 失效
**应对**:
- 重新生成（脚本在 CHEAT-SHEET.md）
- 用 backup task_id（4 个备选）

## 问题 4: 邮件没收到 / 进了垃圾箱
**应对**:
- 提前打开收件箱 + 垃圾箱两个 Tab
- 演示前发一封测试邮件确保通道畅通

## 问题 5: 网络断了
**应对**:
- **完全转 PPT 模式** + 截图 backup
- 强调 "现场网络不稳定，演示用预录"

## 问题 6: AWS 控制台卡 / 弹窗
**应对**:
- **永远不打开 AWS 控制台**！全程用我们自己的界面
- 如果必须打开，准备好截图 backup

---

# 📋 录制完检查清单

## 4 个视频通用检查
- [ ] 时长符合（Demo 1: 4-5min, Demo 2: 3-4min, Demo 3: 3min, Demo 4: 2-3min）
- [ ] 麦克风声音正常（无杂音、音量足）
- [ ] 没有出现 AWS 控制台
- [ ] 没有出现密码 / Token / 敏感信息
- [ ] 字幕无错别字
- [ ] 黑屏过渡干净

## Demo 1 专项
- [ ] CPU 压测启动（让 demo-api 真"慢"）
- [ ] 飞书对话清晰
- [ ] DOA Operator 截图清晰
- [ ] 7 个 Tab 都演示了
- [ ] "复制公告"按钮有点击演示

## Demo 2 专项
- [ ] 触发命令清晰（终端字够大）
- [ ] Lambda 日志展示
- [ ] 飞书红色卡片到达
- [ ] 邮件到达 + 故障公告草稿可见

## Demo 3 专项
- [ ] 7 Tab 逐个演示
- [ ] 操作按钮（特别是复制公告）演示
- [ ] Mermaid 拓扑图渲染正常
- [ ] ECharts 图表可见

## Demo 4 专项
- [ ] 自动 Skill markdown 内容展示
- [ ] 与手写 Skill 对比
- [ ] MTTR 改进数字醒目（87% 减少）

---

# 🎯 录制顺序建议

**推荐顺序**: Demo 3 → Demo 4 → Demo 1 → Demo 2

**理由**:
1. **Demo 3 最稳**：纯展示已生成的 HTML，无外部依赖
2. **Demo 4 次稳**：基于 Demo 3 的诊断书展开
3. **Demo 1 中等**：依赖飞书 + DOA 创建任务
4. **Demo 2 最不稳**：依赖完整 SNS → DOA → EB 链路

按稳定性递减录制，**前 2 个录完心理压力小**，后 2 个出问题也不影响整体。

---

# 📚 关联资源

- [CHEAT-SHEET.md](./CHEAT-SHEET.md) - 演示当天救命包
- [DEMO-SCRIPT.md](./DEMO-SCRIPT.md) - 30 分钟演示话术
- [JUDGE-QA.md](./JUDGE-QA.md) - 60+ 评委问题预案
- [PROJECT.md](./PROJECT.md) - 工程师手册

---

✅ **现在去录吧**！每录完一个 Demo 检查一遍清单，发现问题尽早重录。

如果遇到不能解决的问题，把具体错误信息告诉我。
