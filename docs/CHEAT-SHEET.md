# 🚨 NLOps v4 演示当天 Cheat Sheet

> **演示日期**: 2026-06-02 周二  
> **打印此页或开在屏幕一角**

---

## 🔗 关键 URL（演示用）

| 用途 | URL |
|------|-----|
| API Gateway | `https://0ij69qdk8c.execute-api.us-east-1.amazonaws.com/prod/` |
| HTML 介绍页 (客户分享) | `https://nlopsv4stack-reportbucket577f0fcd-xwmgrghecgja.s3.us-east-1.amazonaws.com/reports/v6-overview.html` |
| DOA Web App | `https://52e43342-bbe2-4fb7-aadd-c072410509ba.aidevops.global.app.aws/` |
| Lambda (CloudWatch 日志) | `aws logs tail /aws/lambda/NLOpsV4Stack-OrchestratorFn... --follow` |
| GitHub Repo | `https://github.com/penghui1234/nlops/tree/feat/v4-doa-native` |

## 📋 演示前 5 分钟检查清单

```bash
# 1. 验证 API 健康（返回 5 个工具数）
curl -sS -X POST https://0ij69qdk8c.execute-api.us-east-1.amazonaws.com/prod/mcp-quick \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/list"}' | jq '.result.tools | length'
# 期望: 5

# 2. 重置告警状态（避免误触发）
aws cloudwatch set-alarm-state \
  --alarm-name demo-api-high-cpu \
  --state-value OK --state-reason "demo prep" \
  --region us-east-1

# 3. 验证 SES 邮箱
aws ses get-identity-verification-attributes \
  --identities penghuichen@nwcdcloud.cn --region us-east-1

# 4. 验证 DOA Agent Space 在线
aws devops-agent get-agent-space \
  --agent-space-id 52e43342-bbe2-4fb7-aadd-c072410509ba \
  --region us-east-1
```

## 🌐 浏览器要打开的标签

1. **PPT v7** (本机打开)
2. **HTML 介绍页** - 演示开场用
3. **DOA Web App** - https://52e43342-...aidevops.global.app.aws/
4. **SES 邮箱** - penghuichen@nwcdcloud.cn
5. **飞书** - 机器人测试群
6. **GitHub repo** - 备用 Skills/代码展示
7. **诊断书 backup URL** (已生成的几个,翻车时直接用):
   - `https://nlopsv4stack-reportbucket577f0fcd-xwmgrghecgja.s3.us-east-1.amazonaws.com/reports/diagnostic/1780154028/39a8dd51-3724-4e81-a190-4114d1593927.html`

## 📝 已完成的 task_id 库（演示备用）

```
68fdf7d8-4c55-4cee-ad59-00fc3d48046b  - 修复后验证 (推荐用)
92d519cc-7aeb-4384-93ad-21f833b8c927  - ECS 服务响应延迟告警
39a8dd51-3724-4e81-a190-4114d1593927  - AI 增强测试 (含完整数据)
1660387b-892f-4012-9e03-884c9b19fa71  - 飞书闭环测试
```

---

## 🎬 Demo 1: 飞书 @机器人智能问诊

### 演示话术
> "我现在用飞书来演示。我们的 SRE 在群里 @ 这个机器人,机器人会调用 AWS DevOps Agent 自动调查问题。"

### 操作
1. 在飞书群发：`@NLOps 帮我调查一下 demo-api 服务为什么慢`
2. 等 3-5 秒，机器人回复 task_id
3. 切到 DOA Web App，看 Investigation 状态

### 翻车应对
- **机器人不响应** → 切换 backup 视频 / 用 curl 直接演示 MCP API
- **Investigation 卡住** → 用现成 task_id `39a8dd51-...`,说"为节省时间,这是上次完成的调查"

---

## 🎬 Demo 2: 凌晨告警自动闭环

### 演示话术
> "假设凌晨 2 点 demo-api 高 CPU,SRE 在睡觉。我现在按一下这个按钮触发告警,看完整闭环。"

### 操作
```bash
# 触发告警
aws cloudwatch set-alarm-state \
  --alarm-name demo-api-high-cpu \
  --state-value ALARM \
  --state-reason "[demo] CPU spike on demo-api" \
  --region us-east-1

# 看 Lambda 日志（实时）
aws logs tail /aws/lambda/NLOpsV4Stack-OrchestratorFn6F7CE538-8CQbnN8zYC4C \
  --follow --region us-east-1

# 切到飞书群和邮箱等通知
```

### 翻车应对
- **Lambda 没响应** → 检查 SNS subscription:`aws sns list-subscriptions-by-topic --topic-arn arn:aws:sns:us-east-1:828414850215:NLOpsV4Stack-AlarmTopic...`
- **DOA 5-15min 太久** → 用预录视频 / 切到 backup task_id

---

## 🎬 Demo 3: HTML 诊断书走查

### 演示话术
> "我们的诊断书不是 Dashboard,是 AI 报告。点开看 7 个 Tab。"

### 操作
1. 直接打开 backup 诊断书 URL（有完整内容的）
2. 演示 7 个 Tab 切换：概览 → 根因 → 报告 → 通报 → 行动 → 证据 → 原始数据
3. 重点展示：
   - "📋 复制故障公告" 按钮（弹出 alert，打开邮箱粘贴）
   - "🔍 打开 DOA Operator" 按钮（跳转 DOA Web App）
   - ECharts 趋势图
   - Mermaid 服务拓扑
   - AI markdown 报告

### 翻车应对
- **URL 失效** → 用其他 backup URL（多备几个）
- **Tab 不切换** → 刷新页面 / 改用浏览器 F5

---

## 🎬 Demo 4: 经验沉淀

### 演示话术
> "每次调查完成后,系统自动生成一个 Skill。下次相似问题秒级匹配。"

### 操作
1. 在诊断书页面找"🧬 经验已自动沉淀为 Skill"卡片
2. 点 Skill markdown 链接，展示 markdown 文件内容
3. 切到 GitHub 展示 `skills/01~03-*.md` 手工编写的 3 个 Skills
4. 切到 DOA Web App Skills 页面展示已上传的 Skills

### 翻车应对
- **自动 Skill URL 失效** → 用 GitHub 上的 markdown 替代

---

## 🛡️ 应急工具箱

### 重新生成诊断书 URL（如果 backup 失效）
```bash
curl -sS -X POST https://0ij69qdk8c.execute-api.us-east-1.amazonaws.com/prod/mcp-quick \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"get_html_report","arguments":{"task_id":"39a8dd51-3724-4e81-a190-4114d1593927"}}}' \
  | python3 -c "import sys,json,re;d=json.load(sys.stdin);t=d.get('result',{}).get('content',[{}])[0].get('text','');m=re.search(r'\{.*\}',t,re.DOTALL);print(json.loads(m.group(0)).get('html_url','')) if m else None"
```

### 直接发飞书测试卡片
```bash
curl -sS -X POST https://0ij69qdk8c.execute-api.us-east-1.amazonaws.com/prod/mcp-quick \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"notify_im","arguments":{"channel":"lark","subject":"测试","body":"演示中","html_url":"https://example.com"}}}'
```

### 触发新 Investigation
```bash
curl -sS -X POST https://0ij69qdk8c.execute-api.us-east-1.amazonaws.com/prod/mcp-quick \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"start_investigation","arguments":{"title":"演示触发","description":"...","priority":"HIGH"}}}'
```

---

## ❓ Q&A 常见问题（10 题）

### Q1: 这个跟 AWS 官方 DevOps Agent 有什么区别?
> NLOps 是 DOA 的中国化驾驶舱。DOA 是引擎(运维 AI),我们补:
> - 飞书入口 (DOA 原生只支持 Slack)
> - HTML 诊断书 (DOA 是文本输出)
> - 经验自动沉淀 (DOA 需手动)
> - 故障公告自动化 (DOA 没有)

### Q2: 中国区能用吗?
> DOA 当前不支持中国区。我们设计了 Phase 5 降级路径:用 CloudWatch Investigations + Bedrock KB。体验层(飞书/HTML)保持一致。

### Q3: 数据安全吗? 日志会出客户账户吗?
> 不会。DOA 通过 IAM Role 反向访问客户账户的 CW/Logs/X-Ray,数据不离开客户 region。NLOps 部署在客户自己的 us-east-1。

### Q4: 月成本 ¥9/人 怎么算的?
> 50 人团队场景:DOA $900 + Nova Pro $60 + 其他 $17 = $977/月。Enterprise Support 抵扣 75% 后 $452/月,折合 ~$9/人/月。

### Q5: 演示中 query_doa 偶尔超时是产品问题吗?
> 不是。DOA Chat 是 5-30s 同步调用,API GW 29s 硬限制偶尔超时。生产场景用异步 start_investigation 不阻塞。

### Q6: v3 vs v4 改了什么? 为什么重做?
> v3 自建大量代理层(Strands + 21 工具 + L2 写 Lambda)。v4 减法:Lambda 2→1,工具 21→5,代码 -25%,成本 -73%。让 DOA 做擅长的事,我们做 DOA 不擅长的。

### Q7: 飞书机器人的实现复杂吗?
> 自建 App 中等复杂度。关键点:Lark 要求 3s 内 ack,所以我们用了"异步两段式":Lambda 收到事件立即返回 200,然后用 lambda.invoke 自调用做实际处理。

### Q8: SSM Runbook 怎么扩展?
> 在 ssm-runbooks/ 加 yaml,CDK 自动加载。任何 ECS/RDS/EC2 操作都可以做成 Runbook,默认 dry_run。

### Q9: HTML 诊断书 URL 怎么保证不失效?
> S3 bucket policy 配置 /reports/* 公开读,直接用虚拟主机式 URL,永久有效。安全权衡:URL 含 UUID + 时间戳外部猜不到。

### Q10: 这个能扩展到其他云吗?
> 可以。DOA 本身支持 multi-cloud + on-prem。NLOps 的 5 个 MCP 工具是协议层抽象,后端可以接入 Azure Monitor / GCP Logging。

---

## 🔧 演示后清理（可选）

```bash
# 重置 alarm 到 OK
aws cloudwatch set-alarm-state \
  --alarm-name demo-api-high-cpu \
  --state-value OK --state-reason "demo end" \
  --region us-east-1

# 不要 cdk destroy! Stack 保留供后续演示
```

---

## 📞 应急联系

如果演示当天有不可恢复的问题：
- 切换到 backup 视频 + PPT 截图，叙事不变
- 强调"这是早期 PoC，本次演示部分场景用预录"
- 把焦点转到设计文档（design-v4.md）和 Roadmap

**核心原则**：宁可承认是预录，也不要让客户看到 ERROR 页面。

---

✅ 检查完毕,演示加油!🚀
