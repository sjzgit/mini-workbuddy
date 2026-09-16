/**
 * 运行记录 API 封装（specs/011，契约主定义 specs/011-context-compression-run-records/contracts/runs-api.md）。
 * 类型 MUST 与后端 schemas/runs.py 逐字段对齐，变更先改契约。
 */
import { http } from './request'

// ---- 枚举与常量（契约唯一主定义，实现侧只消费）----

export type RunStatus = 'running' | 'succeeded' | 'partial' | 'failed' | 'cancelled'

export const RUN_STATUSES: RunStatus[] = ['running', 'succeeded', 'partial', 'failed', 'cancelled']

export const RUN_STATUS_META: Record<RunStatus, { text: string; color: string }> = {
  running: { text: '运行中', color: 'processing' },
  succeeded: { text: '成功', color: 'success' },
  partial: { text: '部分完成', color: 'warning' },
  failed: { text: '失败', color: 'error' },
  cancelled: { text: '已取消', color: 'default' },
}

// ---- 数据结构 ----

export interface RunSummary {
  run_id: string
  conversation_id: number | null
  agent_name: string
  model_name: string
  status: RunStatus
  end_reason: string
  error_summary: string | null
  started_at: string
  finished_at: string | null
  total_duration_ms: number | null
  model_call_count: number
  tool_call_count: number
  prompt_tokens: number | null
  completion_tokens: number | null
  total_tokens: number | null
  first_output_ms: number | null
}

export interface RunListResponse {
  items: RunSummary[]
  total: number
  page: number
  page_size: number
}

export interface RunEventOut {
  seq: number
  event_type: string
  round: number | null
  call_id: string | null
  data: Record<string, unknown>
  created_at: string
}

export interface RunDetail {
  summary: RunSummary
  events: RunEventOut[]
}

export interface RunPayloadMeta {
  id: number
  call_id: string
  payload_type: string
  char_count: number
}

export interface RunPayloadContent extends RunPayloadMeta {
  content: string
}

export const PAYLOAD_TYPE_TEXT: Record<string, string> = {
  model_input: '模型输入',
  model_output: '模型输出',
  tool_params: '工具参数',
  tool_result: '工具结果',
  compression_input: '压缩输入',
  compression_output: '压缩摘要',
}

export interface RunListQuery {
  status?: RunStatus
  agent_id?: number
  conversation_id?: number
  page?: number
  page_size?: number
}

// ---- API ----


// ---- 会话消息过程回放（011 优化①：刷新后回显工具调用全过程）----

export type ReplayItem =
  | { kind: 'reasoning' | 'content'; round: number | null; text: string }
  | {
      kind: 'tool'
      round: number | null
      callId: string
      toolName: string
      displayName: string
      toolType: 'builtin' | 'mcp' | 'skill'
      serverName: string | null
      status: 'success' | 'error' | 'denied' | 'cancelled'
      durationMs: number | null
      paramsSummary: string
      resultSummary: string
      paramsText: string
      resultText: string
    }

export interface RunReplay {
  run_id: string
  reply_message_id: number | null
  status: RunStatus
  items: ReplayItem[]
}

export const runsApi = {
  list(query: RunListQuery = {}): Promise<RunListResponse> {
    const params = new URLSearchParams()
    if (query.status) params.set('status', query.status)
    if (query.agent_id != null) params.set('agent_id', String(query.agent_id))
    if (query.conversation_id != null) params.set('conversation_id', String(query.conversation_id))
    params.set('page', String(query.page ?? 1))
    params.set('page_size', String(query.page_size ?? 20))
    return http.get(`/runs?${params.toString()}`)
  },
  detail(runId: string): Promise<RunDetail> {
    return http.get(`/runs/${runId}`)
  },
  payloads(runId: string): Promise<RunPayloadMeta[]> {
    return http.get(`/runs/${runId}/payloads`)
  },
  payload(runId: string, payloadId: number): Promise<RunPayloadContent> {
    return http.get(`/runs/${runId}/payloads/${payloadId}`)
  },
  conversationRuns(conversationId: number): Promise<RunSummary[]> {
    return http.get(`/conversations/${conversationId}/runs`)
  },
  conversationReplays(conversationId: number): Promise<RunReplay[]> {
    return http.get(`/conversations/${conversationId}/run-replays`)
  },
}
