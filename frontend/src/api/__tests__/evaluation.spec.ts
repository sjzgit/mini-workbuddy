/**
 * 评测 API 封装测试（specs/012 T035）：类型消费、状态映射、请求路径与重试语义。
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import {
  CASE_RUN_STATUS_META,
  EVAL_RUN_STATUSES,
  EVAL_RUN_STATUS_META,
  exportDatasetUrl,
  listEvalRuns,
  retryEvalRunCase,
  type EvalRunStatus,
} from '../evaluation'

const fetchMock = vi.fn()

beforeEach(() => {
  vi.stubGlobal('fetch', fetchMock)
  fetchMock.mockReset()
})

afterEach(() => {
  vi.unstubAllGlobals()
})

function jsonResponse(body: unknown): Response {
  return {
    ok: true,
    status: 200,
    json: async () => body,
  } as unknown as Response
}

describe('状态元数据映射', () => {
  it('全部评测运行状态都有文案与颜色', () => {
    for (const status of EVAL_RUN_STATUSES) {
      const meta = EVAL_RUN_STATUS_META[status]
      expect(meta.text.length).toBeGreaterThan(0)
      expect(meta.color.length).toBeGreaterThan(0)
    }
  })

  it('全部 CaseRun 状态都有文案与颜色', () => {
    const statuses = Object.keys(CASE_RUN_STATUS_META) as (keyof typeof CASE_RUN_STATUS_META)[]
    expect(statuses).toContain('passed')
    expect(statuses).toContain('execution_failed')
    expect(statuses).toContain('judge_failed')
    for (const status of statuses) {
      expect(CASE_RUN_STATUS_META[status].text.length).toBeGreaterThan(0)
    }
  })

  it('失败类状态用警示色，通过用成功色', () => {
    expect(CASE_RUN_STATUS_META.passed.color).toBe('success')
    expect(CASE_RUN_STATUS_META.execution_failed.color).toBe('error')
    expect(EVAL_RUN_STATUS_META.completed.color).toBe('success')
    expect(EVAL_RUN_STATUS_META.interrupted.color).toBe('warning')
  })
})

describe('导出地址', () => {
  it('拼接 /api 前缀相对路径', () => {
    expect(exportDatasetUrl(3)).toBe('/api/evaluation/datasets/3/export')
  })
})

describe('listEvalRuns', () => {
  it('携带过滤与分页 query', async () => {
    fetchMock.mockResolvedValueOnce(jsonResponse({ items: [], total: 0, page: 1, page_size: 20 }))
    await listEvalRuns({ status: 'completed', page: 2, page_size: 10, task_id: 5 })
    const called = fetchMock.mock.calls[0]?.[0] as string
    expect(called).toContain('/api/evaluation/runs')
    expect(called).toContain('status=completed')
    expect(called).toContain('page=2')
    expect(called).toContain('page_size=10')
    expect(called).toContain('task_id=5')
  })

  it('无过滤时不带 query', async () => {
    fetchMock.mockResolvedValueOnce(jsonResponse({ items: [], total: 0, page: 1, page_size: 20 }))
    await listEvalRuns()
    expect(fetchMock.mock.calls[0]?.[0]).toBe('/api/evaluation/runs')
  })
})

describe('retryEvalRunCase', () => {
  it('POST case_run_id 到 retry 端点', async () => {
    fetchMock.mockResolvedValueOnce(jsonResponse({ run: { id: 1 }, case_run: { id: 2 } }))
    const result = await retryEvalRunCase(7, 42)
    const [called, init] = fetchMock.mock.calls[0] as [string, RequestInit]
    expect(called).toBe('/api/evaluation/runs/7/retry')
    expect(init.method).toBe('POST')
    expect(JSON.parse(String(init.body))).toEqual({ case_run_id: 42 })
    expect(result.case_run.id).toBe(2)
  })
})
