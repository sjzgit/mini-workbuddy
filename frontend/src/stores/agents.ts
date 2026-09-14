/**
 * Agent 管理列表全局状态（Pinia）。
 * 与既有 stores 边界一致：列表/加载态/动作；对话框表单态由组件自持。
 */
import { defineStore } from 'pinia'
import { ref } from 'vue'

import {
  agentsApi,
  type AgentDeleteResponse,
  type AgentDetail,
  type AgentListItem,
  type AgentSaveRequest,
  type BindingOptionsResponse,
  type ReferencedByAgentBody,
  type RequiresNewDefaultBody,
} from '@/api/agents'
import { ApiError } from '@/api/request'

/** 解析 409 响应体（结构化 detail 对象 vs 普通字符串） */
export function parseConflictBody(e: unknown): ReferencedByAgentBody | RequiresNewDefaultBody | null {
  if (e instanceof ApiError && e.status === 409 && e.body && typeof e.body === 'object') {
    const detail = (e.body as { detail?: unknown }).detail
    if (detail && typeof detail === 'object') {
      return detail as ReferencedByAgentBody | RequiresNewDefaultBody
    }
  }
  return null
}

export const useAgentsStore = defineStore('agents', () => {
  const items = ref<AgentListItem[]>([])
  const loading = ref(false)
  const saving = ref(false)
  /** binding-options 缓存（编辑对话框打开时拉取） */
  const options = ref<BindingOptionsResponse | null>(null)

  async function fetchAgents(): Promise<void> {
    loading.value = true
    try {
      items.value = await agentsApi.list()
    } finally {
      loading.value = false
    }
  }

  async function loadBindingOptions(agentId?: number): Promise<BindingOptionsResponse> {
    const result = await agentsApi.bindingOptions(agentId)
    options.value = result
    return result
  }

  async function fetchDetail(id: number): Promise<AgentDetail> {
    return agentsApi.detail(id)
  }

  async function save(payload: AgentSaveRequest, agentId?: number): Promise<AgentDetail> {
    saving.value = true
    try {
      const detail = agentId === undefined ? await agentsApi.create(payload) : await agentsApi.update(agentId, payload)
      await fetchAgents()
      return detail
    } finally {
      saving.value = false
    }
  }

  /** 删除（可带 new_default_id）；409 结构化响应体（requires_new_default）原样抛出供调用方识别 */
  async function remove(id: number, newDefaultId?: number): Promise<AgentDeleteResponse> {
    const result = await agentsApi.remove(id, newDefaultId)
    await fetchAgents()
    return result
  }

  async function setDefault(id: number): Promise<void> {
    await agentsApi.setDefault(id)
    await fetchAgents()
  }

  return {
    items,
    loading,
    saving,
    options,
    fetchAgents,
    loadBindingOptions,
    fetchDetail,
    save,
    remove,
    setDefault,
  }
})
