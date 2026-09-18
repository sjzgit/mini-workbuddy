<script setup lang="ts">
/**
 * 单条消息气泡（specs/008-chat-conversations FR-026/027/013/014）。
 * 用户消息靠右、Agent 回复靠左并显示 agent_name 快照；
 * 思考过程与正文分区展示；正文 Markdown 渲染（v-html 经清洗）；
 * 复制 + 仅最后一条 assistant 回复可重新生成。
 */
import { computed, ref } from 'vue'
import { message as antMessage } from 'ant-design-vue'

import type { MessageOut } from '@/api/chat'
import { renderMarkdown } from '@/utils/markdown'

const props = defineProps<{
  message: MessageOut
  /** 是否最后一条 assistant 消息（重新生成入口，FR-014） */
  isLastAssistant: boolean
}>()

const emit = defineEmits<{ (e: 'regenerate'): void }>()

const isUser = computed(() => props.message.role === 'user')
const reasoningExpanded = ref(false)

const renderedContent = computed(() => renderMarkdown(props.message.content))
const renderedReasoning = computed(() => renderMarkdown(props.message.reasoning_content ?? ''))

const statusLabel = computed(() => {
  if (props.message.status === 'incomplete') {
    return props.message.content ? '回复未完成（已停止或生成中断）' : ''
  }
  return ''
})

async function copyContent(): Promise<void> {
  try {
    await navigator.clipboard.writeText(props.message.content)
    antMessage.success('已复制')
  } catch {
    antMessage.error('复制失败')
  }
}
</script>

<template>
  <div class="msg-row" :class="isUser ? 'msg-user' : 'msg-agent'">
    <div class="msg-bubble">
      <!-- Agent 回复顶部显示 Agent 名称快照（FR-003） -->
      <div v-if="!isUser && message.agent_name" class="msg-agent-name">
        {{ message.agent_name }}
      </div>

      <!-- 思考过程分区（可折叠） -->
      <details v-if="!isUser && message.reasoning_content" class="msg-reasoning">
        <summary>思考过程</summary>
        <div class="msg-reasoning-body" v-html="renderedReasoning"></div>
      </details>

      <!-- 正文：Markdown 渲染（FR-013） -->
      <div class="msg-content" v-html="renderedContent"></div>

      <!-- 未完成标识（FR-024 / US5） -->
      <div v-if="statusLabel" class="msg-incomplete">{{ statusLabel }}</div>

      <!-- 操作区：复制 + 重新生成（仅最后一条 assistant） -->
      <div v-if="!isUser" class="msg-actions">
        <a class="msg-action" @click="copyContent">复制</a>
        <a
          v-if="isLastAssistant && message.status !== 'generating'"
          class="msg-action"
          @click="emit('regenerate')"
        >重新生成</a>
      </div>
    </div>
  </div>
</template>

<style scoped lang="scss">
.msg-row {
  display: flex;
  margin-bottom: 16px;

  &.msg-user {
    justify-content: flex-end;

    .msg-bubble {
      background: var(--accent-dim);
      border-color: transparent;
    }
  }

  &.msg-agent {
    justify-content: flex-start;

    .msg-bubble {
      background: var(--bg-surface);
    }
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
    user-select: none;
  }
}

.msg-reasoning-body {
  margin-top: 6px;
  font-size: 13px;
  color: var(--text-secondary);
}

.msg-content {
  :deep(p) {
    margin: 0 0 8px;

    &:last-child {
      margin-bottom: 0;
    }
  }

  :deep(pre) {
    background: var(--bg-deep);
    border: 1px solid var(--border);
    border-radius: 8px;
    padding: 10px 12px;
    overflow-x: auto;
    font-family: var(--font-mono);
    font-size: 13px;
    margin: 8px 0;
  }

  :deep(code) {
    font-family: var(--font-mono);
    font-size: 13px;
    background: var(--bg-deep);
    border-radius: 4px;
    padding: 1px 5px;
  }

  :deep(pre code) {
    background: none;
    padding: 0;
  }

  :deep(table) {
    border-collapse: collapse;
    margin: 8px 0;

    th,
    td {
      border: 1px solid var(--border);
      padding: 4px 10px;
      font-size: 13px;
    }
  }

  :deep(a) {
    color: var(--accent);
  }
}

.msg-incomplete {
  margin-top: 6px;
  font-size: 12.5px;
  color: var(--warning);
}

.msg-actions {
  margin-top: 6px;
  display: flex;
  gap: 12px;
}

.msg-action {
  font-size: 12.5px;
  color: var(--text-secondary);
  cursor: pointer;

  &:hover {
    color: var(--accent);
  }
}
</style>
