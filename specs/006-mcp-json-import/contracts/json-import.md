# JSON Import Contract: MCP 表单 JSON 导入（第六阶段）

**消费方**: 前端 `frontend/src/components/mcp/jsonImport.ts`（唯一实现）| **Date**: 2026-09-11

本文件是 stdio 类型 MCP 配置 JSON 导入格式的**主定义**（宪法 II/III）：使用者粘贴的 JSON 必须
符合本文结构；实现侧（解析函数、错误文案）MUST 与本文一致，变更先改这里。

该契约仅约束**前端解析行为**，不涉及任何 HTTP 接口——保存仍走既有
[mcp-api.md](../004-skills-mcp-management/contracts/mcp-api.md) §2 的提交契约（三态协议不变）。

## 1. 目标结构（合法输入示例）

```json
{
  "name": "filesystem",
  "description": "filesystem",
  "transport": "stdio",
  "enabled": true,
  "command": "npx",
  "args": ["-y", "@modelcontextprotocol/server-filesystem"],
  "env": {}
}
```

与业界 MCP Server 配置片段（Claude Desktop 等）同形，可直接粘贴使用。

## 2. 字段定义（解析规则主定义）

| 字段 | 类型要求 | 导入行为 | 异常语义 |
|------|---------|---------|---------|
| `name` | string | 填入表单"名称" | 存在但非 string → 整体失败 |
| `description` | string | 填入"描述" | 同上 |
| `transport` | 必须为 `"stdio"`（若提供） | 不导入（术语校验） | 存在且 !== "stdio" → 整体失败："该导入区域仅支持 stdio 类型配置（transport 为 http 时请直接使用远程 HTTP 表单）" |
| `enabled` | 任意 | **忽略**（启用状态由界面开关管理，spec Assumption） | 永不因该字段失败 |
| `command` | string | 填入"启动命令" | 存在但非 string → 整体失败 |
| `args` | string[]（可空数组） | 填入"启动参数"动态行，**保序** | 存在但非数组 → 失败"启动参数（args）必须为字符串数组"；数组含非字符串元素 → 同前 |
| `env` | object（值均为 string） | 填入"环境变量"动态行 | 存在但非对象 → 失败"环境变量（env）必须为键值对对象"；任一值非 string → 同前；键为空串 → 跳过该键 |
| 其他未知字段 | 任意 | **忽略** | 永不因该字段失败 |

## 3. 整体校验顺序（零部分填充的结构性保证，SC-003）

1. 输入去空白后为空 → 失败："请输入 JSON 内容"
2. `JSON.parse` 失败 → 失败："JSON 格式不合法，请检查逗号、引号等语法"
3. 解析结果非普通对象（数组/字符串/数字/null）→ 失败："JSON 需为一个对象（{...}）"
4. `transport` 校验（§2）→ 失败即停
5. `name`/`description`/`command`/`args`/`env` 类型校验 → 任一失败即停，**不产出任何字段**
6. 可识别字段一个都没有 → 失败："未找到可导入的字段（需要 name/description/command/args/env 至少一项）"
7. 全部通过 → 产出 `form` 对象（仅含出现的字段），调用方整体写回表单

**实现侧 MUST 把上述顺序收敛为纯函数** `parseMcpJson(text): ParseResult`：

```ts
type McpJsonImportForm = {
  name?: string
  description?: string
  command?: string
  args?: string[]
  env?: Record<string, string>
}
type ParseResult =
  | { ok: true; form: McpJsonImportForm }
  | { ok: false; reason: string }   // 人话原因，与本文文案一致
```

## 4. 组件侧行为（McpServerFormModal.vue 消费）

- 导入区仅 `server_type === 'stdio'` 时展示（多行文本框 + "解析 JSON"按钮，FR-003）。
- `ok:true` → 五个字段整体写回表单（`args`/`env` 转动态行；env 行 `keep=false` 即视为新值），
  提示"已导入 N 个字段"；`ok:false` → `message.warning(reason)`，表单不动（FR-005）。
- 覆盖语义：解析成功即覆盖表单当前对应字段；编辑态 env"留空保留原值"的三态语义不受影响。

## 5. 前端类型派生要求

`jsonImport.ts` 的 `McpJsonImportForm` / `ParseResult` MUST 按本文编写；错误文案 MUST 与 §2/§3
一致（Vitest 表驱动断言锁定，SC-002/SC-003）。
