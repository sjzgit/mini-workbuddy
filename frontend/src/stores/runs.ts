/**
 * 运行记录全局状态（Pinia，specs/011）。
 *
 * 列表：筛选 + 后端分页（恒定查询次数由后端保证，前端不追加请求）。
 * 详情：按 runId 缓存；载荷全文懒加载（FR-018：详情默认不读载荷）。
 */
import { defineStore } from 'pinia'
import { ref } from 'vue'

import {
  runsApi,
  type RunDetail,
  type RunListQuery,
  type RunPayloadContent,
  type RunPayloadMeta,
  type RunSummary,
} from '@/api/runs'

export const useRunsStore = defineStore('runs', () => {
  // ---- 列表 ----
  const items = ref<RunSummary[]>([])
  const total = ref(0)
  const page = ref(1)
  const pageSize = ref(20)
  const loading = ref(false)
  const error = ref<string | null>(null)
  const filters = ref<RunListQuery>({})

  async function fetchList(query?: Partial<RunListQuery>): Promise<void> {
    if (query) {
      filters.value = { ...filters.value, ...query }
      // 筛选变化回到第一页
      if ('status' in query || 'agent_id' in query || 'conversation_id' in query) {
        page.value = 1
      }
    }
    loading.value = true
    error.value = null
    try {
      const response = await runsApi.list({
        ...filters.value,
        page: page.value,
        page_size: pageSize.value,
      })
      items.value = response.items
      total.value = response.total
    } catch (e) {
      error.value = e instanceof Error ? e.message : '加载运行记录失败'
    } finally {
      loading.value = false
    }
  }

  function setPage(next: number, size: number): void {
    page.value = next
    pageSize.value = size
    void fetchList()
  }

  function resetFilters(): void {
    filters.value = {}
    page.value = 1
  }

  // ---- 详情 ----
  const currentDetail = ref<RunDetail | null>(null)
  const detailLoading = ref(false)
  const detailError = ref<string | null>(null)

  async function fetchDetail(runId: string): Promise<RunDetail> {
    detailLoading.value = true
    detailError.value = null
    try {
      currentDetail.value = await runsApi.detail(runId)
      return currentDetail.value
    } catch (e) {
      detailError.value = e instanceof Error ? e.message : '加载运行详情失败'
      throw e
    } finally {
      detailLoading.value = false
    }
  }

  // ---- 载荷（懒加载） ----
  const payloadMetas = ref<Record<string, RunPayloadMeta[]>>({})
  const payloadContents = ref<Record<number, RunPayloadContent>>({})
  const payloadLoadingId = ref<number | null>(null)

  async function fetchPayloadMetas(runId: string): Promise<void> {
    if (payloadMetas.value[runId]) return
    payloadMetas.value[runId] = await runsApi.payloads(runId)
  }

  async function fetchPayloadContent(runId: string, payloadId: number): Promise<RunPayloadContent> {
    const cached = payloadContents.value[payloadId]
    if (cached) return cached
    payloadLoadingId.value = payloadId
    try {
      const content = await runsApi.payload(runId, payloadId)
      payloadContents.value[payloadId] = content
      return content
    } finally {
      payloadLoadingId.value = null
    }
  }

  return {
    items, total, page, pageSize, loading, error, filters,
    fetchList, setPage, resetFilters,
    currentDetail, detailLoading, detailError, fetchDetail,
    payloadMetas, payloadContents, payloadLoadingId,
    fetchPayloadMetas, fetchPayloadContent,
  }
})
