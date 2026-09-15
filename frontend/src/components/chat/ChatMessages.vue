<script setup lang="ts">
/**
 * 消息区容器（specs/008-chat-conversations FR-027；010 US1/US2/US6 增强）。
 * 展示历史消息与生成中的流式占位；工具调用渲染过程卡片（ToolProcessCard）。
 * 终态后保留最近一轮 segments（卡片可回看，FR-023），对应回复消息从列表过滤。
 */
import { computed, nextTick, ref, watch } from 'vue'

import { useChatStore, type ToolCardSegment } from '@/stores/chat'
import MessageBubble from './MessageBubble.vue'
import ToolProcessCard from './ToolProcessCard.vue'

const chat = useChatStore()
const container = ref<HTMLElement | null>(null)
/** 用户是否主动上滚离开底部 */
const userScrolledUp = ref(false)

/** 终态回复改由 segments 展示（保留卡片与交错序），messages 渲染时过滤该条 */
const visibleMessages = computed(() => {
  const finishedId = chat.finishedReplyId
  if (finishedId === null) {
    return chat.messages
  }
  return chat.messages.filter((m) => m.id !== finishedId)
})

/** 片段 key：卡片用调用标识（防并行/多次调用错位，FR-008/009），文本段用位置 */
function segKey(seg: { kind: string; callId?: string }, index: number): string {
  return seg.kind === 'tool' ? `t-${seg.callId ?? index}` : `s-${index}`
}

/** 高度突变补偿：上滚状态保持阅读位置（FR-019；覆盖流式追加与卡片展开/收起） */
async function compensateOnResize(): Promise<void> {
  const el = container.value
  if (!el || !userScrolledUp.value) {
    return
  }
  const before = el.scrollHeight
  await nextTick()
  const delta = el.scrollHeight - before
  if (delta !== 0) {
    el.scrollTop += delta
  }
}

/** "回到最新消息"（FR-018）：滚至底部并恢复自动跟随 */
async function scrollToLatest(): Promise<void> {
  userScrolledUp.value = false
  await nextTick()
  const el = container.value
  if (el) {
    el.scrollTop = el.scrollHeight
  }
}

function onScroll(): void {
  if (!container.value) {
    return
  }
  const el = container.value
  userScrolledUp.value = el.scrollHeight - el.scrollTop - el.clientHeight > 80
}

async function scrollToBottom(): Promise<void> {
  if (userScrolledUp.value || !container.value) {
    return
  }
  await nextTick()
  container.value.scrollTop = container.value.scrollHeight
}

watch(
  // 流式片段字符总量变化（reasoning/content 触发跟随滚动；卡片以数量计）
  () => chat.messages.length + chat.segments.reduce((n, s) => n + (s.kind === 'tool' ? 1 : s.text.length), 0),
  () => void scrollToBottom(),
)

watch(
  // 片段任意变化（含卡片状态/文本增长）时补偿阅读位置
  () => chat.segments,
  () => void compensateOnResize(),
  { deep: true },
)

watch(
  () => chat.currentId,
  () => {
    // 切换会话：回到底部跟随
    userScrolledUp.value = false
    void scrollToBottom()
  },
)
</script>

<template>
  <div ref="container" class="chat-messages" @scroll="onScroll">
    <template v-if="chat.messagesLoading">
      <div class="chat-loading">加载中…</div>
    </template>
    <template v-else-if="chat.messages.length === 0 && chat.phase === 'idle'">
      <div class="chat-empty">
        <p>开始新的对话吧</p>
        <p class="chat-empty-hint">在下方输入消息，Enter 发送，Shift + Enter 换行</p>
      </div>
    </template>
    <template v-else>
      <MessageBubble
        v-for="(item, index) in visibleMessages"
        :key="item.id"
        :message="item"
        :is-last-assistant="
          item.role === 'assistant' &&
          index === visibleMessages.length - 1 &&
          chat.phase === 'idle'
        "
        @regenerate="chat.regenerate()"
      />

      <!-- 流式/最近一轮回复：片段按 Runtime 到达顺序渲染（思考/正文/工具卡片交错，FR-006） -->
      <div v-if="chat.segments.length > 0 || chat.phase !== 'idle'" class="msg-row msg-agent">
        <div class="msg-bubble">
          <div class="msg-agent-name">{{ 'Agent' }}</div>
          <div v-if="chat.segments.length === 0 && chat.phase === 'thinking'" class="msg-thinking">正在思考…</div>
          <template v-for="(seg, index) in chat.segments" :key="segKey(seg, index)">
            <details
              v-if="seg.kind === 'reasoning'"
              class="msg-reasoning"
              open
            >
              <summary>思考过程</summary>
              <div class="msg-reasoning-body">{{ seg.text }}</div>
            </details>
            <div v-else-if="seg.kind === 'content'" class="msg-content">{{ seg.text }}</div>
            <ToolProcessCard v-else :card="(seg as ToolCardSegment)" @toggle="compensateOnResize" />
          </template>
          <div v-if="chat.phase === 'generating'" class="msg-generating">正在生成…</div>
        </div>
      </div>

      <!-- 独立错误条（FR-023）：不渲染为聊天气泡 -->
      <div v-if="chat.error" class="chat-error" role="alert">
        {{ chat.error.message }}
      </div>

      <!-- 回到最新消息（FR-018）：上滚暂停跟随时提供快捷返回 -->
      <button v-if="userScrolledUp" type="button" class="jump-latest" @click="scrollToLatest">
        回到最新消息 ↓
      </button>
    </template>
  </div>
</template>

<style scoped lang="scss">
.chat-messages {
  flex: 1;
  overflow-y: auto;
  padding: 20px 24px;
}

.chat-loading,
.chat-empty {
  height: 100%;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  color: var(--text-tertiary);
  font-size: 14px;
}

.chat-empty-hint {
  font-size: 12.5px;
  margin-top: 6px;
}

.msg-row {
  display: flex;
  margin-bottom: 16px;

  &.msg-agent {
    justify-content: flex-start;
  }
}

.msg-bubble {
  max-width: 78%;
  padding: 10px 14px;
  border: 1px solid var(--border);
  border-radius: 10px;
  font-size: 14px;
  line-height: 1.5;
  color: var(--text-primary);
  background: var(--bg-surface);
  word-break: break-word;
}

.msg-agent-name {
  font-size: 12.5px;
  font-weight: 600;
  color: var(--text-secondary);
  margin-bottom: 4px;
}

.msg-reasoning {
  margin-bottom: 8px;
  border: 1px dashed var(--border);
  border-radius: 8px;
  padding: 6px 10px;
  background: var(--bg-base);

  summary {
    font-size: 12.5px;
    color: var(--text-tertiary);
    cursor: pointer;
  }
}

.msg-reasoning-body {
  margin-top: 6px;
  font-size: 13px;
  color: var(--text-secondary);
  white-space: pre-wrap;
}

.msg-thinking,
.msg-generating {
  font-size: 12.5px;
  color: var(--text-tertiary);
}

.msg-generating::after {
  content: '…';
  animation: blink 1s infinite;
}

@keyframes blink {
  50% {
    opacity: 0.2;
  }
}

.chat-error {
  border: 1px solid var(--danger);
  background: color-mix(in srgb, var(--danger) 8%, var(--bg-surface));
  color: var(--danger);
  border-radius: 8px;
  padding: 10px 14px;
  font-size: 13px;
  margin-top: 4px;
}

.jump-latest {
  position: sticky;
  bottom: 12px;
  margin: 0 auto;
  display: block;
  border: 1px solid var(--border);
  background: var(--bg-surface);
  color: var(--text-secondary);
  border-radius: 999px;
  padding: 6px 14px;
  font-size: 12.5px;
  cursor: pointer;
  box-shadow: 0 2px 8px rgb(0 0 0 / 8%);
}

.jump-latest:hover {
  color: var(--accent);
  border-color: var(--accent);
}
</style>
