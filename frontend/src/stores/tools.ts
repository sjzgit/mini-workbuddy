/**
 * 工具列表全局状态（Pinia）。
 *
 * 只承载列表/加载/错误状态；启停动作由视图调用 api 后同步本地列表
 * （单行变更，无需整表刷新）。
 */
import { defineStore } from 'pinia'
import { ref } from 'vue'

import { toolsApi, type ToolItem } from '@/api/tools'

export const useToolsStore = defineStore('tools', () => {
  /** 工具列表（name 字母序，由后端保证） */
  const items = ref<ToolItem[]>([])
  /** 是否加载中 */
  const loading = ref(false)
  /** 加载错误（人话信息；null = 无错误） */
  const error = ref<string | null>(null)
  /** 正在切换启停的工具名（防重复提交）；null = 无 */
  const togglingName = ref<string | null>(null)

  /** 拉取列表；失败时写入 error，不清空已有数据 */
  async function fetchTools(): Promise<void> {
    loading.value = true
    error.value = null
    try {
      items.value = await toolsApi.list()
    } catch (e) {
      error.value = e instanceof Error ? e.message : '加载工具列表失败'
    } finally {
      loading.value = false
    }
  }

  /**
   * 启停某工具：成功后同步列表中该行（含 updated_at）。
   * 返回是否成功；错误信息向上抛由调用方决定提示方式。
   */
  async function setEnabled(name: string, enabled: boolean): Promise<ToolItem> {
    togglingName.value = name
    try {
      const updated = await toolsApi.setEnabled(name, { enabled })
      const index = items.value.findIndex((t) => t.name === name)
      if (index >= 0) items.value[index] = updated
      return updated
    } finally {
      togglingName.value = null
    }
  }

  return { items, loading, error, togglingName, fetchTools, setEnabled }
})
