/**
 * Agent 管理接口封装。
 *
 * 契约主定义：specs/007-agent-management/contracts/agents-api.md
 * 类型 MUST 与契约逐字段类型对齐（null 不混用 undefined）。
 */
import { http } from './request'

/** 绑定资源类型（契约枚举） */
export type ResourceType = 'tool' | 'skill' | 'mcp'

/** 深度思考程度（契约枚举 ThinkingLevel） */
export type ThinkingLevel = 'off' | 'low' | 'medium' | 'high'

/** 常量（契约"枚举与常量"节，实现侧只消费） */
export const MAX_ROUNDS_DEFAULT = 10
export const MAX_ROUNDS_MIN = 1
export const MAX_ROUNDS_MAX = 100
export const ENABLE_DEEP_THINKING_DEFAULT = false
export const THINKING_LEVEL_DEFAULT: ThinkingLevel = 'off'

/** 绑定项（详情返回；enabled=false → 前端标"已停用，不可用"） */
export interface BindingItem {
  resource_type: ResourceType
  resource_id: number
  name: string
  description: string
  enabled: boolean
}

/** 候选项（binding-options；仅启用资源） */
export interface BindingOption {
  id: number
  name: string
  description: string
  selected: boolean
}

/** 模型候选（展示名称与标识，FR-013） */
export interface ModelOption {
  id: number
  display_name: string
  model_identifier: string
  is_default: boolean
}

/** 提示词版本 */
export interface PromptVersion {
  version: number
  content: string
  created_at: string
}

/** 提交体中的绑定引用 */
export interface BindingRef {
  resource_type: ResourceType
  resource_id: number
}

/** 列表卡片项（契约 AgentListItem；bindings 全量，卡片按类分行展示用） */
export interface AgentListItem {
  id: number
  name: string
  description: string
  model_display_name: string
  model_identifier: string
  tool_count: number
  skill_count: number
  mcp_count: number
  bindings: BindingItem[]
  is_default: boolean
  updated_at: string
}

/** 详情/保存返回（契约 AgentDetail） */
export interface AgentDetail {
  id: number
  name: string
  description: string
  model_id: number
  model_display_name: string
  model_identifier: string
  system_prompt: string
  prompt_versions: PromptVersion[]
  bindings: BindingItem[]
  max_rounds: number
  enable_deep_thinking: boolean
  thinking_level: ThinkingLevel
  is_default: boolean
  updated_at: string
}

/** 删除默认 Agent 缺新默认时的 409 响应体（契约 requires_new_default） */
export interface RequiresNewDefaultBody {
  detail: string
  requires_new_default: boolean
  candidates: { id: number; name: string }[]
}

/** 引用保护 409 响应体（契约引用保护节） */
export interface ReferencedByAgentBody {
  detail: string
  referenced_by_agents: { id: number; name: string }[]
}

/** 资源候选聚合响应（契约 binding-options） */
export interface BindingOptionsResponse {
  tools: BindingOption[]
  skills: BindingOption[]
  mcp_servers: BindingOption[]
  models: ModelOption[]
  prompt_template: string
}

/** 新建/编辑提交体（契约 AgentSaveRequest；bindings 缺省 = 保持原绑定） */
export interface AgentSaveRequest {
  name: string
  description?: string
  model_id: number
  system_prompt: string
  max_rounds?: number
  enable_deep_thinking?: boolean
  thinking_level?: ThinkingLevel
  is_default?: boolean
  bindings?: BindingRef[]
}

/** 删除响应 */
export interface AgentDeleteResponse {
  deleted: boolean
  cleared_default: boolean
}

export const agentsApi = {
  list(): Promise<AgentListItem[]> {
    return http.get('/agents')
  },
  detail(id: number): Promise<AgentDetail> {
    return http.get(`/agents/${id}`)
  },
  create(payload: AgentSaveRequest): Promise<AgentDetail> {
    return http.post('/agents', payload)
  },
  update(id: number, payload: AgentSaveRequest): Promise<AgentDetail> {
    return http.put(`/agents/${id}`, payload)
  },
  remove(id: number, newDefaultId?: number): Promise<AgentDeleteResponse> {
    const query = newDefaultId === undefined ? '' : `?new_default_id=${newDefaultId}`
    return http.del(`/agents/${id}${query}`)
  },
  setDefault(id: number): Promise<{ id: number }> {
    return http.post(`/agents/${id}/default`)
  },
  bindingOptions(agentId?: number): Promise<BindingOptionsResponse> {
    const query = agentId === undefined ? '' : `?agent_id=${agentId}`
    return http.get(`/agents/binding-options${query}`)
  },
}
