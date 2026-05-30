#!/usr/bin/env node
/**
 * NLOps v4 MCP Bridge
 *
 * Local stdio MCP server for Quick Desktop, forwards JSON-RPC to AWS API GW.
 *
 * v4 changes vs v3:
 *   - Updated default URL to v4 NLOpsV4Stack endpoint
 *   - Now exposes 5 tools (was 21 in v3)
 *   - Read URL from env NLOPS_MCP_URL (fallback to default)
 *   - Added 60s timeout for start_investigation
 */

import { Server } from '@modelcontextprotocol/sdk/server/index.js';
import { StdioServerTransport } from '@modelcontextprotocol/sdk/server/stdio.js';
import {
  CallToolRequestSchema,
  ListToolsRequestSchema,
} from '@modelcontextprotocol/sdk/types.js';

// Resolve MCP API URL: env > default
const MCP_API_URL = process.env.NLOPS_MCP_URL
  || 'https://0ij69qdk8c.execute-api.us-east-1.amazonaws.com/prod/mcp-quick';

const TIMEOUT_MS = parseInt(process.env.NLOPS_MCP_TIMEOUT_MS || '60000', 10);

console.error(`[NLOps v4] MCP Bridge starting...`);
console.error(`[NLOps v4] API URL: ${MCP_API_URL}`);
console.error(`[NLOps v4] Timeout: ${TIMEOUT_MS}ms`);

const server = new Server(
  { name: 'nlops-v4-mcp-bridge', version: '4.0.0' },
  { capabilities: { tools: {} } }
);

async function forwardToAws(method, params) {
  const requestId = Date.now();
  const body = { jsonrpc: '2.0', id: requestId, method, params };

  const controller = new AbortController();
  const timeoutId = setTimeout(() => controller.abort(), TIMEOUT_MS);

  try {
    const response = await fetch(MCP_API_URL, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
      signal: controller.signal,
    });

    if (!response.ok) {
      const errBody = await response.text().catch(() => '');
      throw new Error(`AWS API ${response.status}: ${errBody.substring(0, 200)}`);
    }

    const result = await response.json();
    if (result.error) {
      throw new Error(result.error.message || JSON.stringify(result.error));
    }
    return result.result;
  } catch (err) {
    if (err.name === 'AbortError') {
      throw new Error(`Request timed out after ${TIMEOUT_MS}ms`);
    }
    throw err;
  } finally {
    clearTimeout(timeoutId);
  }
}

server.setRequestHandler(ListToolsRequestSchema, async () => {
  return await forwardToAws('tools/list', {});
});

server.setRequestHandler(CallToolRequestSchema, async (request) => {
  const { name, arguments: args } = request.params;
  return await forwardToAws('tools/call', { name, arguments: args });
});

async function main() {
  const transport = new StdioServerTransport();
  await server.connect(transport);
  console.error('[NLOps v4] MCP Bridge ready');
}

main().catch((error) => {
  console.error('[NLOps v4] Fatal error:', error);
  process.exit(1);
});
