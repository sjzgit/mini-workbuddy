# Data Model: Skills 与 MCP 管理（第四阶段）

**Date**: 2026-09-10 | **Source of Truth**: 本文件是数据模型的主定义（宪法 II/III），实现侧 SQLAlchemy ORM（`backend/app/models/`）字段与类型 MUST 与本文一致，变更必须先改这里再落 Alembic 迁移。

本特性新增 `skills`、`mcp_servers` 两表，并**复用**既有 `secrets_vault` 表（002 主定义）承载 MCP 敏感值密文。Skill 内容文本以文件为本体（[research.md](research.md) R1），不入库。

## 实体关系

```text
skills（Skill 启用状态表）                workspace/skills/<dir_name>/skill.md（内容事实源，不入库）
┌──────────────────────────┐
│ id (PK)                  │      列表页的 name/description/instruction 实时读文件，
│ dir_name (UNIQUE) ◄──────┼────  以 dir_name 关联目录；DB 只出 enabled。
│ enabled                  │      刷新动作做"目录 ↔ 行"双向同步（research R1）。
│ created_at / updated_at  │
└──────────────────────────┘

mcp_servers（MCP Server 配置与测试快照表）     secrets_vault（既有，002）
┌───────────────────────────────┐
│ id (PK)                       │
│ name (UNIQUE)                 │
│ description                   │
│ server_type ('stdio'|'http')  │
│ command / command_args (JSON) │
│ env_secret_ref  ──────────────┼──► secrets_vault.id（密文 = JSON(env dict)）
│ url / headers_secret_ref      │
│                 ──────────────┼──► secrets_vault.id（密文 = JSON(headers dict)）
│ enabled                       │
│ last_test_status / _message   │
│ last_test_tool_count / _at    │
│ tools_json (快照文本列)        │
│ created_at / updated_at       │
└───────────────────────────────┘
```

- `skills`、`mcp_servers` 之间无关联；`mcp_servers` 经两个可空外键指向既有 `secrets_vault`（同 002 `models.secret_ref` 模式）。
- `tools_json` 是快照语义文本列（结构见下），**不建第三张表**（research R6）。

## 表：skills

| 列 | 类型 | 约束 / 默认 | 说明 |
|----|------|------------|------|
| `id` | INTEGER | PK, 自增 | 内部主键，不出现在 API 契约中 |
| `dir_name` | VARCHAR(100) | NOT NULL, UNIQUE | Skill 目录名（`workspace/skills/` 下的目录名），即对外标识 |
| `enabled` | BOOLEAN | NOT NULL, DEFAULT 1 | 启用状态；停用后不再提供给 Agent 使用（FR-013），文件保留 |
| `created_at` | DATETIME | NOT NULL, 当前时间(UTC) | 首次发现/导入时间 |
| `updated_at` | DATETIME | NOT NULL, 每次更新刷新(UTC) | 编辑保存/启停时刷新；列表"更新时间"展示优先取**文件 mtime**（文件为本），此列为管理操作时间 |

**索引**：`uq_skills_dir_name`（唯一索引，dir_name）。

**校验规则**：

1. `dir_name` 去空白后非空；合法字符 = 字母、数字、`-`、`_`、`.`（不含 `/` `\` 空格起止）——ZIP 导入与手动创建均可能产生新目录，收敛字符集防路径歧义。目录名长度 ≤ 100 字符。
2. `dir_name` 的合法行集合 = `workspace/skills/` 下合规目录集合；刷新同步时两侧对齐（多出的行删除，缺的行补默认启用）。
3. `enabled` 布尔无第三态；无删除接口之外的状态修改。

## 表：mcp_servers

| 列 | 类型 | 约束 / 默认 | 说明 |
|----|------|------------|------|
| `id` | INTEGER | PK, 自增 | 对外标识（HTTP 路径 `{id}`） |
| `name` | VARCHAR(100) | NOT NULL, UNIQUE | 展示名（列表识别用，FR-015）；同名拒绝创建 |
| `description` | VARCHAR(500) | NOT NULL, DEFAULT '' | 用途说明 |
| `server_type` | VARCHAR(10) | NOT NULL | `stdio`（本机启动）/ `http`（远程 HTTP），枚举校验在 Pydantic 层 |
| `command` | VARCHAR(500) | NULL | stdio：启动命令（可执行文件名或路径）。与 `command_args` 分开保存、直传进程（FR-021） |
| `command_args` | JSON | NULL | stdio：启动参数**有序列表**（JSON 数组，顺序即传参顺序） |
| `env_secret_ref` | INTEGER | NULL, FK → secrets_vault.id | stdio：环境变量 dict 的 Fernet 密文指针；NULL = 未配置 |
| `url` | VARCHAR(500) | NULL | http：Server 地址（格式校验在 Pydantic 层） |
| `headers_secret_ref` | INTEGER | NULL, FK → secrets_vault.id | http：请求 Header dict 的 Fernet 密文指针；NULL = 未配置 |
| `enabled` | BOOLEAN | NOT NULL, DEFAULT 1 | 启停状态，决定是否提供给 Agent 使用（FR-032） |
| `last_test_status` | VARCHAR(20) | NULL | NULL=未测试 / `success` / `failed` / `config_changed`（枚举校验在服务层） |
| `last_test_message` | TEXT | NULL | 最近一次测试的人话提示（**已脱敏**，FR-023） |
| `last_test_tool_count` | INTEGER | NULL | 最近一次**成功**测试发现的工具数量；未成功为 NULL（前端显示"未知"） |
| `last_test_at` | DATETIME | NULL | 最近一次测试完成时间（成功与失败都刷新） |
| `tools_json` | TEXT | NULL | 最近一次成功测试的工具快照：`McpToolInfo[]` JSON 序列化（结构见下）；失败/未测试为 NULL；`config_changed` 时**保留**旧快照（仍是最近一次成功测试的事实，research R6） |
| `created_at` | DATETIME | NOT NULL, 当前时间(UTC) | 创建时间 |
| `updated_at` | DATETIME | NOT NULL, 每次更新刷新(UTC) | 列表"最后更新"参考 |

**索引**：`uq_mcp_servers_name`（唯一索引，name）；`ix_mcp_servers_updated_at`（updated_at，列表排序）。

**校验规则**：

1. `server_type='stdio'` 时 `command` 必填（非空）、`command_args` 为字符串数组（可为空数组）、`url`/`headers` 必须为空；`server_type='http'` 时 `url` 必填（合法 http/https URL）、`headers` 为字符串键值对、`command`/`args`/`env` 必须为空——互斥由 Pydantic 模型校验（契约 §4）。
2. 敏感值（env、headers 的值）**只**以密文存在于 `secrets_vault`；本表任何列不存明文。
3. `secrets_vault.ciphertext` 为 `String(512)`——SQLite 不强制 VARCHAR 长度上限，长 JSON 密文可存（002 既有列语义注明，无需迁移）。
4. 删除 Server 时同事务删除两个 secret_ref 指向的密文行（复用 `secret_vault.delete_secret`）。
5. 测试进行中（服务层 per-id `asyncio.Lock` 占用）拒绝删除与编辑（Edge Case）。

### tools_json 快照结构

`McpToolInfo[]`（契约 mcp-api.md §3）的 JSON 数组，元素：

```json
{
  "name": "get_weather",
  "description": "查询城市天气",
  "params": [
    { "name": "city", "type": "string", "required": true, "description": "城市名" }
  ]
}
```

`params` 由工具 `inputSchema`（JSON Schema object）的 `properties` 与 `required` 解析而来；无 schema 或无属性时为空数组。整体快照覆写，不增量更新。

## 状态与生命周期

```text
skills:
[目录不存在] --手动创建/导入合规目录+刷新--> [行 inserted, enabled=1]
[行存在] --目录被外部删除+刷新--> [行 removed]            # 文件为本
[enabled=1] --停用--> [enabled=0]                          # 文件保留，Agent 集合移除
[enabled=0] --启用--> [enabled=1]
删除（确认） --> 目录整体删除 + 行删除
任意状态 --重启后端--> enabled/行 保持                      # 持久化（FR-012）

mcp_servers:
[无行] --POST--> [行, enabled=1, last_test_status=NULL]
编辑(command/args/env/url/headers 实际变化 且 有旧结果) --> last_test_status='config_changed'
测试成功 --> status='success', tool_count=N, tools_json=快照, at=now（不改 enabled，FR-033）
测试失败/超时 --> status='failed', message=分类提示(脱敏), at=now
测试进行中 --> 第二次测试/编辑/删除被拒（400）
删除（确认） --> 行删除 + 两份密文删除 + 测试进程零残留
```

## 初始数据（迁移播种）

**无播种**：`skills` 行由目录扫描产生（空目录 = 空表 = 页面空状态）；`mcp_servers` 无预置 Server。迁移仅建两表。

## 与 spec 需求的映射

| spec 需求 | 数据层落点 |
|-----------|-----------|
| FR-001~005 Skills 列表/刷新/空状态 | 目录扫描 ⨝ `skills.enabled`；空目录 → `[]`；skipped 提示来自扫描结果 |
| FR-011 编辑写文件 + 更新时间 | 编辑写 `skill.md`（文件为本）+ 刷新 `skills.updated_at` |
| FR-012/013 启停持久化/文件保留 | `skills.enabled` 列；停用不动目录 |
| FR-022/004 MCP 配置持久化/未测试显示 | `mcp_servers` 全列；`last_test_status IS NULL` → "未测试"/"未知" |
| FR-015/016 测试结果与工具数量 | `last_test_*` 四列 + `tools_json` |
| FR-023/024 敏感值掩码/保留替换 | `env_secret_ref`/`headers_secret_ref` 密文 + 契约 null 三态协议 |
| FR-034 配置变更标记 | 编辑服务层值比较 → `config_changed` |
| FR-031 进程零残留 | 不落库——SDK 上下文管理保证（research R3/R4） |
