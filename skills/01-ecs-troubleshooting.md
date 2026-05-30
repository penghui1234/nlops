# Skill: ECS 服务故障排查指南

## 适用场景

当 AWS DevOps Agent 在调查中遇到以下任一情况时,应应用此 Skill:

- 告警名称包含 `TargetResponseTime`、`HealthyHostCount`、`5xx`、`4xx`
- 资源类型为 ECS Service / ECS Task
- 服务名匹配 `*-api`、`*-service`、`*-worker`

## 调查步骤(按顺序)

### 1. 检查 ECS 服务健康度

```
ecs:DescribeServices(cluster, service)
```

关键指标:
- `desiredCount` vs `runningCount`(差距 > 0 说明启动失败)
- `pendingCount`(持续 > 0 说明资源不足或镜像拉取失败)
- `events`(最近 10 条,看错误信息)

### 2. 检查 ALB Target Group

```
elasticloadbalancing:DescribeTargetHealth
```

- `healthy_count` 是否等于预期 task 数
- `unhealthy_targets` 的 `reason` 字段(常见:Target.FailedHealthChecks、Target.ResponseCodeMismatch)

### 3. 查最近 30 分钟的部署事件

```
github (via DOA integration): list_commits(repo, since=-30m)
codepipeline:ListPipelineExecutions
```

如果有最近部署 → 优先怀疑代码回归。

### 4. 分析 ECS Task CloudWatch 指标

- `CPUUtilization` 持续 > 80% → 扩容或代码效率问题
- `MemoryUtilization` 持续 > 90% → OOM kill 风险
- `NetworkRxBytes` 异常 → 上下游流量风暴

### 5. 查任务日志

```
logs:FilterLogEvents
  log_group: /ecs/<service-name>
  pattern: "ERROR" OR "OOM" OR "OutOfMemory" OR "Timeout"
  time: -30m
```

### 6. 检查依赖服务

- RDS: `rds:DescribeDBInstances` → 看 CPU、连接数、读写延迟
- ElastiCache: `elasticache:DescribeCacheClusters` → 节点状态
- Lambda(下游): 调用错误率
- 内部 HTTP API: 通过 X-Ray service map

## 常见根因(按发生频率排序)

| 根因 | 比例 | 验证方法 | 修复 Runbook |
|------|------|---------|--------------|
| RDS 连接池耗尽 | ~30% | RDS DatabaseConnections 接近 max_connections | `nlops-rds-proxy-expand` |
| 部署引入代码 bug | ~25% | GitHub 最近 commit 时间与告警时间吻合 | git revert + redeploy |
| ECS task OOM | ~15% | StoppedTasks 中有 reason=OutOfMemoryError | 提升 memory 配置 |
| ALB 健康检查路径不通 | ~10% | unhealthy_targets reason=Health checks failed | 修复健康检查路径或 SG |
| 下游 Lambda 限流 | ~10% | Lambda Throttles > 0 | 调高并发限额 |
| ElastiCache failover | ~5% | CacheNodes status != available | 等待 failover 完成或扩容 |
| 网络配置变更 | ~5% | AWS Config 显示 SG 或 VPC 变更 | 回滚 Config 变更 |

## 修复策略

### 临时缓解(< 5 分钟)

如果是流量激增或单次部署引起:
- **扩容**: 调用 `nlops-ecs-scale` Runbook,desiredCount × 1.5
- **回滚**: 通过 CodeDeploy / GitHub Actions 触发上一版本部署

### 根本修复(代码级)

通过 Agent-ready Spec 交给 Kiro:
1. 定位代码文件(基于 GitHub commit diff)
2. 生成修复 PR
3. 走 PR review → CI → 部署流程

## 输出格式约定

调查报告中应包含:
- ✅ 根因(单选,最可能的一个)
- ✅ 证据链(metric/log/trace 引用)
- ✅ 修复建议(临时 + 根本)
- ✅ 风险等级(low/medium/high)
- ✅ 是否生成 Agent-ready Spec(是/否)
