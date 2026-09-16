/**
 * 运行记录 store 单元测试（specs/011）。
 * mock 风格沿用 stores/__tests__/chat.spec.ts。
 */
import { setActivePinia, createPinia } from 'pinia'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import type { RunDetail, RunListResponse, RunSummary } from '@/api/runs'

const { runsApiMock } = vi.hoisted(() => ({
  runsApiMock: {
    list: vi.fn(),
    detail: vi.fn(),
    payloads: vi.fn(),
    payload: vi.fn(),
    conversationRuns: vi.fn(),
  },
}))

vi.mock('@/api/runs', () => ({
  runsApi: runsApiMock,
}))

import { useRunsStore } from '@/stores/runs'

function makeSummary(overrides: Partial<RunSummary> = {}): RunSummary {
  return {
    run_id: 'run1',
    conversation_id: 1,
    agent_name: '测试助手',
    model_name: 'GPT 测试模型',
    status: 'succeeded',
    end_reason: '正常结束',
    error_summary: null,
    started_at: '2026-09-16T10:00:00',
    finished_at: '2026-09-16T10:00:05',
    total_duration_ms: 5000,
    model_call_count: 2,
    tool_call_count: 1,
    prompt_tokens: 100,
    completion_tokens: 50,
    total_tokens: 150,
    first_output_ms: 300,
    ...overrides,
  }
}

function makeListResponse(items: RunSummary[]): RunListResponse {
  return { items, total: items.length, page: 1, page_size: 20 }
}

beforeEach(() => {
  setActivePinia(createPinia())
  vi.clearAllMocks()
})

describe('runs store 列表', () => {
  it('fetchList 拼装分页参数并写入 items/total', async () => {
    runsApiMock.list.mockResolvedValue(makeListResponse([makeSummary()]))
    const store = useRunsStore()
    await store.fetchList()
    expect(runsApiMock.list).toHaveBeenCalledWith({ page: 1, page_size: 20 })
    expect(store.items).toHaveLength(1)
    expect(store.total).toBe(1)
  })

  it('筛选变化重置回第一页并携带筛选', async () => {
    runsApiMock.list.mockResolvedValue(makeListResponse([]))
    const store = useRunsStore()
    store.setPage(3, 20)
    await store.fetchList({ status: 'failed' })
    expect(runsApiMock.list).toHaveBeenLastCalledWith({
      status: 'failed', page: 1, page_size: 20,
    })
  })

  it('失败时写入 error 且不清空已有数据', async () => {
    runsApiMock.list.mockResolvedValueOnce(makeListResponse([makeSummary()]))
    runsApiMock.list.mockRejectedValueOnce(new Error('网络失败'))
    const store = useRunsStore()
    await store.fetchList()
    await store.fetchList()
    expect(store.error).toBe('网络失败')
    expect(store.items).toHaveLength(1)
  })
})

describe('runs store 详情与载荷懒加载', () => {
  it('fetchDetail 写入 currentDetail', async () => {
    const detail: RunDetail = {
      summary: makeSummary(),
      events: [{ seq: 1, event_type: 'run_started', round: 0, call_id: null, data: {}, created_at: 'x' }],
    }
    runsApiMock.detail.mockResolvedValue(detail)
    const store = useRunsStore()
    await store.fetchDetail('run1')
    expect(store.currentDetail).toEqual(detail)
  })

  it('载荷元数据同 runId 只拉一次；全文按 payloadId 缓存', async () => {
    runsApiMock.payloads
      .mockResolvedValueOnce([{ id: 9, call_id: 'm1', payload_type: 'model_input', char_count: 10 }])
      .mockResolvedValue([])
    runsApiMock.payload.mockResolvedValue({
      id: 9, call_id: 'm1', payload_type: 'model_input', char_count: 10, content: 'HELLO',
    })
    const store = useRunsStore()
    await store.fetchPayloadMetas('run1')
    await store.fetchPayloadMetas('run1')
    expect(runsApiMock.payloads).toHaveBeenCalledTimes(1)
    await store.fetchPayloadContent('run1', 9)
    await store.fetchPayloadContent('run1', 9)
    expect(runsApiMock.payload).toHaveBeenCalledTimes(1)
    expect(store.payloadContents[9]?.content).toBe('HELLO')
  })
})
