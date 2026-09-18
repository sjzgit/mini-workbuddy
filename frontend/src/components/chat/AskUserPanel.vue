<script setup lang="ts">
/**
 * Ask User 询问面板（specs/013-ask-user-tool，US2/US3；013 回写：由弹窗改为
 * 输入区内嵌面板，与聊天输入区域融合——挂在 ChatComposer 上方）。
 *
 * - 开放式：问题 + 文本输入框（FR-005）
 * - 选项式：单选 Radio / 多选 Checkbox + 末尾自动追加"其他，我手动输入"，
 *   选中其他后下方出现输入框（FR-006/007）
 * - 空回答禁止提交（FR-008）；提交 loading 防重复，失败面板保留可重试（FR-017）
 */
import { computed, ref, watch } from 'vue'

import { Button, Checkbox, CheckboxGroup, Input, Radio, RadioGroup } from 'ant-design-vue'

import { useChatStore } from '@/stores/chat'

const OTHER_LABEL = '其他，我手动输入'

const store = useChatStore()
const ask = computed(() => store.pendingAsk)

const textInput = ref('')
const selectedSingle = ref<string | null>(null)
const selectedMulti = ref<string[]>([])

/** 切换到新询问时重置本地输入（重放/连环询问场景） */
watch(
  () => ask.value?.callId,
  () => {
    textInput.value = ''
    selectedSingle.value = null
    selectedMulti.value = []
  },
)

const isMulti = computed(() => ask.value?.multiSelect ?? false)
const hasOptions = computed(() => (ask.value?.options.length ?? 0) > 0)
const otherSelected = computed(() =>
  isMulti.value
    ? selectedMulti.value.includes(OTHER_LABEL)
    : selectedSingle.value === OTHER_LABEL,
)

/** 空回答判定：无选中项且无有效文本（FR-008） */
const canSubmit = computed(() => {
  if (!ask.value) return false
  if (hasOptions.value) {
    const picked = isMulti.value ? selectedMulti.value : selectedSingle.value
    const hasPick = isMulti.value
      ? (picked as string[]).length > 0
      : picked === OTHER_LABEL || picked !== null
    if (!hasPick) return false
    if (otherSelected.value && !textInput.value.trim()) return false
    return true
  }
  return textInput.value.trim().length > 0
})

async function submit(): Promise<void> {
  if (!ask.value || !canSubmit.value || ask.value.submitting) return
  const rawText = textInput.value.trim()
  if (!hasOptions.value) {
    await store.submitAskAnswer([], rawText)
    return
  }
  if (isMulti.value) {
    const picked = selectedMulti.value.filter((item) => item !== OTHER_LABEL)
    const useOther = selectedMulti.value.includes(OTHER_LABEL)
    await store.submitAskAnswer(picked, useOther && rawText ? rawText : null)
  } else {
    if (selectedSingle.value === OTHER_LABEL) {
      await store.submitAskAnswer([], rawText)
    } else {
      await store.submitAskAnswer(selectedSingle.value ? [selectedSingle.value] : [], null)
    }
  }
}
</script>

<template>
  <div v-if="ask" class="ask-panel">
    <div class="ask-label">Agent 向你提问</div>
    <p class="ask-question">{{ ask.question }}</p>

    <!-- 开放式：文本输入框 -->
    <textarea
      v-if="!hasOptions"
      v-model="textInput"
      class="ask-textarea"
      rows="3"
      placeholder="输入你的回答…"
    />

    <!-- 选项式：单选 -->
    <RadioGroup v-else-if="!isMulti" v-model:value="selectedSingle" class="ask-options">
      <Radio v-for="opt in ask.options" :key="opt" :value="opt" class="ask-option">
        {{ opt }}
      </Radio>
      <Radio :value="OTHER_LABEL" class="ask-option ask-option--other">{{ OTHER_LABEL }}</Radio>
    </RadioGroup>

    <!-- 选项式：多选 -->
    <CheckboxGroup v-else v-model:value="selectedMulti" class="ask-options">
      <div v-for="opt in ask.options" :key="opt">
        <Checkbox :value="opt" class="ask-option">{{ opt }}</Checkbox>
      </div>
      <div>
        <Checkbox :value="OTHER_LABEL" class="ask-option ask-option--other">
          {{ OTHER_LABEL }}
        </Checkbox>
      </div>
    </CheckboxGroup>

    <!-- 选中"其他"后的输入框 -->
    <Input
      v-if="hasOptions && otherSelected"
      v-model:value="textInput"
      class="ask-other-input"
      placeholder="输入你的回答…"
    />

    <div class="ask-actions">
      <Button
        type="primary"
        :disabled="!canSubmit"
        :loading="ask.submitting"
        @click="submit"
      >
        提交回答
      </Button>
      <span v-if="!canSubmit" class="ask-hint">请先选择或输入回答</span>
    </div>
  </div>
</template>

<style scoped lang="scss">
.ask-panel {
  display: flex;
  flex-direction: column;
  gap: 10px;
  margin-bottom: 10px;
  padding: 12px 14px;
  background: var(--bg-surface);
  border: 1px solid var(--accent);
  border-radius: 10px;
}

.ask-label {
  font-size: 12px;
  font-weight: 600;
  color: var(--accent);
}

.ask-question {
  margin: 0;
  font-size: 14px;
  line-height: 1.5;
  color: var(--text-primary);
  white-space: pre-wrap;
}

.ask-textarea {
  width: 100%;
  padding: 8px 10px;
  border: 1px solid var(--border);
  border-radius: 6px;
  resize: vertical;
  font-family: var(--font-body);
  font-size: 14px;
  line-height: 1.5;
  color: var(--text-primary);
  background: var(--bg-base);

  &:focus {
    outline: none;
    border-color: var(--accent);
  }
}

.ask-options {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.ask-option {
  font-size: 14px;
  color: var(--text-primary);
}

.ask-option--other {
  color: var(--text-secondary);
}

.ask-actions {
  display: flex;
  align-items: center;
  gap: 10px;
}

.ask-hint {
  font-size: 12.5px;
  color: var(--text-tertiary);
}
</style>
