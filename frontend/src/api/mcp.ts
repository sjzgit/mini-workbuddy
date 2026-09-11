/**
 * MCP 管理接口封装。
 *
 * 契约主定义：specs/004-skills-mcp-management/contracts/mcp-api.md
 * 类型 MUST 与契约逐字段对齐（null 不混用 undefined）。
 */

/** Server 类型（契约 §2） */
export type ServerType = 'stdio' | 'http'

/** 测试结果状态（契约 §2） */
export type TestStatus = 'success' | 'failed' | 'config_changed'

/** 测试失败分类（契约 §5） */
export type TestCategory =
  | 'command_not_found'
  | 'process_failed'
  | 'timeout'
  | 'protocol_incompatible'
  | 'server_error'
  | 'connection_failed'
  | 'unknown'

/** 工具参数说明 */
export interface McpToolParam {
  name: string
  type: string
  required: boolean
  description: string
}

/** 测试发现的单个工具 */
export interface McpToolInfo {
  name: string
  description: string
  params: McpToolParam[]
}

/** 列表项 */
export interface McpServerItem {
  id: number
  name: string
  description: string
  server_type: ServerType
  enabled: boolean
  last_test_status: TestStatus | null
  last_test_message: string | null
  last_test_tool_count: number | null
  last_test_at: string | null
  updated_at: string
}

/** 详情（编辑页与工具弹窗数据源；敏感值只出掩码） */
export interface McpServerDetail extends McpServerItem {
  command: string | null
  command_args: string[] | null
  env_masked: Record<string, string> | null
  url: string | null
  headers_masked: Record<string, string> | null
  tools: McpToolInfo[]
}

/**
 * 新增/编辑提交体（契约 §2 三态协议）：
 * env/headers 值为 string = 替换/新增；null = 保留原值；键缺席 = 删除。
 */
export interface McpServerUpsertPayload {
  name: string
  description: string
  server_type: ServerType
  command: string | null
  command_args: string[] | null
  env: Record<string, string | null> | null
  url: string | null
  headers: Record<string, string | null> | null
}

/** 测试连接结果 */
export interface McpTestResult {
  status: 'success' | 'failed'
  category: TestCategory | null
  message: string
  tool_count: number | null
  tools: McpToolInfo[]
  item: McpServerItem
}

/** 删除响应 */
export interface McpDeletedResponse {
  deleted: boolean
}

import { http } from './request'

export const mcpApi = {
  list(): Promise<McpServerItem[]> {
    return http.get<McpServerItem[]>('/mcp/servers')
  },
  detail(id: number): Promise<McpServerDetail> {
    return http.get<McpServerDetail>(`/mcp/servers/${id}`)
  },
  create(payload: McpServerUpsertPayload): Promise<McpServerDetail> {
    return http.post<McpServerDetail>('/mcp/servers', payload)
  },
  update(id: number, payload: McpServerUpsertPayload): Promise<McpServerDetail> {
    return http.put<McpServerDetail>(`/mcp/servers/${id}`, payload)
  },
  remove(id: number): Promise<McpDeletedResponse> {
    return http.del<McpDeletedResponse>(`/mcp/servers/${id}`)
  },
  setEnabled(id: number, enabled: boolean): Promise<McpServerItem> {
    return http.put<McpServerItem>(`/mcp/servers/${id}/enabled`, { enabled })
  },
  test(id: number): Promise<McpTestResult> {
    return http.post<McpTestResult>(`/mcp/servers/${id}/test`)
  },
}
