# NLOps MCP Bridge

Local stdio MCP bridge that forwards Quick Desktop's MCP requests to the deployed NLOps MCP API on AWS.

## Architecture

```
┌──────────────────┐  stdio   ┌─────────────────┐  HTTPS   ┌──────────────────┐
│  Quick Desktop   │◀───────▶│  mcp-bridge     │────────▶│  NLOps McpApi    │
│  (Claude/Nova)   │ JSON-RPC│  index.js       │ POST    │  (API Gateway →  │
│                  │         │  (this proj)    │         │   L1 Orchestrator)│
└──────────────────┘         └─────────────────┘         └──────────────────┘
```

The bridge is a thin Node.js stdio shim. It:

1. Receives JSON-RPC 2.0 messages from Quick Desktop on stdin
2. Forwards them as HTTPS POST to `https://y20o7icdbb.execute-api.us-east-1.amazonaws.com/prod/mcp-quick`
3. Streams the JSON response back on stdout

The server endpoint is hardcoded in `index.js`. To point at a different deployment, edit `MCP_API_URL`.

## Why a bridge?

Quick Desktop only supports two MCP transports today:
- **stdio** — local subprocess
- **SSE** — long-lived HTTP stream

NLOps deploys behind API Gateway + Lambda which has a 30s response timeout, so a long-lived SSE connection isn't practical. A stdio bridge that does plain request-response is the simplest reliable transport.

## Install

```bash
npm install
```

Requires Node.js 18+.

## Configure Quick Desktop

In Quick Desktop's MCP server settings:

| Field | Value |
|---|---|
| Mode | Local |
| Command | `node` |
| Arguments | `<absolute path>/mcp-bridge/index.js` |

## Available Tools (21 in v3)

After Quick Desktop connects you should see these tools registered:

**Discovery (3)**
- `discover_resources` — EC2 / ECS / RDS / ELB / Lambda
- `discover_alerts` — Active CloudWatch alarms
- `discover_incidents` — Recent incidents from AuditTable

**Knowledge (4)**
- `query_knowledge_base` / `search_runbooks` — Bedrock KB
- `get_service_owner` / `get_service_dependencies` — Resource Tagging API + X-Ray service map

**Analysis (4)**
- `analyze_logs` (CW Logs Insights) / `analyze_metrics` / `analyze_traces` (X-Ray) / `analyze_root_cause` (Bedrock Nova Pro)

**Execution (4)**
- `execute_remediation` / `restart_service` / `scale_service` / `create_ticket` — all go via L2 ExecutionFn (write isolation + confirm token)

**Reporting (3)**
- `generate_report` / `list_investigations` / `get_investigation`

**Smart / High-level (3 — added in v3)**
- `smart_diagnose` — One-stop SRE diagnosis: routes via Strands Agent → DOA → HTML report
- `consult_devops_agent` — Direct one-shot chat with AWS DevOps Agent (5-30s)
- `request_confirm_token` — Issue a 5-min single-use token for write actions

## Troubleshooting

### Bridge keeps reconnecting / no tools shown

1. Check Quick Desktop logs for stdio errors
2. Verify `node index.js` runs locally without errors:
   ```bash
   echo '{"jsonrpc":"2.0","id":1,"method":"tools/list"}' | node index.js
   # Should print a JSON response with 21 tools
   ```
3. Verify network reachability:
   ```bash
   curl -X POST https://y20o7icdbb.execute-api.us-east-1.amazonaws.com/prod/mcp-quick \
     -H "Content-Type: application/json" \
     -d '{"jsonrpc":"2.0","id":1,"method":"tools/list"}'
   ```

### Tools list returns 18 instead of 21

You're talking to a stale Lambda deployment. Re-run `cdk deploy` from `infra/`.

### Tools/call returns mock data when you wanted real

Check `MOCK_MODE` env var on the L1 OrchestratorFn:

```bash
aws lambda get-function-configuration \
  --region us-east-1 \
  --function-name NLOpsStack-OrchestratorFn6F7CE538-fDx1bctLRCvy \
  --query 'Environment.Variables.MOCK_MODE'
```

Should be `"false"` for real mode. To flip:

```bash
aws lambda update-function-configuration \
  --region us-east-1 \
  --function-name NLOpsStack-OrchestratorFn6F7CE538-fDx1bctLRCvy \
  --environment "Variables={MOCK_MODE=false,...其他保留...}"
```

## License

Apache-2.0 (matches parent repo).
