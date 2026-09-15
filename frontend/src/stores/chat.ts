/**
 * 聊天全局状态（Pinia）——会话列表、当前会话消息、生成状态与流订阅。
 *
 * 订阅生命周期独立于组件（FR-022）：ChatView 卸载不断开订阅；
 * 切换/新建会话后回到原会话按消息状态重订阅完成重放（research R4）。
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

/** 生成状态：空闲 → 思考中（已发送未收到正文）→ 生成中（正文流式追加） */
export type GenerationPhase = 'idle' | 'thinking' | 'generating'

/** 轻量错误条（独立于聊天气泡展示，FR-023） */
export interface ChatError {
  category: string
  message: string
}

export const useChatStore = defineStore('chat', () => {
  // ---- 会话列表 ----
  const conversations = ref<ConversationSummary[]>([])
  const conversationsLoading = ref(false)
  /** 当前会话 id（持久到 sessionStorage：刷新后恢复上次活跃会话） */
  const currentId = ref<number | null>(null)

  // ---- 消息与生成态 ----
  const messages = ref<MessageOut[]>([])
  const messagesLoading = ref(false)
  const phase = ref<GenerationPhase>('idle')
  /** 生成中的回复消息 id（订阅与停止的键） */
  const generatingReplyId = ref<number | null>(null)
  const thinkingContent = ref('')
  const generatingContent = ref('')
  const error = ref<ChatError | null>(null)

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
    if (currentId.value === id && messages.value.length >= 0 && messagesLoading.value === false) {
      // 同会话重入：仍需检查是否有进行中的生成需要恢复订阅
    }
    currentId.value = id
    error.value = null
    await loadMessages(id)
  }

  async function loadMessages(id: number): Promise<void> {
    messagesLoading.value = true
    try {
      messages.value = await chatApi.messages(id)
      // 恢复订阅：该会话若有 generating 消息则重新订阅（后台继续生成，FR-022）
      const generating = messages.value.find((m) => m.status === 'generating')
      if (generating) {
        phase.value = 'generating'
        generatingReplyId.value = generating.id
        void subscribeStream(id, generating.id)
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
    if (phase.value !== 'idle') {
      return
    }
    phase.value = 'thinking'
    error.value = null
    // 无选中会话时自动新建会话（bug 修复：进入聊天页直接发送 → 创建新会话）
    if (cid === null) {
      const agentId = effectiveAgentId.value ?? defaultAgentId()
      if (agentId === null) {
        phase.value = 'idle'
        error.value = { category: 'no_agent', message: '还没有可用 Agent，请先创建 Agent' }
        return
      }
      let created: ConversationSummary
      try {
        created = await chatApi.create(agentId)
      } catch (e) {
        phase.value = 'idle'
        error.value = {
          category: 'create_failed',
          message: e instanceof ApiError ? e.message : '新建会话失败，请重试',
        }
        throw e
      }
      conversations.value.unshift(created)
      cid = created.id
      currentId.value = created.id
      pendingAgentId.value = null
    }
    let response
    try {
      response = await chatApi.send(cid, content)
    } catch (e) {
      phase.value = 'idle'
      // 发送失败：保留输入内容由调用方处理，提示原因（FR-009）
      error.value = {
        category: 'send_failed',
        message: e instanceof ApiError ? e.message : '网络请求失败，请检查后端服务是否已启动',
      }
      throw e
    }
    if (response.user_message) {
      messages.value.push(response.user_message)
    }
    upsertConversation(response.conversation)
    generatingReplyId.value = response.reply_message_id
    thinkingContent.value = ''
    generatingContent.value = ''
    void subscribeStream(cid, response.reply_message_id)
  }

  async function regenerate(): Promise<void> {
    const cid = currentId.value
    if (cid === null || phase.value !== 'idle') {
      return
    }
    phase.value = 'thinking'
    error.value = null
    try {
      const response = await chatApi.regenerate(cid)
      upsertConversation(response.conversation)
      generatingReplyId.value = response.reply_message_id
      thinkingContent.value = ''
      generatingContent.value = ''
      // 原地重置：移除旧的最终回复展示，进入流式占位
      messages.value = messages.value.filter((m) => m.id !== response.reply_message_id)
      void subscribeStream(cid, response.reply_message_id)
    } catch (e) {
      phase.value = 'idle'
      error.value = {
        category: 'regenerate_failed',
        message: e instanceof ApiError ? e.message : '重新生成请求失败',
      }
    }
  }

  async function stopGeneration(): Promise<void> {
    const cid = currentId.value
    const mid = generatingReplyId.value
    if (cid === null || mid === null) {
      return
    }
    try {
      await chatApi.stop(cid, mid)
    } catch {
      // 停止失败不阻塞前端状态恢复；终态仍以流事件为准
    }
  }

  // ---- 流订阅（store 层持有，组件卸载不中断，FR-022）----

  function handleStreamEvent(event: StreamEvent): void {
    if (event.event === 'reasoning_delta') {
      thinkingContent.value += event.data.text
      if (phase.value === 'thinking') {
        phase.value = 'generating'
      }
    } else if (event.event === 'content_delta') {
      generatingContent.value += event.data.text
      phase.value = 'generating'
    } else if (event.event === 'error') {
      error.value = { category: event.data.category, message: event.data.message }
    } else if (event.event === 'done') {
      if (event.data.message) {
        const index = messages.value.findIndex((m) => m.id === event.data.message!.id)
        if (index === -1) {
          messages.value.push(event.data.message)
        } else {
          messages.value[index] = event.data.message
        }
      } else {
        // 占位行被删除（停止/失败且无正文）：保持列表不含空白回复（FR-024）
      }
      phase.value = 'idle'
      generatingReplyId.value = null
      thinkingContent.value = ''
      generatingContent.value = ''
    }
  }

  async function subscribeStream(cid: number, mid: number): Promise<void> {
    try {
      await openStream(cid, mid, handleStreamEvent)
    } catch {
      // 流异常断开且无终态：结束等待态，允许用户继续操作（FR-023）
      if (phase.value !== 'idle') {
        phase.value = 'idle'
        error.value = { category: 'stream_interrupted', message: '连接中断，请重试或查看该条消息状态。' }
      }
    }
  }

  // ---- Agent 选择 ----

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
    pendingAgentId,
    effectiveAgentId,
    messages,
    messagesLoading,
    phase,
    generatingReplyId,
    thinkingContent,
    generatingContent,
    error,
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
