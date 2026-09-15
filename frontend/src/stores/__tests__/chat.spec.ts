/**
 * 聊天 store 测试（specs/008-chat-conversations T032/T036/T039 前端部分）。
 * mock @/api/chat：验证发送流转、终态复位、切换 Agent、错误与后台订阅恢复。
 */
import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import type { MessageOut } from '@/api/chat'

const { chatApiMock, openStreamMock } = vi.hoisted(() => ({
  chatApiMock: {
    list: vi.fn(),
    create: vi.fn(),
    switchAgent: vi.fn(),
    messages: vi.fn(),
    send: vi.fn(),
    regenerate: vi.fn(),
    stop: vi.fn(),
  },
  openStreamMock: vi.fn(),
}))

vi.mock('@/api/chat', () => ({
  chatApi: chatApiMock,
  openStream: openStreamMock,
}))

vi.mock('@/stores/agents', () => ({
  useAgentsStore: () => ({ items: [], fetchAgents: vi.fn() }),
}))

import { useChatStore } from '../chat'

function makeMessage(overrides: Partial<MessageOut>): MessageOut {
  return {
    id: 1,
    conversation_id: 1,
    role: 'user',
    agent_id: null,
    agent_name: null,
    reasoning_content: null,
    content: 'hi',
    status: 'completed',
    seq: 1,
    created_at: '2026-09-14T00:00:00',
    ...overrides,
  }
}

/** 从 openStream mock 抓取 onEvent 回调 */
function streamHandler(): (e: Parameters<Parameters<typeof openStreamMock>[2]>[0]) => void {
  const calls = openStreamMock.mock.calls
  const call = calls[calls.length - 1]
  if (call === undefined) {
    throw new Error('openStream not called')
  }
  return call[2] as never
}

describe('chat store', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.clearAllMocks()
  })

  it('send：流转 thinking → 订阅流，done 后复位 idle 且消息入列', async () => {
    const chat = useChatStore()
    chat.currentId = 1
    chatApiMock.send.mockResolvedValue({
      user_message: makeMessage({ id: 10, role: 'user', seq: 1 }),
      reply_message_id: 11,
      conversation: { id: 1, title: 'hi', agent_id: 1, updated_at: 't', created_at: 't' },
    })
    openStreamMock.mockResolvedValue(undefined)

    const pending = chat.send('hi')
    expect(chat.phase).toBe('thinking')
    await pending

    expect(chatApiMock.send).toHaveBeenCalledWith(1, 'hi')
    expect(openStreamMock).toHaveBeenCalledWith(1, 11, expect.any(Function))
    expect(chat.messages).toHaveLength(1)

    // 模拟终态 done
    const handler = streamHandler()
    handler({
      event: 'done',
      data: { message: makeMessage({ id: 11, role: 'assistant', seq: 2, content: '答' }), stopped: false },
    })
    expect(chat.phase).toBe('idle')
    expect(chat.messages).toHaveLength(2)
    expect(chat.messages[1]?.content).toBe('答')
  })

  it('error 事件写入独立错误条且正文不受污染；done 后 idle', async () => {
    const chat = useChatStore()
    chat.currentId = 1
    chatApiMock.send.mockResolvedValue({
      user_message: makeMessage({ id: 10 }),
      reply_message_id: 11,
      conversation: { id: 1, title: 'hi', agent_id: 1, updated_at: 't', created_at: 't' },
    })
    openStreamMock.mockResolvedValue(undefined)
    await chat.send('hi')

    const handler = streamHandler()
    handler({ event: 'error', data: { category: 'auth_error', message: '认证失败：API Key 无效' } })
    expect(chat.error?.category).toBe('auth_error')
    handler({ event: 'done', data: { message: null, stopped: false } })
    expect(chat.phase).toBe('idle')
  })

  it('send 失败：phase 复位并抛出（调用方恢复输入 FR-009）', async () => {
    const chat = useChatStore()
    chat.currentId = 1
    chatApiMock.send.mockRejectedValue(new Error('boom'))
    await expect(chat.send('hi')).rejects.toThrow()
    expect(chat.phase).toBe('idle')
    expect(chat.error).not.toBeNull()
  })

  it('switchAgent 调 PUT 并更新会话排序位', async () => {
    const chat = useChatStore()
    chat.currentId = 1
    chat.conversations = [{ id: 1, title: 'a', agent_id: 1, updated_at: 't', created_at: 't' }]
    chatApiMock.switchAgent.mockResolvedValue({
      id: 1,
      title: 'a',
      agent_id: 2,
      updated_at: 't2',
      created_at: 't',
    })
    await chat.switchAgent(2)
    expect(chatApiMock.switchAgent).toHaveBeenCalledWith(1, 2)
    expect(chat.currentConversation?.agent_id).toBe(2)
  })

  it('loadMessages：恢复订阅 generating 消息（后台继续生成 FR-022）', async () => {
    const chat = useChatStore()
    chatApiMock.messages.mockResolvedValue([
      makeMessage({ id: 10, role: 'user' }),
      makeMessage({ id: 11, role: 'assistant', status: 'generating', seq: 2, content: '' }),
    ])
    openStreamMock.mockResolvedValue(undefined)
    await chat.loadMessages(1)
    expect(openStreamMock).toHaveBeenCalledWith(1, 11, expect.any(Function))
    expect(chat.phase).toBe('generating')
  })

  it('stopGeneration 调停止端点', async () => {
    const chat = useChatStore()
    chat.currentId = 1
    chat.generatingReplyId = 11
    chatApiMock.stop.mockResolvedValue({ stopped: true })
    await chat.stopGeneration()
    expect(chatApiMock.stop).toHaveBeenCalledWith(1, 11)
  })

  it('无会话发送：自动新建会话再发送（bug 1 修复）', async () => {
    const chat = useChatStore()
    chat.pendingAgentId = 5
    chatApiMock.create.mockResolvedValue({
      id: 99,
      title: '新会话',
      agent_id: 5,
      updated_at: 't',
      created_at: 't',
    })
    chatApiMock.send.mockResolvedValue({
      user_message: makeMessage({ id: 10, conversation_id: 99 }),
      reply_message_id: 11,
      conversation: { id: 99, title: '新会话', agent_id: 5, updated_at: 't', created_at: 't' },
    })
    openStreamMock.mockResolvedValue(undefined)

    await chat.send('你好')

    expect(chatApiMock.create).toHaveBeenCalledWith(5)
    expect(chatApiMock.send).toHaveBeenCalledWith(99, '你好')
    expect(chat.currentId).toBe(99)
    // 模拟终态 done 后回到 idle
    const calls = openStreamMock.mock.calls
    const call = calls[calls.length - 1]
    if (call === undefined) {
      throw new Error('openStream not called')
    }
    const handler = call[2] as (e: unknown) => void
    handler({
      event: 'done',
      data: { message: makeMessage({ id: 11, role: 'assistant', seq: 2, conversation_id: 99 }), stopped: false },
    })
    expect(chat.phase).toBe('idle')
  })

  it('无会话时 selectAgent 只记录待用选择，不调切换接口', async () => {
    const chat = useChatStore()
    await chat.selectAgent(7)
    expect(chat.pendingAgentId).toBe(7)
    expect(chatApiMock.switchAgent).not.toHaveBeenCalled()
  })

  it('effectiveAgentId：无会话取 pendingAgentId，有会话取会话保存值', () => {
    const chat = useChatStore()
    chat.pendingAgentId = 5
    expect(chat.effectiveAgentId).toBe(5)
    chat.conversations = [{ id: 1, title: 'a', agent_id: 3, updated_at: 't', created_at: 't' }]
    chat.currentId = 1
    expect(chat.effectiveAgentId).toBe(3)
  })
})
