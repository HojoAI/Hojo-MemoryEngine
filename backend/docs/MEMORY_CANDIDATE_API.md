# M13 候选记忆接口

候选记忆接口用于“添加记忆”页面的分析和确认前预览。两个接口都不会写入、更新或删除记忆。

## 公共约定

- 服务内前缀：`/api/v1`。如果 management 网关去除 `/api`，对外路径为 `/v1/...`。
- 请求和业务响应字段使用 camelCase；请求同时兼容 snake_case。
- `Content-Type: application/json`。
- 正常鉴权模式使用 `Authorization: Bearer <MemoryEngine API Key>`，API Key 需要 `data:read`、`data:*` 或 `*` 权限。
- `X-Tenant-Id` 和 `X-Org-Id` 可省略，省略时从 API Key 获取；显式传入时必须与 API Key 一致。
- `X-User-Id` 不决定目标记忆用户；目标用户由请求体 `userId` 指定。
- 这两个接口不使用 H5 的 `X-User-Token`。
- `APP_DISABLE_AUTH=true` 时不校验 API Key，但 `X-Tenant-Id` 必填，`X-Org-Id` 默认 `0`。

成功响应统一封装：

```json
{
  "code": 0,
  "message": "ok",
  "data": {}
}
```

## 提取候选记忆

`POST /api/v1/memory/candidates/extract`

将文本、语音转写文本或 OSS 文档拆成原子记忆，归入 `identity / projects / preferences / terms`，并识别敏感内容。

### 请求

```json
{
  "requestId": "req_add_001",
  "userId": "user_10001",
  "scene": "memory_add",
  "source": {
    "type": "import_file",
    "sourceId": "file_001",
    "ossUrl": "https://bucket.oss-cn-shanghai.aliyuncs.com/memory.pdf?...",
    "text": "OSS 不可用时的调用方原始文本"
  },
  "language": "zh-CN",
  "categorySchemaVersion": "m13-v1",
  "allowedCategories": ["identity", "projects", "preferences", "terms"],
  "options": {
    "atomic": true,
    "detectSensitivity": true,
    "extractTerms": true
  }
}
```

顶层字段：

| 字段 | 类型 | 必填 | 默认值 | 约束与含义 |
|---|---|---:|---|---|
| `requestId` | string | 否 | `req_{uuid}` | 最长 128；同时作为 LLM 计费事件 trace ID。 |
| `userId` | string | 是 | - | 长度 1～255；候选记忆所属用户。 |
| `scene` | string | 否 | `memory_add` | `memory_add` 或 `memory_supplement`。 |
| `source` | object | 是 | - | 原始内容，定义见下表。 |
| `language` | string | 否 | `zh-CN` | 长度 2～32；用于模型输出语言。 |
| `categorySchemaVersion` | string | 否 | `m13-v1` | 最长 32。 |
| `allowedCategories` | string[] | 否 | 全部四类 | 1～4 个不重复分类。 |
| `options` | object | 否 | 全部为 `true` | 提取选项。 |

`source` 字段：

| 字段 | 类型 | 必填 | 约束与含义 |
|---|---|---:|---|
| `type` | string | 是 | `manual_text / manual_audio / import_file / memory_supplement`。 |
| `sourceId` | string | 否 | 最长 255；来源文件、录音或业务记录 ID。 |
| `ossUrl` | string | 条件必填 | 最长 4096；HTTPS OSS 文档地址。 |
| `text` | string | 条件必填 | 长度 1～200000；直接输入或已转换的文本。 |

`ossUrl` 和 `text` 至少有一个有效值，选择规则固定为：

1. `ossUrl` 去除首尾空白后非空：下载并解析 OSS 文档，忽略 `text`；内部来源类型按 `import_file` 处理。
2. `ossUrl` 缺失、为 `null`、空字符串或仅含空白：直接使用 `text`。
3. 两者都为空：返回 422。
4. 非空 `ossUrl` 下载或解析失败：返回对应错误，不回退到 `text`。

OSS 文档规则：

- 只接受 HTTPS。
- 默认允许阿里云 OSS 域名；自定义 CNAME 通过 `MEMORY_CANDIDATE_OSS_ALLOWED_HOSTS` 配置，多个域名以逗号分隔。
- 不跟随 HTTP 重定向，调用方应传最终预签名 URL。
- 支持 `.md`、`.markdown`、`.txt` 和含文本层的 `.pdf`。
- TXT/Markdown 支持 UTF-8、UTF-8 BOM 和 GB18030。
- 默认下载上限 20 MiB、超时 15 秒；PDF 最多 500 页；解析正文最多 200000 字符。
- 加密 PDF 不支持；没有文本层的扫描 PDF 暂不支持 OCR。
- OSS 预签名 URL 只用于下载，不发送给 LLM，也不在响应中返回。

相关环境变量：

| 变量 | 默认值 | 说明 |
|---|---:|---|
| `MEMORY_CANDIDATE_OSS_TIMEOUT_SECONDS` | `15` | 下载超时秒数。 |
| `MEMORY_CANDIDATE_OSS_MAX_BYTES` | `20971520` | 最大下载字节数。 |
| `MEMORY_CANDIDATE_OSS_ALLOWED_HOSTS` | 空 | 额外允许的 OSS 主机或域名后缀，逗号分隔。 |

`options` 字段：

| 字段 | 类型 | 默认值 | 含义 |
|---|---|---:|---|
| `atomic` | boolean | `true` | 将独立事实拆成多条候选。 |
| `detectSensitivity` | boolean | `true` | 检测敏感和禁止保存内容。 |
| `extractTerms` | boolean | `true` | 提取专有名词、别名和定义。 |

分类值：

| 值 | 页面分类 | 内容范围 |
|---|---|---|
| `identity` | 认识一下你 | 身份、职业、公司、职责和稳定背景。 |
| `projects` | 项目 | 项目、团队、合作人、目标、里程碑和工作上下文。 |
| `preferences` | 偏好 | 工作习惯、沟通偏好、长期喜好和厌恶。 |
| `terms` | 名词 | 专有名词、缩写、产品名、别名和术语定义。 |

### 响应

```json
{
  "code": 0,
  "message": "ok",
  "data": {
    "requestId": "req_add_001",
    "modelVersion": "gpt-4o-mini",
    "categorySchemaVersion": "m13-v1",
    "candidates": [
      {
        "candidateId": "cand_add_001_1",
        "category": "identity",
        "label": "职业职责",
        "content": "用户在 Acme 负责企业产品。",
        "confidence": 0.96,
        "sensitivity": "normal",
        "sourceSpans": [
          {"segmentId": "seg_1", "start": 0, "end": 16}
        ]
      }
    ],
    "rejected": [],
    "warnings": []
  }
}
```

`data` 字段：

| 字段 | 类型 | 含义 |
|---|---|---|
| `requestId` | string | 原请求 ID。 |
| `modelVersion` | string | 实际使用的模型。 |
| `categorySchemaVersion` | string | 分类规则版本。 |
| `candidates` | object[] | 提取成功的候选记忆。 |
| `rejected` | object[] | 被拒绝的片段和原因。 |
| `warnings` | string[] | 文档解析或模型处理提示。 |

`candidates[]` 字段：

| 字段 | 类型 | 必有 | 约束与含义 |
|---|---|---:|---|
| `candidateId` | string | 是 | 服务生成的候选 ID。 |
| `category` | string | 是 | 四类之一。 |
| `label` | string | 是 | 长度 1～64；页面展示标题。 |
| `content` | string | 是 | 长度 1～16000；原子记忆正文。 |
| `confidence` | number | 是 | 0～1。 |
| `sensitivity` | string | 是 | `normal / sensitive / prohibited`。 |
| `sensitiveType` | string | 否 | 最长 64；敏感内容类型。 |
| `sensitiveReason` | string | 否 | 最长 1000；敏感判定原因。 |
| `sourceSpans` | object[] | 是 | 最多 50 个原文位置；无法确定时为空。 |
| `term` | object | 否 | 仅 `category=terms` 时允许。 |

`sourceSpans[]` 包含可选 `segmentId`、非负整数 `start` 和 `end`，且 `end >= start`。

`term` 包含：

- `text`：标准名词，长度 1～255。
- `aliases`：别名数组，最多 20 个。
- `definition`：可选定义，最长 4000。

`rejected[]` 包含 `content` 和 `reason`。

## 比较候选记忆

`POST /api/v1/memory/candidates/compare`

将一条候选与指定用户、namespace 下的当前有效记忆比较。接口读取已有记忆，但不修改数据。

### 请求

```json
{
  "requestId": "req_compare_001",
  "userId": "user_10001",
  "candidate": {
    "candidateId": "cand_add_001_2",
    "category": "projects",
    "label": "企业版定价试点",
    "content": "用户正在推进 Q3 企业版定价试点。",
    "confidence": 0.94,
    "sensitivity": "normal",
    "sourceSpans": []
  },
  "namespaceType": "user",
  "namespaceId": "default",
  "candidateLimit": 40,
  "language": "zh-CN"
}
```

| 字段 | 类型 | 必填 | 默认值 | 约束与含义 |
|---|---|---:|---|---|
| `requestId` | string | 否 | `req_{uuid}` | 最长 128。 |
| `userId` | string | 是 | - | 长度 1～255；待查询记忆的用户。 |
| `candidate` | object | 是 | - | 单条候选，字段与 extract 的 `candidates[]` 相同；`candidateId` 可省略。 |
| `namespaceType` | string | 否 | `user` | 最长 64。 |
| `namespaceId` | string | 否 | `default` | 最长 255。 |
| `candidateLimit` | integer | 否 | `40` | 1～100；参与比较的当前记忆数量上限。 |
| `language` | string | 否 | `zh-CN` | 长度 2～32；展示原因的语言。 |

已有记忆按 `API Key tenant + API Key organization + userId + namespaceType + namespaceId` 隔离。

### 响应

```json
{
  "code": 0,
  "message": "ok",
  "data": {
    "requestId": "req_compare_001",
    "modelVersion": "gpt-4o-mini",
    "result": "MERGE",
    "confidence": 0.91,
    "matchedItemIds": ["mc_79f5dc36"],
    "reasonCode": "SAME_PROJECT_WITH_NEW_PROGRESS",
    "displayReason": "属于同一个项目，并补充了季度进展。",
    "mergePreview": {
      "content": "用户正在推进企业版定价试点，并计划在 Q3 完成。",
      "baseItemId": "mc_79f5dc36",
      "baseVersion": 3
    }
  }
}
```

| 字段 | 类型 | 含义 |
|---|---|---|
| `requestId` | string | 原请求 ID。 |
| `modelVersion` | string | 模型名称；确定性规则返回时带 `:deterministic`。 |
| `result` | string | `NEW / DUPLICATE / MERGE / CONFLICT / REJECT`。 |
| `confidence` | number | 0～1。 |
| `matchedItemIds` | string[] | 相关的已有记忆 ID。 |
| `reasonCode` | string | 最长 128；供程序判断和埋点使用。 |
| `displayReason` | string | 最长 1000；页面展示原因。 |
| `mergePreview` | object | 仅 `MERGE` 返回。 |

结果含义：

| result | 含义 |
|---|---|
| `NEW` | 未发现重复或冲突，可作为新记忆。 |
| `DUPLICATE` | 与已有记忆表达同一事实。 |
| `MERGE` | 同一主题且可安全合并，返回合并预览。 |
| `CONFLICT` | 与已有记忆表达互不兼容的事实。 |
| `REJECT` | 不适合作为记忆保存。 |

`DUPLICATE / MERGE / CONFLICT` 必须至少包含一个真实 `matchedItemIds`。`MERGE` 的 `mergePreview` 包含 `content`、`baseItemId` 和当前 `baseVersion`，且 `baseItemId` 必须出现在 `matchedItemIds` 中。

以下情况使用确定性规则，不调用 LLM：

- `candidate.sensitivity=prohibited`：`REJECT / PROHIBITED_CONTENT`。
- namespace 下没有已有记忆：`NEW / NO_EXISTING_MEMORY`。
- 忽略大小写和空白后与已有记忆完全相同：`DUPLICATE / EXACT_MATCH`。

## 错误响应

鉴权和权限错误返回 HTTP 403：

```json
{"detail": "Missing permission: data:read"}
```

请求字段或业务校验错误返回 HTTP 422。字段错误的 `detail` 是数组，业务错误的 `detail` 是带稳定前缀的字符串。OSS 和文档错误包括：

| detail 前缀 | 含义 |
|---|---|
| `INVALID_OSS_URL` | URL 不是 HTTPS 或域名不在允许范围。 |
| `OSS_REDIRECT_NOT_ALLOWED` | OSS URL 返回重定向。 |
| `OSS_DOWNLOAD_FAILED` | OSS 下载网络错误或上游返回错误状态。 |
| `OSS_FILE_TOO_LARGE` | 下载内容超过限制。 |
| `UNSUPPORTED_DOCUMENT_TYPE` | 不是 Markdown、TXT 或 PDF。 |
| `DOCUMENT_DECODE_FAILED` | 文本编码不支持。 |
| `DOCUMENT_ENCRYPTED` | PDF 已加密。 |
| `DOCUMENT_TOO_MANY_PAGES` | PDF 超过 500 页。 |
| `DOCUMENT_PARSE_FAILED` | PDF 损坏或解析失败。 |
| `DOCUMENT_TEXT_EMPTY` | 文档没有可提取文本，可能需要 OCR。 |
| `DOCUMENT_TEXT_TOO_LARGE` | 解析正文超过 200000 字符。 |
| `EXTRACTION_FAILED` | 模型返回的候选结构不合法。 |
| `INVALID_CATEGORY` | 模型返回了调用方未允许的分类。 |
| `COMPARE_FAILED` | 比较结果、关联 ID、置信度或合并预览不合法。 |

LLM、MongoDB 或计费服务发生未处理异常时返回 HTTP 500。接口当前不提供服务端自动重试或结果缓存。
