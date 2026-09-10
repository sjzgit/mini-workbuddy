# API Contract: 工具管理（第三阶段）

**Base Path**: `/api/tools` | **Date**: 2026-09-10

本文件是工具管理 HTTP 接口契约的**主定义**（宪法 II/III）。后端 `backend/app/schemas/tool.py`（Pydantic）与前端 `frontend/src/api/tools.ts`（TypeScript 类型）MUST 与本文逐字段对齐，变更先改这里。

工具标识、参数定义、统一执行结果与错误码的主定义见 [tool-definitions.md](tool-definitions.md)——本文的 `ToolItem` / `ToolDetail` 引用其内容。

**通用约定**：

- 所有响应为 JSON；错误统一 `{"detail": "人话错误信息"}`（沿用 002 既有全局 422 处理与约定），detail 不含堆栈与内部路径。
- 路径参数 `{name}` 为注册表键（`current_time` / `shell` / `file_read_write`），非数字 id（research R2）。
- **本阶段无执行类 HTTP 端点**（统一执行入口为进程内服务，见 [tool-definitions.md](tool-definitions.md)）；**无删除端点**（FR-007：系统内置工具不允许删除，接口层不提供）。

## 数据结构

### ToolItem（列表项）

| 字段 | 类型 | 说明 |
|------|------|------|
| `name` | string | 工具标识（注册表键） |
| `display_name` | string | 显示名称（如"当前时间"） |
| `purpose` | string | 用途说明（一句话，列表展示） |
| `params_summary` | string | 参数概要（如 `timezone（可选）`，多项以 `、` 连接） |
| `enabled` | boolean | 启用状态 |
| `is_builtin` | boolean | 是否系统内置（本阶段恒为 true） |
| `updated_at` | string (ISO 8601) | 最后更新时间 |

### ToolDetail（详情）

ToolItem 全部字段，另加：

| 字段 | 类型 | 说明 |
|------|------|------|
| `params` | `ToolParam[]` | 参数定义列表（完整含义） |
| `usage_scenarios` | string | 适用场景 |
| `input_requirements` | string | 输入要求 |
| `restrictions` | string | 使用限制 |

### ToolParam

| 字段 | 类型 | 说明 |
|------|------|------|
| `name` | string | 参数名 |
| `type` | string | 类型（`string` / `enum`） |
| `required` | boolean | 是否必填 |
| `description` | string | 参数含义与填写说明 |

### ToolToggleRequest（启停提交体）

| 字段 | 类型 | 必填 | 校验 |
|------|------|------|------|
| `enabled` | boolean | 是 | 仅接受布尔值 |

## 接口

### 1. 列表

`GET /api/tools` → `200` `ToolItem[]`

- 按 `name` 字母序返回；空表返回 `[]`（前端据此渲染空状态，FR-002）。

### 2. 详情

`GET /api/tools/{name}` → `200` `ToolDetail`；未知 name → `404` `{"detail": "工具不存在"}`

### 3. 启停

`PUT /api/tools/{name}/enabled` body `ToolToggleRequest` → `200` `ToolItem`；未知 name → `404`；body 非法 → `422`

- 更新 `tools.enabled` 并刷新 `updated_at`，返回更新后的完整列表项（FR-005）。
- 系统内置工具允许启停；无其他可修改字段（FR-007）。

## 前端类型派生要求

`frontend/src/api/tools.ts` 中的 `ToolItem` / `ToolDetail` / `ToolParam` / `ToolTogglePayload` 类型 MUST 按本文与 [tool-definitions.md](tool-definitions.md) 编写，禁止手改字段名或放宽类型（null 不混用 undefined）。
