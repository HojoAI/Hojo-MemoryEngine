# Canal CDC for Memory Engine

Canal 订阅 MySQL binlog，将 `memory_field`、`parse_rule`、`retrieve_rule`、`call_rule`、`capability_registry` 变更写入 Kafka topic `canal-memory-engine`。Memory Engine API 的 `canal_binlog_consumer` 消费后更新 Redis 缓存与 SDK changelog stream。

## 前置条件

MySQL 需开启 binlog（ROW 模式）：

```ini
log-bin=mysql-bin
binlog-format=ROW
server-id=1
```

## 本地 Docker Compose

```bash
cd infra/docker-compose
# 配置 .env：MYSQL_HOST、MYSQL_USER、MYSQL_PASSWORD、CANAL_MYSQL_DATABASE
docker compose up -d canal-server kafka
```

在 `backend/.env` 中启用：

```env
CANAL_ENABLED=true
KAFKA_CONSUMERS_ENABLED=true
SCHEMA_SYNC_API_PUBLISH=false
KAFKA_CANAL_TOPIC=canal-memory-engine
CANAL_MYSQL_DATABASE=memory_engine
```

重启 API 后，**仅写 MySQL** 的变更（含 Dashboard、直连 SQL）也会经 Canal 热更新 Redis 与 SDK。

## 生产部署

参考 [Canal Deployer](https://github.com/alibaba/canal/wiki/QuickStart) 将 `instance.properties` 中 `canal.mq.servers` 指向集群 Kafka，`canal.instance.filter.regex` 与 `CANAL_MYSQL_DATABASE` 一致。
