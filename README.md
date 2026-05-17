# NLOps · 自然语言驱动的 AI 运维平台

> 基于 AWS Bedrock / AgentCore / Nova Sonic 打造的智能闭环运维平台。
> 让 SRE 通过语音 / 文字完成"发现 → 定位 → 修复 → 沉淀"全流程。

## 当前进度

- [x] 需求分析 — `docs/01-requirements.md`
- [x] 实现方案 — `docs/02-design.md`
- [x] CDK 基础设施 — `infra/`
- [ ] 6 个 Agent 代码 — `src/agents/`
- [ ] 工具适配器 — `src/tools/`
- [ ] Lambda 入口 — `src/handlers/`
- [ ] HTML 报告生成器 — `src/report/`
- [ ] Nova Sonic 适配 — `src/voice/`
- [ ] 单元测试 — `tests/`

## 核心架构

```
入口 (Quick / 企微 / 飞书)
    ↓
API Gateway → Entry Lambda
    ↓
Router Agent ─┬─ Discovery (CloudWatch MCP)
              ├─ Knowledge (Bedrock KB)
              ├─ Analysis  (DevOps Agent)
              ├─ Execution (Policy Guard)
              └─ Report    (HTML 分析页 → S3)
```

## 快速开始（部署）

```bash
cd infra
pip install -r requirements.txt
cdk bootstrap        # 首次需要
cdk deploy
```

详见 `docs/02-design.md`。

## 许可

仅作内部方案验证使用。
