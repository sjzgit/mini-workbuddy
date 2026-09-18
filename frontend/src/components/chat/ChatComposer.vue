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
import { ApiError } from '@/api/request'
import AskUserPanel from './AskUserPanel.vue'

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

// ---- 014：工作空间入口（输入区底部，spec 八；设置/清除经 store，失败保留原值）----
const workspaceOpen = ref(false)
const workspaceDraft = ref('')
const workspaceSaving = ref(false)

/** 无会话时入口禁用（工作空间属于会话，spec 六） */
const noConversation = computed(() => chat.currentId === null)

/** 显示文案：有值显示目录名（过长折叠中间段），无值提示未选择 */
const workspaceLabel = computed(() => {
  const path = chat.currentWorkspace
  if (!path) return '未选择工作空间'
  const normalized = path.replace(/\\/g, '/')
  const parts = normalized.split('/').filter(Boolean)
  if (parts.length <= 2) return parts.join('/')
  return `${parts[0]}/…/${parts[parts.length - 1]}`
})

function openWorkspace(): void {
  workspaceDraft.value = chat.currentWorkspace ?? ''
  workspaceOpen.value = !workspaceOpen.value
}

async function confirmWorkspace(): Promise<void> {
  const path = workspaceDraft.value.trim()
  if (!path || workspaceSaving.value) return
  workspaceSaving.value = true
  try {
    await chat.setWorkspace(path)
    workspaceOpen.value = false
    message.success('工作空间已更新')
  } catch (e) {
    message.error(e instanceof ApiError ? e.message : '设置工作空间失败')
  } finally {
    workspaceSaving.value = false
  }
}

async function removeWorkspace(): Promise<void> {
  if (workspaceSaving.value) return
  workspaceSaving.value = true
  try {
    await chat.clearWorkspace()
    workspaceDraft.value = ''
    message.success('已清除工作空间')
  } catch (e) {
    message.error(e instanceof ApiError ? e.message : '清除工作空间失败')
  } finally {
    workspaceSaving.value = false
  }
}

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
    <!-- 013 回写：Ask User 询问面板内嵌在输入区上方（与聊天输入融合，替代原全屏弹窗） -->
    <AskUserPanel v-if="chat.pendingAsk" />
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
      <!-- 014：工作空间行（输入区底部，spec 八；设置/清除经 store，失败保留原值） -->
      <div class="composer-workspace" :class="{ disabled: noConversation }">
        <button class="workspace-trigger" :disabled="noConversation" @click="openWorkspace">
          <span class="workspace-icon">📁</span>
          <span class="workspace-path" :title="chat.currentWorkspace ?? ''">{{ workspaceLabel }}</span>
        </button>
        <div v-if="workspaceOpen && !noConversation" class="workspace-popover">
          <div class="workspace-popover-title">当前工作空间</div>
          <div v-if="chat.currentWorkspace" class="workspace-current" :title="chat.currentWorkspace">
            {{ chat.currentWorkspace }}
          </div>
          <input
            v-model="workspaceDraft"
            class="workspace-input"
            placeholder="输入绝对路径，如 D:\projects\demo"
            @keydown.enter.prevent="confirmWorkspace"
          />
          <div class="workspace-popover-actions">
            <button
              class="workspace-btn primary"
              :disabled="workspaceSaving || !workspaceDraft.trim()"
              @click="confirmWorkspace"
            >
              设置
            </button>
            <button
              class="workspace-btn"
              :disabled="workspaceSaving || !chat.currentWorkspace"
              @click="removeWorkspace"
            >
              清除当前工作空间
            </button>
          </div>
        </div>
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

/* ---- 014：工作空间入口（设计令牌引用，无独立色值） ---- */
.composer-workspace {
  margin-top: 8px;
  position: relative;

  &.disabled {
    opacity: 0.55;
  }
}

.workspace-trigger {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  border: none;
  background: none;
  padding: 2px 6px;
  border-radius: 6px;
  cursor: pointer;
  font-size: 12.5px;
  color: var(--text-secondary);
  font-family: var(--font-body);
  max-width: 480px;

  &:hover:not(:disabled) {
    background: var(--bg-hover);
    color: var(--text-primary);
  }

  &:disabled {
    cursor: not-allowed;
  }
}

.workspace-icon {
  font-size: 12px;
}

.workspace-path {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.workspace-popover {
  position: absolute;
  left: 0;
  bottom: calc(100% + 6px);
  background: var(--bg-elevated);
  border: 1px solid var(--border);
  border-radius: 10px;
  box-shadow: 0 8px 24px rgba(45, 32, 23, 0.12);
  padding: 10px;
  width: 360px;
  z-index: 20;
}

.workspace-popover-title {
  font-size: 12px;
  color: var(--text-tertiary);
  margin-bottom: 6px;
}

.workspace-current {
  font-size: 12.5px;
  color: var(--text-primary);
  background: var(--bg-hover);
  border-radius: 6px;
  padding: 5px 8px;
  margin-bottom: 6px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.workspace-input {
  width: 100%;
  border: 1px solid var(--border);
  border-radius: 6px;
  background: var(--bg-surface);
  color: var(--text-primary);
  font-size: 13px;
  font-family: var(--font-body);
  padding: 6px 8px;
  outline: none;

  &:focus {
    border-color: var(--accent);
  }
}

.workspace-popover-actions {
  display: flex;
  gap: 8px;
  margin-top: 8px;
  justify-content: flex-end;
}

.workspace-btn {
  border: 1px solid var(--border);
  border-radius: 6px;
  background: var(--bg-surface);
  color: var(--text-primary);
  font-size: 13px;
  padding: 5px 12px;
  cursor: pointer;
  font-family: var(--font-body);

  &:disabled {
    opacity: 0.45;
    cursor: not-allowed;
  }

  &:hover:not(:disabled) {
    background: var(--bg-hover);
  }

  &.primary {
    background: var(--accent);
    border-color: var(--accent);
    color: var(--text-inverse);

    &:hover:not(:disabled) {
      background: var(--accent-hover);
    }
  }
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
