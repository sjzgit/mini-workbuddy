<script setup lang="ts">
/**
 * 底部输入区（specs/008-chat-conversations FR-008/009/028/029）。
 * Enter 发送 / Shift+Enter 换行 / IME 组字回车不发送；Agent 选择 + @ 唤起；
 * 生成中发送切换为停止（FR-020）；无可用 Agent 禁用发送并提供入口（FR-029）。
 */
import { message, Select } from 'ant-design-vue'
import { computed, ref, watch } from 'vue'
import { useRouter } from 'vue-router'

import { useAgentsStore } from '@/stores/agents'
import { useChatStore } from '@/stores/chat'

const router = useRouter()
const chat = useChatStore()
const agents = useAgentsStore()

const draft = ref('')
/** IME 组字状态（FR-008） */
const composing = ref(false)
/** @ 唤起的 Agent 选择弹层 */
const mentionOpen = ref(false)
/** @ 弹层键盘高亮项索引（↑/↓ 移动，Enter 选中） */
const mentionIndex = ref(0)

/** 输入框 DOM 引用（@ 检测与选中替换用） */
const inputRef = ref<HTMLTextAreaElement | null>(null)

const noAgent = computed(() => agents.items.length === 0)

/** Agent 下拉选项（a-select 需要的 label/value 形态） */
const agentOptions = computed(() =>
  agents.items.map((a) => ({ label: a.name, value: a.id })),
)

const placeholderText = '输入消息，Enter 发送，Shift + Enter 换行，@ 唤起 Agent 选择'

const canSend = computed(
  () => chat.phase === 'idle' && draft.value.trim().length > 0 && !noAgent.value,
)

// 无会话且未选择 Agent 时，预置默认 Agent（FR-029），下拉实时显示当前生效项
watch(
  () => agents.items,
  (items) => {
    if (chat.effectiveAgentId === null && items.length > 0) {
      const fallback = items.find((a) => a.is_default) ?? items[0]
      if (fallback !== undefined) {
        chat.pendingAgentId = fallback.id
      }
    }
  },
  { immediate: true },
)

function onCompositionStart(): void {
  composing.value = true
}

function onCompositionEnd(): void {
  composing.value = false
}

function onKeydown(e: KeyboardEvent): void {
  // @ 弹层打开时接管导航键：↑/↓ 移动高亮、Enter 选中、Esc 关闭（bug 3b）
  if (mentionOpen.value && agentOptions.value.length > 0) {
    const total = agentOptions.value.length
    if (e.key === 'ArrowDown') {
      e.preventDefault()
      mentionIndex.value = (mentionIndex.value + 1) % total
      return
    }
    if (e.key === 'ArrowUp') {
      e.preventDefault()
      mentionIndex.value = (mentionIndex.value - 1 + total) % total
      return
    }
    if (e.key === 'Enter') {
      e.preventDefault()
      const picked = agentOptions.value[mentionIndex.value]
      if (picked !== undefined) {
        pickFromMention(picked.value)
      }
      return
    }
    if (e.key === 'Escape') {
      e.preventDefault()
      mentionOpen.value = false
      return
    }
  }
  if (e.key === 'Enter' && !e.shiftKey) {
    if (composing.value) {
      return
    }
    e.preventDefault()
    void doSend()
  }
}

/** 输入变化时检测光标前的 @（FR-028 快捷唤起）；重置高亮到首项 */
function onInput(): void {
  const el = inputRef.value
  if (el === null) {
    mentionOpen.value = false
    return
  }
  const before = draft.value.slice(0, el.selectionStart ?? draft.value.length)
  mentionOpen.value = /@[\s]*$/.test(before)
  mentionIndex.value = 0
}

/** @ 弹层选中（鼠标/键盘统一入口）：写入 Agent 选择并清掉触发文本 */
function pickFromMention(agentId: number): void {
  mentionOpen.value = false
  void chat.selectAgent(agentId).catch(() => {
    message.error('切换 Agent 失败')
  })
  // 移除触发文本中的 @（仅当光标前确为 @ 时）
  const el = inputRef.value
  if (el !== null) {
    const pos = el.selectionStart ?? draft.value.length
    if (draft.value[pos - 1] === '@') {
      draft.value = draft.value.slice(0, pos - 1) + draft.value.slice(pos)
    }
  }
}

/** 下拉选择（Select change）：统一走 store.selectAgent（SelectValue 兼容 number） */
function pickAgent(value: unknown): void {
  if (chat.phase !== 'idle' || typeof value !== 'number') {
    return
  }
  void chat.selectAgent(value)
}


async function doSend(): Promise<void> {
  if (!canSend.value) {
    return
  }
  const content = draft.value
  draft.value = ''
  try {
    await chat.send(content)
  } catch {
    // 发送失败：恢复输入内容（FR-009）
    draft.value = content
  }
}

function onStop(): void {
  void chat.stopGeneration()
}
</script>

<template>
  <div class="composer">
    <div v-if="noAgent" class="composer-no-agent">
      <span>还没有可用 Agent，请先创建。</span>
      <a @click="router.push('/agents')">前往 Agent 管理</a>
    </div>
    <div class="composer-main">
      <textarea
        ref="inputRef"
        v-model="draft"
        class="composer-input"
        rows="3"
        placeholder="输入消息，Enter 发送，Shift + Enter 换行，@ 唤起 Agent 选择"
        @compositionstart="onCompositionStart"
        @compositionend="onCompositionEnd"
        @keydown="onKeydown"
        @input="onInput"
      />
      <div class="composer-actions">
        <div class="composer-agent">
          <span class="composer-agent-label">对话 Agent：</span>
          <Select
            :value="chat.effectiveAgentId ?? undefined"
            style="min-width: 180px"
            :options="agentOptions"
            :disabled="chat.phase !== 'idle'"
            placeholder="选择 Agent"
            @change="pickAgent"
          />
        </div>
        <button
          v-if="chat.phase === 'idle'"
          class="composer-send"
          :disabled="!canSend"
          @click="doSend"
        >
          发送
        </button>
        <button v-else class="composer-stop" @click="onStop">停止</button>
      </div>
    </div>
    <!-- @ 唤起的 Agent 选择弹层（FR-028） -->
    <div v-if="mentionOpen" class="mention-popover">
      <div class="mention-title">选择 Agent</div>
      <button
        v-for="(option, index) in agentOptions"
        :key="option.value"
        class="mention-item"
        :class="{ active: index === mentionIndex }"
        @mousedown.prevent="pickFromMention(option.value)"
        @mousemove="mentionIndex = index"
      >
        {{ option.label }}
      </button>
    </div>
  </div>
</template>

<style scoped lang="scss">
.composer {
  padding: 12px 24px 16px;
  border-top: 1px solid var(--border);
  background: var(--bg-base);
  position: relative;
}

.composer-no-agent {
  display: flex;
  gap: 10px;
  align-items: center;
  font-size: 13px;
  color: var(--warning);
  margin-bottom: 8px;

  a {
    color: var(--accent);
    cursor: pointer;
  }
}

.composer-main {
  border: 1px solid var(--border);
  border-radius: 10px;
  background: var(--bg-surface);
  padding: 10px 12px;

  &:focus-within {
    border-color: var(--accent);
  }
}

.composer-input {
  width: 100%;
  border: none;
  outline: none;
  resize: none;
  font-size: 14px;
  font-family: var(--font-body);
  color: var(--text-primary);
  background: transparent;
  line-height: 1.5;
}

.composer-actions {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-top: 8px;
}

.composer-agent {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 13px;
  color: var(--text-secondary);
}

.composer-send,
.composer-stop {
  border: none;
  border-radius: 8px;
  padding: 7px 22px;
  font-size: 13.5px;
  cursor: pointer;
  font-family: var(--font-body);
}

.composer-send {
  background: var(--accent);
  color: var(--text-inverse);

  &:disabled {
    opacity: 0.45;
    cursor: not-allowed;
  }

  &:hover:not(:disabled) {
    background: var(--accent-hover);
  }
}

.composer-stop {
  background: var(--bg-active);
  color: var(--text-primary);

  &:hover {
    background: var(--border-hover);
  }
}

.mention-popover {
  position: absolute;
  left: 24px;
  bottom: 100%;
  margin-bottom: 8px;
  background: var(--bg-elevated);
  border: 1px solid var(--border);
  border-radius: 10px;
  box-shadow: 0 8px 24px rgba(45, 32, 23, 0.12);
  padding: 8px;
  min-width: 220px;
}

.mention-title {
  font-size: 12px;
  color: var(--text-tertiary);
  padding: 2px 8px 6px;
}

.mention-item {
  display: block;
  width: 100%;
  text-align: left;
  border: none;
  background: none;
  padding: 7px 10px;
  font-size: 13.5px;
  border-radius: 6px;
  cursor: pointer;
  color: var(--text-primary);
  font-family: var(--font-body);

  &:hover,
  &.active {
    background: var(--bg-hover);
  }
}
</style>
