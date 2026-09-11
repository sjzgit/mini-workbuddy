# Skills Contract: Skills 管理（第四阶段）

**Base Path**: `/api/skills` | **Date**: 2026-09-10

本文件是 Skills 管理 HTTP 接口、`skill.md` 文件格式与 ZIP 导入规则的**主定义**（宪法 II/III）。后端 `backend/app/schemas/skill.py`（Pydantic）与 `backend/app/services/skill_files.py`、前端 `frontend/src/api/skills.ts`（TypeScript 类型）MUST 与本文逐字段对齐，变更先改这里。

**通用约定**：所有响应为 JSON；错误统一 `{"detail": "人话错误信息"}`（沿用既有全局 422 处理与约定），detail 不含堆栈、内部路径与文件内容。

## 1. 对外标识

Skill 对外以 `dir_name`（目录名）为标识，即 HTTP 路径参数 `{dir_name}`。合法字符：字母、数字、`-`、`_`、`.`；长度 1–100（[data-model.md](../data-model.md) 校验规则）。

## 2. skill.md 文件格式（文件事实源的主定义）

每个 Skill 一个独立目录：`workspace/skills/<dir_name>/skill.md`（路径根由 `settings.skills_dir` 配置，默认 `./workspace/skills`）。文件结构：

```markdown
---
name: 会议纪要整理
description: 把口述或草稿整理成结构化会议纪要
---
（此后为详细指令正文，Markdown，供 Agent 阅读）
```

- **frontmatter**：首行 `---` 开始，逐行 `key: value`（仅支持单行标量值），至闭合 `---`。消费 `name`（显示名）与 `description`（用途说明）两键。
- **正文**：闭合 `---` 之后的内容为详细指令（Markdown，原样保留）。
- **宽松读、严格写**：读取时无 frontmatter → `name` 取目录名、`description` 为空串、全文视作指令；保存时一律重写为规范格式（frontmatter 仅 `name`/`description` 两键，未知键丢弃）。UTF-8、`\n` 换行。
- **合规判定**（刷新跳过与 ZIP 导入共用同一口径）：目录内存在非空 `skill.md` 即合规；缺失或空文件不合规。

## 3. 数据结构

### SkillItem（列表项）

| 字段 | 类型 | 说明 |
|------|------|------|
| `dir_name` | string | 目录名（对外标识） |
| `name` | string | 显示名（读文件；缺省 = 目录名） |
| `description` | string | 用途说明（读文件） |
| `enabled` | boolean | 启用状态（DB） |
| `updated_at` | string (ISO 8601) | 更新时间（`skill.md` mtime；文件不可得时为 DB `updated_at`） |

### SkillDetail（详情，编辑页数据源）

SkillItem 全部字段，另加：

| 字段 | 类型 | 说明 |
|------|------|------|
| `instruction` | string | 详细指令正文（Markdown 全文） |

### SkillUpdateRequest（编辑提交体，PUT）

| 字段 | 类型 | 必填 | 校验 |
|------|------|------|------|
| `name` | string | 是 | 去空白后 1–100 字符 |
| `description` | string | 否（默认 ""） | ≤ 500 字符 |
| `instruction` | string | 是 | 允许空串（≤ 200000 字符） |

### SkillToggleRequest（启停提交体，PUT …/enabled）

| 字段 | 类型 | 必填 | 校验 |
|------|------|------|------|
| `enabled` | boolean | 是 | 仅接受布尔值 |

### SkillRefreshResult（POST /refresh 响应）

| 字段 | 类型 | 说明 |
|------|------|------|
| `items` | `SkillItem[]` | 同步后的完整列表（按 updated_at 倒序） |
| `skipped` | `string[]` | 被跳过的不合规目录名列表（前端以警告提示，FR-005） |

## 4. 接口

### 1. 列表

`GET /api/skills` → `200` `SkillItem[]`

- 合并口径：扫描 `skills_dir` 合规目录 ⨝ DB `enabled`（无行视为启用并在响应前补行，保证幂等）。
- 按 `updated_at` 倒序；无合规目录 → `[]`（前端渲染空状态，FR-004）。

### 2. 详情

`GET /api/skills/{dir_name}` → `200` `SkillDetail`；目录不存在或不合规 → `404` `{"detail": "Skill 不存在"}`

### 3. 编辑

`PUT /api/skills/{dir_name}` body `SkillUpdateRequest` → `200` `SkillItem`；404 同上；body 非法 → `422`

- 保存 = 重写 `skill.md`（frontmatter 两键 + 正文）→ 刷新 DB 行 `updated_at` → 返回最新列表项（FR-011）。

### 4. 启停

`PUT /api/skills/{dir_name}/enabled` body `SkillToggleRequest` → `200` `SkillItem`；404/422 同上。

- 只改 DB `enabled`，不触碰文件（FR-013）。

### 5. 删除

`DELETE /api/skills/{dir_name}` → `200` `{"deleted": true}`；不存在 → `404`

- 删除整个目录 + DB 行；目录被占用等系统错误 → `400` `{"detail": 人话原因}`（Edge Case）。

### 6. 手动刷新

`POST /api/skills/refresh` → `200` `SkillRefreshResult`

- 重扫目录：新合规目录补行（默认启用）、已消失目录清行、不合规目录计入 `skipped`（FR-003/005）。无需重启服务。

### 7. ZIP 导入

`POST /api/skills/import`（multipart/form-data，字段 `file`）→ `201` `SkillItem`；失败 → `400` `{"detail": 失败原因}`；非 ZIP / 超限 → `422`

失败原因（`detail` 人话文案，覆盖 FR-007/008/009）：

| 场景 | detail 示例 |
|------|------------|
| 非 ZIP 文件 / 魔数不符 | 导入失败：文件不是有效的 ZIP 压缩包 |
| 路径逃逸条目 | 导入失败：压缩包内包含不安全的文件路径（…），已拒绝解压 |
| 解压超限（>10MB 或 >200 条目） | 导入失败：压缩包超过大小/数量上限 |
| 结构不符（无合规 skill.md） | 导入失败：压缩包内未找到有效的 skill.md 文件 |
| 同名冲突 | 导入失败：已存在同名 Skill「X」，为避免覆盖请先重命名 |
| 目录名非法（字符集外） | 导入失败：Skill 名称「X」包含不支持的字符 |

成功语义：解压到隔离临时目录 → 校验 → 原子移入 `skills_dir` → 刷新同步 → 返回新 Skill 的 `SkillItem`（`enabled=true`）。

## 5. ZIP 导入安全规则（主定义）

1. 双重校验 ZIP：请求文件名以 `.zip` 结尾 **且** 文件头为 `PK\x03\x04` 魔数。
2. 逐条目检查：绝对路径、`..` 片段、以 `/` 或盘符开头的条目名一律拒绝；解压目标收敛 `resolve()` 后必须落在临时根内（包含性校验，research R7）。
3. 资源上限：解压总大小 ≤ `settings.skill_import_max_bytes`（默认 10MB）、条目数 ≤ 200；超限整体失败。
4. 全程临时目录操作，任何失败不触碰 `skills_dir`，临时目录用后即清。
5. 单个 ZIP 对应一个 Skill（spec Assumption）：根直接含 `skill.md` → 目录名取 ZIP 文件名去后缀；唯一顶层目录含 `skill.md` → 取该目录名；其余形态结构不符。

## 6. 前端类型派生要求

`frontend/src/api/skills.ts` 的 `SkillItem` / `SkillDetail` / `SkillUpdatePayload` / `SkillRefreshResult` 类型 MUST 按本文编写，禁止手改字段名或放宽类型（null 不混用 undefined）。

## 7. 配置常量（进 `core/config.py`，环境变量可覆盖）

| 常量 | 默认值 | 消费方 |
|------|--------|--------|
| `skills_dir` | `./workspace/skills` | Skill 目录根（首次访问自动创建） |
| `skill_import_max_bytes` | `10485760` | ZIP 解压总大小上限 |
