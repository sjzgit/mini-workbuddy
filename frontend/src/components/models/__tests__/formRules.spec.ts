import { describe, expect, it } from 'vitest'

import {
  validateBaseUrl,
  validateMaxOutput,
  validatePositiveInt,
  validatePrice,
} from '../formRules'

describe('validateBaseUrl（服务地址校验，FR-006/007）', () => {
  it.each([
    'https://api.example.com/v1',
    'https://api.example.com/v1/',
    'http://127.0.0.1:8000/v1',
    'https://gateway.corp/llm/v1',
    'http://localhost:11434/v1',
  ])('接受合法地址：%s', (value) => {
    expect(validateBaseUrl(value)).toBeNull()
  })

  it.each([
    [' ', '请填写服务地址'],
    ['ftp://api.example.com/v1', '必须以 http'],
    ['https:///missing-host/v1', '格式不正确'],
    ['https://api.example.com/v1/chat/completions', 'chat/completions'],
    ['https://api.example.com/v1/chat/completions/', 'chat/completions'],
  ])('拒绝非法地址：%s', (value, keyword) => {
    const error = validateBaseUrl(value)
    expect(error).not.toBeNull()
    expect(error).toContain(keyword)
  })
})

describe('validateMaxOutput（最大输出 ≤ 上下文，FR-007）', () => {
  it('合法：正整数且不超过上下文', () => {
    expect(validateMaxOutput(4096, 8192)).toBeNull()
    expect(validateMaxOutput(8192, 8192)).toBeNull() // 边界相等允许
  })

  it('拒绝：超过上下文 / 非正整数 / 未填写', () => {
    expect(validateMaxOutput(9999, 8192)).toContain('不能超过上下文长度')
    expect(validateMaxOutput(0, 8192)).toContain('正整数')
    expect(validateMaxOutput(10.5, 8192)).toContain('正整数')
    expect(validateMaxOutput(null, 8192)).toContain('请填写')
  })
})

describe('validatePrice（未配置 vs 免费，FR-007）', () => {
  it('留空（未配置）与 0（免费）都合法', () => {
    expect(validatePrice(null)).toBeNull()
    expect(validatePrice(0)).toBeNull()
  })

  it('拒绝负数', () => {
    expect(validatePrice(-0.1)).toContain('负数')
  })
})

describe('validatePositiveInt（上下文长度等，FR-007）', () => {
  it('正整数合法', () => {
    expect(validatePositiveInt(1)).toBeNull()
    expect(validatePositiveInt(1000000)).toBeNull()
  })

  it('拒绝 0 / 负数 / 小数 / 未填写', () => {
    expect(validatePositiveInt(0)).toContain('正整数')
    expect(validatePositiveInt(-5)).toContain('正整数')
    expect(validatePositiveInt(1.5)).toContain('正整数')
    expect(validatePositiveInt(null)).toContain('必填')
  })
})
