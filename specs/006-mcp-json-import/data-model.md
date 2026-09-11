# Data Model: MCP 表单 JSON 导入与类型命名修正（第六阶段）

**Date**: 2026-09-11 | **Source of Truth**: 本文件是数据模型的主定义（宪法 II/III）。

## 数据模型变更声明

**本特性零数据模型变更**：`skills`、`mcp_servers`、`secrets_vault` 表结构与 004 主定义
（[../004-skills-mcp-management/data-model.md](../004-skills-mcp-management/data-model.md)）完全一致，
**无 Alembic 迁移、无 API 契约变更**。类型改名仅是前端展示文案（`server_type` 取值不变）；
JSON 导入是纯前端解析（research R3），不产生新的持久化事实。

## 非持久化结构（契约主定义见 [contracts/json-import.md](contracts/json-import.md)）

### McpJsonImport（导入解析产出，前端内存对象，非表）

| 字段 | 类型 | 必出 | 说明 |
|------|------|------|------|
| `name` | string | 否 | 填入表单名称（存在且为字符串时） |
| `description` | string | 否 | 填入表单描述 |
| `command` | string | 否 | 填入启动命令 |
| `args` | string[] | 否 | 填入启动参数（保序） |
| `env` | Record<string, string> | 否 | 填入环境变量动态行 |

任何字段类型不符 → 整体失败（`ok:false`），不产出该结构（零部分填充）。

## 与既有实体的关系

| 既有实体 | 本特性的关系 |
|---------|--------------|
| `mcp_servers.server_type` | 取值不变（`stdio`/`http`）；仅前端展示文案变化 |
| 表单保存（POST/PUT） | 走既有契约（004 mcp-api.md §2 三态协议），无新字段 |
| 密钥掩码链路 | 无变化；导入的 env 值经表单提交后照常加密入 `secrets_vault` |
