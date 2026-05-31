# NLOps v4 代码结构详解

> 给开发者/Code reviewer 的代码导览  
> 版本：v4.0 · 最后更新 2026-05-31  
> 总代码量：~2270 行（vs v3 ~3000 行，-25%）

---

## 📂 目录树（含每个文件的核心职责）

```
nlops/
│
├── README.md                              # GitHub 首页
├── requirements.txt                        # Python 运行时依赖（boto3, jinja2）
├── .gitignore
│
├── docs/                                   # 📚 文档
│   ├── design-v4.md                        # 设计文档（架构 + 决策）
│   ├── PROJECT.md                          # 工程师手册
│   ├── CODE-STRUCTURE.md                   # 本文件
│   ├── 04-demo-script-v4.md                # Demo 演示脚本
│   ├── CHEAT-SHEET.md                      # 演示当天救命包
│   ├── DEMO-SCRIPT.md                      # 逐字演示话术
│   ├── v6-overview.html                    # 客户介绍 HTML
│   ├── architecture-figure1.html           # AWS 官方风格架构图
│   └── deployment-diagram.html             # 部署架构图
│
├── infra/                                  # 🏗️ CDK v2 (Python)
│   ├── app.py                              # CDK app entry (3 行)
│   ├── nlops_v4_stack.py                   # Stack 定义 (290 行)
│   └── cdk.json                            # CDK 配置
│
├── src/                                    # 🐍 Lambda 源码 (Python 3.12)
│   ├── __init__.py
│   │
│   ├── handlers/                           # 入口路由
│   │   ├── __init__.py
│   │   ├── api_handler.py                  # 主路由 (430 行) ⭐
│   │   └── lark_handler.py                 # 飞书事件处理 (210 行)
│   │
│   ├── tools/                              # 业务适配器
│   │   ├── __init__.py
│   │   ├── devops_agent.py                 # DOA boto3 client (190 行)
│   │   ├── lark_app.py                     # 飞书 Custom App (140 行)
│   │   ├── lark_bot.py                     # 飞书 Custom Robot (135 行)
│   │   ├── ssm_runbook.py                  # SSM Automation (90 行)
│   │   └── ai_enhance.py                   # Nova Pro 增强 (260 行)
│   │
│   ├── mcp_server/                         # MCP 协议层
│   │   ├── __init__.py
│   │   ├── server.py                       # JSON-RPC 服务器 (200 行)
│   │   └── v4_tools.py                     # 5 个 MCP 工具 (270 行) ⭐
│   │
│   ├── report/                             # HTML 诊断书
│   │   ├── __init__.py
│   │   ├── generator.py                    # Jinja2 + S3 (130 行)
│   │   └── templates/
│   │       └── analysis.html               # 7-Tab 模板 (590 行) ⭐
│   │
│   └── common/                             # 通用工具
│       ├── __init__.py
│       ├── audit.py                        # DDB 审计日志 (50 行)
│       └── logging_utils.py                # 结构化日志 (50 行)
│
├── ssm-runbooks/                           # 🛠️ SSM Automation YAML
│   ├── ecs-scale.yaml                      # ECS service 扩容
│   └── rds-proxy-expand.yaml               # RDS Proxy 连接池扩容
│
├── skills/                                 # 🧬 DOA Skills
│   ├── 01-ecs-troubleshooting.md           # ECS 故障排查指南
│   ├── 02-rds-connection-pool.md           # RDS 连接池处理
│   ├── 03-lambda-throttling.md             # Lambda 限流修复
│   └── zip/                                # 打包好的 zip (DOA 上传格式)
│       ├── ecs-troubleshooting.zip
│       ├── rds-connection-pool.zip
│       └── lambda-throttling.zip
│
├── mcp-bridge/                             # 🌉 Quick Desktop bridge
│   ├── index.js                            # stdio MCP server (90 行)
│   └── package.json
│
└── assets/                                 # 🎨 演示资料
    ├── AB：自然语言驱动的 AI 运维平台-v6.pptx
    └── AB：自然语言驱动的 AI 运维平台-v7.pptx     # 23 页 PPT
```

---

## 🎯 核心模块详解（按调用频次）

### 1. `src/handlers/api_handler.py` — Lambda 主入口 ⭐

**职责**：单一 Lambda 的所有事件入口，根据 event 形态路由到不同 handler。

**关键函数**：
```python
def handler(event, context):
    """Single entry. Routes by event shape."""
    # 1. 自调用异步 Lark
    if event.get("_async_lark") is True:
        return lark_handler.handler(event, context)

    # 2. EventBridge from DOA
    if event.get("source") in ("aws.devopsagent", "aws.aidevops"):
        return _handle_doa_event(event)

    # 3. SNS event (CW Alarm)
    if "Records" in event and event["Records"][0].get("Sns"):
        return _handle_alarm_webhook(event)

    # 4. API Gateway proxy event
    path = event.get("path", "").lower()
    if path.startswith("/mcp"):
        return _handle_mcp(event)
    if "/lark-event" in path:
        return lark_handler.handler(event, context)
    if "/webhook-incoming" in path:
        return _handle_alarm_webhook(event)
    if "/chat" in path:
        return _handle_chat(event)
```

**4 个核心 handler**：

| Handler | 输入 | 输出 |
|---------|------|------|
| `_handle_chat` | API GW POST /chat | DOA Chat 直传响应 |
| `_handle_mcp` | API GW POST /mcp* | JSON-RPC 工具调用结果 |
| `_handle_alarm_webhook` | SNS 或 HTTP webhook | DOA Investigation 启动 |
| `_handle_doa_event` | EventBridge | HTML 报告生成 + 飞书+邮件推送 |

**关键设计**：
- 全局共享对象（warm container 复用）：`_doa`, `_report`, `_lark`, `_ses`
- 每个 handler 独立 try/except，单点失败不影响其他路由

---

### 2. `src/handlers/lark_handler.py` — 飞书事件处理

**职责**：处理飞书 Custom App 的事件订阅 webhook。

**关键设计：异步两段式**

飞书要求 3 秒内 ack，但 DOA 调用需要 5-30 秒。所以分两阶段：

```python
def handler(event, context):
    # Stage 2: 自调用的异步处理
    if event.get("_async_lark") is True:
        return _process_async(event)

    # Stage 1: 同步快速 ack
    body = parse_body(event)
    
    # URL verification (初次配置)
    if body.get("type") == "url_verification":
        return {"statusCode": 200, "body": json.dumps({"challenge": body["challenge"]})}
    
    # 去重（Lark 重发保护）
    if _seen_event(body["header"]["event_id"]):
        return _resp(200, {"status": "duplicate"})
    
    # 异步触发自调用
    _lambda.invoke(
        FunctionName=_SELF_FN,
        InvocationType="Event",  # 异步,不阻塞
        Payload=json.dumps({"_async_lark": True, "lark_body": body}),
    )
    
    return _resp(200, {"status": "queued"})  # < 1s 返回
```

**意图路由**（`_process_question`）：
- 关键词 `你好/help` → 返回工具能力介绍
- 含 task_id + `诊断书` → 调 `get_html_report`
- 含 `调查/排查/为什么` → 调 `start_investigation`
- 默认 → `query_doa`（DOA Chat，带 fallback）

---

### 3. `src/mcp_server/v4_tools.py` — 5 个 MCP 工具 ⭐

**职责**：实现 NLOps 暴露给所有 MCP 客户端的 5 个工具。

**注册机制**（自动）：
```python
from mcp_server.server import McpServer
server = McpServer()  # singleton

@server.tool   # 装饰器自动注册到 server._tools
def query_doa(question: str) -> dict:
    """Ask AWS DevOps Agent a one-shot question (5-30s)."""
    answer = _get_doa().chat(question, user_id="nlops-mcp")
    return {"question": question, "answer": answer, ...}
```

**5 个工具**：

| 工具 | 调用栈 |
|------|--------|
| `query_doa` | → `DevOpsAgent.chat()` → boto3 `create_chat` + `send_message` |
| `start_investigation` | → `DevOpsAgent.start_investigation()` → boto3 `create_backlog_task` |
| `get_html_report` | → `DevOpsAgent.get_investigation()` + `ListJournalRecords` → `ReportGenerator.render_and_upload()` |
| `trigger_runbook` | → `SSMRunbook.execute()` → boto3 `start_automation_execution` |
| `notify_im` | → `LarkBot.send_card()` 或 SES `send_email` |

**关键工具：`get_html_report`**

这个工具是 v4 的差异化核心：
1. 拉 DOA Investigation 的元数据 (`get_backlog_task`)
2. 拉 AI 完整报告 (`list_journal_records`) → 抓 markdown 文本
3. 调 `ai_enhance` 模块生成公告 / 摘要 / 自动 Skill / ECharts 数据
4. Jinja2 渲染 7-Tab 模板
5. S3 上传 → 永久公开 URL

---

### 4. `src/tools/devops_agent.py` — DOA 适配器

**职责**：封装 boto3 `devops-agent` service，支持 mock fallback。

**关键方法**：
- `chat(prompt)` — 5-30s 同步调用，超时返回 mock
- `start_investigation(title, desc, priority)` — 异步，立即返回 task_id
- `get_investigation(task_id)` — 拉元数据
- `get_investigation_findings(execution_id)` — **拉 AI 完整报告**（关键！）

**重要发现**：DOA 的 AI 输出在 `list_journal_records` API（不在 `get_backlog_task`）。这是踩坑后才找到的。

```python
def get_investigation_findings(self, execution_id):
    resp = self._client.list_journal_records(
        agentSpaceId=self.agent_space_id,
        executionId=execution_id,
    )
    text_chunks = []
    tool_uses = []
    for rec in resp.get("records", []):
        content = json.loads(rec.get("content", "{}"))
        # assistant text → AI 报告
        if content.get("role") == "assistant":
            for c in content.get("content", []):
                if "text" in c:
                    text_chunks.append(c["text"])
        # utilization → DOA 用过的 AWS 工具
        for tool in content.get("data", {}).get("tools", []):
            tool_uses.append(tool.get("name"))
    return {
        "report_md": "\n\n".join(text_chunks),
        "tool_uses": list(set(tool_uses)),
    }
```

---

### 5. `src/tools/ai_enhance.py` — Nova Pro 增强

**职责**：用 Bedrock Nova Pro 做 4 件事：
1. 故障公告生成（中文用户公告）
2. SRE 内部摘要（含行动项）
3. 自动 Skill markdown（提取经验）
4. ECharts 指标图（CW GetMetricData → option dict）

**统一 invoke 函数**：
```python
def _invoke_nova(prompt: str, max_tokens: int = 800) -> str:
    resp = _bedrock.invoke_model(
        modelId="amazon.nova-pro-v1:0",
        body=json.dumps({
            "messages": [{"role": "user", "content": [{"text": prompt}]}],
            "inferenceConfig": {"maxTokens": max_tokens, "temperature": 0.3},
        }),
    )
    body = json.loads(resp["body"].read())
    return body["output"]["message"]["content"][0]["text"]
```

各功能用不同 prompt 模板，输出长度 200-1500 字符。

---

### 6. `src/tools/lark_app.py` + `lark_bot.py` — 飞书双栈

**`lark_app.py` (Custom App)**：
- 用于 @机器人双向对话
- `get_access_token()` 缓存 tenant_access_token（2h TTL）
- `reply_message(message_id, text|card)` 用 Reply API 回复原消息
- `send_message(chat_id, text|card)` 主动发消息

**`lark_bot.py` (Custom Robot Webhook)**：
- 用于群消息推送（告警闭环）
- `send_card(title, body_md, template, url_buttons, metadata)` 发交互式卡片
- 支持 5 种颜色模板（red / orange / yellow / blue / green）
- 不需要 Auth，仅用 Webhook URL

---

### 7. `src/report/templates/analysis.html` — 7-Tab 诊断书 ⭐

**职责**：HTML 诊断书模板，用 Jinja2 渲染。

**结构**：
```html
<head>
  <!-- CDN: ECharts + marked.js + mermaid -->
</head>
<body>
  <!-- 1. Hero (severity badge + metadata) -->
  <!-- 2. Quick Stats Bar (4 stat boxes) -->
  <!-- 3. Action Buttons (4 个按钮) -->
  <!-- 4. Tabs (7 个标签) -->
  <div class="tab-content active" id="tab-overview">
    <!-- ECharts metrics + Mermaid topology + 工具标签 + 时间线 -->
  </div>
  <div class="tab-content" id="tab-root-cause">...</div>
  <div class="tab-content" id="tab-report">...</div>
  <div class="tab-content" id="tab-comm">...</div>
  <div class="tab-content" id="tab-action">...</div>
  <div class="tab-content" id="tab-evidence">...</div>
  <div class="tab-content" id="tab-raw">...</div>
  
  <script>{% autoescape false %}
    /* Tab switching, marked.js render, ECharts init, Mermaid init,
       copy buttons */
  {% endautoescape %}</script>
</body>
```

**关键技术点**：
- `{% autoescape false %}` 包裹 `<script>` —— 否则 Jinja2 会把 `""` 转义成 `&#34;` 破坏 JS 语法（踩坑修复）
- `tojson | safe` filter 让 markdown 内容安全嵌入 JS
- ECharts / marked.js / mermaid 全部 CDN 加载，无需打包

---

### 8. `infra/nlops_v4_stack.py` — CDK Stack

**职责**：用 AWS CDK Python 部署所有资源。

**资源清单**：

```python
class NLOpsV4Stack(Stack):
    def __init__(self, ...):
        # 1. Storage
        report_bucket = s3.Bucket(...)        # /reports/* 公开读
        sessions_table = ddb.Table(...)        # PK: session_id
        audit_table = ddb.Table(...)           # PK: trace_id, SK: ts
        
        # 2. Notifications
        alarm_topic = sns.Topic(...)
        
        # 3. Lambda Layer (botocore + jinja2)
        botocore_layer = lambda_.LayerVersion(
            code=lambda_.Code.from_asset("/tmp/botocore-layer.zip"),
        )
        
        # 4. Orchestrator Lambda
        orchestrator_fn = lambda_.Function(
            runtime=PYTHON_3_12,
            memory=1024, timeout=120,
            environment={..., DOA_AGENT_SPACE_ID, LARK_APP_ID, ...},
            layers=[botocore_layer],
        )
        
        # 5. SNS → Lambda subscription
        alarm_topic.add_subscription(LambdaSubscription(orchestrator_fn))
        
        # 6. API Gateway 7 routes
        api = apigw.LambdaRestApi(handler=orchestrator_fn)
        # /chat /webhook-incoming /lark-event (NoAuth)
        # /mcp (IAM auth, 给 DOA 用)
        # /mcp-quick /sse /message (NoAuth, 给 Quick Desktop)
        
        # 7. EventBridge Rule
        events.Rule(
            event_pattern=events.EventPattern(
                source=["aws.devopsagent"],
                detail_type=["Investigation Completed", ...],
            ),
            targets=[LambdaFunction(orchestrator_fn)],
        )
        
        # 8. DOA Invoke Role (DOA 反向调 MCP API)
        doa_invoke_role = iam.Role(
            assumed_by=ServicePrincipal("aidevops.amazonaws.com"),
        )
        
        # 9. SSM Documents (从 yaml 加载)
        for rb_name, rb_file in [...]:
            content_dict = yaml.safe_load(rb_path.read_text())
            ssm.CfnDocument(name=rb_name, content=content_dict, ...)
```

**部署完成后输出 (CFN Outputs)**：`ApiUrl`, `ChatUrl`, `WebhookUrl`, `McpUrl`, `McpQuickUrl`, `AlarmTopicArn`, `DOAInvokeRoleArn`, `ReportBucketName`, `OrchestratorFnArn`

---

## 🔗 模块依赖关系

```
api_handler.py ─┬─ mcp_server/v4_tools.py ──┬─ tools/devops_agent.py
                │                              ├─ tools/ssm_runbook.py
                │                              ├─ tools/lark_bot.py
                │                              └─ tools/ai_enhance.py
                ├─ handlers/lark_handler.py ─┬─ tools/lark_app.py
                │                              └─ tools/devops_agent.py
                ├─ tools/devops_agent.py
                ├─ tools/lark_bot.py
                ├─ tools/ai_enhance.py ────── (调 Bedrock Nova Pro)
                ├─ report/generator.py ────── (Jinja2 + S3)
                └─ common/audit.py ─────────── (DDB write)
```

**关键调用入口**：
- 飞书 @机器人 → `api_handler.handler` → `lark_handler.handler` → `_process_question` → DOA / 工具
- API GW MCP 调用 → `api_handler.handler` → `_handle_mcp` → `MCP_SERVER.handle` → `v4_tools.<tool>`
- CW Alarm → SNS → `api_handler.handler` → `_handle_alarm_webhook` → `DevOpsAgent.start_investigation`
- DOA EB 完成 → `api_handler.handler` → `_handle_doa_event` → 解析 + AI 增强 + Jinja2 + 飞书+邮件

---

## 📊 代码量统计

| 模块 | 行数 | 职责 |
|------|-----:|------|
| handlers/api_handler.py | ~430 | 主路由 + EB Handler |
| handlers/lark_handler.py | ~210 | 飞书事件异步处理 |
| mcp_server/v4_tools.py | ~270 | 5 个 MCP 工具实现 |
| mcp_server/server.py | ~200 | JSON-RPC 服务器 |
| tools/ai_enhance.py | ~260 | Nova Pro 增强 |
| tools/devops_agent.py | ~190 | DOA boto3 client |
| tools/lark_app.py | ~140 | 飞书 Custom App |
| tools/lark_bot.py | ~135 | 飞书 Custom Robot |
| tools/ssm_runbook.py | ~90 | SSM Automation |
| report/generator.py | ~130 | Jinja2 + S3 上传 |
| report/templates/analysis.html | ~590 | 7-Tab 模板（含 CSS+JS） |
| common/audit.py | ~50 | DDB 审计 |
| common/logging_utils.py | ~50 | JSON 结构化日志 |
| infra/nlops_v4_stack.py | ~290 | CDK Stack |
| ssm-runbooks/*.yaml | ~100 | SSM 自动化文档 |
| skills/*.md | ~400 | DOA Skills 内容 |
| **合计** | **~2270 行** | |

vs v3 ~3000 行，**减少 25%**。

---

## 🎨 设计模式

### 1. 装饰器自动注册（MCP 工具）
```python
@server.tool
def my_tool(arg1: str) -> dict:
    """Tool description."""
    ...
```
`@server.tool` 装饰器自动：
- 注册到 `server._tools[name]`
- 用 `inspect.signature` 提取 input schema
- 工具上线无需修改注册表

### 2. Lambda Warm Container 单例
```python
# 模块级初始化（每个 Lambda 容器启动时执行一次）
_doa = DevOpsAgent()
_report = ReportGenerator()
_lark = LarkBot()
```
后续调用复用，避免每次重建 boto3 client（节省 200-500ms）。

### 3. Mock Fallback（生产 + 测试）
```python
class DevOpsAgent:
    def chat(self, prompt):
        try:
            return self._do_chat(prompt)
        except Exception as exc:
            return self._mock(prompt, error=str(exc))
```
DOA 不可用时返回 mock 数据，保证演示和测试不挂。

### 4. 异步两段式（飞书）
- Stage 1: < 1s 返回 200，Lambda 自调用
- Stage 2: 异步处理任意时长

避免被飞书 3s timeout 重试，避免重复回复。

### 5. 配置即代码（CDK）
所有资源在 Python 代码里描述，`cdk deploy` 一键部署/更新/回滚。

---

## 🔧 如何扩展

### 添加新 MCP 工具

1. 在 `src/mcp_server/v4_tools.py` 加：
```python
@server.tool
def my_new_tool(param: str) -> dict:
    """工具描述（会成为 LLM 看到的 description）."""
    # 实现逻辑
    return {"result": "..."}
```
2. `cdk deploy NLOpsV4Stack`
3. 客户端 `tools/list` 自动看到新工具

### 添加新 SSM Runbook

1. 在 `ssm-runbooks/` 新建 yaml：
```yaml
schemaVersion: "0.3"
description: "..."
parameters:
  ...
mainSteps:
  ...
```
2. 在 `infra/nlops_v4_stack.py` 的 `for rb_name, rb_file in [...]` 列表加一行
3. `cdk deploy`

### 添加新 IM 通道（如企微）

1. 新建 `src/tools/wecom_bot.py`，实现 `WeComBot` class
2. 在 `mcp_server/v4_tools.py` 的 `notify_im` 里加 `if channel == "wecom"`
3. CDK 加新环境变量 `WECOM_WEBHOOK_URL`

### 添加新 DOA Skill

1. 写 markdown：
```markdown
---
name: my-skill
description: ...
---
# Skill: ...
## 适用场景
## 调查步骤
## 常见根因
## 修复 Runbook
```
2. 打包 zip：`zip skill.zip SKILL.md`
3. 在 DOA Operator Console 上传

---

## 🐛 调试技巧

### 1. 看 Lambda 日志
```bash
aws logs tail /aws/lambda/NLOpsV4Stack-OrchestratorFn... --since 5m --follow --region us-east-1
```

### 2. 本地测试 MCP 工具
```bash
cd src
python3 -c "
import sys; sys.path.insert(0, '.')
from mcp_server.v4_tools import server
print(server._tools)
"
```

### 3. 调试 Lark webhook
```bash
# 模拟 url_verification
curl -X POST $ApiUrl/lark-event \
  -H "Content-Type: application/json" \
  -d '{"type":"url_verification","challenge":"test"}'
```

### 4. 查看实际 EB 事件结构
代码已经 log 了，搜 `eb.event_dump`：
```bash
aws logs filter-log-events \
  --log-group-name /aws/lambda/... \
  --filter-pattern "eb.event_dump"
```

---

## 📚 相关文档

- [设计文档 design-v4.md](design-v4.md) — 整体架构 + 设计决策
- [工程师手册 PROJECT.md](PROJECT.md) — 部署 + 故障排查
- [演示脚本 04-demo-script-v4.md](04-demo-script-v4.md) — Demo 流程
- [演示救命包 CHEAT-SHEET.md](CHEAT-SHEET.md) — 关键 URL + 命令
- [GitHub Repo](https://github.com/penghui1234/nlops/tree/feat/v4-doa-native)

---

## 🤝 Code Review 关注点

如果做 PR review，关注：

1. **MCP 工具 dry_run 默认**：写操作 (`trigger_runbook`) 必须默认 `dry_run=True`
2. **Lambda 超时处理**：DOA / Bedrock 调用必须有 timeout，避免 Lambda 跑满 120s
3. **IAM 最小权限**：新增 boto3 调用要在 CDK 里 grant 最小权限
4. **autoescape 处理**：Jinja2 模板里 JS 内容必须 `{% autoescape false %}`
5. **错误返回结构一致**：所有 Lambda 返回 `{statusCode, headers, body}`，body 是 JSON 字符串

---

代码质量目标：每个 Python 文件 < 500 行，每个函数 < 100 行。  
当前最大文件：`api_handler.py` 430 行（接近上限，下次重构可拆分）。
