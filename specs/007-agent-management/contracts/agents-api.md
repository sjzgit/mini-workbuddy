# API Contract: Agent 管理（第七阶段）

**Base Path**: `/api/agents` | **Date**: 2026-09-11

本文件是前后端接口契约的**主定义**（宪法 II/III）。后端 `backend/app/schemas/agents.py`（Pydantic）与前端 `frontend/src/api/agents.ts`（TypeScript 类型）MUST 与本文逐字段对齐，变更先改这里。

**通用约定**（与 002~006 阶段一致）：

- 所有响应为 JSON；错误统一 `{"detail": "人话错误信息"}`。
- 字段校验失败返回 `422`；业务冲突返回 `409`；资源不存在返回 `404`；未引用检查通过被拒为 `409`。

## 枚举与常量（唯一主定义，实现侧只消费）

```text
ResourceType:
  tool    工具（tools 表）
  skill   技能（skills 表）
  mcp     MCP Server（mcp_servers 表）

ThinkingLevel:
  off     关闭
  low     低
  medium  中
  high    高

MAX_ROUNDS_DEFAULT = 10      最大执行轮数默认值
MAX_ROUNDS_MIN     = 1       最小值（正整数）
MAX_ROUNDS_MAX     = 100     最大值

CARD_BINDING_LIMIT = 3       卡片能力条目展示上限（纯前端展示规则；+N = 绑定总数 − 3）

深度思考常量:
  ENABLE_DEEP_THINKING_DEFAULT = false   深度思考开关默认值
  THINKING_LEVEL_DEFAULT       = "off"   深度思考程度默认值（关闭）

系统提示词默认模板: 常量 PROMPT_TEMPLATE（内容 = spec FR-009 规定的角色/目标/技能/工作流/输出格式/限制 六段文本，主定义在 backend/app/services/agent_service.py；经 GET /api/agents/binding-options 响应字段 prompt_template 下发，前端不复制文本，新建时取该值预填）
```

## 数据结构

### BindingItem（绑定项，读取时返回）

| 字段 | 类型 | 说明 |
|------|------|------|
| `resource_type` | ResourceType | `tool` \| `skill` \| `mcp` |
| `resource_id` | integer | 资源 id |
| `name` | string | 资源名称（tool.name / skill.dir_name / mcp.name） |
| `description` | string | 用途说明（tool/skill 的描述或占位文案、mcp.description） |
| `enabled` | boolean | 资源当前启用状态；false → 前端标"已停用，不可用"（实时计算，无快照） |

### BindingOption（候选项，选择区返回；只含启用资源）

| 字段 | 类型 | 说明 |
|------|------|------|
| `id` | integer | 资源 id |
| `name` | string | 名称 |
| `description` | string | 用途说明 |
| `selected` | boolean | 是否已被当前 Agent 绑定（编辑态回显用） |

### ModelOption（模型候选项）

| 字段 | 类型 | 说明 |
|------|------|------|
| `id` | integer | |
| `display_name` | string | 模型名称 |
| `model_identifier` | string | 模型标识（契约要求展示，不得只显示内部 id） |
| `is_default` | boolean | 是否当前默认模型（新建时前端默认选中） |

### PromptVersionItem（提示词版本）

| 字段 | 类型 | 说明 |
|------|------|------|
| `version` | integer | 版本号，从 1 起 |
| `content` | string | 该版本完整内容 |
| `created_at` | string (ISO 8601) | 生成时间 |

### AgentListItem（列表卡片项）

| 字段 | 类型 | 说明 |
|------|------|------|
| `id` | integer | |
| `name` | string | |
| `description` | string | |
| `model_display_name` | string | 所用模型名称（冗余直读，卡片直显） |
| `model_identifier` | string | 模型标识 |
| `tool_count` | integer | 工具绑定数（含停用） |
| `skill_count` | integer | Skills 绑定数（含停用） |
| `mcp_count` | integer | MCP Server 绑定数（含停用） |
| `bindings` | BindingItem[] | 全部绑定（tool→skill→mcp、id 升序；卡片按类分行展示用） |
| `is_default` | boolean | |
| `updated_at` | string (ISO 8601) | 最后更新时间 |

> `tool_count` / `skill_count` / `mcp_count` 为该类绑定计数（含停用）；`bindings` 为全量列表（含停用项，enabled 标记），不再做"至多 3 条"截断（FR-004 演进：按类分行全量展示）。

### AgentDetail（详情/保存返回）

| 字段 | 类型 | 说明 |
|------|------|------|
| `id` | integer | |
| `name` | string | |
| `description` | string | |
| `model_id` | integer | |
| `model_display_name` | string | |
| `model_identifier` | string | |
| `system_prompt` | string | 最新提示词内容 |
| `prompt_versions` | PromptVersionItem[] | 全部版本，按 version 升序 |
| `bindings` | BindingItem[] | 全部绑定（含停用资源，标记 enabled=false） |
| `max_rounds` | integer | |
| `enable_deep_thinking` | boolean | 深度思考开关 |
| `thinking_level` | string | ThinkingLevel 枚举（off/low/medium/high） |
| `is_default` | boolean | |
| `updated_at` | string (ISO 8601) | |

### AgentSaveRequest（新建/编辑提交体）

| 字段 | 类型 | 必填 | 校验 |
|------|------|------|------|
| `name` | string | 是 | 去空白后 1–100 字符；**全局唯一**——与其他 Agent 重名 → `409 {"detail": "已存在同名 Agent「xx」"}`；编辑时与自身同名允许 |
| `description` | string | 否 | ≤ 500 字符，默认 '' |
| `model_id` | integer | 是 | 必须指向已存在模型（422：模型不存在或未选择） |
| `system_prompt` | string | 是 | 允许空串；后端以此内容做版本判定 |
| `max_rounds` | integer | 否 | 1–100，缺省 10；非正整数 → 422 |
| `is_default` | boolean | 否 | 仅显式 true 时切换默认（自动取消旧默认）；缺省保持现状 |
| `enable_deep_thinking` | boolean | 否 | 深度思考开关，缺省 false |
| `thinking_level` | string | 否 | ThinkingLevel 枚举：off/low/medium/high，缺省 off；非法值 → 422 |
| `bindings` | array \| null | 否 | 元素 `{resource_type, resource_id}`；**缺省（null）= 保持原绑定不变；显式 `[]` = 清空全部绑定**；resource_type 非法 → 422；resource_id 不存在 → 422；同一资源重复 → 422 |

**保存语义**：编辑时 `bindings` 非缺省则整体覆写（提交集合为准：不含 = 移除，含 = 保留/新增）；缺省则绑定原样保留（便于"仅改其他配置"场景）。提示词版本按 research R5 规则判定。

### AgentOption（删除默认 Agent 时供选择的候选）

| 字段 | 类型 | 说明 |
|------|------|------|
| `id` | integer | |
| `name` | string | |

### 资源候选项接口的三类响应

`{options: BindingOption[]}` 与 `{models: ModelOption[]}`；空集合返回空数组（前端渲染引导/空态）。

## 接口

### 1. 列表

`GET /api/agents` → `200` `AgentListItem[]`

- 排序：默认 Agent 置顶（至多一个），其余按 `updated_at` 倒序；空表返回 `[]`（前端据此渲染空状态）。

### 2. 详情

`GET /api/agents/{agent_id}` → `200` `AgentDetail`；不存在 → `404`

### 3. 新建

`POST /api/agents` body `AgentSaveRequest` → `201` `AgentDetail`

- 系统中无任何 Agent 时自动 `is_default = true`（FR-021），无论 payload 是否显式要求。
- 显式 `is_default: true` 时取消旧默认（FR-022）。
- 首次保存生成提示词版本 1（FR-018）。

### 4. 编辑

`PUT /api/agents/{agent_id}` body `AgentSaveRequest` → `200` `AgentDetail`；不存在 → `404`

- 版本规则：`system_prompt` 与最新版本不同 → 新增版本（max+1）；相同或未变 → 不新增（FR-018/019）。
- `is_default: true` → 切换默认；`is_default: false` 且当前已是默认 → 允许保存（默认状态不变：系统必须始终有默认，见 FR-021 的"有 Agent 时保持一个默认项"）。

### 5. 删除

`DELETE /api/agents/{agent_id}?new_default_id={id?}` → `200` `{"deleted": true, "cleared_default": bool}`

- 删除默认 Agent 且还有其他 Agent 且 `new_default_id` 缺失 → `409`：

  ```json
  {
    "detail": "该 Agent 是默认 Agent，请先选择新的默认 Agent",
    "requires_new_default": true,
    "candidates": [AgentOption]
  }
  ```

- `new_default_id` 不属于其余 Agent → `400`；删除最后一个 Agent → `cleared_default: true`（页面据此回空状态）。
- 删除普通 Agent（非默认）→ 直接删除，`cleared_default: false`。

### 6. 设为默认

`POST /api/agents/{agent_id}/default` → `200` `{"id": agent_id}`

- 自动取消旧默认；已是默认 → 幂等成功。

### 7. 发布（无独立端点）

"发布" = 编辑端点（PUT）整体保存，不设独立发布接口（spec Assumptions：本阶段无发布状态机）。

### 8. 资源候选项

`GET /api/agents/binding-options` → `200`

```json
{
  "tools":   [BindingOption],
  "skills":  [BindingOption],
  "mcp_servers": [BindingOption],
  "models":  [ModelOption],
  "prompt_template": "string（系统提示词默认模板全文）"
}
```

- 一个请求聚合四类候选；仅含**启用**的资源（FR-016）；`selected` 按可选 query 参数 `agent_id`（编辑态）回显。
- 无模型时 `models: []`——前端渲染"先添加模型"引导（FR-014）。

## 引用保护（接入既有接口）

以下既有接口在删除链路最前端增加 Agent 引用检查（research R4），被引用时返回：

`409` `{"detail": "「<资源名>」正被 Agent「A」「B」使用，请先在对应 Agent 中移除绑定或更换模型后重试", "referenced_by_agents": [{"id": 1, "name": "A"}]}`

| 既有接口 | 检查 |
|----------|------|
| `DELETE /api/models/{model_id}` | 先查 Agent 引用（含默认模型），**后**走既有默认切换规则（FR-029） |
| `DELETE /api/skills/{dir_name}` | 先查 Agent 引用，后执行目录删除 |
| `DELETE /api/mcp/servers/{server_id}` | 先查 Agent 引用，后清理 |

内置工具本无删除接口，保持不变（FR-028）。
