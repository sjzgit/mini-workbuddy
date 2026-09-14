# Data Model: Agent 管理（第七阶段）

**Date**: 2026-09-11 | **Feature**: [spec.md](./spec.md) | **Research**: [research.md](./research.md)

> 本文件是本特性数据模型的**主定义**（宪法 II SSOT）。`backend/app/models/__init__.py` 中的 ORM 字段与类型 MUST 与本文一致，变更先改本文再落 Alembic 迁移。既有表（models / tools / skills / mcp_servers / secrets_vault）主定义见各前期 spec 的 data-model.md，本阶段不改其结构。

## 实体关系总览

```text
agents 1 ──── n agent_bindings        （能力绑定：tool / skill / mcp 三类）
agents 1 ──── n agent_prompt_versions （提示词版本，只追加）
agents n ──── 1 models                （引用一个模型，业务引用非外键）
agent_bindings n ──── 1 tools / skills / mcp_servers（业务引用，见下方外键说明）
```

## 1. `agents` 表 —— Agent 主配置

| 字段 | 类型（SQLAlchemy / SQLite） | 约束 | 说明 |
|------|------|------|------|
| `id` | Integer | PK, autoincrement | |
| `name` | String(100) | NOT NULL | Agent 名称（不强制唯一，spec Assumptions） |
| `description` | String(500) | NOT NULL, default `''` | 用途说明 |
| `model_id` | Integer | NOT NULL | 引用 `models.id`；**不建数据库外键**（资源删除走应用层引用保护，见 §5），service 层校验存在性 |
| `system_prompt` | Text | NOT NULL, default `''` | 最新提示词快照（冗余自版本表最新行，直读免 join） |
| `max_rounds` | Integer | NOT NULL, default 10 | 最大执行轮数，正整数 1~100（常量主定义见 contracts） |
| `enable_deep_thinking` | Boolean | NOT NULL, default False | 深度思考开关（本阶段仅保存配置） |
| `thinking_level` | String(10) | NOT NULL, default `'off'` | 深度思考程度：off/low/medium/high（枚举主定义见 contracts） |
| `is_default` | Boolean | NOT NULL, default False | 部分唯一索引兜底，见下 |
| `created_at` | DateTime | NOT NULL, default utcnow | naive UTC（沿用 `_utcnow` 惯例） |
| `updated_at` | DateTime | NOT NULL, default utcnow, onupdate | |

**索引**：
- `uq_agents_single_default`：部分唯一索引 `(is_default)` WHERE `is_default = 1`（数据库层保证至多一个默认 Agent，research R2）
- `ix_agents_updated_at`：`(updated_at)`（列表按更新时间倒序）

**校验规则**（service + Pydantic 双层）：
- `name`：去空白后 1~100 字符，必填
- `model_id`：必须指向已存在的模型
- `max_rounds`：整数，1 ≤ x ≤ 100（默认 10）

## 2. `agent_bindings` 表 —— 能力绑定（通表）

| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| `id` | Integer | PK, autoincrement | |
| `agent_id` | Integer | NOT NULL, ForeignKey `agents.id`（ON DELETE CASCADE） | 归属 Agent；Agent 删除时级联清理绑定 |
| `resource_type` | String(10) | NOT NULL | `tool` \| `skill` \| `mcp`（枚举主定义见 contracts） |
| `resource_id` | Integer | NOT NULL | 指向 `tools.id` / `skills.id` / `mcp_servers.id` |
| `created_at` | DateTime | NOT NULL, default utcnow | |

**索引**：
- `uq_agent_bindings_unique`：唯一索引 `(agent_id, resource_type, resource_id)`（同一资源在同一 Agent 内不重复绑定）
- `ix_agent_bindings_resource`：`(resource_type, resource_id)`（反查"哪些 Agent 引用了此资源"——删除保护高频查询）

**约束规则**：
- **不建指向 tools/skills/mcp_servers 的数据库外键**：删除保护在应用层执行（先查引用、给人话报错、阻止删除），DB 外键只在 Agent 侧级联（agent_id → agents.id ON DELETE CASCADE）。
- `(resource_type, resource_id)` 组合必须指向真实存在且类型匹配的行——service 层保存时校验；`resource_type` 非法值被 Pydantic 枚举拒绝。
- 保存语义：整体覆写（删除旧绑定 + 插入新绑定），与 mcp 表 `tools_json` 快照的整体覆写惯例一致；保留绑定 = 保存的绑定集合中仍包含该资源。

## 3. `agent_prompt_versions` 表 —— 系统提示词版本（只追加）

| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| `id` | Integer | PK, autoincrement | |
| `agent_id` | Integer | NOT NULL, ForeignKey `agents.id`（ON DELETE CASCADE） | |
| `version` | Integer | NOT NULL | 从 1 起递增；`uq_agent_prompt_versions` 唯一索引 `(agent_id, version)` |
| `content` | Text | NOT NULL | 该版本完整提示词内容（大字段，不限长度） |
| `created_at` | DateTime | NOT NULL, default utcnow | 版本生成时间 |

**索引**：
- `uq_agent_prompt_versions`：唯一索引 `(agent_id, version)`

**状态规则**（FR-018~020）：
- 首次保存 Agent → 插入 version 1
- 后续保存：`payload.system_prompt != 最新版本内容` → 插入 `max(version)+1`；相同 → 不插
- 历史行只读：任何路径禁止 UPDATE / DELETE 此表（Agent 删除级联除外）
- 版本号变化只由提示词内容驱动；改名称/模型/绑定/轮数不产生新版本

## 4. 既有表（只读引用，本阶段不改结构）

| 表 | 本阶段用途 |
|----|-----------|
| `models` | Agent 引用的模型来源；删除前接入引用检查（FR-029：先查 Agent 引用，再走既有默认切换规则） |
| `tools` | 绑定来源之一；内置工具本无删除接口，无需改动 |
| `skills` | 绑定来源之一；删除前接入引用检查 |
| `mcp_servers` | 绑定来源之一；删除前接入引用检查 |

## 5. 引用保护与一致性规则

1. **引用检查**（`services/agent_references.py`）：删除模型 / skill / mcp 前按 `(resource_type, resource_id)` 反查 `agent_bindings`，命中即抛 `ReferencedByAgentError`（携带引用 Agent 名称列表）→ API 层 409。
2. **默认模型删除顺序**：Agent 引用检查 → 既有默认切换规则（FR-029）。
3. **默认 Agent 不变式**：任意写操作（新建/编辑/删除/设默认）后，`COUNT(is_default=1) ≤ 1` 恒成立；保存第一个 Agent 自动置默认；删最后一个默认 Agent 清除默认（页面回空状态）。
4. **删除默认 Agent（还有其他 Agent）**：必须携带 `new_default_id`（其余 Agent 之一），同一事务内"删旧 + 置新"；缺参 → 409 `requires_new_default`。
5. **绑定与停用**：绑定不快照 enabled；读取时实时 join 计算可用性（research R6）。

## 6. Alembic 迁移

- 007a 增量迁移：`agents` 表追加 `enable_deep_thinking`（BOOLEAN NOT NULL server_default 0）与 `thinking_level`（VARCHAR(10) NOT NULL server_default 'off'）两列。
- 首个迁移文件：新增三张表 + 全部索引（`backend/migrations/versions/`），downGRADE 依次 drop 三表。
- SQL 存档同步 `backend/sql/migrations/`（宪法数据库约束）。
