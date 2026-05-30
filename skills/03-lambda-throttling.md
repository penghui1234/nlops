# Skill: Lambda 限流 / 性能问题修复

## 适用场景

- 告警包含 `Throttles`、`Errors`、`Duration`、`ConcurrentExecutions`
- HTTP 5xx 来自 API Gateway → Lambda 集成
- 错误日志包含 `Task timed out`、`Rate exceeded`、`TooManyRequestsException`

## 调查步骤

### 1. 查 Lambda 函数当前配置

```
lambda:GetFunctionConfiguration(FunctionName)
```

记录:
- `MemorySize`(MB)
- `Timeout`(s)
- `ReservedConcurrentExecutions`(预留并发,可能为 None)
- `Runtime`、`Architecture`

### 2. 查并发使用情况

```
cloudwatch:GetMetricStatistics
  Namespace: AWS/Lambda
  MetricName: ConcurrentExecutions
  Dimensions: FunctionName=<name>
  Stat: Maximum
  Window: -30m
```

对比账户级 Quota:
```
service-quotas:GetServiceQuota
  ServiceCode: lambda
  QuotaCode: L-B99A9384  (Concurrent executions)
```

默认账户级是 1000(可申请提升)。

### 3. 查限流(Throttles)指标

```
cloudwatch:GetMetricStatistics
  Namespace: AWS/Lambda
  MetricName: Throttles
  Stat: Sum
```

- `Throttles > 0` → 已经触发限流
- 同时看 `Invocations` 和 `Errors` 是否随之上升

### 4. 查执行时长分布

```
cloudwatch:GetMetricStatistics
  Namespace: AWS/Lambda
  MetricName: Duration
  Stat: Average / p99 / Maximum
```

- 如果 `Duration` 接近 `Timeout` → 函数性能问题
- 如果 `Duration p99` 远大于 `Average` → 冷启动或个别慢调用

### 5. 检查依赖

通过 X-Ray:
```
xray:GetTraceSummaries
  FilterExpression: service("<lambda-name>") { fault = true OR responsetime > 5 }
```

看慢调用链路最长的 segment 是哪个(RDS / DynamoDB / 外部 HTTP)。

### 6. 检查冷启动

```
logs:FilterLogEvents
  log_group: /aws/lambda/<name>
  pattern: "REPORT" "Init Duration"
```

- 频繁 Init Duration > 1000ms → Provisioned Concurrency 候选

## 常见根因

| 根因 | 比例 | 修复 Runbook / 行动 |
|------|------|-------------------|
| 突发流量超过 burst limit | ~30% | 申请账户 Quota 提升 + 加 reserved concurrency |
| 函数 timeout 太低 | ~20% | 改 Timeout(注意 API Gateway 上游 29s 限制) |
| 内存不足导致超时 | ~15% | 提升 MemorySize(Lambda 自动给更多 CPU) |
| 下游 RDS / DynamoDB 慢 | ~15% | 处理下游(走 Skill 02 或 04) |
| 冷启动频繁 | ~10% | 启用 Provisioned Concurrency |
| 依赖 SDK 内部重试 | ~5% | 调整 boto3/AWS SDK retry config |
| 代码 bug(死循环、内存泄漏) | ~5% | 代码 review |

## 修复策略

### 临时缓解(< 5 分钟)

#### 选项 A:扩并发

通过 Agent-ready Spec 修改 IaC:
```yaml
# CDK 示例
fn.addEnvironment('RESERVED', '500')  # 删
# 改用:
fn.reservedConcurrentExecutions = 500  # 预留 500 并发
```

或直接命令(临时):
```
aws lambda put-function-concurrency \
  --function-name <name> \
  --reserved-concurrent-executions 500
```

- 风险: 占用账户级 quota
- 立即生效

#### 选项 B:升级内存

内存倍增通常带来 1.5-2x 性能(Lambda CPU 与 memory 成正比)。

```
aws lambda update-function-configuration \
  --function-name <name> \
  --memory-size 1024
```

成本影响: 内存 × 单价线性增加。

### 根本修复(代码级)

通过 Agent-ready Spec 交给 Kiro:

1. **优化冷启动**:
   - 移到 ARM64(Graviton2,启动快 ~30%)
   - 减小部署包(去除未用依赖)
   - 用 Lambda Snapshot Snapping(JVM)

2. **优化运行时**:
   - 复用 boto3 client(模块级单例)
   - 异步并发调用下游(asyncio / Promise.all)
   - 缓存热点数据(Lambda 容器复用期间)

3. **架构改造**:
   - 考虑 SQS 缓冲流量峰值
   - 长任务移到 Step Functions / ECS

## 验证

修复后 5-15 分钟观察:
- `Throttles` 应回到 0
- `Errors` 率应 < 0.1%
- `Duration p99` 应稳定且远低于 Timeout

## 自动 Runbook 候选

虽然 v4 暂未实现 Lambda Runbook,但可使用通用方法:

```
aws lambda put-function-concurrency \
  --function-name {{ FunctionName }} \
  --reserved-concurrent-executions {{ ReservedConcurrency }}
```

或交给 Kiro 通过 IaC 提交 PR(推荐路径)。
