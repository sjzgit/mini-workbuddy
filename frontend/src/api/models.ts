/**
 * 模型管理接口封装。
 *
 * 契约主定义：specs/002-model-management/contracts/api-contract.md
 * 类型 MUST 与契约逐字段对齐（null 不混用 undefined）。
 */

/** 测试连接错误分类（契约枚举） */
export type TestErrorCategory =
  | 'auth_error'
  | 'model_not_found'
  | 'unreachable'
  | 'timeout'
  | 'bad_response'
  | 'unknown'

/** 列表项 */
export interface ModelItem {
  id: number
  display_name: string
  model_identifier: string
  base_url: string
  context_length: number
  api_key_configured: boolean
  is_default: boolean
  updated_at: string
}

/** 详情（含可编辑字段） */
export interface ModelDetail extends ModelItem {
  max_output_tokens: number
  temperature: number
  input_price: number | null
  output_price: number | null
  cached_input_price: number | null
}

/** 新增/编辑提交体 */
export interface ModelUpsertPayload {
  display_name: string
  model_identifier: string
  base_url: string
  api_key: string | null
  context_length: number
  max_output_tokens: number
  temperature: number
  input_price: number | null
  output_price: number | null
  cached_input_price: number | null
}

/** 测试连接结果 */
export interface TestConnectionResult {
  success: boolean
  category: TestErrorCategory | null
  message: string
  reply_excerpt: string | null
}

/** 删除响应 */
export interface DeleteResponse {
  deleted: boolean
}

/** 设默认响应 */
export interface SetDefaultResponse {
  id: number
  is_default: boolean
}

import { http } from './request'

export const modelsApi = {
  list(): Promise<ModelItem[]> {
    return http.get<ModelItem[]>('/models')
  },
  detail(id: number): Promise<ModelDetail> {
    return http.get<ModelDetail>(`/models/${id}`)
  },
  create(payload: ModelUpsertPayload): Promise<ModelDetail> {
    return http.post<ModelDetail>('/models', payload)
  },
  update(id: number, payload: ModelUpsertPayload): Promise<ModelDetail> {
    return http.put<ModelDetail>(`/models/${id}`, payload)
  },
  remove(id: number, newDefaultId?: number): Promise<DeleteResponse> {
    const query = newDefaultId === undefined ? '' : `?new_default_id=${newDefaultId}`
    return http.del<DeleteResponse>(`/models/${id}${query}`)
  },
  setDefault(id: number): Promise<SetDefaultResponse> {
    return http.post<SetDefaultResponse>(`/models/${id}/default`)
  },
  testConnection(id: number): Promise<TestConnectionResult> {
    return http.post<TestConnectionResult>(`/models/${id}/test-connection`)
  },
}
