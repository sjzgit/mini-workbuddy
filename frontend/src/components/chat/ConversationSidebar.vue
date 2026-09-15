<script setup lang="ts">
/**
 * 左侧会话列表（specs/008-chat-conversations FR-005/006/007、US2）。
 * 顶部"新建会话"按钮 + 会话列表（标题+最后更新时间，倒序由 store 保证）。
 */
import { message } from 'ant-design-vue'
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'

import { useAgentsStore } from '@/stores/agents'
import { useChatStore } from '@/stores/chat'

const router = useRouter()
const chat = useChatStore()
const agents = useAgentsStore()

const defaultAgentId = computed(() => agents.items.find((a) => a.is_default)?.id ?? null)

const creating = ref(false)

async function onNewConversation(): Promise<void> {
  if (creating.value) {
    return
  }
  if (defaultAgentId.value === null) {
    message.warning('还没有可用 Agent，请先创建并设为默认')
    router.push('/agents')
    return
  }
  creating.value = true
  try {
    await chat.createConversation(defaultAgentId.value)
  } catch {
    message.error('新建会话失败')
  } finally {
    creating.value = false
  }
}

function relativeTime(iso: string): string {
  const time = new Date(iso).getTime()
  const diff = Date.now() - time
  if (diff < 60_000) return '刚刚'
  if (diff < 3_600_000) return `${Math.floor(diff / 60_000)} 分钟前`
  if (diff < 86_400_000) return '当天'
  return new Date(iso).toLocaleDateString()
}

onMounted(() => {
  if (agents.items.length === 0) {
    void agents.fetchAgents()
  }
})

</script>

<template>
  <aside class="sidebar">
    <div class="sidebar-head">
      <span class="sidebar-title">会话</span>
      <button class="sidebar-new" :disabled="creating" @click="onNewConversation">
        新建会话
      </button>
    </div>
    <div class="sidebar-list">
      <button
        v-for="item in chat.conversations"
        :key="item.id"
        class="sidebar-item"
        :class="{ active: item.id === chat.currentId }"
        @click="chat.selectConversation(item.id)"
      >
        <span class="sidebar-item-title">{{ item.title }}</span>
        <span class="sidebar-item-time">{{ relativeTime(item.updated_at) }}</span>
      </button>
      <div v-if="chat.conversations.length === 0 && !chat.conversationsLoading" class="sidebar-empty">
        暂无会话，点上方"新建会话"开始
      </div>
    </div>
  </aside>
</template>

<style scoped lang="scss">
.sidebar {
  width: 240px;
  flex-shrink: 0;
  border-right: 1px solid var(--border);
  background: var(--bg-base);
  display: flex;
  flex-direction: column;
}

.sidebar-head {
  padding: 16px 14px 10px;
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.sidebar-title {
  font-size: 16px;
  font-weight: 600;
  color: var(--text-primary);
}

.sidebar-new {
  border: 1px solid var(--accent);
  color: var(--accent);
  background: var(--bg-surface);
  border-radius: 8px;
  padding: 5px 12px;
  font-size: 13px;
  cursor: pointer;

  &:disabled {
    opacity: 0.5;
  }

  &:hover:not(:disabled) {
    background: var(--accent-dim);
  }
}

.sidebar-list {
  flex: 1;
  overflow-y: auto;
  padding: 6px;
}

.sidebar-item {
  display: block;
  width: 100%;
  text-align: left;
  border: none;
  background: none;
  padding: 9px 10px;
  border-radius: 8px;
  cursor: pointer;
  font-family: var(--font-body);

  &:hover {
    background: var(--bg-hover);
  }

  &.active {
    background: var(--bg-active);
  }
}

.sidebar-item-title {
  display: block;
  font-size: 13.5px;
  color: var(--text-primary);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.sidebar-item-time {
  display: block;
  margin-top: 2px;
  font-size: 12px;
  color: var(--text-tertiary);
}

.sidebar-empty {
  padding: 20px 10px;
  font-size: 12.5px;
  color: var(--text-tertiary);
  text-align: center;
}
</style>
