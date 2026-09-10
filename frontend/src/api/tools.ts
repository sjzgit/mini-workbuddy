/**
 * 工具管理接口封装。
 *
 * 契约主定义：specs/003-tool-management/contracts/api-contract.md
 * 类型 MUST 与契约逐字段对齐（null 不混用 undefined）。
 */

import { http } from './request'

/** 工具参数定义（详情参数表的一行） */
export interface ToolParam {
  name: string
  type: 'string' | 'enum'
  required: boolean
  description: string
}

/** 列表项 */
export interface ToolItem {
  name: string
  display_name: string
  purpose: string
  params_summary: string
  enabled: boolean
  is_builtin: boolean
  updated_at: string
}

/** 详情（含参数表与三节说明） */
export interface ToolDetail extends ToolItem {
  params: ToolParam[]
  usage_scenarios: string
  input_requirements: string
  restrictions: string
}

/** 启停提交体 */
export interface ToolTogglePayload {
  enabled: boolean
}

export const toolsApi = {
  list(): Promise<ToolItem[]> {
    return http.get<ToolItem[]>('/tools')
  },
  detail(name: string): Promise<ToolDetail> {
    return http.get<ToolDetail>(`/tools/${name}`)
  },
  setEnabled(name: string, payload: ToolTogglePayload): Promise<ToolItem> {
    return http.put<ToolItem>(`/tools/${name}/enabled`, payload)
  },
}
