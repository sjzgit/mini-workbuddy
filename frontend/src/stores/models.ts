/**
 * 模型列表全局状态（Pinia）。
 * 只承载列表/加载/错误状态；变更操作由视图调用 api 后刷新列表。
 */
import { defineStore } from 'pinia'
import { ref } from 'vue'

import { modelsApi, type ModelItem } from '@/api/models'

export const useModelsStore = defineStore('models', () => {
  /** 模型列表（更新时间倒序，由后端保证） */
  const items = ref<ModelItem[]>([])
  /** 是否加载中 */
  const loading = ref(false)
  /** 加载错误（人话信息；null = 无错误） */
  const error = ref<string | null>(null)

  /** 拉取列表；失败时写入 error，不清空已有数据 */
  async function fetchModels(): Promise<void> {
    loading.value = true
    error.value = null
    try {
      items.value = await modelsApi.list()
    } catch (e) {
      error.value = e instanceof Error ? e.message : '加载模型列表失败'
    } finally {
      loading.value = false
    }
  }

  return { items, loading, error, fetchModels }
})
