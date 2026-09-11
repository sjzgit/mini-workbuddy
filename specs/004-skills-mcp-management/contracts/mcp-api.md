# MCP Contract: MCP 管理（第四阶段）

**Base Path**: `/api/mcp/servers` | **Date**: 2026-09-10

本文件是 MCP 管理 HTTP 接口、测试结果分类与敏感信息规则的**主定义**（宪法 II/III）。后端 `backend/app/schemas/mcp.py`（Pydantic）与 `backend/app/services/mcp_service.py`、`mcp_client.py`、前端 `frontend/src/api/mcp.ts`（TypeScript 类型）MUST 与本文逐字段对齐，变更先改这里。

**通用约定**：所有响应为 JSON；错误统一 `{"detail": "人话错误信息"}`；**任何响应、日志、错误信息、测试结果与诊断信息不得包含环境变量或请求 Header 的完整原文**（FR-023，脱敏规则 §6）。

本版本支持两类 Server：`stdio`（本机启动）与 `http`（远程 HTTP）；**不支持 OAuth 与账号授权**（FR-018）。

## 1. 对外标识

Server 以数字 `id` 为标识（用户自建记录，同 002 模型管理惯例），HTTP 路径参数 `{id}`。

## 2. 数据结构

### McpServerItem（列表项）

| 字段 | 类型 | 说明 |
|------|------|------|
| `id` | number | 标识 |
| `name` | string | 名称（唯一） |
| `description` | string | 说明 |
| `server_type` | `"stdio"` \| `"http"` | 类型 |
| `enabled` | boolean | 启用状态 |
| `last_test_status` | `"success"` \| `"failed"` \| `"config_changed"` \| null | 最近一次测试结果状态；null = 未测试（前端显示"未测试"） |
| `last_test_message` | string \| null | 最近一次测试的人话提示（已脱敏） |
| `last_test_tool_count` | number \| null | 最近一次**成功**测试发现的工具数量；未成功为 null（前端显示"未知"） |
| `last_test_at` | string (ISO 8601) \| null | 最近一次测试完成时间 |
| `updated_at` | string (ISO 8601) | 最后更新时间 |

列表按 `updated_at` 倒序；`tools_json` 快照不经本结构下发（点击工具数量时经详情接口获取，§3）。

### McpServerDetail（详情，编辑页数据源）

McpServerItem 全部字段，另加：

| 字段 | 类型 | 说明 |
|------|------|------|
| `command` | string \| null | stdio：启动命令 |
| `command_args` | string[] \| null | stdio：启动参数（有序） |
| `env_masked` | object \| null | stdio：环境变量键 → 掩码值 `"••••••"`（未配置为 null） |
| `url` | string \| null | http：Server 地址 |
| `headers_masked` | object \| null | http：Header 键 → 掩码值 `"••••••"`（未配置为 null） |
| `tools` | `McpToolInfo[]` | 最近一次成功测试的工具快照（读 `tools_json`；未成功测试过为 `[]`），工具数量弹窗数据源 |

**MUST NOT 出现**：`env`/`headers` 明文、secret_ref 指针、任何密文。

### McpServerUpsertRequest（新增/编辑提交体，POST/PUT）

| 字段 | 类型 | 必填 | 校验 |
|------|------|------|------|
| `name` | string | 是 | 去空白后 1–100 字符；唯一（重复 → 400） |
| `description` | string | 否（默认 ""） | ≤ 500 字符 |
| `server_type` | `"stdio"` \| `"http"` | 是 | 枚举 |
| `command` | string \| null | server_type=stdio 时必填 | 非空 ≤ 500 字符；http 时必须为 null |
| `command_args` | string[] \| null | 否 | 每项 ≤ 500 字符，最多 64 项；http 时必须为 null；缺省 = `[]` |
| `env` | object \| null | 否 | 键：非空 ≤ 100 字符；值：`string \| null`（**null = 保留原值**，§5）；http 时必须为 null |
| `url` | string \| null | server_type=http 时必填 | 合法 http/https URL ≤ 500 字符；stdio 时必须为 null |
| `headers` | object \| null | 否 | 同 `env` 三态协议；stdio 时必须为 null |

**`env`/`headers` 三态协议**（FR-024 的契约表达）：

- 值为字符串 → 替换/新增该键（明文，服务端加密存储）；
- 值为 `null` → **保留该键原值**（不覆盖）；
- 键在提交对象中缺席 → 删除该键。

掩码值 `"••••••"` 永远不会被当作实际值保存——它只存在于只读展示层，不进入表单值。

### McpToggleRequest（启停提交体）

| 字段 | 类型 | 必填 |
|------|------|------|
| `enabled` | boolean | 是 |

### McpToolInfo（测试发现的单个工具 / tools_json 快照元素）

| 字段 | 类型 | 说明 |
|------|------|------|
| `name` | string | 工具名 |
| `description` | string | 用途（Server 未提供时为 ""） |
| `params` | `McpToolParam[]` | 参数说明（由 inputSchema 解析；无 schema 时 `[]`） |

### McpToolParam

| 字段 | 类型 | 说明 |
|------|------|------|
| `name` | string | 参数名 |
| `type` | string | 参数类型（JSON Schema type 原词：`string`/`number`/`boolean`/`object`/`array`/`integer`/未知 → `any`） |
| `required` | boolean | 是否必填（inputSchema.required 判定） |
| `description` | string | 参数含义（schema description，缺省 ""） |

### McpTestResult（POST …/test 响应）

| 字段 | 类型 | 说明 |
|------|------|------|
| `status` | `"success"` \| `"failed"` | 本次测试结果 |
| `category` | string \| null | 失败分类（§5 枚举）；成功为 null |
| `message` | string | 人话结果/失败提示（已脱敏） |
| `tool_count` | number \| null | 成功时 = 工具数量；失败为 null |
| `tools` | `McpToolInfo[]` | 成功时的工具列表（含参数表）；失败为 `[]` |
| `item` | `McpServerItem` | 测试后该 Server 的最新列表项（前端直接替换行） |

## 3. 接口

### 1. 列表

`GET /api/mcp/servers` → `200` `McpServerItem[]`（按 updated_at 倒序；空表 → `[]`）

### 2. 详情

`GET /api/mcp/servers/{id}` → `200` `McpServerDetail`；不存在 → `404` `{"detail": "MCP Server 不存在"}`

- 工具数量弹窗数据源：详情含 `tools` 字段（`McpToolInfo[]`，读自 `tools_json` 快照；未成功测试过为 `[]`）。

### 3. 新增

`POST /api/mcp/servers` body `McpServerUpsertRequest` → `201` `McpServerDetail`；同名 → `400`；字段互斥/格式非法 → `422`

- 创建即 `enabled=true`、无测试结果（`last_test_*` 全 NULL）。

### 4. 编辑

`PUT /api/mcp/servers/{id}` body `McpServerUpsertRequest` → `200` `McpServerDetail`；404/400/422 同上

- `env`/`headers` 按 §2 三态协议合并。
- **`config_changed` 判定**（FR-034）：`command`/`command_args`/`env`/`url`/`headers` 五项任一**实际值变化**（env/headers 解密后按 dict 相等比较）且存在旧测试结果 → `last_test_status='config_changed'`、`last_test_message='配置已变更，待重新测试'`（保留旧 tool_count/tools_json）。仅改 name/description 不触发。
- 测试进行中 → `400` `{"detail": "正在测试中，请稍后再试"}`。

### 5. 删除

`DELETE /api/mcp/servers/{id}` → `200` `{"deleted": true}`；不存在 → `404`

- 同事务删除行与两份密文（`secret_vault.delete_secret`）；测试进行中 → `400`（同上）。

### 6. 启停

`PUT /api/mcp/servers/{id}/enabled` body `McpToggleRequest` → `200` `McpServerItem`；404/422 同上

- 启停不影响测试结果，也不触发 `config_changed`（FR-032/034）。

### 7. 测试连接

`POST /api/mcp/servers/{id}/test` → `200` `McpTestResult`；不存在 → `404`；该 Server 测试进行中 → `400` `{"detail": "该 Server 正在测试中"}`

- 实际启动/连接 → 协议初始化 → 读取工具列表；**仅发现，不执行任何工具**（FR-026）。
- 无论成功、失败、超时，结束前关闭连接并清理进程（FR-031）。
- 结果写快照四列（成功同时写 tools_json）并随响应返回 `item`（FR-015）。
- 停用状态可测试；测试成功**不**自动启用（FR-033）。
- 总超时 `settings.mcp_test_timeout_seconds`（默认 30s）；超时按 `timeout` 分类失败。

## 4. 字段填写指引（FR-020 的页面呈现要求）

新增/编辑表单 MUST 常驻展示（antd Alert）：各字段含义、填写示例、以及一句提示——"配置通常可以从 MCP Server 的使用说明中获取，无需理解协议细节"。示例值：

| 字段 | 示例 |
|------|------|
| 启动命令（stdio） | `npx` 或 `C:\tools\server.exe` |
| 启动参数（stdio） | 每行一项，如 `-y`、`@modelcontextprotocol/server-filesystem`、`C:\data` |
| 环境变量（stdio） | 键如 `API_TOKEN`，值留空表示保留已保存的原值 |
| url（http） | `http://127.0.0.1:9300/mcp` |
| 请求 Header（http） | 键如 `Authorization`，值留空表示保留已保存的原值 |

## 5. 测试结果分类（枚举主定义，实现侧只消费）

| category | 人话提示（message 模板） |
|----------|--------------------------|
| `command_not_found` 启动命令不存在 | 启动命令不存在：请确认命令已安装且可在本机直接运行 |
| `process_failed` 启动失败或提前退出 | 程序启动失败或提前退出：请核对启动命令与参数是否完整（诊断信息见下） |
| `timeout` 连接或读取超时 | 连接或读取工具超时（{N} 秒）：Server 启动缓慢或无响应 |
| `protocol_incompatible` 协议不兼容 | 协议版本或响应格式不兼容：该 Server 与本系统支持的 MCP 协议不匹配 |
| `server_error` Server 返回错误 | Server 返回错误：{脱敏后的 Server 错误信息} |
| `connection_failed` 连接失败 | 连接失败：地址不可达或端口错误，请核对 url 与网络可达性 |
| `unknown` 未知错误 | 未知错误：暂时无法确定原因。诊断信息：{脱敏摘要 ≤ 500 字符} |

无工具的成功：`message = "连接成功，未发现工具"`、`tool_count = 0`（FR-027）。

## 6. 敏感信息规则（FR-023 的实现主定义）

1. 存储：env/headers 整体 JSON 序列化后 Fernet 加密入 `secrets_vault`，`mcp_servers` 只存指针（[data-model.md](../data-model.md)）。
2. 展示：只出 `env_masked`/`headers_masked`（键 + `"••••••"`），任何接口不回明文。
3. 脱敏函数（`_sanitize`）：对诊断文本，将本 Server 配置中所有长度 ≥ 4 的 env 值与 Header 值全量替换为 `******`；诊断摘要截断 500 字符；不输出完整命令行回显。
4. 删除 Server 时同步删除两份密文。

## 7. 前端类型派生要求

`frontend/src/api/mcp.ts` 的 `McpServerItem` / `McpServerDetail` / `McpServerUpsertPayload` / `McpTestResult` / `McpToolInfo` / `McpToolParam` / `TestStatus` / `TestCategory` 类型 MUST 按本文编写（null 不混用 undefined）。

## 8. 配置常量（进 `core/config.py`，环境变量可覆盖）

| 常量 | 默认值 | 消费方 |
|------|--------|--------|
| `mcp_test_timeout_seconds` | `30` | 测试连接总超时 |
