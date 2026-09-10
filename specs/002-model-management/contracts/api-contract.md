# API Contract: 模型管理（第二阶段）

**Base Path**: `/api/models` | **Date**: 2026-09-10

本文件是前后端接口契约的**主定义**（宪法 II/III）。后端 `backend/app/schemas/model.py`（Pydantic）与前端 `frontend/src/api/models.ts`（TypeScript 类型）MUST 与本文逐字段对齐，变更先改这里。

**通用约定**：

- 所有响应为 JSON；错误统一 `{"detail": "人话错误信息"}`，detail 永不包含密钥正文与堆栈（FR-011）。
- 字段校验失败返回 `422`，detail 为面向用户的说明；业务冲突（如默认模型处理违规）返回 `409` 或 `400`。
- 所有响应体中的 `api_key_configured` 是密钥的**唯一**对外信息；任何响应不含密钥明文/密文。

## 枚举与常量（唯一主定义，实现侧只消费）

```text
TestErrorCategory:
  auth_error        密钥错误
  model_not_found   模型标识错误
  unreachable       服务地址不可访问
  timeout           请求超时
  bad_response      返回格式异常
  unknown           无法确定原因

请求超时: 30s
测试连接 max_tokens: 64（取 min(64, 模型配置的 max_output_tokens)）
测试连接提示语: "你好，请回复：连接成功" 之类的固定短句
```

## 数据结构

### ModelItem（列表项）

| 字段 | 类型 | 说明 |
|------|------|------|
| `id` | integer | |
| `display_name` | string | 显示名称 |
| `model_identifier` | string | 模型标识 |
| `base_url` | string | 服务地址（规范形式） |
| `context_length` | integer | 上下文长度（token） |
| `api_key_configured` | boolean | 密钥是否已配置 |
| `is_default` | boolean | 是否默认模型 |
| `updated_at` | string (ISO 8601) | 最后更新时间 |

### ModelDetail（详情，含可选字段）

ModelItem 全部字段，另加：

| 字段 | 类型 | 说明 |
|------|------|------|
| `max_output_tokens` | integer | |
| `temperature` | number | |
| `input_price` | number \| null | 未配置为 null，免费为 0 |
| `output_price` | number \| null | |
| `cached_input_price` | number \| null | |

### ModelUpsertRequest（新增/编辑提交体）

| 字段 | 类型 | 必填 | 校验 |
|------|------|------|------|
| `display_name` | string | 是 | 去空白后 1–100 字符 |
| `model_identifier` | string | 是 | 去空白后 1–200 字符 |
| `base_url` | string | 是 | http/https 合法 URL；不以 `/chat/completions` 结尾 |
| `api_key` | string \| null | 否 | 编辑时省略/为空=保留原密钥；填写=替换 |
| `context_length` | integer | 是 | 正整数 |
| `max_output_tokens` | integer | 是 | 正整数，≤ context_length |
| `temperature` | number | 是 | 0 ≤ x ≤ 2 |
| `input_price` | number \| null | 否 | ≥ 0；null 与 0 含义不同 |
| `output_price` | number \| null | 否 | ≥ 0 |
| `cached_input_price` | number \| null | 否 | ≥ 0 |

## 接口

### 1. 列表

`GET /api/models` → `200` `ModelItem[]`

- 按更新时间倒序。空表返回 `[]`（前端据此渲染空状态）。

### 2. 详情

`GET /api/models/{id}` → `200` `ModelDetail`；不存在 → `404`

### 3. 新增

`POST /api/models` body `ModelUpsertRequest` → `201` `ModelDetail`

- 若当前无默认模型，自动 `is_default = true`（FR-018）。
- `api_key` 非空时加密入库，`api_key_configured = true`。

### 4. 编辑

`PUT /api/models/{id}` body `ModelUpsertRequest` → `200` `ModelDetail`；不存在 → `404`

- `api_key` 为 null/空字符串：保留原密钥（FR-012）；非空：替换。
- 不改变 `is_default`。

### 5. 删除

`DELETE /api/models/{id}?new_default_id={id?}` → `200` `{"deleted": true}`；不存在 → `404`

- 删除**非默认**模型：无需 `new_default_id`。
- 删除**默认**模型且存在其他模型：`new_default_id` **必填**且必须指向存在的其他模型，否则 `400`；同事务完成"设新默认 + 删除 + 清理密钥"（FR-020/021）。
- 删除最后一个模型：无需 `new_default_id`；删除后清空默认状态与密钥。

### 6. 设置默认

`POST /api/models/{id}/default` → `200` `{"id": <id>, "is_default": true}`；不存在 → `404`

- 同事务取消旧默认（FR-019）；部分唯一索引兜底唯一性。

### 7. 测试连接

`POST /api/models/{id}/test-connection` → `200` `TestConnectionResult`；不存在 → `404`

```text
TestConnectionResult:
  success: boolean
  category: TestErrorCategory | null    # success=true 时为 null
  message: string                       # 人话提示，含排查建议；不含密钥与堆栈
  reply_excerpt: string | null          # success 时的一小段真实回复（截断至 200 字符）
```

各类别 message 模板（主定义，前端原样展示）：

| category | message 模板 |
|----------|-------------|
| `auth_error` | "认证失败：API Key 无效或无权限。请核对密钥是否正确、是否过期。" |
| `model_not_found` | "模型标识不存在：服务端不认识该 model 名称。请核对与服务商提供的模型标识是否一致。" |
| `unreachable` | "服务地址不可访问。请检查地址是否可达、是否需要 VPN/内网、/v1 写法是否正确（示例：https://api.example.com/v1）。" |
| `timeout` | "请求超时（30 秒）。请检查网络状况或服务端负载。" |
| `bad_response` | "服务返回了无法识别的内容。该地址可能不是 OpenAI Chat Completions 兼容接口。" |
| `unknown` | "连接失败，暂时无法确定原因。请稍后重试或检查模型配置。" |

## 前端类型派生要求

`frontend/src/api/models.ts` 中的 `ModelItem` / `ModelDetail` / `ModelUpsertPayload` / `TestConnectionResult` / `TestErrorCategory` 类型 MUST 按本文定义编写，禁止手改字段名或放宽类型（null vs undefined 不混用，统一 null）。
