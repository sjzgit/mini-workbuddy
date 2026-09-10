<script setup lang="ts">
/**
 * 删除模型确认弹窗。
 *
 * - 普通模型：直接确认删除（FR-020）
 * - 默认模型且还有其他模型：必须先选择新的默认模型（FR-020）
 */
import { computed, ref, watch } from 'vue'

import { FormItem, Modal, Select } from 'ant-design-vue'

import type { ModelItem } from '@/api/models'
import { modelsApi } from '@/api/models'

const props = defineProps<{
  /** 打开状态（v-model:open） */
  open: boolean
  /** 待删除模型 */
  model: ModelItem | null
  /** 其余可选作新默认的模型（来自当前列表） */
  others: ModelItem[]
}>()

const emit = defineEmits<{
  'update:open': [value: boolean]
  /** 删除完成后通知父级刷新 */
  done: []
}>()

const newDefaultId = ref<number | undefined>(undefined)
const deleting = ref(false)
const deleteError = ref<string | null>(null)

/** 默认模型且还有其他模型 → 需要先选新默认 */
const needSuccessor = computed(
  () => props.model?.is_default === true && props.others.length > 0,
)

const options = computed(() =>
  props.others.map((m) => ({ value: m.id, label: m.display_name })),
)

watch(
  () => props.open,
  (open) => {
    if (open) {
      newDefaultId.value = undefined
      deleteError.value = null
    }
  },
)

function handleClose(): void {
  emit('update:open', false)
}

async function handleConfirm(): Promise<void> {
  if (!props.model) return
  if (needSuccessor.value && newDefaultId.value === undefined) {
    deleteError.value = '请选择新的默认模型'
    return
  }
  deleting.value = true
  deleteError.value = null
  try {
    await modelsApi.remove(
      props.model.id,
      needSuccessor.value ? newDefaultId.value : undefined,
    )
    emit('done')
    handleClose()
  } catch (e) {
    deleteError.value = e instanceof Error ? e.message : '删除失败，请稍后重试'
  } finally {
    deleting.value = false
  }
}
</script>

<template>
  <Modal
    :open="open"
    title="删除模型"
    :confirm-loading="deleting"
    ok-text="删除"
    :ok-button-props="{ danger: true }"
    cancel-text="取消"
    :mask-closable="false"
    @ok="handleConfirm"
    @cancel="handleClose"
  >
    <p class="delete-text">
      确认删除「{{ model?.display_name }}」？删除后其保存的密钥将一并清理，此操作不可恢复。
    </p>

    <FormItem
      v-if="needSuccessor"
      label="选择新的默认模型"
      required
      :validate-status="deleteError && newDefaultId === undefined ? 'error' : undefined"
      :help="deleteError && newDefaultId === undefined ? deleteError : undefined"
    >
      <Select
        v-model:value="newDefaultId"
        :options="options"
        placeholder="请选择删除后接替的默认模型"
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
