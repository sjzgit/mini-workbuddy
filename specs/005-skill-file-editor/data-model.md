# Data Model: Skill 目录浏览与文件在线编辑（第五阶段）

**Date**: 2026-09-11 | **Source of Truth**: 本文件是数据模型的主定义（宪法 II/III）。

## 数据模型变更声明

**本特性零数据模型变更**：`skills`、`mcp_servers`、`secrets_vault` 表结构与 004 主定义
（[../004-skills-mcp-management/data-model.md](../004-skills-mcp-management/data-model.md)）完全一致，
**无 Alembic 迁移**。原因：文件树与文件内容实时读自 `workspace/skills/` 磁盘（文件为本，research R1@004），
无新增持久化事实；启停状态复用 `skills.enabled` 既有列。

## 非持久化结构（契约主定义见 [contracts/skill-files-api.md](contracts/skill-files-api.md)）

### SkillFileNode（目录树节点，响应结构非表）

```text
SkillFileNode
├── name: string          # 节点名（文件名或目录名，不含路径）
├── path: string          # 相对 Skill 目录的 POSIX 风格路径（"skill.md"、"scripts/run.py"）
├── type: "file" | "dir"
├── children: SkillFileNode[]   # 仅目录有；文件为 []
└── (排序：目录在前、名称字典序)
```

### SkillFileContent（单文件读取结果，响应结构非表）

| 字段 | 类型 | 说明 |
|------|------|------|
| `path` | string | 相对路径（回显） |
| `editable` | boolean | 是否可进入编辑态 |
| `reason` | string \| null | 不可编辑原因：`not_text`（非 UTF-8）/ `too_large`（超 1MB）；可编辑为 null |
| `content` | string \| null | 文件文本内容；不可编辑为 null（零乱码保证） |
| `size` | number | 文件字节数 |

### 路径安全约束（读/写共用，主定义 contracts §4）

1. 相对路径非法形态：`..` 片段、以 `/`/`\` 开头、含盘符（`X:`）、空串 → 拒绝。
2. `(skill_dir / path).resolve()` 必须落在 `skill_dir.resolve()` 内（包含性校验，防符号链接逃逸）。
3. 目标必须真实存在（读取文件；保存时为已存在文件）。

## 与既有实体的关系

| 既有实体 | 本特性的关系 |
|---------|--------------|
| `skills` 表行 | 无列变更；保存 `skill.md` 时刷新 `updated_at`（既有 onupdate 行为） |
| `workspace/skills/<dir>/` | 唯一数据源：树与文件内容实时读磁盘 |
| `file_max_bytes`（settings，1MB） | 单文件读写上限的唯一口径（复用，不新建设置项） |
| 启停状态 | 复用既有 `PUT /api/skills/{dir_name}/enabled`，无新语义 |

## 状态与生命周期

```text
[目录树]  --打开对话框/点刷新--> 实时扫描磁盘（无缓存、无轮询）
[文件内容] --点击树节点--> 实时读取（编码/上限判定在前）
[文件保存] --PUT--> 覆盖写回磁盘；skill.md 额外刷新 DB updated_at
任意操作 --重启后端--> 无状态变化（一切以磁盘为准）
```
