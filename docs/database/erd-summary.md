# Memory Engine 数据库速查 v0.4

## 全局标准字段（每张表必有）

```sql
deleted     TINYINT(1)   NOT NULL DEFAULT 0
create_time DATETIME(3)  NOT NULL DEFAULT CURRENT_TIMESTAMP(3)
update_time DATETIME(3)  NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3)
```

## org_id 语义

| org_id | 含义 |
|--------|------|
| `0` | 仅租户级，无组织（**不建 FK**） |
| `≥1` | 对应 `organization.id` |

## 外键统计

- **43 条**外键，详见 `foreign-keys-and-indexes.md`
- 根表 `tenant`、`permission` 无父 FK

## 核心文档

| 文档 | 内容 |
|------|------|
| `schema-design.md` | 表结构、业务语义、版本策略 |
| `foreign-keys-and-indexes.md` | 外键清单、索引清单、API 场景映射 |
| `001_initial_schema.sql` | 可执行 DDL v0.4 |

## API 日志（非 MySQL）

```
FastAPI → Kafka → TOS Parquet → Hive/Trino → Dashboard
```
