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

const runsApiMock = vi.hoisted(() => ({
  conversationReplays: vi.fn(),
}))
vi.mock('@/api/runs', () => ({ runsApi: runsApiMock }))
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

    // 模拟终态 run_completed（009 契约）
    const handler = streamHandler()
    handler({
      event: 'run_completed',
      data: {
        run_id: 'r1', seq: 9, status: 'completed', reason: '',
        usage_total: null,
        message: makeMessage({ id: 11, role: 'assistant', seq: 2, content: '答' }),
        stopped: false,
      },
    })
    expect(chat.phase).toBe('idle')
    expect(chat.messages).toHaveLength(2)
    expect(chat.messages[1]?.content).toBe('答')
  })

  it('error 事件写入独立错误条且正文不受污染；run_completed 后 idle', async () => {
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
    handler({
      event: 'run_completed',
      data: { run_id: 'r1', seq: 9, status: 'error', reason: '', usage_total: null, message: null, stopped: false },
    })
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
    chat.currentId = 1
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
    chat.runStates[1] = {
      phase: 'generating', generatingReplyId: 11, segments: [], error: null, finishedReplyId: null,
    }
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
    // 模拟终态 run_completed 后回到 idle
    const calls = openStreamMock.mock.calls
    const call = calls[calls.length - 1]
    if (call === undefined) {
      throw new Error('openStream not called')
    }
    const handler = call[2] as (e: unknown) => void
    handler({
      event: 'run_completed',
      data: {
        run_id: 'r1', seq: 9, status: 'completed', reason: '',
        usage_total: null,
        message: makeMessage({ id: 11, role: 'assistant', seq: 2, conversation_id: 99 }),
        stopped: false,
      },
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

describe('chat store — 009 runtime 事件', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.clearAllMocks()
  })

  function setupStore() {
    const chat = useChatStore()
    chat.currentId = 1
    chatApiMock.send.mockResolvedValue({
      user_message: makeMessage({ id: 10, role: 'user' }),
      reply_message_id: 11,
      conversation: { id: 1, title: 'hi', agent_id: 1, updated_at: 't', created_at: 't' },
    })
    openStreamMock.mockResolvedValue(undefined)
    return chat.send('hi').then(() => streamHandler()).then((handler) => ({ chat, handler }))
  }

  it('tool_call_started/completed：卡片段记录展示字段并驱动 phase（010）', async () => {
    const { chat, handler } = await setupStore()
    handler({
      event: 'tool_call_started',
      data: { run_id: 'r', seq: 3, round: 1, call_id: 't1', tool_name: 'current_time', tool_type: 'builtin', params_summary: '{}', params: '{}', display_name: '当前时间', server_name: null },
    })
    expect(chat.phase).toBe('tool')
    const started = chat.segments.find((s) => s.kind === 'tool')
    expect(started?.toolName).toBe('current_time')
    expect(started?.status).toBe('running')
    expect(started?.displayName).toBe('当前时间')
    expect(started?.paramsText).toBe('{}')
    handler({
      event: 'tool_call_completed',
      data: { run_id: 'r', seq: 4, round: 1, call_id: 't1', tool_name: 'current_time', tool_type: 'builtin', status: 'success', duration_ms: 12, result_summary: '12:00', result: '2026-09-15 12:00', display_name: '当前时间', server_name: null },
    })
    expect(started?.status).toBe('success')
    expect(started?.durationMs).toBe(12)
    expect(started?.resultText).toBe('2026-09-15 12:00')
    expect(chat.phase).toBe('generating')
  })

  it('reasoning/content 交错：segments 按 Runtime 到达顺序分段（思考按轮次位置显示）', async () => {
    const { chat, handler } = await setupStore()
    // 轮 1：思考 → 正文；轮 2（工具后）：思考 → 正文
    handler({ event: 'reasoning_delta', data: { run_id: 'r', seq: 1, round: 1, call_id: 'm1', text: '轮1思考' } })
    handler({ event: 'content_delta', data: { run_id: 'r', seq: 2, round: 1, call_id: 'm1', text: '轮1正文' } })
    handler({
      event: 'tool_call_started',
      data: { run_id: 'r', seq: 3, round: 1, call_id: 't1', tool_name: 'current_time', tool_type: 'builtin', params_summary: '{}', params: '{}', display_name: '当前时间', server_name: null },
    })
    handler({
      event: 'tool_call_completed',
      data: { run_id: 'r', seq: 4, round: 1, call_id: 't1', tool_name: 'current_time', tool_type: 'builtin', status: 'success', duration_ms: 5, result_summary: '', result: '', display_name: '当前时间', server_name: null },
    })
    handler({ event: 'reasoning_delta', data: { run_id: 'r', seq: 5, round: 2, call_id: 'm2', text: '轮2思考' } })
    handler({ event: 'content_delta', data: { run_id: 'r', seq: 6, round: 2, call_id: 'm2', text: '轮2正文' } })
    expect(chat.segments.map((s) => (s.kind === 'tool' ? `tool:${s.toolName}` : `${s.kind}:${s.text}`))).toEqual([
      'reasoning:轮1思考',
      'content:轮1正文',
      'tool:current_time',
      'reasoning:轮2思考',
      'content:轮2正文',
    ])
    handler({
      event: 'run_completed',
      data: {
        run_id: 'r', seq: 9, status: 'completed', reason: '',
        usage_total: null,
        message: makeMessage({ id: 11, role: 'assistant', seq: 2, content: '答' }),
        stopped: false,
      },
    })
    // 010 行为变更：终态后保留 segments（卡片可回看，FR-023），消息对账进 messages
    expect(chat.segments).toHaveLength(5)
    expect(chat.phase).toBe('idle')
    expect(chat.finishedReplyId).toBe(11)
    expect(chat.messages).toHaveLength(2)
  })

  it('run_completed 保留卡片片段；stopped 兜底 cancelled；未知事件不抛错（010）', async () => {
    const { chat, handler } = await setupStore()
    handler({
      event: 'tool_call_started',
      data: { run_id: 'r', seq: 3, round: 1, call_id: 't1', tool_name: 'load_skill', tool_type: 'skill', params_summary: '{}', params: '{"skill_id":"demo"}', display_name: '加载 Skill', server_name: null },
    })
    expect(chat.segments).toHaveLength(1)
    handler({
      event: 'run_completed',
      data: {
        run_id: 'r', seq: 9, status: 'cancelled', reason: '',
        usage_total: null,
        message: null,
        stopped: true,
      },
    })
    // FR-022：终态后卡片保留但不停留 running——stopped 兜底为 cancelled
    const card = chat.segments.find((s) => s.kind === 'tool')
    expect(card?.status).toBe('cancelled')
    expect(chat.phase).toBe('idle')
    expect(chat.finishedReplyId).toBeNull() // 占位行被删（message null）
    // 未知运行级事件不抛错
    expect(() => handler({ event: 'future_event', data: {} } as never)).not.toThrow()
  })
})

describe('chat store — 010 工具过程展示', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.clearAllMocks()
  })

  function setupStore() {
    const chat = useChatStore()
    chat.currentId = 1
    chatApiMock.send.mockResolvedValue({
      user_message: makeMessage({ id: 10, role: 'user' }),
      reply_message_id: 11,
      conversation: { id: 1, title: 'hi', agent_id: 1, updated_at: 't', created_at: 't' },
    })
    openStreamMock.mockResolvedValue(undefined)
    return chat.send('hi').then(() => streamHandler()).then((handler) => ({ chat, handler }))
  }

  function startedEvt(seq: number, callId: string, name = 'current_time', display = '当前时间') {
    return {
      event: 'tool_call_started',
      data: { run_id: 'r', seq, round: 1, call_id: callId, tool_name: name, tool_type: 'builtin', params_summary: '{}', params: '{}', display_name: display, server_name: null },
    } as const
  }

  function completedEvt(seq: number, callId: string, status = 'success', duration = 10) {
    return {
      event: 'tool_call_completed',
      data: { run_id: 'r', seq, round: 1, call_id: callId, tool_name: 'current_time', tool_type: 'builtin', status, duration_ms: duration, result_summary: 'ok', result: 'ok', display_name: '当前时间', server_name: null },
    } as const
  }

  it('US2：同一工具多次调用产生独立卡片且状态互不串扰（FR-008）', async () => {
    const { chat, handler } = await setupStore()
    handler(startedEvt(1, 't1'))
    handler(startedEvt(2, 't2'))
    handler(completedEvt(3, 't2', 'success', 20))
    const cards = chat.segments.filter((s) => s.kind === 'tool')
    expect(cards).toHaveLength(2)
    expect(cards[0]?.status).toBe('running') // t1 未完成不受影响
    expect(cards[1]?.status).toBe('success')
    handler(completedEvt(4, 't1', 'error', 5))
    expect(cards[0]?.status).toBe('error')
  })

  it('US2：并行调用按开始顺序排列，完成只原位更新不重排（FR-009）', async () => {
    const { chat, handler } = await setupStore()
    handler(startedEvt(1, 't1'))
    handler(startedEvt(2, 't2'))
    handler(completedEvt(3, 't2', 'success', 1)) // 后开始的先结束
    handler(completedEvt(4, 't1', 'success', 99))
    const cards = chat.segments.filter((s) => s.kind === 'tool')
    expect(cards.map((c) => c.callId)).toEqual(['t1', 't2']) // 顺序保持开始序
    expect(cards[0]?.durationMs).toBe(99)
    expect(cards[1]?.durationMs).toBe(1)
  })

  it('US2：completed 使用未知 call_id 不影响已有卡片（防错位）', async () => {
    const { chat, handler } = await setupStore()
    handler(startedEvt(1, 't1'))
    handler(completedEvt(2, 't_ghost'))
    const cards = chat.segments.filter((s) => s.kind === 'tool')
    expect(cards).toHaveLength(1)
    expect(cards[0]?.status).toBe('running')
  })

  it('US5：流异常断开且无终态 → running 卡片标"状态未知"（FR-021）', async () => {
    const chat = useChatStore()
    chat.currentId = 1
    chatApiMock.send.mockResolvedValue({
      user_message: makeMessage({ id: 10, role: 'user' }),
      reply_message_id: 11,
      conversation: { id: 1, title: 'hi', agent_id: 1, updated_at: 't', created_at: 't' },
    })
    let rejectStream!: (e: Error) => void
    openStreamMock.mockReturnValue(new Promise<void>((_, reject) => { rejectStream = reject }))
    await chat.send('hi')
    const handler = streamHandler()
    handler(startedEvt(1, 't1'))
    handler({ event: 'content_delta', data: { run_id: 'r', seq: 2, round: 1, call_id: 'm1', text: '部分' } })
    rejectStream(new Error('network down'))
    await new Promise((r) => setTimeout(r, 0))
    const card = chat.segments.find((s) => s.kind === 'tool')
    expect(card?.status).toBe('unknown')
    expect(chat.phase).toBe('idle')
    expect(chat.error?.category).toBe('stream_interrupted')
  })

  it('US5：run_completed(error) 残留 running 卡片 → unknown；终态后无 running（FR-022）', async () => {
    const { chat, handler } = await setupStore()
    handler(startedEvt(1, 't1'))
    handler({
      event: 'run_completed',
      data: { run_id: 'r', seq: 9, status: 'error', reason: '', usage_total: null, message: null, stopped: false },
    })
    const cards = chat.segments.filter((s) => s.kind === 'tool')
    expect(cards[0]?.status).toBe('unknown')
    expect(chat.segments.some((s) => s.kind === 'tool' && s.status === 'running')).toBe(false)
  })

  it('US6：生成中切换会话再返回，槽保留且不重复订阅（Q2 无缝续播）', async () => {
    const chat = useChatStore()
    chat.currentId = 1
    chatApiMock.messages.mockImplementation(async (cid: number) => {
      if (cid === 1) {
        return [
          makeMessage({ id: 10, role: 'user' }),
          makeMessage({ id: 11, role: 'assistant', status: 'generating', seq: 2, content: '' }),
        ]
      }
      return [makeMessage({ id: 20, role: 'user', conversation_id: 2 })]
    })
    // 手动控制流生命周期：保持"活跃"（未 resolve）以模拟真实长连接
    let resolveStream!: () => void
    openStreamMock.mockReturnValue(new Promise<void>((resolve) => { resolveStream = resolve }))
    await chat.loadMessages(1) // 会话 A 开始订阅（1 次）
    expect(openStreamMock).toHaveBeenCalledTimes(1)
    chat.currentId = 2
    await chat.loadMessages(2) // 切到 B
    chat.currentId = 1
    await chat.loadMessages(1) // 切回 A：槽内 generatingReplyId=11 且流活跃 → 不再订阅
    expect(openStreamMock).toHaveBeenCalledTimes(1) // 防重复订阅
    expect(chat.phase).toBe('generating') // 槽状态保留
    resolveStream()
  })

  it('US6：历史会话（无活跃流、无 generating）不产生卡片片段（FR-025）', async () => {
    const chat = useChatStore()
    chat.currentId = 2
    chatApiMock.messages.mockResolvedValue([
      makeMessage({ id: 20, role: 'user', conversation_id: 2 }),
      makeMessage({ id: 21, role: 'assistant', status: 'completed', seq: 2, conversation_id: 2 }),
    ])
    openStreamMock.mockResolvedValue(undefined)
    await chat.loadMessages(2)
    expect(openStreamMock).not.toHaveBeenCalled()
    expect(chat.segments).toHaveLength(0)
  })
})


describe('chat store 历史运行回放（011 优化①）', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.clearAllMocks()
  })

  it('loadMessages 拉取回放并按 replyMessageId 映射为片段', async () => {
    runsApiMock.conversationReplays.mockResolvedValue([
      {
        run_id: 'r1', reply_message_id: 42, status: 'succeeded',
        items: [
          { kind: 'reasoning', round: 1, text: '想想' },
          { kind: 'content', round: 1, text: '查询中' },
          { kind: 'tool', round: 1, callId: 't1', toolName: 'current_time', displayName: '当前时间',
            toolType: 'builtin', serverName: null, status: 'success', durationMs: 5,
            paramsSummary: '{}', resultSummary: '12:00', paramsText: '{}', resultText: '12:00' },
          { kind: 'content', round: 2, text: '现在是 12:00' },
        ],
      },
    ])
    chatApiMock.messages.mockResolvedValue([makeMessage({ id: 42, role: 'assistant', content: '现在是 12:00' })])
    const store = useChatStore()
    await store.selectConversation(7)
    const segments = store.historyReplays[42] ?? []
    expect(segments).toHaveLength(4)
    expect(segments[0]).toMatchObject({ kind: 'reasoning', text: '想想' })
    expect(segments[2]).toMatchObject({ kind: 'tool', callId: 't1', status: 'success', resultText: '12:00' })
    expect(segments[3]).toMatchObject({ kind: 'content', text: '现在是 12:00' })
  })

  it('回放接口失败时降级为空映射（不阻塞消息展示）', async () => {
    runsApiMock.conversationReplays.mockRejectedValue(new Error('network'))
    chatApiMock.messages.mockResolvedValue([makeMessage({ id: 43, role: 'assistant' })])
    const store = useChatStore()
    await store.selectConversation(7)
    expect(store.historyReplays[43]).toBeUndefined()
  })
})
