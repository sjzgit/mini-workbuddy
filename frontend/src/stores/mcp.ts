/**
 * MCP Server 列表全局状态（Pinia）。
 * testingId 单一进行中标识（spec FR-030：同一 Server 同时至多一次测试）。
 */
import { defineStore } from 'pinia'
import { ref } from 'vue'

import { mcpApi, type McpServerItem, type McpTestResult } from '@/api/mcp'

export const useMcpStore = defineStore('mcp', () => {
  /** Server 列表（更新时间倒序，由后端保证） */
  const items = ref<McpServerItem[]>([])
  /** 是否加载中 */
  const loading = ref(false)
  /** 加载错误（人话信息；null = 无错误） */
  const error = ref<string | null>(null)
  /** 正在测试连接的 Server id（null = 无测试进行中） */
  const testingId = ref<number | null>(null)

  async function fetchServers(): Promise<void> {
    loading.value = true
    error.value = null
    try {
      items.value = await mcpApi.list()
    } catch (e) {
      error.value = e instanceof Error ? e.message : '加载 MCP Server 列表失败'
    } finally {
      loading.value = false
    }
  }

  /** 就地替换一行（启停/测试结果返回 item 时用） */
  function replaceItem(updated: McpServerItem): void {
    const index = items.value.findIndex((item) => item.id === updated.id)
    if (index >= 0) items.value.splice(index, 1, updated)
  }

  async function setEnabled(id: number, enabled: boolean): Promise<void> {
    const updated = await mcpApi.setEnabled(id, enabled)
    replaceItem(updated)
  }

  async function remove(id: number): Promise<void> {
    await mcpApi.remove(id)
    items.value = items.value.filter((item) => item.id !== id)
  }

  /** 测试连接：置位 testingId → 完成后复位并用返回 item 替换行 */
  async function test(id: number): Promise<McpTestResult> {
    testingId.value = id
    try {
      const result = await mcpApi.test(id)
      replaceItem(result.item)
      return result
    } finally {
      testingId.value = null
    }
  }

  return { items, loading, error, testingId, fetchServers, replaceItem, setEnabled, remove, test }
})
