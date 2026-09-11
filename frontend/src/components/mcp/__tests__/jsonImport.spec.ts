import { describe, expect, it } from 'vitest'

import { parseMcpJson } from '@/components/mcp/jsonImport'

/** 契约主定义：specs/006-mcp-json-import/contracts/json-import.md（表驱动锁定全部分支） */

const FULL_JSON = `{
  "name": "filesystem",
  "description": "filesystem",
  "transport": "stdio",
  "enabled": true,
  "command": "npx",
  "args": ["-y", "@modelcontextprotocol/server-filesystem"],
  "env": {}
}`

describe('parseMcpJson（JSON 导入契约）', () => {
  // ---- 成功分支（SC-002）----

  it('完整示例 JSON：五字段全部填充且 args 保序', () => {
    const result = parseMcpJson(FULL_JSON)
    expect(result.ok).toBe(true)
    if (!result.ok) return
    expect(result.form.name).toBe('filesystem')
    expect(result.form.description).toBe('filesystem')
    expect(result.form.command).toBe('npx')
    expect(result.form.args).toEqual(['-y', '@modelcontextprotocol/server-filesystem'])
    expect(result.form.env).toEqual({})
  })

  it('部分字段：仅填出现的字段', () => {
    const result = parseMcpJson('{ "name": "partial", "command": "uvx" }')
    expect(result.ok).toBe(true)
    if (!result.ok) return
    expect(result.form.name).toBe('partial')
    expect(result.form.command).toBe('uvx')
    expect(result.form.description).toBeUndefined()
    expect(result.form.args).toBeUndefined()
    expect(result.form.env).toBeUndefined()
  })

  it('enabled 与未知字段被忽略', () => {
    const result = parseMcpJson(
      '{ "enabled": false, "icons": [], "name": "x", "command": "npx" }',
    )
    expect(result.ok).toBe(true)
    if (!result.ok) return
    expect(result.form.name).toBe('x')
    expect(Object.keys(result.form)).toEqual(['name', 'command'])
  })

  it('args 为空数组合法', () => {
    const result = parseMcpJson('{ "command": "npx", "args": [] }')
    expect(result.ok).toBe(true)
    if (!result.ok) return
    expect(result.form.args).toEqual([])
  })

  it('env 空 key 跳过，非空键正常导入', () => {
    const result = parseMcpJson('{ "env": { "": "ignored", "TOKEN": "v" } }')
    expect(result.ok).toBe(true)
    if (!result.ok) return
    expect(result.form.env).toEqual({ TOKEN: 'v' })
  })

  // ---- 失败分支（SC-003）：reason 与契约 §2/§3 逐字一致 ----

  it('空输入', () => {
    expect(parseMcpJson('')).toEqual({ ok: false, reason: '请输入 JSON 内容' })
    expect(parseMcpJson('   \n  ')).toEqual({ ok: false, reason: '请输入 JSON 内容' })
  })

  it('非法 JSON 语法', () => {
    const result = parseMcpJson('{ name: 1 }')
    expect(result).toEqual({ ok: false, reason: 'JSON 格式不合法，请检查逗号、引号等语法' })
  })

  it('非对象（数组/字符串/数字/null）', () => {
    const reason = 'JSON 需为一个对象（{...}）'
    expect(parseMcpJson('[1,2]')).toEqual({ ok: false, reason })
    expect(parseMcpJson('"text"')).toEqual({ ok: false, reason })
    expect(parseMcpJson('42')).toEqual({ ok: false, reason })
    expect(parseMcpJson('null')).toEqual({ ok: false, reason })
  })

  it('transport 非 stdio', () => {
    const result = parseMcpJson('{ "transport": "http", "name": "x" }')
    expect(result).toEqual({
      ok: false,
      reason: '该导入区域仅支持 stdio 类型配置（transport 为 http 时请直接使用远程 HTTP 表单）',
    })
  })

  it('name/command/description 非 string', () => {
    expect(parseMcpJson('{ "name": 123 }').ok).toBe(false)
    expect(parseMcpJson('{ "command": { "a": 1 } }').ok).toBe(false)
    expect(parseMcpJson('{ "description": true }').ok).toBe(false)
  })

  it('args 非字符串数组', () => {
    const reason = '启动参数（args）必须为字符串数组'
    expect(parseMcpJson('{ "args": "x" }')).toEqual({ ok: false, reason })
    expect(parseMcpJson('{ "args": [1, 2] }')).toEqual({ ok: false, reason })
    expect(parseMcpJson('{ "args": {} }')).toEqual({ ok: false, reason })
  })

  it('env 非"值均为 string 的对象"', () => {
    const reason = '环境变量（env）必须为键值对对象'
    expect(parseMcpJson('{ "env": "x" }')).toEqual({ ok: false, reason })
    expect(parseMcpJson('{ "env": { "K": 1 } }')).toEqual({ ok: false, reason })
  })

  it('无可识别字段', () => {
    const result = parseMcpJson('{ "enabled": true, "icons": [] }')
    expect(result).toEqual({
      ok: false,
      reason: '未找到可导入的字段（需要 name/description/command/args/env 至少一项）',
    })
  })

  it('失败时绝不携带 form（零部分填充的结构性保证）', () => {
    const result = parseMcpJson('{ "name": "good", "command": 123 }')
    if (result.ok) {
      expect.unreachable('应当失败')
    } else {
      expect(result).not.toHaveProperty('form')
    }
  })
})
