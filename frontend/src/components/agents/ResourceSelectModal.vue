<script setup lang="ts">
/**
 * 能力选择弹窗（FR-004a）：关键词筛选 + 卡片式多选。
 * 由 Agent 维护表单中"维护"按钮打开；勾选结果实时同步回表单（确定/取消均保留已勾选状态）。
 */
import { computed, ref, watch } from 'vue'

import { Checkbox, Input, Modal } from 'ant-design-vue'
import { SearchOutlined } from '@ant-design/icons-vue'

import type { BindingOption } from '@/api/agents'

const props = defineProps<{
  open: boolean
  /** 弹窗标题（如"选择工具"） */
  title: string
  options: BindingOption[]
  /** 当前已选 id 集合（进入弹窗时拷贝为工作集） */
  selectedIds: Set<number>
  emptyText?: string
}>()

const emit = defineEmits<{
  'update:open': [value: boolean]
  /** 点确定时提交工作集 */
  confirm: [ids: Set<number>]
}>()

const keyword = ref('')
const workingSet = ref(new Set<number>())

watch(
  () => props.open,
  (open) => {
    if (open) {
      workingSet.value = new Set(props.selectedIds) // 拷贝，取消可回退
      keyword.value = ''
    }
  },
)

/** 关键词过滤（名称或说明，不区分大小写） */
const filteredOptions = computed(() => {
  const text = keyword.value.trim().toLowerCase()
  if (!text) return props.options
  return props.options.filter(
    (option) =>
      option.name.toLowerCase().includes(text) ||
      option.description.toLowerCase().includes(text),
  )
})

/** 筛选命中的已选数量（供"清除筛选"提示） */
const matchedSelectedCount = computed(
  () => filteredOptions.value.filter((option) => workingSet.value.has(option.id)).length,
)

function isChecked(option: BindingOption): boolean {
  return workingSet.value.has(option.id)
}

function toggle(option: BindingOption, checked: boolean): void {
  const next = new Set(workingSet.value)
  if (checked) {
    next.add(option.id)
  } else {
    next.delete(option.id)
  }
  workingSet.value = next
}

function clearFilter(): void {
  keyword.value = ''
}

function handleOk(): void {
  emit('confirm', new Set(workingSet.value))
  emit('update:open', false)
}

function handleClose(): void {
  emit('update:open', false)
}
</script>

<template>
  <Modal
    :open="open"
    :title="title"
    ok-text="确定"
    cancel-text="取消"
    :width="560"
    :mask-closable="false"
    @ok="handleOk"
    @cancel="handleClose"
  >
    <Input
      v-model:value="keyword"
      placeholder="输入名称或用途说明关键词筛选"
      allow-clear
      class="filter-input"
    >
      <template #prefix>
        <SearchOutlined style="color: var(--text-tertiary)" />
        <span class="visually-hidden">搜索</span>
      </template>
    </Input>
    <p class="match-hint">
      共 {{ options.length }} 项，筛选命中 {{ filteredOptions.length }} 项
      <button
        v-if="keyword"
        type="button"
        class="clear-btn"
        @click="clearFilter"
      >清除筛选</button>
    </p>

    <div class="option-list">
      <label
        v-for="option in filteredOptions"
        :key="option.id"
        class="option-card"
        :class="{ 'option-card--selected': isChecked(option) }"
      >
        <Checkbox
          :checked="isChecked(option)"
          @change="(e) => toggle(option, (e.target as HTMLInputElement).checked)"
        />
        <span class="option-card__body">
          <span class="option-card__name">{{ option.name }}</span>
          <span class="option-card__desc">{{ option.description || '暂无说明' }}</span>
        </span>
      </label>
      <p v-if="filteredOptions.length === 0" class="option-empty">
        {{ options.length === 0 ? (emptyText || '暂无可选项') : '没有匹配的选项' }}
      </p>
    </div>
  </Modal>
</template>

<style scoped lang="scss">
.filter-input {
  margin-bottom: 8px;
}

.match-hint {
  margin: 0 0 10px;
  font-size: 12px;
  color: var(--text-tertiary);

  .clear-btn {
    border: none;
    background: none;
    padding: 0 0 0 8px;
    font-size: 12px;
    color: var(--accent);
    cursor: pointer;
  }
}

.option-list {
  max-height: 380px;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
  gap: 8px;
  padding-right: 4px;
}

.option-card {
  display: flex;
  align-items: flex-start;
  gap: 10px;
  padding: 10px 12px;
  border: 1px solid var(--border);
  border-radius: 8px;
  background: var(--bg-surface);
  cursor: pointer;
  transition: border-color 0.15s ease, background 0.15s ease;

  &:hover {
    border-color: var(--border-hover);
    background: var(--bg-hover);
  }

  &--selected {
    border-color: var(--accent);
    background: var(--accent-dim);
  }
}

.option-card__body {
  display: flex;
  flex-direction: column;
  gap: 2px;
  min-width: 0;
}

.option-card__name {
  font-size: 14px;
  font-weight: 600;
  color: var(--text-primary);
}

.option-card__desc {
  font-size: 12.5px;
  color: var(--text-secondary);
  line-height: 1.4;
}

.option-empty {
  margin: 12px 0;
  text-align: center;
  font-size: 12.5px;
  color: var(--text-tertiary);
}

.visually-hidden {
  position: absolute;
  width: 1px;
  height: 1px;
  overflow: hidden;
  clip: rect(0 0 0 0);
}
</style>
