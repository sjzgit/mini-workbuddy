<script setup lang="ts">
/**
 * 能力卡片多选（可复用于工具 / Skills / MCP Server 候选区）。
 * 契约要求卡片展示名称 + 用途说明（FR-013）；候选项只含启用资源（FR-016）。
 */
import { computed } from 'vue'

import { Checkbox } from 'ant-design-vue'

import type { BindingOption } from '@/api/agents'

const props = defineProps<{
  /** 候选项（只含启用资源，来自 binding-options） */
  options: BindingOption[]
  /** 已勾选的资源 id 集合 */
  selectedIds: Set<number>
  /** 无候选项时的空文案 */
  emptyText?: string
}>()

const emit = defineEmits<{
  toggle: [id: number, checked: boolean]
}>()

const hasOptions = computed(() => props.options.length > 0)

function isChecked(option: BindingOption): boolean {
  return props.selectedIds.has(option.id)
}
</script>

<template>
  <div v-if="hasOptions" class="option-cards">
    <label
      v-for="option in options"
      :key="option.id"
      class="option-card"
      :class="{ 'option-card--selected': isChecked(option) }"
    >
      <Checkbox
        :checked="isChecked(option)"
        @change="(e) => emit('toggle', option.id, (e.target as HTMLInputElement).checked)"
        @click.stop
      />
      <span class="option-card__body">
        <span class="option-card__name">{{ option.name }}</span>
        <span class="option-card__desc">{{ option.description || '暂无说明' }}</span>
      </span>
    </label>
  </div>
  <p v-else class="option-empty">{{ emptyText || '暂无可选项' }}</p>
</template>

<style scoped lang="scss">
.option-cards {
  display: flex;
  flex-direction: column;
  gap: 8px;
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
  font-size: 12.5px;
  color: var(--text-tertiary);
  margin: 0;
}
</style>
