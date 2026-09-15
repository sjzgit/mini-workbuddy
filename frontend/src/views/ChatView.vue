<script setup lang="ts">
/**
 * 聊天页容器（specs/008-chat-conversations FR-026）。
 * 左右布局：左侧会话列表 + 右侧聊天区（标题栏 / 消息区 / 输入区）。
 * 挂载时加载会话列表并恢复上次活跃会话（US2 刷新恢复）。
 */
import { onMounted } from 'vue'

import ChatComposer from '@/components/chat/ChatComposer.vue'
import ChatMessages from '@/components/chat/ChatMessages.vue'
import ConversationSidebar from '@/components/chat/ConversationSidebar.vue'
import { useChatStore } from '@/stores/chat'

const chat = useChatStore()

onMounted(async () => {
  await chat.fetchConversations()
  // 恢复上次活跃会话：列表第一条（updated_at 倒序），无会话保持空态
  const first = chat.conversations[0]
  if (first !== undefined) {
    await chat.selectConversation(first.id)
  }
})

</script>

<template>
  <div class="chat-page">
    <ConversationSidebar />
    <section class="chat-main">
      <header class="chat-header">
        <h1 class="chat-header-title">{{ chat.currentConversation?.title ?? '聊天' }}</h1>
      </header>
      <ChatMessages />
      <ChatComposer />
    </section>
  </div>
</template>

<style scoped lang="scss">
.chat-page {
  display: flex;
  height: 100%;
}

.chat-main {
  flex: 1;
  display: flex;
  flex-direction: column;
  min-width: 0;
}

.chat-header {
  padding: 14px 24px;
  border-bottom: 1px solid var(--border);
  background: var(--bg-surface);
}

.chat-header-title {
  font-size: 22px;
  font-weight: 650;
  color: var(--text-primary);
  margin: 0;
}
</style>
