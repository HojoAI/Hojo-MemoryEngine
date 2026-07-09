# Memory Engine Java SDK

与 Python SDK（`memory_engine_sdk`）逻辑对齐的 Java 17 客户端（`com.memoryengine`）。

## 依赖

- Java 17+
- Maven 3.9+

## 构建

```bash
cd sdk/java
mvn -q clean package
# 产物：target/memory-engine-sdk-0.5.0.jar
```

## 配置

环境变量（与 Python 一致）：

| 变量 | 说明 | 默认 |
|------|------|------|
| `MEMORY_ENGINE_API_BASE` | API 根路径 | `http://127.0.0.1:6030/api/v1` |
| `MEMORY_ENGINE_API_KEY` | Bearer Token（完整密钥，**必填**） | — |
| `MEMORY_ENGINE_API_KEY_PREFIX` | 可选；未设置时由完整 Key 前 16 字符推导 | — |
| `MEMORY_ENGINE_TENANT_ID` / `MEMORY_ENGINE_ORG_ID` | 租户与组织 | `1` / `0` |
| `MEMORY_ENGINE_USER_ID` | 可选请求头 | — |
| `MEMORY_ENGINE_HTTP_TIMEOUT` | 非 LLM 请求超时（秒） | `30` |
| `MEMORY_ENGINE_PARSE_TIMEOUT` | `Data.parse` 超时（秒） | `max(HTTP, 180)` |

`Data.parse` / `Data.get(schema)` 默认使用当前 Key 的 **`memory_user_id`**（`GET /onboarding/session`）作为 Mongo/Qdrant 分区，一般无需再传 `user_id`。`userId` 非空时覆盖该默认值（`parse(..., userId)`、`get(schema, userId)`、`get(schema, userId, rule)`）。

## 快速开始

```java
import com.memoryengine.MemoryEngine;
import com.memoryengine.enums.SearchEnum;
import com.memoryengine.model.*;

public class Example {
  public static void main(String[] args) throws Exception {
    MemoryEngine mos = MemoryEngine.fromEnvironment();
    mos.schema().enableHotReload(2000);

    var schema = mos.schema().getOrCreate("用户年龄", SearchEnum.SEMANTIC, null);

    MemoryData mem = mos.data().parse(schema.name(), new ParseInput("我今年25岁"));

    var retrieved = mos.data().get(schema.name());
    retrieved.ifPresent(m -> System.out.println(m.data()));

    mos.schema().llmParse(
        "用户性别",
        "extract_gender",
        "从用户输入中抽取「{field}」…\n\n用户输入：{text}",
        "qwen-max-2025-01-25",
        java.util.Map.of("temperature", 0.1, "top_p", 0.9));

    String filled = mos.data().call(
        schema.name(), "用户<年龄>岁，能否考驾照？", "<年龄>", mem.data(), null, false);
    System.out.println(filled);
  }
}
```

## API 对照

| Python (`memory_engine_sdk`) | Java |
|-------------------------------|------|
| `Schema.get` / `getOrCreate` | `mos.schema().get` / `getOrCreate` |
| `Schema.llm_parse` / `ensure_parse_rule` | `mos.schema().llmParse` / `ensureParseRule` |
| `ParseRule.llm_parse` / `llm_field_extract` | `ParseRule.llmParse` / `llmFieldExtract` |
| `Schema.enable_hot_reload` | `mos.schema().enableHotReload` |
| `Data.parse(schema, input)` | `mos.data().parse(schema, input)` |
| `Data.get(schema)` | `mos.data().get(schema)` |
| `Data.get(user_id, RetrieveRule)` | `mos.data().getByUser(userId, rule)` |
| `Data.get(schema, rule=...)` | `mos.data().get(schema, rule)` |
| `Data.call` | `mos.data().call` |
| `memory_user_id()` | `MemoryEngineCredentials.memoryUserId(http)` |

> **跨字段检索**：Python 的 `Data.get(user_id, RetrieveRule)` 在 Java 中为 `getByUser`，因 Java 无法用第二个参数类型区分 `get(schema, rule)` 与 `get(user, rule)`。

## Maven 依赖

```xml
<dependency>
  <groupId>com.memoryengine</groupId>
  <artifactId>memory-engine-sdk</artifactId>
  <version>0.5.0</version>
</dependency>
```
