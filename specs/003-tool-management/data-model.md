# Data Model: 工具管理（第三阶段）

**Date**: 2026-09-10 | **Source of Truth**: 本文件是数据模型的主定义（宪法 II/III），实现侧 SQLAlchemy ORM（`backend/app/models/`）字段与类型 MUST 与本文一致，变更必须先改这里再落 Alembic 迁移。

工具**元数据**（名称、说明、参数）不入库，主定义在 [contracts/tool-definitions.md](contracts/tool-definitions.md)（实现载体为代码注册表）；数据库只承载**注册事实与启停状态**——两者职责划分见 [research.md](research.md) R1。

## 实体关系

```text
tools（工具注册与启停状态表）
┌──────────────────────────┐
│ id (PK)                  │      元数据（不入库）：
│ name (UNIQUE)  ◄─────────┼────  services/tool_registry.py 按 name 关联
│ enabled                   │      （display_name / purpose / params / 说明文本）
│ created_at / updated_at   │
└──────────────────────────┘
```

- 无外键、无其他表关联（本阶段唯一新表）。
- `tools.name` 的合法取值 = 注册表键集合（`current_time` / `shell` / `file_read_write`）；执行入口"存在性"查注册表、"启停"查本表，两侧以 name 对齐（research R2）。

## 表：tools

| 列 | 类型 | 约束 / 默认 | 说明 |
|----|------|------------|------|
| `id` | INTEGER | PK, 自增 | 内部主键，不出现在 API 契约中 |
| `name` | VARCHAR(50) | NOT NULL, UNIQUE | 注册表键（工具标识），Agent 调用与 HTTP 路径均使用此键 |
| `enabled` | BOOLEAN | NOT NULL, DEFAULT 1 | 启停状态；停用后统一执行入口拒绝调用（FR-006） |
| `created_at` | DATETIME | NOT NULL, 当前时间(UTC) | 播种时间 |
| `updated_at` | DATETIME | NOT NULL, 每次更新刷新(UTC) | 列表"最后更新时间"来源 |

**索引**：`uq_tools_name`（唯一索引，name）；无其他索引（数据量恒为个位数）。

**校验规则**：

1. `name` 去空白后非空，且必须存在于代码注册表中——服务层在播种与启停时校验（HTTP 层对未知 name 返回 404，不产生脏行）。
2. `enabled` 为布尔值，无第三态。
3. 系统内置工具的行只能更新 `enabled`（无删除、无用途修改路径，FR-007 由"不提供此类接口"保证）。

## 初始数据（迁移播种）

建表迁移同版本插入三行（主定义见 [contracts/tool-definitions.md](contracts/tool-definitions.md)）：

| name | enabled |
|------|---------|
| `current_time` | 1 |
| `shell` | 1 |
| `file_read_write` | 1 |

幂等引导函数 `tool_service.ensure_seeded(session)`（插入注册表中尚缺的行，不覆盖已有启停状态）供测试夹具与运维恢复使用，正常运行时不自动调用（research R1）。

## 状态与生命周期

```text
[空表（迁移前/被清空）] --迁移播种 / ensure_seeded--> [3 行内置工具，全部启用]
[启用] --停用（确认）--> [enabled=0]                  # 执行入口随即拒绝（FR-006）
[enabled=0] --启用（确认）--> [enabled=1]              # 执行入口恢复可用
任意状态 --重启后端--> 保持                            # 持久化（FR-008）
```

- 列表接口返回 DB 行 ⨝ 注册表元数据；DB 无行时返回 `[]`（前端渲染空状态，US1 场景 3 / Edge Case）。
- 播种行与注册表键不一致时（理论上的版本漂移），以注册表为准做 ensure_seeded 补齐；多余的 DB 行不出现在列表（注册表查无此键即跳过）。

## 与 spec 需求的映射

| spec 需求 | 数据层落点 |
|-----------|-----------|
| FR-001 列表字段 | tools 行（name/enabled/updated_at）+ 注册表元数据（display_name/purpose/params）联查 |
| FR-002 空状态 | tools 空表 → 列表返回 `[]` |
| FR-005/006 启停与调用联动 | tools.enabled 是执行入口第 2 道检查的数据来源 |
| FR-007 内置保护 | 无删除/用途修改接口；ORM 层不提供此类操作 |
| FR-008 持久化 | tools 表落 SQLite，重启保留 |
| FR-010 执行前检查 | 存在性 → 注册表；启停 → tools 行；参数 → 注册表 Pydantic 模型（非本表） |
