/**
 * 聊天功能接口封装。
 *
 * 契约主定义：specs/008-chat-conversations/contracts/chat-api.md
 * 类型 MUST 与契约逐字段类型对齐（null 不混用 undefined）。
 */
import { http } from './request'

/** 消息角色（契约枚举 Role） */
export type Role = 'user' | 'assistant'

/** 消息状态（契约枚举 MessageStatus） */
export type MessageStatus = 'generating' | 'completed' | 'incomplete'

/** 流内错误类别（契约枚举 StreamErrorCategory） */
export type StreamErrorCategory =
  | 'unreachable'
  | 'timeout'
  | 'auth_error'
  | 'model_not_found'
  | 'bad_response'
  | 'empty_response'
  | 'stream_interrupted'
  | 'context_overflow'
  | 'unknown'

/** 会话摘要（列表 / 新建 / 切换返回；只含摘要不含消息，FR-006） */
export interface ConversationSummary {
  id: number
  title: string
  agent_id: number
  updated_at: string
  created_at: string
}

/** 消息（读取与流终态事件返回） */
export interface MessageOut {
  id: number
  conversation_id: number
  role: Role
  agent_id: number | null
  agent_name: string | null
  reasoning_content: string | null
  content: string
  status: MessageStatus
  seq: number
  created_at: string
}

/** 发送 / 重新生成响应 */
export interface StartReplyResponse {
  user_message: MessageOut | null
  reply_message_id: number
  conversation: ConversationSummary
}

/** 停止响应 */
export interface StopResponse {
  stopped: boolean
}

/** 切换 Agent / 新建会话请求体 */
export interface AgentRefRequest {
  agent_id: number
}

// ---- SSE 事件（契约主定义：specs/009-agent-runtime/contracts/agent-runtime-api.md §2/§3）----

export interface ReasoningDeltaData {
  run_id: string
  seq: number
  round: number
  call_id: string
  text: string
}

export interface ContentDeltaData {
  run_id: string
  seq: number
  round: number
  call_id: string
  text: string
}

/** 工具类型（契约 §4） */
export type RuntimeToolType = 'builtin' | 'mcp' | 'skill'

export interface ToolCallStartedData {
  run_id: string
  seq: number
  round: number
  call_id: string
  tool_name: string
  tool_type: RuntimeToolType
  params_summary: string
  /** 010 增补：完整参数 JSON 文本（后端已按上限截断并附标记） */
  params: string
  /** 易读名称：builtin=注册表名；mcp=原工具名；skill="加载 Skill" */
  display_name: string
  /** MCP Server 显示名，仅 tool_type=mcp 非空 */
  server_name: string | null
}

export interface ToolCallCompletedData {
  run_id: string
  seq: number
  round: number
  call_id: string
  tool_name: string
  tool_type: RuntimeToolType
  status: 'success' | 'error' | 'denied' | 'cancelled'
  duration_ms: number
  result_summary: string
  /** 010 增补：完整结果文本（成功=结果全文；失败=人话原因无堆栈；超限截断附标记） */
  result: string
  display_name: string
  server_name: string | null
}

export interface ErrorEventData {
  category: StreamErrorCategory
  message: string
}

/** Token 用量（null = 接口未返回，未知；不出现 0 冒充，FR-034） */
export interface RuntimeUsage {
  prompt_tokens: number | null
  completion_tokens: number | null
  total_tokens: number | null
}

/** 运行终态（取代 008 done；桥接层已剥离 content_text/reasoning_text） */
export interface RunCompletedData {
  run_id: string
  seq: number
  status: 'completed' | 'max_rounds' | 'error' | 'cancelled'
  reason: string
  usage_total: RuntimeUsage | null
  message: MessageOut | null
  stopped: boolean
}

/** 流事件联合（运行级事件由聊天页忽略，仅透传给调试面板；终态为 run_completed） */
export type StreamEvent =
  | { event: 'run_started'; data: { run_id: string; seq: number; agent_id: number; agent_name: string } }
  | { event: 'model_request_started'; data: { run_id: string; seq: number; round: number; call_id: string } }
  | { event: 'reasoning_delta'; data: ReasoningDeltaData }
  | { event: 'content_delta'; data: ContentDeltaData }
  | { event: 'model_request_completed'; data: { run_id: string; seq: number; round: number; call_id: string; status: string; duration_ms: number; usage: RuntimeUsage | null } }
  | { event: 'tool_call_started'; data: ToolCallStartedData }
  | { event: 'tool_call_completed'; data: ToolCallCompletedData }
  | { event: 'error'; data: ErrorEventData }
  | { event: 'run_completed'; data: RunCompletedData }

/** SSE 帧解析：喂入文本块，产出解析完成的事件。 */
export class SseParser {
  private buffer = ''

  /** 解析一个文本块，返回解析出的帧（event 名 + 原始 data JSON） */
  push(chunk: string): { event: string; data: string }[] {
    this.buffer += chunk
    const frames: { event: string; data: string }[] = []
    // SSE 帧以空行结束
    let index: number
    while ((index = this.buffer.indexOf('\n\n')) !== -1) {
      const raw = this.buffer.slice(0, index)
      this.buffer = this.buffer.slice(index + 2)
      let eventName = 'message'
      let data = ''
      for (const line of raw.split('\n')) {
        if (line.startsWith('event: ')) {
          eventName = line.slice(7).trim()
        } else if (line.startsWith('data: ')) {
          data = line.slice(6)
        }
      }
      if (data) {
        frames.push({ event: eventName, data })
      }
    }
    return frames
  }
}

/** 打开生成流订阅（fetch POST 之外的 GET + ReadableStream，research R1）。 */
export async function openStream(
  conversationId: number,
  messageId: number,
  onEvent: (event: StreamEvent) => void,
  signal?: AbortSignal,
): Promise<void> {
  const response = await fetch(
    `/api/conversations/${conversationId}/messages/${messageId}/stream`,
    { headers: { Accept: 'text/event-stream' }, signal },
  )
  if (!response.ok || !response.body) {
    throw new Error(`流订阅失败（HTTP ${response.status}）`)
  }
  const reader = response.body.getReader()
  const decoder = new TextDecoder()
  const parser = new SseParser()
  try {
    for (;;) {
      const { done, value } = await reader.read()
      if (done) break
      for (const frame of parser.push(decoder.decode(value, { stream: true }))) {
        dispatchFrame(frame, onEvent)
      }
    }
    // 冲刷残余 buffer（服务端保证 done 后关流，残余视为不完整帧丢弃）
  } finally {
    reader.releaseLock()
  }
}

function dispatchFrame(frame: { event: string; data: string }, onEvent: (e: StreamEvent) => void): void {
  try {
    const data = JSON.parse(frame.data)
    switch (frame.event) {
      case 'run_started':
        onEvent({ event: 'run_started', data })
        break
      case 'model_request_started':
        onEvent({ event: 'model_request_started', data })
        break
      case 'reasoning_delta':
        onEvent({ event: 'reasoning_delta', data: data as ReasoningDeltaData })
        break
      case 'content_delta':
        onEvent({ event: 'content_delta', data: data as ContentDeltaData })
        break
      case 'model_request_completed':
        onEvent({ event: 'model_request_completed', data })
        break
      case 'tool_call_started':
        onEvent({ event: 'tool_call_started', data: data as ToolCallStartedData })
        break
      case 'tool_call_completed':
        onEvent({ event: 'tool_call_completed', data: data as ToolCallCompletedData })
        break
      case 'error':
        onEvent({ event: 'error', data: data as ErrorEventData })
        break
      case 'run_completed':
        onEvent({ event: 'run_completed', data: data as RunCompletedData })
        break
      default:
        break // 未知事件忽略（前向兼容）
    }
  } catch {
    // 无法解析的帧忽略
  }
}

export const chatApi = {
  list(): Promise<ConversationSummary[]> {
    return http.get('/conversations')
  },
  create(agentId: number): Promise<ConversationSummary> {
    return http.post('/conversations', { agent_id: agentId })
  },
  switchAgent(conversationId: number, agentId: number): Promise<ConversationSummary> {
    return http.put(`/conversations/${conversationId}`, { agent_id: agentId })
  },
  messages(conversationId: number): Promise<MessageOut[]> {
    return http.get(`/conversations/${conversationId}/messages`)
  },
  send(conversationId: number, content: string): Promise<StartReplyResponse> {
    return http.post(`/conversations/${conversationId}/messages`, { content })
  },
  regenerate(conversationId: number): Promise<StartReplyResponse> {
    return http.post(`/conversations/${conversationId}/regenerate`)
  },
  stop(conversationId: number, messageId: number): Promise<StopResponse> {
    return http.post(`/conversations/${conversationId}/messages/${messageId}/stop`)
  },
}
