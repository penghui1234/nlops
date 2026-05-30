# Skill: RDS 连接池问题处理

## 适用场景

- 告警包含 `DatabaseConnections`、`CPUUtilization (RDS)`、`ReadLatency`、`WriteLatency`
- 错误日志包含 `Connection timeout`、`max_connections`、`too many connections`
- 服务延迟突增同时伴随 RDS 指标异常

## 调查步骤

### 1. 检查 RDS 实例当前状态

```
rds:DescribeDBInstances(DBInstanceIdentifier)
```

记录:
- `DBInstanceClass`(实例规格)
- `DBInstanceStatus`(应为 available)
- `MaxAllocatedStorage` / `AllocatedStorage`(磁盘是否快满)

### 2. 查 max_connections 参数

```
rds:DescribeDBParameters(DBParameterGroupName)
```

- 找 `max_connections`,通常默认值是 `LEAST({DBInstanceClassMemory/12582880}, 5000)`
- 对 db.t3.medium 约 80-90 连接,db.r5.large 约 1000+

### 3. 查实际连接数

```
cloudwatch:GetMetricStatistics
  Namespace: AWS/RDS
  MetricName: DatabaseConnections
  Dimensions: DBInstanceIdentifier=<id>
  Period: 60
  Stat: Maximum
  Window: -30m
```

如果 `DatabaseConnections / max_connections > 80%` → 连接池压力大。

### 4. 检查 RDS Proxy(如有)

```
rds:DescribeDBProxies
rds:DescribeDBProxyTargetGroups
```

- `MaxConnectionsPercent`: 默认 100,可降到 50-90 留余量
- `ConnectionBorrowTimeout`: 默认 120s,如果应用超时短(< 5s)会 borrow 失败

### 5. 应用层连接配置

通过日志判断:
- Java 应用看 HikariCP 配置:`maximumPoolSize`、`connectionTimeout`
- Node.js 看 `pg.Pool` 或 `mysql2.createPool` 的 `max` 配置
- Python 看 SQLAlchemy `pool_size` + `max_overflow`

### 6. 慢查询识别

```
logs:FilterLogEvents
  log_group: /aws/rds/instance/<id>/slowquery
  time: -30m
```

或 Performance Insights:
```
pi:DescribeDimensionKeys
  Metric: db.load.avg
  GroupBy: db.sql.id
```

## 常见根因

| 根因 | 比例 | 修复 Runbook |
|------|------|--------------|
| 应用未使用连接池或池过小 | ~35% | 应用代码改 HikariCP/Pool 配置 |
| RDS Proxy MaxConnectionsPercent 过低 | ~25% | `nlops-rds-proxy-expand` |
| 慢查询占据连接 | ~20% | 加索引 / 改查询 |
| max_connections 配置过小 | ~15% | 升级实例或调参数组 |
| 连接泄漏(应用 bug) | ~5% | 代码 review 找未关闭的 Connection |

## 修复策略

### 临时缓解

#### 选项 A:扩容 RDS Proxy 连接池

```
Runbook: nlops-rds-proxy-expand
Parameters:
  ProxyName: <proxy-name>
  TargetGroupName: default
  MaxConnectionsPercent: 100  (从 80 → 100)
```

- 风险: 低
- 立即生效,无需重启
- 副作用: 接近 RDS 实例 max_connections 上限,需要后续升级实例

#### 选项 B:调整应用连接池

通过 Agent-ready Spec 交给 Kiro 修改应用配置:
```yaml
HikariConfig:
  maximumPoolSize: 20       # 从 10 → 20
  connectionTimeout: 30000  # ms
  idleTimeout: 600000       # ms
```

### 根本修复

1. 慢查询: 加索引,改 SQL
2. 实例升级: db.t3.medium → db.r5.large(走变更窗口)
3. 读写分离: 引入 RDS Read Replica

## 验证

修复后 5-10 分钟内观察:
- `DatabaseConnections` 应稳定在 < 70% max
- 应用 P99 延迟应回落到正常水平
- 错误日志中 `Connection timeout` 应消失

## 重要提醒

❌ 不要做:
- 直接重启 RDS 实例(切换时间 30-90s,影响生产)
- 在高峰期修改实例规格(走 modify-db-instance 会触发 reboot)

✅ 推荐做:
- 优先扩 RDS Proxy(无重启)
- 应用侧加 retry + circuit breaker
- 提前准备读副本作为应急路由
