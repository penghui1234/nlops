"""Local end-to-end NLOps demo runner.

Simulates the 5 demo scenarios from docs/04-demo-script.md without
needing AWS DevOps Agent Agent Space, Bedrock model access, S3, or
DynamoDB.

What's real:
  * The full Orchestrator engine + 6 logical Agents (Tool wiring)
  * Policy Guard + Confirm Token validation flow
  * Report generator + Jinja2 templating
  * MCP Server JSON-RPC dispatch

What's mocked (because no live AWS services):
  * Router LLM           — canned plans per scenario
  * DevOps Agent chat    — deterministic mock string (already in tools)
  * S3 upload            — write HTML to local /tmp/nlops-demo/ instead
  * DDB session/audit    — no-op
  * Lambda cross-invoke  — direct call

Run:
    python3 -m demo.run_demo

Outputs:
  * Pretty terminal summary of each scenario
  * /tmp/nlops-demo/scenario-{n}.html for each
  * /tmp/nlops-demo/index.html linking all
"""
from __future__ import annotations

import os
import sys
import time
import uuid
from pathlib import Path

# Make ``src`` importable as a top-level package
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# Force local-mode env BEFORE importing src.*
os.environ.setdefault("DOA_AGENT_SPACE_ID", "")        # -> mock
os.environ.setdefault("REPORT_BUCKET", "")              # -> handled below
os.environ.setdefault("SESSIONS_TABLE", "")
os.environ.setdefault("AUDIT_TABLE", "")
os.environ.setdefault("CONFIRM_TOKENS_TABLE", "")

from src.agents.base import AgentContext  # noqa: E402
from src.agents.report import ReportAgent  # noqa: E402
from src.orchestrator.engine import Orchestrator  # noqa: E402
from src.report.generator import ReportGenerator  # noqa: E402
from src.tools.devops_agent import DevOpsAgentTool  # noqa: E402

# --------------------------------------------------------------------- #
OUT_DIR = Path("/tmp/nlops-demo")
OUT_DIR.mkdir(parents=True, exist_ok=True)


# --------------------------------------------------------------------- #
# Local report generator: render to /tmp instead of S3
# --------------------------------------------------------------------- #
class LocalReportGenerator(ReportGenerator):
    def __init__(self, out_dir: Path = OUT_DIR) -> None:
        self.out_dir = out_dir

    def render_and_upload(self, finding, kind="diagnostic", trace_id=None):
        report_id = trace_id or f"rpt-{uuid.uuid4().hex[:8]}"
        ts = int(time.time())
        html = self._render(finding, kind=kind, report_id=report_id, ts=ts)
        path = self.out_dir / f"{kind}-{report_id}.html"
        path.write_text(html, encoding="utf-8")
        return f"file://{path}"


# --------------------------------------------------------------------- #
# Mock-router agent: returns canned plans per scenario for demo
# --------------------------------------------------------------------- #
SCENARIOS = {
    1: {
        "title": "早晨巡检 (Health Check)",
        "user_query": "早上好，系统今天怎么样？",
        "intent": "health_check",
        "finding": {
            "title": "早晨巡检报告 · 5 月 17 日",
            "severity": "info",
            "investigation_id": None,
            "operator_portal_url": "",
            "timeline": [
                {"ts": "2026-05-17T07:30:00Z", "event": "全量巡检启动 (12 个核心服务)"},
                {"ts": "2026-05-17T07:30:08Z", "event": "11/12 健康；order-service P99 略高"},
                {"ts": "2026-05-17T07:30:09Z", "event": "RDS 连接池使用率 78%（关注）"},
            ],
            "root_cause": (
                "整体健康，order-service P99=320ms（基线 200ms），疑似 batch job 触发的连接占用上升。"
            ),
            "fix_steps": [
                {"action": "暂不需修复，持续观察 30 分钟", "risk": "low", "auto": False},
                {"action": "若 P99 持续 > 350ms 触发深度调查", "risk": "low", "auto": True},
            ],
            "evidence": {
                "trace_ids": ["1-66a01234-..."],
                "log_snippets": [
                    "07:30:00 INFO scheduled batch job started",
                    "07:30:02 INFO 12 services queried",
                ],
            },
        },
    },
    2: {
        "title": "故障下钻 (Troubleshoot)",
        "user_query": "order-service 延迟为什么涨了？",
        "intent": "troubleshoot",
        "finding": {
            "title": "order-service P99 延迟突增 · 完整诊断",
            "severity": "high",
            "investigation_id": "task-2026-05-17-abc",
            "operator_portal_url": (
                "https://us-east-1.console.aws.amazon.com/aidevops/spaces/space-001/tasks/task-2026-05-17-abc"
            ),
            "timeline": [
                {"ts": "2026-05-17T14:30:00Z", "event": "P99 latency rose 200ms -> 320ms"},
                {"ts": "2026-05-17T14:32:10Z", "event": "RDS CPU reached 85%"},
                {"ts": "2026-05-17T14:34:00Z", "event": "ConnectionPoolExhausted errors begin"},
                {"ts": "2026-05-17T14:35:00Z", "event": "Error rate 0.05% -> 0.4%"},
            ],
            "root_cause": (
                "RDS Proxy 连接池配置过小 (max=200)，结合 14:30 的 batch job 大量并发写入造成"
                "连接饥饿。getUserOrders() 等待连接平均 1.8s，请求堆积。"
            ),
            "fix_steps": [
                {"action": "扩容 RDS Proxy 连接池 200 → 400", "risk": "low", "auto": True},
                {"action": "给 orders 表加索引 (created_at, user_id)", "risk": "med", "auto": False},
                {"action": "重启 order-service Pod 清连接", "risk": "low", "auto": True},
            ],
            "evidence": {
                "trace_ids": ["1-66a01234-aabbccdd", "1-66a01235-eeff0011"],
                "log_snippets": [
                    "14:31:08 SLOW QUERY: SELECT * FROM orders WHERE created_at > ... (2.3s)",
                    "14:34:12 ERROR ConnectionPoolExhausted (RDSProxy.DatabaseConnections=200)",
                    "14:34:15 ERROR ConnectionPoolExhausted (...18 occurrences)",
                ],
            },
        },
    },
    3: {
        "title": "执行修复 (Execute · Confirm Token)",
        "user_query": "帮我扩容到 400",
        "intent": "execute_action",
        "action": {
            "type": "rds.modify_proxy_connections",
            "params": {"proxy_name": "rds-proxy-prod-orders", "max_connections": 400},
        },
        "finding": {
            "title": "执行成功：RDS Proxy 连接池扩容",
            "severity": "info",
            "operator_portal_url": "",
            "timeline": [
                {"ts": "2026-05-17T14:42:00Z", "event": "用户点击 [✓ 确认执行]"},
                {"ts": "2026-05-17T14:42:01Z", "event": "Confirm Token ct-abc 验证通过"},
                {"ts": "2026-05-17T14:42:02Z", "event": "Policy Guard 通过 (写权限 + 资源 tag 边界)"},
                {"ts": "2026-05-17T14:42:08Z", "event": "AWS API ModifyDBProxy 完成"},
                {"ts": "2026-05-17T14:43:00Z", "event": "P99 已恢复至 195ms"},
            ],
            "root_cause": "扩容 RDS Proxy max_connections 200 → 400",
            "fix_steps": [
                {"action": "持续观察 5 分钟，确认 P99 稳定", "risk": "low", "auto": True},
                {"action": "在下次发布同步基础设施代码 (CDK)", "risk": "low", "auto": False},
            ],
            "evidence": {
                "trace_ids": [],
                "log_snippets": [
                    "audit-2026-05-17-001 user=alice@corp action=rds.modify_proxy_connections "
                    "params={proxy_name=rds-proxy-prod-orders, max=400} status=ok",
                ],
            },
        },
    },
    4: {
        "title": "经验复用 (Knowledge Replay)",
        "user_query": "上次 order-service 延迟是怎么解决的？",
        "intent": "knowledge_query",
        "finding": {
            "title": "历史方案匹配 · 相似度 92%",
            "severity": "info",
            "investigation_id": "inc-2026-04-26-001",
            "operator_portal_url": (
                "https://us-east-1.console.aws.amazon.com/aidevops/spaces/space-001/tasks/inc-2026-04-26-001"
            ),
            "timeline": [
                {"ts": "2026-04-26T14:30:00Z", "event": "(历史) order-service P99 突增"},
                {"ts": "2026-04-26T14:42:00Z", "event": "(历史) RDS Proxy 200 → 400 已修复"},
                {"ts": "2026-05-17T15:08:00Z", "event": "本次匹配返回，匹配度 92%"},
            ],
            "root_cause": "DevOps Agent Custom Skill 自动匹配 — 同一根因、同一修复方案",
            "fix_steps": [
                {"action": "一键复用 (扩容 RDS Proxy 200 → 400)", "risk": "low", "auto": True},
                {"action": "走完整 DevOps Agent investigation 流程", "risk": "low", "auto": False},
            ],
            "evidence": {
                "trace_ids": [],
                "log_snippets": [
                    "DOA Custom Skill: nlops-incident-inc-2026-04-26-001 score=0.92",
                    "Bedrock KB top-1 match: inc-2026-04-26-001.json",
                ],
            },
        },
    },
    5: {
        "title": "告警自动闭环 (Event-Driven)",
        "user_query": "(no human input — alarm-driven)",
        "intent": "alert_driven",
        "finding": {
            "title": "🚨 自动调查完成 · payment-service 5xx 飙升",
            "severity": "critical",
            "investigation_id": "task-2026-05-17-xyz",
            "operator_portal_url": (
                "https://us-east-1.console.aws.amazon.com/aidevops/spaces/space-001/tasks/task-2026-05-17-xyz"
            ),
            "timeline": [
                {"ts": "2026-05-17T02:14:00Z", "event": "CloudWatch alarm 触发 (5xx > 1%)"},
                {"ts": "2026-05-17T02:14:30Z", "event": "DOA 自动启动 investigation (无人工)"},
                {"ts": "2026-05-17T02:18:45Z", "event": "DOA 完成 — 根因: cert-mgr-* 证书过期"},
                {"ts": "2026-05-17T02:18:48Z", "event": "EventBridge 事件 -> NLOps L3 Lambda"},
                {"ts": "2026-05-17T02:18:55Z", "event": "HTML 渲染 + IM 卡片推送值班群"},
            ],
            "root_cause": (
                "上游 payment-gateway 的 mTLS 证书 (cert-mgr-prod-payment) 在 02:13 过期，"
                "请求被网关 reject。0.8% 支付请求 5xx。"
            ),
            "fix_steps": [
                {"action": "替换证书 (有 Skill 可复用 — 3 个月前同款故障)", "risk": "low", "auto": True},
                {"action": "把证书续期接入 ACM 自动 rotation", "risk": "low", "auto": False},
            ],
            "evidence": {
                "trace_ids": ["1-66a02000-...."],
                "log_snippets": [
                    "02:13:58 ERROR mTLS handshake failed: certificate expired",
                    "02:14:00 ALARM: payment-service-5xx-rate threshold exceeded",
                ],
            },
        },
    },
}


# --------------------------------------------------------------------- #
# Pretty terminal output
# --------------------------------------------------------------------- #
def _hr(c="─", w=70):
    print(c * w)


def render_im_card(scenario_id: int, finding: dict, html_url: str) -> None:
    sev_emoji = {
        "critical": "🔴",
        "high":     "🟠",
        "med":      "🟡",
        "low":      "🟢",
        "info":     "🔵",
    }.get((finding.get("severity") or "info").lower(), "⚪")

    print()
    _hr("═")
    print(f" 📱 Scenario {scenario_id} — IM Card Preview")
    _hr("═")
    print(f" {sev_emoji} {finding['title']}")
    print(f"    severity: {finding.get('severity', 'info')}")
    print()

    rc = finding.get("root_cause", "")
    if rc:
        print(" 🔬 根因")
        for line in _wrap(rc, 64):
            print(f"    {line}")
        print()

    steps = finding.get("fix_steps") or []
    if steps:
        print(" 🛠️  修复建议")
        for s in steps:
            risk = s.get("risk", "low")
            auto = "⚡可自动" if s.get("auto") else "📋需评审"
            print(f"    [{risk:>4}] {auto}  {s['action']}")
        print()

    print(f" 📄 HTML 诊断书: {html_url}")
    _hr("═")


def _wrap(text: str, width: int) -> list[str]:
    out = []
    line = ""
    for word in text.split():
        if len(line) + len(word) + 1 > width:
            out.append(line)
            line = word
        else:
            line = (line + " " + word) if line else word
    if line:
        out.append(line)
    return out


# --------------------------------------------------------------------- #
# Driver
# --------------------------------------------------------------------- #
def run_one(scenario_id: int, scenario: dict, report_agent: ReportAgent) -> dict:
    print()
    _hr("█")
    print(f" Scenario {scenario_id}: {scenario['title']}")
    _hr("█")
    print(f' 用户输入: "{scenario["user_query"]}"')
    print(f" Intent  : {scenario['intent']}")
    print()

    # Simulate Discovery / Analysis output (would normally call DOA)
    if scenario["intent"] == "health_check":
        doa = DevOpsAgentTool()
        chat = doa.chat("Summarise system health for 12 services in the last 30 min.")
        print(" → Discovery (DOA chat mock):")
        print(f"   {chat}")
        print()
    elif scenario["intent"] == "troubleshoot":
        doa = DevOpsAgentTool()
        inv_id = doa.start_investigation(
            title="order-service P99 spike",
            context={"service": "order-service", "window_minutes": 30},
        )
        print(f" → Analysis: started DOA investigation {inv_id}")
        print()
    elif scenario["intent"] == "execute_action":
        print(" → Confirm Token: ct-demo-abc (issued)")
        print(" → Policy Guard: write + tag boundary OK")
        print(" → ExecutionLambda: ModifyDBProxy ... ✓")
        print()

    # Render HTML using the Report Agent
    ctx = AgentContext(
        trace_id=f"demo-{scenario_id}",
        user_id="demo@nlops",
        session_id=f"sess-{scenario_id}",
        channel="local-demo",
        user_confirmed=(scenario["intent"] == "execute_action"),
    )
    result = report_agent.run(ctx, finding=scenario["finding"], kind=scenario["intent"])

    render_im_card(scenario_id, scenario["finding"], result["html_url"])
    return result


def write_index(results: dict[int, dict]) -> Path:
    rows = []
    for sid, r in sorted(results.items()):
        scn = SCENARIOS[sid]
        url = r["html_url"]
        rel = url.replace("file://", "")
        name = Path(rel).name
        rows.append(
            f'<tr><td>{sid}</td><td>{scn["title"]}</td>'
            f'<td><code>{scn["user_query"]}</code></td>'
            f'<td><a href="{name}">查看 →</a></td></tr>'
        )
    html = (
        "<!doctype html><meta charset=utf-8>"
        "<title>NLOps Demo Index</title>"
        "<style>"
        "body{font-family:-apple-system,sans-serif;max-width:900px;margin:2em auto;padding:0 1em}"
        "table{width:100%;border-collapse:collapse}"
        "th,td{padding:10px;border-bottom:1px solid #eee;text-align:left}"
        "h1{border-bottom:2px solid #ff9900;padding-bottom:8px}"
        "</style>"
        "<h1>NLOps Demo · 5 Scenarios</h1>"
        "<p>本页索引由 demo/run_demo.py 自动生成。每条链接打开对应场景的智能诊断书。</p>"
        "<table><tr><th>#</th><th>场景</th><th>用户输入</th><th>诊断书</th></tr>"
        + "".join(rows)
        + "</table>"
    )
    out = OUT_DIR / "index.html"
    out.write_text(html, encoding="utf-8")
    return out


def main() -> None:
    print()
    _hr("▓")
    print("  NLOps Local Demo Runner — 5 scenarios, all-in-process, no AWS deps")
    _hr("▓")

    report_agent = ReportAgent(generator=LocalReportGenerator())

    results = {}
    for sid, scn in SCENARIOS.items():
        results[sid] = run_one(sid, scn, report_agent)

    index = write_index(results)
    print()
    _hr("▓")
    print(f"  ✅ 全部完成。HTML 诊断书写入: {OUT_DIR}")
    print(f"  📋 索引页: file://{index}")
    print()
    print("  下载查看：")
    print("     scp -i <key.pem> ec2-user@<EC2-IP>:/tmp/nlops-demo/*.html ./")
    print("  或本机起 HTTP server 然后浏览器看：")
    print("     python3 -m http.server 8080 -d /tmp/nlops-demo/")
    _hr("▓")


if __name__ == "__main__":
    main()
