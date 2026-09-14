<script setup lang="ts">
/**
 * 删除 Agent 确认弹窗（US4 三分支）：
 * 普通 Agent 直接确认；默认 Agent 且还有其他 → 先选新默认（409 requires_new_default 流程）；
 * 最后一个 Agent 确认后清除默认（页面回空状态）。
 */
import { ref, watch } from 'vue'

import { FormItem, Modal, Select, message } from 'ant-design-vue'

import type { AgentListItem } from '@/api/agents'
import { parseConflictBody, useAgentsStore } from '@/stores/agents'

const props = defineProps<{
  open: boolean
  agent: AgentListItem | null
}>()

const emit = defineEmits<{
  'update:open': [value: boolean]
  done: []
}>()

const store = useAgentsStore()

const deleting = ref(false)
const deleteError = ref<string | null>(null)
/** 默认 Agent 删除被 409 拦截后的候选与选择 */
const needSuccessor = ref(false)
const candidates = ref<{ id: number; name: string }[]>([])
const newDefaultId = ref<number | undefined>(undefined)

watch(
  () => props.open,
  (open) => {
    if (open) {
      deleteError.value = null
      needSuccessor.value = false
      candidates.value = []
      newDefaultId.value = undefined
    }
  },
)

function handleClose(): void {
  emit('update:open', false)
}

async function handleConfirm(): Promise<void> {
  if (!props.agent) return
  if (needSuccessor.value && newDefaultId.value === undefined) {
    deleteError.value = '请选择新的默认 Agent'
    return
  }
  deleting.value = true
  deleteError.value = null
  try {
    await store.remove(
      props.agent.id,
      needSuccessor.value ? newDefaultId.value : undefined,
    )
    message.success(`已删除「${props.agent.name}」`)
    emit('done')
    handleClose()
  } catch (e) {
    const conflict = parseConflictBody(e)
    if (conflict && 'requires_new_default' in conflict && conflict.requires_new_default) {
      // 删除默认 Agent 且还有其他：展示候选，让用户选定新默认后重发
      needSuccessor.value = true
      candidates.value = conflict.candidates
      return
    }
    deleteError.value = e instanceof Error ? e.message : '删除失败，请稍后重试'
  } finally {
    deleting.value = false
  }
}
</script>

<template>
  <Modal
    :open="open"
    title="删除 Agent"
    :confirm-loading="deleting"
    ok-text="删除"
    :ok-button-props="{ danger: true }"
    cancel-text="取消"
    :mask-closable="false"
    @ok="handleConfirm"
    @cancel="handleClose"
  >
    <p class="delete-text">
      确认删除「{{ agent?.name }}」？
      <template v-if="agent?.is_default && !needSuccessor && (store.items.length > 1)">
        它是默认 Agent，删除前需要选择新的默认 Agent。
      </template>
      删除后该 Agent 的绑定与提示词版本将一并清除，此操作不可恢复。
    </p>

    <FormItem
      v-if="needSuccessor"
      label="选择新的默认 Agent"
      required
      :validate-status="deleteError && newDefaultId === undefined ? 'error' : undefined"
      :help="deleteError && newDefaultId === undefined ? deleteError : undefined"
    >
      <Select
        v-model:value="newDefaultId"
        :options="candidates.map((c) => ({ value: c.id, label: c.name }))"
        placeholder="请选择删除后接替的默认 Agent"
      />
    </FormItem>

    <p v-if="deleteError && !needSuccessor" class="delete-error">{{ deleteError }}</p>
  </Modal>
</template>

<style scoped lang="scss">
.delete-text {
  font-size: 14px;
  line-height: 1.5;
  color: var(--text-primary);
}

.delete-error {
  font-size: 12.5px;
  color: var(--danger);
}
</style>
