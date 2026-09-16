/**
 * stores/agents 单元测试（specs/007）：
 * fetch/save/remove/setDefault 动作与 409 结构化响应体解析（parseConflictBody）。
 */
import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { ApiError } from '@/api/request'
import { parseConflictBody, useAgentsStore } from '@/stores/agents'

const listMock = vi.fn()
const detailMock = vi.fn()
const createMock = vi.fn()
const updateMock = vi.fn()
const removeMock = vi.fn()
const setDefaultMock = vi.fn()
const bindingOptionsMock = vi.fn()

vi.mock('@/api/agents', () => ({
  MAX_ROUNDS_DEFAULT: 10,
  MAX_ROUNDS_MIN: 1,
  MAX_ROUNDS_MAX: 100,
  agentsApi: {
    list: (...args: unknown[]) => listMock(...args),
    detail: (...args: unknown[]) => detailMock(...args),
    create: (...args: unknown[]) => createMock(...args),
    save: undefined,
    update: (...args: unknown[]) => updateMock(...args),
    remove: (...args: unknown[]) => removeMock(...args),
    setDefault: (...args: unknown[]) => setDefaultMock(...args),
    bindingOptions: (...args: unknown[]) => bindingOptionsMock(...args),
  },
}))

const sampleItem = {
  id: 1,
  name: 'A',
  description: '',
  model_display_name: 'M',
  model_identifier: 'mid',
  tool_count: 0,
  skill_count: 0,
  mcp_count: 0,
  bindings: [],
  is_default: true,
  updated_at: '2026-09-11T10:00:00',
}

describe('parseConflictBody', () => {
  it('解析 409 requires_new_default 结构化响应体', () => {
    const error = new ApiError(409, '该 Agent 是默认 Agent，请先选择新的默认 Agent', {
      detail: {
        detail: '该 Agent 是默认 Agent，请先选择新的默认 Agent',
        requires_new_default: true,
        candidates: [{ id: 2, name: 'B' }],
      },
    })
    const body = parseConflictBody(error)
    expect(body).not.toBeNull()
    expect(body && 'requires_new_default' in body && body.requires_new_default).toBe(true)
    expect(body && 'candidates' in body && body.candidates).toEqual([{ id: 2, name: 'B' }])
  })

  it('普通字符串 detail 的 409 返回 null', () => {
    const error = new ApiError(409, '普通冲突')
    expect(parseConflictBody(error)).toBeNull()
  })

  it('非 409 错误返回 null', () => {
    expect(parseConflictBody(new ApiError(400, 'x'))).toBeNull()
  })
})

describe('useAgentsStore', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    listMock.mockReset()
    removeMock.mockReset()
  })

  it('fetchAgents 填充列表', async () => {
    listMock.mockResolvedValue([sampleItem])
    const store = useAgentsStore()
    await store.fetchAgents()
    expect(store.items).toHaveLength(1)
    expect(store.items[0]!.name).toBe('A')
  })

  it('remove 成功后刷新列表', async () => {
    listMock.mockResolvedValue([])
    removeMock.mockResolvedValue({ deleted: true, cleared_default: true })
    const store = useAgentsStore()
    await store.remove(1)
    expect(removeMock).toHaveBeenCalledWith(1, undefined)
    expect(store.items).toEqual([])
  })

  it('remove 409 原样抛出供调用方识别 requires_new_default', async () => {
    const conflict = new ApiError(409, 'conflict', {
      detail: { requires_new_default: true, candidates: [{ id: 2, name: 'B' }] },
    })
    removeMock.mockRejectedValue(conflict)
    const store = useAgentsStore()
    await expect(store.remove(1)).rejects.toThrow('conflict')
  })

  it('setDefault 调用接口并刷新', async () => {
    listMock.mockResolvedValue([])
    setDefaultMock.mockResolvedValue({ id: 2 })
    const store = useAgentsStore()
    await store.setDefault(2)
    expect(setDefaultMock).toHaveBeenCalledWith(2)
    expect(listMock).toHaveBeenCalled()
  })

  it('save 提交体携带压缩配置四字段（011）', async () => {
    updateMock.mockResolvedValue({ id: 1 })
    listMock.mockResolvedValue([])
    const store = useAgentsStore()
    await store.save(
      {
        name: 'A', model_id: 1, system_prompt: '',
        auto_compact: false,
        compact_trigger_ratio: 0.6,
        compact_keep_recent_rounds: 3,
        compact_summary_target_tokens: 500,
      },
      1,
    )
    expect(updateMock).toHaveBeenCalledWith(
      1,
      expect.objectContaining({
        auto_compact: false,
        compact_trigger_ratio: 0.6,
        compact_keep_recent_rounds: 3,
        compact_summary_target_tokens: 500,
      }),
    )
  })
})
