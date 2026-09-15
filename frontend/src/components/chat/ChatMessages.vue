<script setup lang="ts">
/**
 * 消息区容器（specs/008-chat-conversations FR-027）。
 * 展示历史消息与生成中的流式占位，新消息/流式追加时自动滚动到底部
 * （用户上滚查看历史时不强制跟随）。
 */
import { nextTick, ref, watch } from 'vue'

import { useChatStore } from '@/stores/chat'
import MessageBubble from './MessageBubble.vue'

const chat = useChatStore()
const container = ref<HTMLElement | null>(null)
/** 用户是否主动上滚离开底部 */
const userScrolledUp = ref(false)

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
  () => [chat.messages.length, chat.generatingContent, chat.thinkingContent],
  () => void scrollToBottom(),
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
        v-for="(item, index) in chat.messages"
        :key="item.id"
        :message="item"
        :is-last-assistant="
          item.role === 'assistant' &&
          index === chat.messages.length - 1 &&
          chat.phase === 'idle'
        "
        @regenerate="chat.regenerate()"
      />

      <!-- 生成中流式占位 -->
      <div v-if="chat.phase !== 'idle'" class="msg-row msg-agent">
        <div class="msg-bubble">
          <div class="msg-agent-name">{{ 'Agent' }}</div>
          <details v-if="chat.thinkingContent" class="msg-reasoning" open>
            <summary>思考过程</summary>
            <div class="msg-reasoning-body">{{ chat.thinkingContent }}</div>
          </details>
          <div v-if="chat.phase === 'thinking' && !chat.thinkingContent" class="msg-thinking">
            正在思考…
          </div>
          <template v-else>
            <div class="msg-content">{{ chat.generatingContent }}</div>
            <div v-if="chat.phase === 'generating'" class="msg-generating">正在生成…</div>
          </template>
        </div>
      </div>

      <!-- 独立错误条（FR-023）：不渲染为聊天气泡 -->
      <div v-if="chat.error" class="chat-error" role="alert">
        {{ chat.error.message }}
      </div>
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
</style>
