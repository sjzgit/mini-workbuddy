/**
 * MCP 表单 JSON 导入解析（契约主定义：specs/006-mcp-json-import/contracts/json-import.md）。
 *
 * 纯函数：parseMcpJson(text) → ParseResult。
 * 整体校验通过才产出 form（零部分填充，SC-003）；错误文案与契约 §2/§3 逐字一致。
 */

export type McpJsonImportForm = {
  name?: string
  description?: string
  command?: string
  args?: string[]
  env?: Record<string, string>
}

export type ParseResult =
  | { ok: true; form: McpJsonImportForm }
  | { ok: false; reason: string }

function isPlainObject(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}

export function parseMcpJson(text: string): ParseResult {
  // 契约 §3.1：空输入
  const input = text.trim()
  if (!input) {
    return { ok: false, reason: '请输入 JSON 内容' }
  }

  // 契约 §3.2：JSON 语法
  let data: unknown
  try {
    data = JSON.parse(input)
  } catch {
    return { ok: false, reason: 'JSON 格式不合法，请检查逗号、引号等语法' }
  }

  // 契约 §3.3：必须是普通对象
  if (!isPlainObject(data)) {
    return { ok: false, reason: 'JSON 需为一个对象（{...}）' }
  }

  // 契约 §3.4：transport 仅接受 stdio
  if (data.transport !== undefined && data.transport !== 'stdio') {
    return {
      ok: false,
      reason: '该导入区域仅支持 stdio 类型配置（transport 为 http 时请直接使用远程 HTTP 表单）',
    }
  }

  // 契约 §3.5：五字段类型校验——任一失败即停，不产出任何字段
  const form: McpJsonImportForm = {}
  for (const key of ['name', 'description', 'command'] as const) {
    const value = data[key]
    if (value === undefined) continue
    if (typeof value !== 'string') {
      return { ok: false, reason: `字段 ${key} 必须为字符串` }
    }
    form[key] = value
  }

  if (data.args !== undefined) {
    if (!Array.isArray(data.args) || data.args.some((arg) => typeof arg !== 'string')) {
      return { ok: false, reason: '启动参数（args）必须为字符串数组' }
    }
    form.args = [...data.args]
  }

  if (data.env !== undefined) {
    if (!isPlainObject(data.env)) {
      return { ok: false, reason: '环境变量（env）必须为键值对对象' }
    }
    const env: Record<string, string> = {}
    for (const [key, value] of Object.entries(data.env)) {
      if (key === '') continue // 空 key 跳过
      if (typeof value !== 'string') {
        return { ok: false, reason: '环境变量（env）必须为键值对对象' }
      }
      env[key] = value
    }
    form.env = env
  }

  // 契约 §3.6：至少一个可识别字段
  const hasAny =
    form.name !== undefined ||
    form.description !== undefined ||
    form.command !== undefined ||
    form.args !== undefined ||
    form.env !== undefined
  if (!hasAny) {
    return {
      ok: false,
      reason: '未找到可导入的字段（需要 name/description/command/args/env 至少一项）',
    }
  }

  // enabled 与未知字段忽略（契约 §2）
  return { ok: true, form }
}
