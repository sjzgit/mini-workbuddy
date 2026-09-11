# Skill Files Contract: 目录树与文件在线编辑（第五阶段）

**Base Path**: `/api/skills/{dir_name}` 子资源 | **Date**: 2026-09-11

本文件是 Skill 目录树与文件读取/保存 HTTP 接口的**主定义**（宪法 II/III）。后端 `backend/app/schemas/skill.py`（Pydantic）与 `backend/app/services/skill_files.py`、前端 `frontend/src/api/skills.ts`（TypeScript 类型）MUST 与本文逐字段对齐，变更先改这里。

**通用约定**：沿用 004 [skills-api.md](../004-skills-mcp-management/contracts/skills-api.md)——错误统一 `{"detail": 人话信息}`；`dir_name` 合法字符集与其 §1 一致；Skill 不存在 → `404`。本契约三端点是 004 Skill 资源的子资源，无独立前缀。

## 1. 路径标识

文件以 **Skill 目录内的相对路径**为唯一标识：POSIX 风格 `/` 分隔（如 `skill.md`、`scripts/run.py`），树返回的 `path` 与读写收到的 `path` 同一口径。**非法形态**（读取与保存同等校验，§4）：`..` 片段、以 `/` 或 `\` 开头、含盘符（`X:`）、空串、解析后落在 Skill 目录之外。

## 2. 数据结构

### SkillFileNode（树节点，递归）

| 字段 | 类型 | 说明 |
|------|------|------|
| `name` | string | 节点名（文件名/目录名，不含路径） |
| `path` | string | 相对路径（根文件为 `skill.md` 形态） |
| `type` | `"file"` \| `"dir"` | 节点类型 |
| `children` | `SkillFileNode[]` | 子节点；文件恒为 `[]`；目录在前、同类型按名称字典序 |

### SkillFileContent（读取响应）

| 字段 | 类型 | 说明 |
|------|------|------|
| `path` | string | 相对路径（回显） |
| `editable` | boolean | 是否可进入编辑态 |
| `reason` | `"not_text"` \| `"too_large"` \| null | 不可编辑原因；可编辑为 null |
| `content` | string \| null | UTF-8 文本内容；不可编辑时恒为 null（零乱码） |
| `size` | number | 文件字节数 |

### SkillFileWriteRequest（保存提交体）

| 字段 | 类型 | 必填 | 校验 |
|------|------|------|------|
| `path` | string | 是 | 合法相对路径且文件已存在（§4） |
| `content` | string | 是 | UTF-8 编码后 ≤ `file_max_bytes`（1MB）；空串合法 |

## 3. 接口

### 1. 目录树

`GET /api/skills/{dir_name}/tree` → `200` `SkillFileNode[]`（根层级列表）

- 实时扫描磁盘（无缓存）；Skill 目录不存在或不合规 → `404`。
- 空目录 → `[]`；目录仅展开语义，不区分展示。

### 2. 读取文件

`GET /api/skills/{dir_name}/file?path=<相对路径>` → `200` `SkillFileContent`

- `editable=false` 是**正常查询结果**（200），不是错误：非 UTF-8 → `reason="not_text"`、内容 null；超上限 → `reason="too_large"`、内容 null。
- 路径非法 → `400` `{"detail": "非法的文件路径"}`；文件不存在 → `404` `{"detail": "文件不存在"}`；Skill 不存在 → `404` `{"detail": "Skill 不存在"}`。

### 3. 保存文件

`PUT /api/skills/{dir_name}/file` body `SkillFileWriteRequest` → `200` `{"saved": true, "path": "<相对路径>"}`

- 覆盖写回（UTF-8、`\n` 换行），空内容合法（清空文件）。
- 目标为 `skill.md` → 同步刷新 DB 行 `updated_at`（列表名称/说明/更新时间随之更新，FR-012）；其他文件不影响列表。
- 错误语义同上（路径非法 400 / 文件不存在 404 / Skill 不存在 404 / 超上限 422 `{"detail": 人话上限提示}`）。

## 4. 路径安全规则（主定义，读取与保存共用同一函数）

1. **黑名单**：`..` 片段、绝对路径（`/` 或 `\` 开头）、盘符（`X:`）、空串 → 拒绝（400）。
2. **包含性**：`(skill_dir / path).resolve()` 必须落在 `skill_dir.resolve()` 内（防符号链接等解析层逃逸）→ 否则拒绝（400）。
3. 读写同等拦截：不存在"只挡写不挡读"的不对称面（SC-004）。

## 5. 前端类型派生要求

`frontend/src/api/skills.ts` 的 `SkillFileNode` / `SkillFileContent` / `SkillFileWritePayload` 类型 MUST 按本文编写（null 不混用 undefined）。

## 6. 配置常量

无新增——单文件上限复用 `core/config.py` 既有 `file_max_bytes`（1MB，与 003 文件工具同口径，唯一主定义）。
