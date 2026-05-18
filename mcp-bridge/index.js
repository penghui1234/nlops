#!/usr/bin/env node
/**
 * NLOps MCP Bridge
 * 
 * 这是一个本地 MCP 服务器，使用 stdio 传输与 Quick Desktop 通信。
 * 它将请求转发到 AWS API Gateway 上部署的 MCP 服务端点。
 */

import { Server } from '@modelcontextprotocol/sdk/server/index.js';
import { StdioServerTransport } from '@modelcontextprotocol/sdk/server/stdio.js';
import {
  CallToolRequestSchema,
  ListToolsRequestSchema,
} from '@modelcontextprotocol/sdk/types.js';

// AWS MCP API 端点
const MCP_API_URL = 'https://y20o7icdbb.execute-api.us-east-1.amazonaws.com/prod/mcp-quick';

// 创建 MCP 服务器
const server = new Server(
  { name: 'nlops-mcp-bridge', version: '1.0.0' },
  { capabilities: { tools: {} } }
);

// 转发请求到 AWS API
async function forwardToAws(method, params) {
  const requestId = Date.now();
  const body = {
    jsonrpc: '2.0',
    id: requestId,
    method,
    params
  };

  // 使用 AbortController 设置 30 秒超时
  const controller = new AbortController();
  const timeoutId = setTimeout(() => controller.abort(), 30000);

  try {
    const response = await fetch(MCP_API_URL, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify(body),
      signal: controller.signal
    });

    if (!response.ok) {
      throw new Error(`AWS API error: ${response.status} ${response.statusText}`);
    }

    const result = await response.json();
    
    if (result.error) {
      throw new Error(result.error.message || 'Unknown error');
    }
    
    return result.result;
  } finally {
    clearTimeout(timeoutId);
  }
}

// 处理工具列表请求
server.setRequestHandler(ListToolsRequestSchema, async () => {
  const result = await forwardToAws('tools/list', {});
  return result;
});

// 处理工具调用请求
server.setRequestHandler(CallToolRequestSchema, async (request) => {
  const { name, arguments: args } = request.params;
  const result = await forwardToAws('tools/call', { name, arguments: args });
  return result;
});

// 启动服务器
async function main() {
  const transport = new StdioServerTransport();
  await server.connect(transport);
  console.error('NLOps MCP Bridge started');
}

main().catch((error) => {
  console.error('Fatal error:', error);
  process.exit(1);
});
