/**
 * 聊天全局状态（Pinia）——会话列表、当前会话消息、按会话的运行展示槽与流订阅。
 *
 * 010（FR-023 / clarify Q2）：运行展示状态按会话隔离——生成中切换会话不断流、
 * 不销毁槽位，返回原会话无缝续播；事件经订阅闭包路由到所属会话的槽。
 * 运行结束后保留最近一轮 segments（卡片可回看，FR-023）；终态消息 upsert 进
 * messages 供切换回会话时对账（渲染时过滤 finishedReplyId，避免正文重复）。
 */
import { defineStore } from 'pinia'
import { computed, ref } from 'vue'

import {
  chatApi,
  openStream,
  type ConversationSummary,
  type MessageOut,
  type StreamEvent,
} from '@/api/chat'
import { ApiError } from '@/api/request'
import { useAgentsStore } from '@/stores/agents'

/** 生成状态：空闲 → 思考中（已发送未收到输出）→ 生成中（正文流式追加）→ 调用工具 */
export type GenerationPhase = 'idle' | 'thinking' | 'generating' | 'tool'

/** 轻量错误条（独立于聊天气泡展示，FR-023） */
export interface ChatError {
  category: string
  message: string
}

/** 工具卡片状态终态机（FR-020/021/022） */
export type ToolCardStatus = 'running' | 'success' | 'error' | 'denied' | 'cancelled' | 'unknown'

/** 工具过程卡片段（010 data-model §3.2） */
export interface ToolCardSegment {
  kind: 'tool'
  round: number
  /** 工具调用标识：开始/完成事件关联键（不作标题，FR-003） */
  callId: string
  toolName: string
  displayName: string
  toolType: 'builtin' | 'mcp' | 'skill'
  serverName: string | null
  status: ToolCardStatus
  durationMs: number | null
  paramsSummary: string
  resultSummary: string
  paramsText: string
  resultText: string
}

/** reasoning / content 文本片段（按 Runtime 到达顺序排列，FR-013） */
export interface TextSegment {
  kind: 'reasoning' | 'content'
  round: number
  text: string
}

export type StreamSegment = TextSegment | ToolCardSegment

/** 每个会话的运行展示槽（010 data-model §3.1） */
export interface RunDisplayState {
  phase: GenerationPhase
  generatingReplyId: number | null
  segments: StreamSegment[]
  error: ChatError | null
  /** 最近一轮已结束运行的回复 id：渲染时从 messages 过滤（该回复由 segments 展示） */
  finishedReplyId: number | null
}

function createRunState(): RunDisplayState {
  return { phase: 'idle', generatingReplyId: null, segments: [], error: null, finishedReplyId: null }
}

/** 空槽常量：无槽会话的稳定返回值（避免 computed 每次新建对象） */
const EMPTY_RUN: RunDisplayState = createRunState()

export const useChatStore = defineStore('chat', () => {
  // ---- 会话列表 ----
  const conversations = ref<ConversationSummary[]>([])
  const conversationsLoading = ref(false)
  /** 当前会话 id（持久到 sessionStorage：刷新后恢复上次活跃会话） */
  const currentId = ref<number | null>(null)

  // ---- 消息（当前查看会话的消息列表）----
  const messages = ref<MessageOut[]>([])
  const messagesLoading = ref(false)

  // ---- 按会话运行展示槽 + 活跃订阅登记（FR-023 / clarify Q2）----
  const runStates = ref<Record<number, RunDisplayState>>({})
  /** 按 replyMessageId 登记：防止同一运行重复订阅（双连接双倍事件） */
  const activeStreams = new Set<number>()

  /** 当前查看会话的运行槽（无槽返回稳定空槽） */
  const currentRun = computed<RunDisplayState>(() => {
    const key = currentId.value
    if (key === null) {
      return EMPTY_RUN
    }
    return runStates.value[key] ?? EMPTY_RUN
  })

  /** 取会话槽，不存在则创建（仅在事件路由/发起新运行时调用） */
  function ensureRun(cid: number): RunDisplayState {
    let run = runStates.value[cid]
    if (!run) {
      run = createRunState()
      runStates.value[cid] = run
    }
    return run
  }

  const currentConversation = computed(
    () => conversations.value.find((c) => c.id === currentId.value) ?? null,
  )

  /** 无会话时的 Agent 选择（Composer 预置默认 Agent、@ 快捷选择写入此处） */
  const pendingAgentId = ref<number | null>(null)

  /** 当前生效的 Agent id：有会话取会话保存值，无会话取本地选择（下拉实时显示） */
  const effectiveAgentId = computed<number | null>(() => {
    const conv = currentConversation.value
    if (conv !== null) {
      return conv.agent_id
    }
    return pendingAgentId.value
  })

  // ---- 会话列表 ----

  async function fetchConversations(): Promise<void> {
    conversationsLoading.value = true
    try {
      conversations.value = await chatApi.list()
    } finally {
      conversationsLoading.value = false
    }
  }

  async function createConversation(agentId: number): Promise<ConversationSummary> {
    const created = await chatApi.create(agentId)
    conversations.value.unshift(created)
    pendingAgentId.value = null
    await selectConversation(created.id)
    return created
  }

  function upsertConversation(summary: ConversationSummary): void {
    const index = conversations.value.findIndex((c) => c.id === summary.id)
    if (index === -1) {
      conversations.value.unshift(summary)
    } else {
      conversations.value[index] = summary
    }
    // 按 updated_at 倒序重排（FR-005）
    conversations.value.sort((a, b) => b.updated_at.localeCompare(a.updated_at))
  }

  async function selectConversation(id: number): Promise<void> {
    currentId.value = id
    await loadMessages(id)
  }

  async function loadMessages(id: number): Promise<void> {
    messagesLoading.value = true
    try {
      messages.value = await chatApi.messages(id)
      // 恢复订阅（FR-022 重放重建）：仅当该运行无活跃订阅时；已有活跃流则槽内
      // 状态持续更新中，切回即见最新（Q2 无缝续播，不重复建连接）
      const existing = runStates.value[id]
      const generatingId = existing?.generatingReplyId ?? null
      const fallbackGenerating = generatingId === null
        ? messages.value.find((m) => m.status === 'generating')
        : undefined
      const targetId = generatingId ?? fallbackGenerating?.id ?? null
      if (targetId !== null && !activeStreams.has(targetId)) {
        // 刷新后/首次进入（槽不存在）时按消息状态建槽恢复订阅
        const run = ensureRun(id)
        run.phase = 'generating'
        run.generatingReplyId = targetId
        void subscribeStream(id, targetId)
      }
    } finally {
      messagesLoading.value = false
    }
  }

  // ---- Agent 选择（统一入口）----

  function defaultAgentId(): number | null {
    const agentsStore = useAgentsStore()
    const fallback = agentsStore.items.find((a) => a.is_default) ?? agentsStore.items[0]
    return fallback?.id ?? null
  }

  /** 选择 Agent：有会话走切换接口，无会话记为待用选择（下次发送/新建生效） */
  async function selectAgent(agentId: number): Promise<void> {
    if (currentId.value !== null) {
      await switchAgent(agentId)
    } else {
      pendingAgentId.value = agentId
    }
  }

  // ---- 发送 / 重新生成 / 停止 ----

  async function send(content: string): Promise<void> {
    let cid = currentId.value
    if (currentRun.value.phase !== 'idle') {
      return
    }
    const run = ensureRun(cid ?? -1)
    run.phase = 'thinking'
    run.error = null
    // 新一轮展示：重置上一轮片段（上一轮回复已在 messages/气泡中）
    run.segments = []
    run.finishedReplyId = null
    // 无选中会话时自动新建会话
    if (cid === null) {
      const agentId = effectiveAgentId.value ?? defaultAgentId()
      if (agentId === null) {
        run.phase = 'idle'
        run.error = { category: 'no_agent', message: '还没有可用 Agent，请先创建 Agent' }
        return
      }
      let created: ConversationSummary
      try {
        created = await chatApi.create(agentId)
      } catch (e) {
        run.phase = 'idle'
        run.error = {
          category: 'create_failed',
          message: e instanceof ApiError ? e.message : '新建会话失败，请重试',
        }
        throw e
      }
      conversations.value.unshift(created)
      cid = created.id
      currentId.value = created.id
      runStates.value[cid] = run
      pendingAgentId.value = null
    }
    let response
    try {
      response = await chatApi.send(cid, content)
    } catch (e) {
      run.phase = 'idle'
      run.error = {
        category: 'send_failed',
        message: e instanceof ApiError ? e.message : '网络请求失败，请检查后端服务是否已启动',
      }
      throw e
    }
    if (response.user_message) {
      messages.value.push(response.user_message)
    }
    upsertConversation(response.conversation)
    run.generatingReplyId = response.reply_message_id
    void subscribeStream(cid, response.reply_message_id)
  }

  async function regenerate(): Promise<void> {
    const cid = currentId.value
    if (cid === null || currentRun.value.phase !== 'idle') {
      return
    }
    const run = ensureRun(cid)
    run.phase = 'thinking'
    run.error = null
    run.segments = []
    run.finishedReplyId = null
    try {
      const response = await chatApi.regenerate(cid)
      upsertConversation(response.conversation)
      run.generatingReplyId = response.reply_message_id
      // 原地重置：移除旧的最终回复展示，进入流式占位
      messages.value = messages.value.filter((m) => m.id !== response.reply_message_id)
      void subscribeStream(cid, response.reply_message_id)
    } catch (e) {
      run.phase = 'idle'
      run.error = {
        category: 'regenerate_failed',
        message: e instanceof ApiError ? e.message : '重新生成请求失败',
      }
    }
  }

  async function stopGeneration(): Promise<void> {
    const cid = currentId.value
    const mid = currentRun.value.generatingReplyId
    if (cid === null || mid === null) {
      return
    }
    try {
      await chatApi.stop(cid, mid)
    } catch {
      // 停止失败不阻塞前端状态恢复；终态仍以流事件为准
    }
  }

  // ---- 流事件路由（写入所属会话的槽，FR-007）----

  /** 追加增量：相邻同类文本片段合并，kind 切换或工具卡片时新开一段（保持到达顺序） */
  function appendDelta(run: RunDisplayState, kind: 'reasoning' | 'content', round: number, text: string): void {
    const last = run.segments[run.segments.length - 1]
    if (last && last.kind === kind) {
      last.text += text
    } else {
      run.segments.push({ kind, round, text })
    }
  }

  /** 找到 callId 对应的卡片段（事件关联，FR-007） */
  function findCard(run: RunDisplayState, callId: string): ToolCardSegment | undefined {
    return run.segments.find((s): s is ToolCardSegment => s.kind === 'tool' && s.callId === callId)
  }

  function handleStreamEvent(event: StreamEvent, run: RunDisplayState, cid: number): void {
    if (event.event === 'reasoning_delta') {
      appendDelta(run, 'reasoning', event.data.round, event.data.text)
      if (run.phase === 'thinking') {
        run.phase = 'generating'
      }
    } else if (event.event === 'content_delta') {
      appendDelta(run, 'content', event.data.round, event.data.text)
      run.phase = 'generating'
    } else if (event.event === 'tool_call_started') {
      run.segments.push({
        kind: 'tool',
        round: event.data.round,
        callId: event.data.call_id,
        toolName: event.data.tool_name,
        displayName: event.data.display_name || event.data.tool_name,
        toolType: event.data.tool_type,
        serverName: event.data.server_name,
        status: 'running',
        durationMs: null,
        paramsSummary: event.data.params_summary,
        resultSummary: '',
        paramsText: event.data.params,
        resultText: '',
      })
      run.phase = 'tool'
    } else if (event.event === 'tool_call_completed') {
      // 就地更新对应调用标识的卡片（开始时已在其时序位置占位，FR-007/009）
      const seg = findCard(run, event.data.call_id)
      if (seg) {
        seg.status = event.data.status
        seg.durationMs = event.data.duration_ms
        seg.resultSummary = event.data.result_summary
        seg.resultText = event.data.result
        seg.displayName = event.data.display_name || seg.displayName
        seg.serverName = event.data.server_name ?? seg.serverName
      }
      run.phase = 'generating'
    } else if (event.event === 'error') {
      run.error = { category: event.data.category, message: event.data.message }
    } else if (event.event === 'run_completed') {
      finalizeRun(run, cid, event.data)
    }
    // run_started / model_request_* 等运行级事件聊天页暂不消费（前向兼容）
  }

  /** 运行终态：残留 running 卡片兜底（FR-022 不变量）+ 终态消息对账 + 槽收尾 */
  function finalizeRun(run: RunDisplayState, cid: number, data: {
    status: string
    stopped: boolean
    message: MessageOut | null
  }): void {
    for (const seg of run.segments) {
      if (seg.kind === 'tool' && seg.status === 'running') {
        seg.status = data.stopped || data.status === 'cancelled' ? 'cancelled' : 'unknown'
      }
    }
    if (data.message && cid === currentId.value) {
      const index = messages.value.findIndex((m) => m.id === data.message!.id)
      if (index === -1) {
        messages.value.push(data.message)
      } else {
        messages.value[index] = data.message
      }
    }
    if (data.message) {
      // 该回复改由 segments 展示（保留卡片与交错序），messages 渲染时过滤此条
      run.finishedReplyId = data.message.id
    }
    run.phase = 'idle'
    run.generatingReplyId = null
  }

  // ---- 流订阅（store 层持有，组件卸载不中断，FR-022；activeStreams 防重复）----

  async function subscribeStream(cid: number, mid: number): Promise<void> {
    if (activeStreams.has(mid)) {
      return
    }
    activeStreams.add(mid)
    const run = ensureRun(cid)
    try {
      await openStream(cid, mid, (event) => handleStreamEvent(event, run, cid))
    } catch {
      // 流异常断开且无终态：无法确认未完成工具的执行结果 → 状态未知（FR-021）
      finalizeOnInterrupt(run)
    } finally {
      activeStreams.delete(mid)
    }
  }

  /** 断流兜底：未完成卡片标"状态未知"，结束等待态允许用户继续操作（FR-021/023） */
  function finalizeOnInterrupt(run: RunDisplayState): void {
    for (const seg of run.segments) {
      if (seg.kind === 'tool' && seg.status === 'running') {
        seg.status = 'unknown'
      }
    }
    if (run.phase !== 'idle') {
      run.phase = 'idle'
      run.generatingReplyId = null
      run.error = { category: 'stream_interrupted', message: '连接中断，请重试或查看该条消息状态。' }
    }
  }

  // ---- Agent 切换 ----

  async function switchAgent(agentId: number): Promise<void> {
    const cid = currentId.value
    if (cid === null) {
      return
    }
    const summary = await chatApi.switchAgent(cid, agentId)
    upsertConversation(summary)
  }

  return {
    conversations,
    conversationsLoading,
    currentId,
    currentConversation,
    currentRun,
    pendingAgentId,
    effectiveAgentId,
    messages,
    messagesLoading,
    /** 以下为当前查看会话运行槽的委托（组件按需消费） */
    phase: computed(() => currentRun.value.phase),
    segments: computed(() => currentRun.value.segments),
    error: computed(() => currentRun.value.error),
    generatingReplyId: computed(() => currentRun.value.generatingReplyId),
    finishedReplyId: computed(() => currentRun.value.finishedReplyId),
    runStates,
    fetchConversations,
    createConversation,
    selectConversation,
    loadMessages,
    selectAgent,
    send,
    regenerate,
    stopGeneration,
    switchAgent,
    upsertConversation,
  }
})
