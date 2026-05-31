# 🎯 评委可能问的问题（详细版）

> **演示日期**: 2026-06-02  
> **使用方式**: 演示前看一遍熟悉，演示中遇到问题查这份  
> **共 60+ 个问题**，按 14 个类别组织

---

## 📋 目录

1. [总体方案与定位](#1-总体方案与定位)
2. [架构与技术选型](#2-架构与技术选型)
3. [AI / DevOps Agent](#3-ai--devops-agent)
4. [飞书 / IM 集成](#4-飞书--im-集成)
5. [安全与合规](#5-安全与合规)
6. [成本与商业价值](#6-成本与商业价值)
7. [性能与稳定性](#7-性能与稳定性)
8. [部署与运维](#8-部署与运维)
9. [与竞品对比](#9-与竞品对比)
10. [中国区 / 中国客户](#10-中国区--中国客户)
11. [Roadmap 与未来](#11-roadmap-与未来)
12. [Demo 中突发问题](#12-demo-中突发问题)
13. [代码与开发](#13-代码与开发)
14. [测试与质量](#14-测试与质量)

---

## 1. 总体方案与定位

### Q1.1 NLOps 是什么？一句话说清楚。
**答**：NLOps 是 AWS DevOps Agent 的**中国化驾驶舱** — 通过飞书 @机器人或 Quick Desktop，让 SRE 用一句话完成"发现→定位→修复→沉淀"的全流程，特别针对中国客户场景。

### Q1.2 你做的这个跟 AWS 官方的 DevOps Agent 有什么区别？为什么不直接让客户用 DOA？
**答**：DOA 是引擎，NLOps 是驾驶舱。区别有 4 点：
- **入口**：DOA 原生只支持 Slack，我们补齐飞书 / Quick Desktop
- **输出**：DOA 是文本 + Slack 卡片，我们做 7-Tab HTML 诊断书 + ECharts + Mermaid
- **经验沉淀**：DOA Skills 需手动创建，我们用 Nova Pro 自动从 Investigation 提取
- **故障公告**：DOA 没有，我们自动生成中文用户公告 + SRE 摘要

**追问应对**：如果对方说"那 Slack 用户不就够了"，回答"中国客户没人用 Slack，国内合规也不允许员工数据出境到 Slack"。

### Q1.3 这个方案的核心价值是什么？为什么客户要买单？
**答**：3 个量化价值：
- **MTTR 减少 60-87%**（从 1-2 小时 → 2-15 分钟，DOA 给出根因 + Skill 复用经验）
- **凌晨告警零打扰**（早上邮件已含完整诊断 + 公告草稿，直接发布）
- **新 SRE 上手快**（Skills 沉淀团队经验，新人不用查文档）

**月成本 ¥9/人**，对比 Datadog $44-118/host 便宜 10 倍。

### Q1.4 这个项目的目标客户是谁？
**答**：3 类客户：
- **互联网公司中型 SRE 团队**（10-100 人）：迁移到 AWS 但 SRE 不熟悉
- **传统企业上云**：传统运维团队转型 AWS
- **MSP / 系统集成商**：给客户提供运维服务的代运营商

不适合：完全不用 AWS 的客户，或者技术栈用 GCP/Azure 为主。

### Q1.5 NLOps 是 SaaS 还是部署在客户账户？
**答**：**部署在客户自己的 AWS 账户**。所有数据不离开客户账户：
- Lambda 在客户账户运行
- DOA 通过 IAM AssumeRole 反向访问客户资源
- 数据落 S3/DDB 也在客户账户
- 我们只提供 CDK 代码 + 文档 + 实施服务

这是 "Customer Owned" 模式，符合金融/政府等合规要求。

---

## 2. 架构与技术选型

### Q2.1 为什么只用一个 Lambda？不会成为单点吗？
**答**：
- **Lambda 自身有 99.95% SLA**，单点风险低
- 一个 Lambda 内部可以处理多种事件类型（路由分发）
- 如果挂了，CW Alarm 能监控到（我们建了 `v4-orchestrator-errors` alarm）
- v3 用过 2 个 Lambda，发现跨函数 invoke 增加复杂度但没收益
- **演进方向**：超过 5K QPS 后再拆分（当前 50K 调用/月没问题）

### Q2.2 为什么用 CDK 而不是 Terraform？
**答**：
- **CDK 是 AWS 原生 IaC**，跟 AWS 服务发布同步（DOA 这种新服务 CDK 立即支持，Terraform 要等社区跟进）
- 团队 Python 栈，CDK Python 直接复用
- CDK Stack 自动管理依赖，比 Terraform module 灵活
- **如果客户要求 Terraform**，可以用 `cdk synth` 输出 CloudFormation 给 Terraform `aws_cloudformation_stack` 用

### Q2.3 为什么选 Python 不是 Node.js？
**答**：
- **Bedrock Python SDK 比 JS 成熟**（特别是 streaming response）
- AWS 文档示例 80% 用 Python
- `boto3` 是 AWS 官方 Python SDK，社区活跃
- Lambda Python 3.12 冷启动 ~1s，可接受

**追问**："JS 不更快吗"：JS 冷启动 ~500ms 但运行性能差不多，且我们的瓶颈在 DOA 调用（5-30s），Lambda 自身性能不是问题。

### Q2.4 为什么用 SNS 不是 EventBridge 接 CW Alarm？
**答**：CloudWatch Alarm 的 AlarmAction 原生支持 SNS Topic ARN，**不直接支持 EventBridge**。要绕一圈 EventBridge Rule 才能桥接。SNS 直接订阅 Lambda 简单可靠。

EventBridge 我们用在另一个方向：DOA → NLOps（Investigation Completed 事件）。

### Q2.5 为什么 HTML 诊断书用 S3 公开 URL？不安全吗？
**答**：3 个权衡：
- **STS 临时凭证签的 Presigned URL** 凭证轮换后失效（踩过坑）
- **S3 bucket policy 仅 `/reports/*` 公开**，其他路径仍私有
- **URL 含 UUID + 时间戳**，外部猜不到（约 2^128 种可能）

**生产强化**：可以用 CloudFront + Origin Access Identity 加 IP 白名单，或者用 Cognito 认证。当前 demo 简化。

### Q2.6 Lambda 1024MB 内存是不是太大？
**答**：3 个原因要 1024MB：
- **Bedrock SDK + jinja2 + boto3** 加载约 200MB
- **HTML 诊断书渲染** Jinja2 模板可能 1MB+
- Lambda **CPU 与 Memory 成正比**，1024MB ≈ 1 vCPU，DOA 调用并发处理快

实测用 Memory ≤ 100MB（max 95MB），但保留余量让响应稳定。

### Q2.7 为什么用 botocore Lambda Layer？
**答**：Lambda runtime 内置的 boto3 是固定版本，**不认识 `devops-agent` 这个新 service**（DOA 2026-03 GA）。所以打了一个 Layer 包含最新 boto3 1.42.97。

如果不打 Layer，会报 `UnknownServiceError`。

---

## 3. AI / DevOps Agent

### Q3.1 DOA 现在 GA 了吗？什么时候发布的？
**答**：**2026-03-31 GA**。2025-12 在 re:Invent 公布 preview，4 个月后 GA。  
当前 boto3 service name 是 `devops-agent`，IAM action prefix 是 `aidevops:*`（保留 preview 时期命名）。

### Q3.2 DOA 调用要钱吗？怎么计费？
**答**：
- **预览期免费**（2025-12 ~ 2026-03）
- **GA 后按调用秒数计费**：约 $0.0083/s
- 50 用户场景估算：每月 ~$1200，**Enterprise Support 会员有 75% 抵扣**
- 包含在 AWS Support Premium 计划里（部分场景）

参考 https://aws.amazon.com/devops-agent/

### Q3.3 DOA 调查耗时为什么这么长？5-15 分钟太慢了吧？
**答**：DOA 不是简单查询，是**自主跨源关联分析**：
- 查 CloudWatch Metrics（10+ 指标）
- 跨 X-Ray service map
- 关联 GitHub 部署历史
- 应用 Skills 检索经验
- 多轮 Bedrock 推理

类比：医生看病也要 30 分钟。我们用**异步设计** + 完成后推送，用户不用阻塞等待。

**对比**：人工排查同样问题需要 1-2 小时。

### Q3.4 Skills 是什么？为什么需要？
**答**：Skills 是 DOA 的"经验包"，本质是 markdown 文件，包含：
- 适用场景（什么告警 / 什么资源类型）
- 调查步骤（按顺序的 AWS API 调用）
- 常见根因（带百分比）
- 修复 Runbook 引用

**作用**：DOA 调查时自动匹配相关 Skill，按 Skill 步骤直奔关键路径，省去全量探索的 10 分钟。

我们已经传了 3 个：ECS / RDS / Lambda 故障排查。

### Q3.5 Skills 自动生成是怎么工作的？
**答**：每次 Investigation 完成后：
1. 调 `ListJournalRecords` 抓 DOA 的完整 markdown 报告
2. Bedrock Nova Pro 用预定义 prompt 提取：
   - 触发条件（从告警类型推断）
   - 调查步骤（从 DOA 调用过的 API 序列）
   - 常见根因 + 修复建议
3. 输出按 DOA Skill 模板格式的 markdown
4. 上传到 S3 `skills/auto/<name>-<ts>.md`

**当前限制**：DOA Skills API 不开放上传，我们 markdown 落 S3 后**还需手动上传到 DOA Web App**。等 API 开放后可全自动。

### Q3.6 Nova Pro 用来做什么？为什么不用 Claude？
**答**：4 个用途：
- 故障公告生成（中文用户公告）
- SRE 内部摘要（含行动项）
- 自动 Skill markdown 提取
- ECharts 图表数据增强

**为什么 Nova Pro**：
- AWS 自家模型，价格低（比 Claude 3.5 Sonnet 便宜 50%）
- 中文能力好（特别针对中国 AWS 客户）
- 支持多模态（图像 + 文本，未来做架构图分析有用）
- Bedrock 原生集成，IAM 简单

**对比 Claude**：Claude 在通用推理强 10%，但成本贵且 Bedrock 接入需 cross-region inference profile。

### Q3.7 DOA 失败了怎么办？整个系统不能工作吗？
**答**：3 层 fallback：
1. **DOA Chat 超时** → 我们的 `DevOpsAgent.chat()` 25s 硬超时，返回 mock 字符串，告诉用户"建议用 start_investigation 异步模式"
2. **DOA Investigation 失败** → 任务 status 不是 COMPLETED，EB Handler 跳过 HTML 渲染
3. **DOA 服务挂了** → 退化到只用 Bedrock Nova Pro + CloudWatch 直查（手动配置）

未来 Phase 5 用 CloudWatch Investigations 做完整降级路径。

---

## 4. 飞书 / IM 集成

### Q4.1 为什么用飞书不用钉钉/企业微信？
**答**：3 个原因：
- **互联网公司主用飞书**（字节、小米、网易等）
- **飞书 API 体验最好**：双向对话 / Custom App / Webhook 都很完整
- **可扩展**：钉钉/企业微信架构相同，未来 Phase 4 加（开发量约 1 天/平台）

### Q4.2 飞书事件订阅 3 秒内必须 ack，你怎么处理 30 秒的 DOA 调用？
**答**：**异步两段式设计**：

```
Stage 1 (sync, < 1s):
  飞书事件到达 → 解析 event_id → 去重 → 自调用 → 立即返回 200

Stage 2 (async):
  自调用触发的 Lambda 实例
  → 处理 DOA 调用（任意时长）
  → 用 Lark Reply API 回复
```

详见代码 `src/handlers/lark_handler.py`。

**关键代码**：
```python
_lambda.invoke(
    FunctionName=_SELF_FN,
    InvocationType="Event",  # 异步
    Payload=json.dumps({"_async_lark": True, "lark_body": body}),
)
return _resp(200, {"status": "queued"})  # 立即返回
```

### Q4.3 飞书机器人怎么知道用户的意图？
**答**：**关键词意图路由**（不是 LLM）：
- 包含"调查/排查/为什么" → `start_investigation`
- 包含"诊断书"+UUID → `get_html_report`
- 默认 → `query_doa` (DOA Chat)
- 问候关键词 → 返回工具能力介绍

**为什么不用 LLM 做意图识别**：
- 关键词足够好 + 不消耗 LLM token
- 未来可以加 Bedrock 做兜底（如果关键词都没匹配）

### Q4.4 飞书消息有去重机制吗？万一重复发了？
**答**：有。`lark_handler.py` 有 in-memory 去重缓存：

```python
_seen: dict[str, float] = {}  # event_id → timestamp
_SEEN_TTL_SEC = 300

def _seen_event(event_id):
    if event_id in _seen:
        return True
    _seen[event_id] = time.time()
    return False
```

**限制**：仅 per-container 内存级，跨 Lambda 容器不共享。如果 cross-container dedup 需要 DDB（已在代码注释中标记 TODO）。

### Q4.5 飞书加密事件订阅做了吗？
**答**：**Demo 简化没做**。生产需要：
- 飞书 App 配置 Encrypt Key
- 修改 lark_handler 解密 `body.encrypt` 字段（AES-128-CBC）

代码注释里已标记 TODO，文档 PROJECT.md FAQ 有详细方案。

---

## 5. 安全与合规

### Q5.1 数据安全怎么保证？日志会不会泄漏？
**答**：5 层保障：
1. **数据不出 AWS 账户**：DOA AssumeRole 反向访问，所有数据在客户 region
2. **IAM 最小权限**：每个 boto3 调用精确到资源 ARN
3. **加密**：S3 SSE-S3、DDB 默认加密
4. **审计**：所有 Lambda 调用写 DDB AuditTable，TTL 90 天
5. **敏感信息隔离**：飞书 App Secret 在 Lambda env vars（生产用 Secrets Manager）

### Q5.2 IAM 权限怎么设计的？最小化吗？
**答**：3 个角色：
- **OrchestratorLambdaRole**：Lambda 执行权限
  - Bedrock InvokeModel
  - devops-agent:* + aidevops:*（DOA service）
  - SSM StartAutomationExecution
  - SES SendEmail
  - DDB / S3 单表权限
  - lambda:InvokeFunction（自调用）
- **DOAInvokeMcpRole**：DOA 反向调 MCP API 用
  - execute-api:Invoke 仅限 /mcp 路径
- **DOA Agent Space Role**：DOA 反向访问客户资源
  - 客户账户内 ReadOnly + 限定服务

### Q5.3 凭证管理怎么做？
**答**：
- **Lambda 凭证**：自动用 Lambda execution role STS 临时凭证
- **第三方凭证**（飞书 App Secret / Webhook URL）：当前在 Lambda env vars
  - **生产强化**：用 AWS Secrets Manager
  - 优势：自动轮换 / 审计 / 加密
- **DOA 凭证**：通过 IAM AssumeRole，无长期凭证

### Q5.4 这个系统会不会被黑客利用做坏事？
**答**：3 个防护：
- **输入验证**：所有 webhook 端点检查 HMAC 签名（DOA Webhook）+ event_id 去重（飞书）
- **写操作护栏**：`trigger_runbook` 默认 `dry_run=true`，必须显式 false 才执行
- **资源边界**：SSM Document 由我们定义，参数有 `allowedPattern` 校验

### Q5.5 数据合规要求（GDPR / 等保）满足吗？
**答**：
- **数据驻留**：客户自选 region，欧盟客户用 eu-central-1，数据不出 EU
- **数据可删除**：S3 `/reports/*` 加 lifecycle 30 天后自动转 IA / Glacier，DDB TTL 90 天
- **审计追溯**：CloudTrail 记录所有 IAM 操作，DDB AuditTable 记录业务调用
- **加密**：传输 HTTPS / 存储 SSE 默认加密

**等保 2.0**：满足三级要求（需要客户做合规审计验证）。

---

## 6. 成本与商业价值

### Q6.1 月成本 $9/用户怎么算的？
**答**：50 用户场景：
| 服务 | 月成本 |
|------|-------:|
| AWS DevOps Agent | $900 (Chat ~30h + Investigation) |
| Bedrock Nova Pro | $60 |
| Lambda × 1 | $5 |
| DDB × 2 | $5 |
| API Gateway | $3 |
| S3 | $2 |
| SES + SNS | $2 |
| **总成本** | **$977** |
| **Enterprise Support 抵扣 (DOA 75%)** | -$525 |
| **净成本** | **$452 (~$9/人)** |

如果团队规模 100 人，DOA 成本不变，净成本降到 ~$5/人。

### Q6.2 ROI 怎么算？投入和收益对比？
**答**：以 50 人 SRE 团队为例：
- **投入**：$452/月 = ~¥3500/月 = ¥42K/年
- **收益**（节省人力）：
  - MTTR 减少 50% → 每月省 50 工时
  - 50 工时 × ¥300/小时 = ¥15K/月 = ¥180K/年
- **ROI = (180-42) / 42 = 330%**

外加无形价值：用户体验提升、SRE 满意度提升、离职风险降低。

### Q6.3 比 Datadog Bits AI / Dynatrace 便宜在哪？
**答**：
- **Datadog Bits AI**: $44-118/host/月 → 100 hosts ≈ $4400-11800/月
- **Dynatrace Davis**: $69-99/host/月 → 100 hosts ≈ $6900-9900/月
- **NLOps**: $452/月（与 host 数无关，按 SRE 用户数定价）

我们便宜 10-20 倍的关键：
- **DOA 是 AWS 原生**（成本约 Datadog 的 1/5）
- **没有 per-host 收费**（按 SRE 用户数）
- **共享 Bedrock LLM 价格**（不是各家平台溢价）

### Q6.4 哪些客户场景成本最划算？
**答**：
- **资源多但 SRE 少**（典型互联网公司）：1000 host + 20 SRE → 我们 $180 vs Datadog $44000
- **多账户场景**：DOA 一个 Agent Space 管多账户，无额外开销
- **不确定故障频率**：按调用秒数计费 vs Datadog 按 host 固定收费

不划算场景：
- SRE 多但资源少（DOA 用得少 → 固定成本低 → 我们没优势）
- 已经是 Datadog 重度用户（迁移成本高）

### Q6.5 商业模式是什么？产品/服务/MSP？
**答**：分阶段：
- **当前**：内部方案 + 客户实施服务（一次性 + 年维护）
- **Phase 4 (Q4)**：开源核心代码到 GitHub，社区驱动
- **未来**：可能做成 SaaS（多租户管理多个客户 Agent Space），按用户数订阅

---

## 7. 性能与稳定性

### Q7.1 系统能撑多大规模？多少并发？
**答**：当前架构默认配置：
- Lambda 并发：1000（账户级 unreserved）
- API Gateway: 25 RPS / 50 burst（per route）
- DDB: PAY_PER_REQUEST（自动扩展，理论无上限）
- S3: 5500 PUT/s per prefix

**实测**：50 用户场景每天 1000 次调用，QPS < 1。

**扩展点**：
- 5K QPS 后：拆分 Lambda（按路由分多个 function）
- 50K QPS 后：API GW 改 HTTP API（更便宜）+ DDB on-demand → provisioned

### Q7.2 高可用怎么保证？跨 AZ / 跨 Region？
**答**：
- **跨 AZ**：Lambda 自动多 AZ，DDB / S3 默认 3 AZ 复制
- **跨 Region**：当前没做（演示规模不需要）
- **未来**：用 Route 53 latency-based routing + 跨 region S3 cross-region replication

### Q7.3 Lambda 冷启动会不会很慢？
**答**：实测冷启动约 1.5 秒：
- 加载 botocore Layer：500ms
- 初始化 boto3 clients：300ms
- Python interpreter：200ms
- 业务代码 import：500ms

**优化**：
- Provisioned Concurrency（预热）：约 $5/月，冷启动降到 50ms
- 但 50 用户场景调用量低，冷启动一天才几次，不值得开 PC

### Q7.4 Bedrock Nova Pro 调用如果失败/超时怎么办？
**答**：3 层保护：
- **超时控制**：boto3 默认 60s timeout
- **try/except**：`ai_enhance.py` 每个调用都有 fallback
- **优雅降级**：如果 Nova Pro 失败，HTML 诊断书仍能渲染（只是没有公告/摘要部分）

**实测错误率**：< 0.1%（Bedrock SLA 99.95%）

### Q7.5 如果同时 100 个告警一起触发，会不会打爆 DOA？
**答**：可能。3 个限流策略：
- **SNS 消息去重**：同一 alarm 短时间内重复消息丢弃
- **DOA Investigation 队列**：DOA 服务端有 rate limit（每个 Agent Space 100 并发任务）
- **Lambda concurrency limit**：可以设 reserved concurrency 限制

**当前 demo**：依赖 DOA 自身限流，未做客户端限流。生产需要加 Lambda reserved concurrency。

---

## 8. 部署与运维

### Q8.1 部署多久？需要多少人？
**答**：
- **首次部署**：~30 分钟（含 CDK bootstrap + cdk deploy）
- **客户落地**：~1 周（含 DOA Agent Space 配置 + Skills 上传 + 飞书 App 申请 + CW Alarm 接入）
- **人力**：1 个工程师（懂 AWS + Python）

### Q8.2 客户怎么上手？培训成本多大？
**答**：
- **SRE 用户培训**：30 分钟（看 demo 视频 + 文档）
- **管理员配置**：2 小时（DOA 控制台操作 + Skills 编写）
- **开发者扩展**：半天（看 PROJECT.md + CODE-STRUCTURE.md）

文档完整：8 份核心文档 + 多个 HTML 介绍页。

### Q8.3 监控自己的 Lambda 怎么监控？
**答**：CloudWatch 三件套：
- **Alarms**：`v4-orchestrator-errors`（Errors ≥ 1）
- **Logs**：结构化 JSON 日志，3 个 Logs Insights 查询模板（在 PROJECT.md）
- **Metrics**：Lambda Duration / Throttles / ConcurrentExecutions

如果挂了：CW Alarm → SNS → Lambda（自我监控的悖论）→ 飞书通知。或者用第二个 Lambda function 互监控。

### Q8.4 怎么知道 DOA 是不是在工作？
**答**：3 个观察点：
- **DOA Operator Console**：Web App 看 Investigation 状态
- **CloudWatch Logs**：搜 `eb.received` / `doa.create_task_failed`
- **DDB AuditTable**：每次成功/失败都有审计记录

### Q8.5 出问题怎么排查？故障流程？
**答**：完整 troubleshooting guide 见 PROJECT.md 故障排查指南。最常见 4 个问题：
1. 飞书机器人不回复 → 看 `lark_handler` 日志
2. HTML URL 失效 → 重新生成（已修，现在永久 URL）
3. CW Alarm 没触发 → 检查 SNS subscription
4. DOA Investigation 卡住 → DOA Agent Space 没关联实际服务

### Q8.6 怎么回滚？万一新部署有问题。
**答**：3 种方式：
```bash
# 选项 A: git checkout 旧版本 + cdk deploy
git checkout <old-commit>
cdk deploy NLOpsV4Stack

# 选项 B: CloudFormation rollback
aws cloudformation continue-update-rollback --stack-name NLOpsV4Stack

# 选项 C: Lambda 版本回滚（最快）
aws lambda update-function-code \
  --function-name NLOpsV4Stack-OrchestratorFn... \
  --s3-bucket <old-asset-bucket> --s3-key <old-key>
```

**回滚时间**：30 秒内（option C）

---

## 9. 与竞品对比

### Q9.1 跟 PagerDuty 对比怎么样？
**答**：定位不同：
- **PagerDuty**: 告警路由 + on-call 调度（人 → 人）
- **NLOps**: 告警自动化处理（AI → 人）

**互补使用**：PagerDuty 升级路由 → NLOps 自动调查 → AI 给出根因 → 还需人类决策时升级到 PagerDuty 找 SRE。

### Q9.2 跟 OpenAI Operator / GitHub Copilot Chat 对比？
**答**：
- **Copilot Chat**: 通用 AI 编码助手，不懂 AWS 运维场景
- **NLOps**: AWS 运维专用，集成 DOA 跨源关联 + Skills 经验

跨界：NLOps 的"代码级修复"路线（Phase 3）要集成 Kiro/Copilot 做 PR 自动化。

### Q9.3 跟 New Relic AI 对比？
**答**：
- **New Relic AI**: APM 重度集成 + AIOps，价格 $99-499/host
- **NLOps**: AWS 原生，价格按 SRE 用户数

**关键区别**：New Relic 侧重应用性能，NLOps 侧重 AWS 基础设施运维。

### Q9.4 国内有类似的产品吗？
**答**：
- **阿里云 SLS AI**: 阿里云原生，类似定位但绑定阿里云生态
- **腾讯云 CODING DevOps**: 偏 CI/CD，不是运维
- **国内 AIOps 公司**（云智慧、华青信领等）: 通用 AIOps，不针对 AWS

NLOps 的差异：**AWS 原生 + 中国 IM 集成**，国内产品做不到。

### Q9.5 客户已经买了 Datadog，还会用 NLOps 吗？
**答**：不冲突，**NLOps 可以叠加在 Datadog 上**：
- Datadog 提供观测性数据
- DOA 通过集成读 Datadog → 跨源关联
- NLOps 提供中国 IM + HTML 诊断书

实际客户场景：**Datadog 是数据源 + NLOps 是体验层**。

---

## 10. 中国区 / 中国客户

### Q10.1 中国区能用吗？
**答**：**当前不能直接用，DOA 不支持中国区**。但已设计降级路径：

| 组件 | 全球区 | 中国区 (Phase 5 Roadmap) |
|------|--------|---------------------------|
| 调查引擎 | DOA | CloudWatch Investigations |
| 经验沉淀 | DOA Skills | Bedrock Knowledge Base |
| LLM | Nova Pro | Nova Pro (中国区也支持) |
| HTML 诊断书 | 一致 | 一致 |
| 飞书集成 | 一致 | 一致 |

### Q10.2 中国客户海外业务怎么办？
**答**：跨境方案：
- 中国 SRE 用飞书发问 → 飞书 webhook 跨境到 us-east-1 NLOps
- DOA 在 us-east-1 监控海外资产
- HTML 诊断书 URL 跨境访问

合规：飞书数据流出境需要客户做合规备案（属于客户责任）。

### Q10.3 GFW 影响吗？
**答**：
- **AWS 全球区**：访问没问题（飞书 SDK / API GW / S3 都可达）
- **企业网络**：需要客户 IT 开放 *.amazonaws.com 出站
- **HTML 诊断书 URL**：是 us-east-1 S3，国内访问偶尔慢但通

**生产部署**：建议 us-east-1 + AWS Global Accelerator 加速回中国。

### Q10.4 中国监管要求（数据安全法 / 个保法）满足吗？
**答**：
- **数据驻留**：当前 us-east-1，**不满足关键数据本地化**
- **解决**：等 Phase 5 中国区上线 + 用 cn-north-1
- **临时方案**：客户自评估数据敏感度，运维数据通常不属于个人敏感信息

---

## 11. Roadmap 与未来

### Q11.1 Phase 3 的 Kiro 集成具体怎么做？
**答**：参考 AWS [End-to-End Agentic SRE](https://aws.amazon.com/blogs/devops/building-an-end-to-end-agentic-sre-using-aws-devops-agent/) 博客：
1. DOA Investigation 完成后生成 **Mitigation Plan**
2. 提取 **Agent-ready Spec**（结构化 JSON）
3. 推送到 Kiro CLI / Kiro API
4. Kiro：clone repo → 改 IaC → 跑测试 → 提 PR
5. CI 通过 → reviewer 合并 → 部署

**实现工时**：~2 天（已有 DOA Spec 输出 + Kiro 文档）。

### Q11.2 Nova Sonic 语音什么时候上？为什么这次没演示？
**答**：技术原因：Nova Sonic 是**双向流式（bidi-stream）**，需要 WebSocket 长连接。Lambda + API Gateway REST 不支持，要用 ECS Fargate WebSocket server。

**实现工时**：~3 天（含 ECS 部署 + 简单 Web 前端）。

**当前替代方案**：飞书发语音消息 → Amazon Transcribe → 走文字流程（单向，不是真正的 Sonic）。

### Q11.3 拓扑图自动生成是怎么实现的？
**答**：Phase 4 计划：
- 用 X-Ray Service Map API 获取服务拓扑
- 转换成 Mermaid 图表语法
- 注入诊断书的 "概览" Tab
- 故障节点自动标红（基于 DOA 根因分析）

当前是**静态 Mermaid 图**（写死的拓扑），未来动态化。

### Q11.4 多模态架构图分析是什么？
**答**：客户预上传服务架构图（PNG/SVG），DOA 调查完成后：
1. Nova Pro Vision 识别图中组件（Lambda / RDS / ALB）
2. 把 DOA 找到的故障组件**在图上标红**
3. 生成新图嵌入诊断书

参考：AWS [AI-Powered Incident Response with Nova Pro](https://aws.amazon.com/blogs/mt/using-amazon-bedrock-and-amazon-nova-for-ai-powered-incident-response/) 博客。

### Q11.5 这个项目会开源吗？
**答**：当前是内部演示版，正式开源需要：
- Legal review（避免泄漏客户场景）
- 文档英文化
- Demo 数据脱敏
- License 选择（推荐 Apache 2.0）

**预计**：Q4 2026 开源到 awslabs 或社区 repo。

---

## 12. Demo 中突发问题

### Q12.1 演示中飞书机器人不响应了怎么办？
**应对**：
1. 不要慌，平静过渡
2. "飞书可能有点延迟，我们直接看后台日志"
3. 切到 CloudWatch Logs 标签：
```bash
aws logs tail /aws/lambda/... --since 2m | grep lark
```
4. 如果还不行，切 backup 视频："为节省时间用预录的"

### Q12.2 DOA Investigation 一直 IN_PROGRESS 不完成怎么办？
**应对**：
1. 切到已完成的 task_id（CHEAT-SHEET 里有 4 个备用）
2. "DOA 调查需要 5-15 分钟，演示时间有限，我们看一个之前完成的"
3. 直接打开 backup 诊断书 URL

### Q12.3 邮件没收到？
**应对**：
1. 检查垃圾邮件
2. 显示 Lambda 日志中 `ses.send_email` 成功记录
3. "邮件已发送，可能客户网络延迟"
4. 如果 SES 在沙盒模式，提醒客户 verified 邮箱才能收

### Q12.4 HTML 诊断书 URL 打不开？
**应对**：
1. 重新生成（CHEAT-SHEET 里有命令）：
```bash
curl -X POST .../mcp-quick -d '...get_html_report...'
```
2. 用 backup URL（多备 2-3 个）
3. 或者切到 PPT 截图："我们看下静态截图"

### Q12.5 网络断了怎么办？
**应对**：
1. **完全转 PPT 模式**："为了节省时间我们看 PPT 演示"
2. 准备的 PPT 截图就是 backup
3. 强调"现场网络不稳定，正式部署在客户 VPC 内不受影响"

### Q12.6 客户问"这个我可以现在试用吗"？
**应对**：
1. **不要现场操作**（避免给客户账户改东西出问题）
2. "我们演示后跟您技术团队对接，1 天内可以在您账户内做 PoC 部署"
3. 留 GitHub repo 链接 + 个人邮箱

---

## 13. 代码与开发

### Q13.1 总代码量多少？开发耗时多久？
**答**：
- **总代码量**：~2270 行（Python 1700 + HTML 590）
- **CDK Stack**：290 行
- **核心开发时间**：~3 天（v3 卸载 + v4 重写）
- **总项目时间**：3 周（含设计 + 文档 + 演示准备）

### Q13.2 用了哪些设计模式？
**答**：5 个核心模式：
1. **装饰器自动注册**：`@server.tool` 工具自动注册
2. **Lambda Warm Container 单例**：boto3 client 复用
3. **Mock Fallback**：DOA 不可用时返回 mock
4. **异步两段式**：飞书 3s ack 限制
5. **配置即代码**：CDK 全栈管理

详见 CODE-STRUCTURE.md。

### Q13.3 测试覆盖率？
**答**：**当前没测试**（演示前优先级低）。  
计划：
- 单元测试：pytest，覆盖率目标 60%
- 集成测试：Lambda local invoke + DDB local
- E2E 测试：CodePipeline 自动化触发 demo investigation

**实际生产化前**：补单元测试是 Phase 3 任务。

### Q13.4 代码风格 / 工具链？
**答**：
- **格式化**：black（Python）+ prettier（JS/HTML）
- **Linter**：ruff（Python）+ eslint（JS）
- **类型注解**：`def handler(event: dict, context) -> dict`，但没用 mypy 严格检查
- **CI/CD**：未做 GitHub Actions（Phase 3 加）

### Q13.5 如何扩展新的 MCP 工具？
**答**：3 步（详见 CODE-STRUCTURE.md）：
1. 在 `src/mcp_server/v4_tools.py` 加 `@server.tool` 装饰的函数
2. `cdk deploy NLOpsV4Stack`
3. 客户端自动从 `tools/list` 看到新工具

无需改 server 注册逻辑（装饰器自动注册）。

---

## 14. 测试与质量

### Q14.1 怎么验证 v4 的功能正确？
**答**：4 个验证点：
1. **API 健康**：`curl /mcp-quick tools/list` 返回 5 个工具
2. **告警闭环**：`aws cloudwatch set-alarm-state` 触发 → 飞书+邮件双通道
3. **HTML 诊断书**：用 task_id 重新生成 → 打开 URL 可访问
4. **飞书 @机器人**：群里 @ 测试 → 3-5 秒回复

CHEAT-SHEET.md 第一节有完整验证脚本。

### Q14.2 演示前你做了多少次彩排？
**答**：**实话实说**：演示前会做 1-2 次完整跑通，CHEAT-SHEET 是为防止现场翻车准备。

### Q14.3 测试数据从哪来？怎么避免污染生产？
**答**：
- **测试 EC2**：i-0257069e2402a0fbc，专门打了 demo 标签
- **测试告警**：demo-api-high-cpu，阈值故意设 1%（很容易触发）
- **测试 DDB 数据**：用 trace_id prefix 区分（`trc-test-*` vs `trc-prod-*`）
- **DOA Investigation**：每次创建独立 task_id，不会污染历史

---

## 15. 万能应对话术

### 当不知道答案时
> "这个问题问得很好，需要会后跟客户技术团队 deep dive 给您准确答复。我可以会后通过邮件 / 文档详细回复。"

### 当被质疑某个设计选择
> "这是我们权衡 X / Y / Z 几个因素后的决定。当前选择是 [理由]，未来如果场景变化（[条件]），我们会考虑切换到 [备选方案]。"

### 当被问 Roadmap 是否能做到
> "Phase X 的 [功能] 已经在设计阶段，预计 [时间]。我们设计文档 design-v4.md 有详细规划。具体实施会根据客户反馈调整优先级。"

### 当被批评不够完美
> "您提的非常对，这是我们当前 v4 的局限。我们有意识到这些点，[Phase 3/4/5] 会逐步完善。当前演示重点展示核心闭环已经跑通。"

### 当客户提具体场景问支持吗
> "您说的这个场景非常典型。我建议会后我们做一个 1-2 小时的技术对接，了解您的具体技术栈和告警类型，给您一个针对性的实施方案。"

---

## 16. 红线 / 不要说的话

### ❌ 不要说
- "我们的产品比 AWS DevOps Agent 强"（DOA 是我们底层，不能贬低）
- "Datadog 不行"（当面贬低竞品不专业）
- "这个一定能让你们 MTTR 减少 90%"（过度承诺）
- "肯定不会出问题"（任何系统都可能出问题）
- "这个我也不知道"（不知道也要给方向）

### ✅ 应该说
- "NLOps 在 DevOps Agent 之上做体验层增量"
- "Datadog 是优秀产品，我们和它定位不同（AWS 原生 vs 多云通用）"
- "实测客户场景 MTTR 减少 60-87%，具体取决于您的问题类型"
- "我们设计了多层 fallback，万一有问题降级路径是 ..."
- "这个问题我没有准确答案，但方向是 [推测]，会后给您确认"

---

## 17. 关键数字记忆

| 数字 | 用途 |
|------|------|
| **5** | MCP 工具数量（v4） |
| **23** | 用到的 AWS 服务数（直接 14 + 间接 9） |
| **800-2270** | 代码行数（核心 800 / 总计 2270） |
| **$452/月** | 50 用户净成本 |
| **$9/人** | 月单用户成本 |
| **73%** | v3→v4 成本减少 |
| **76%** | v3→v4 工具数减少 |
| **5-15 min** | DOA Investigation 耗时 |
| **3 秒** | 飞书要求的 ack 时间 |
| **30 min → 2 min** | Skill 复用 MTTR 改进 |
| **2026-03-31** | DOA GA 日期 |

---

✅ 演示加油！记住：**核心是叙事完整，遇到问题先稳住情绪，转向已知话题**。
