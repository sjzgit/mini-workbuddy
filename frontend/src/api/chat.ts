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

// ---- SSE 事件 ----

export interface ReasoningDeltaData {
  text: string
}

export interface ContentDeltaData {
  text: string
}

export interface DoneEventData {
  message: MessageOut | null
  stopped: boolean
}

export interface ErrorEventData {
  category: StreamErrorCategory
  message: string
}

/** 流事件联合 */
export type StreamEvent =
  | { event: 'reasoning_delta'; data: ReasoningDeltaData }
  | { event: 'content_delta'; data: ContentDeltaData }
  | { event: 'error'; data: ErrorEventData }
  | { event: 'done'; data: DoneEventData }

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
    if (frame.event === 'reasoning_delta') {
      onEvent({ event: 'reasoning_delta', data: data as ReasoningDeltaData })
    } else if (frame.event === 'content_delta') {
      onEvent({ event: 'content_delta', data: data as ContentDeltaData })
    } else if (frame.event === 'error') {
      onEvent({ event: 'error', data: data as ErrorEventData })
    } else if (frame.event === 'done') {
      onEvent({ event: 'done', data: data as DoneEventData })
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
