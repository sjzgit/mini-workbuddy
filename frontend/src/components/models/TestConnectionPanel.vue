<script setup lang="ts">
/**
 * 测试连接结果面板（页面内联结果区，research R7）。
 *
 * - 测试中显示"正在测试"（按钮层面的防重复提交在列表操作列处理，FR-014）
 * - 成功显示"模型已连接"与一小段真实回复（FR-015）
 * - 失败展示分类徽标 + 人话提示与排查建议（后端模板，FR-016）
 */
import { Alert, Tag } from 'ant-design-vue'

import type { TestConnectionResult } from '@/api/models'
import { TEST_CATEGORY_LABELS } from './testConnection'

defineProps<{
  /** 正在测试的模型名（同时展示测试中状态） */
  testingModelName: string | null
  /** 最近一次测试结果；null = 无结果 */
  result: { modelName: string; result: TestConnectionResult } | null
}>()
</script>

<template>
  <div v-if="testingModelName || result" class="test-panel">
    <Alert v-if="testingModelName" type="info" show-icon class="test-alert">
      <template #message>正在测试「{{ testingModelName }}」，请稍候…</template>
    </Alert>

    <template v-else-if="result">
      <Alert
        :type="result.result.success ? 'success' : 'error'"
        show-icon
        class="test-alert"
      >
        <template #message>
          <span class="test-title">
            {{ result.result.success ? `「${result.modelName}」模型已连接` : `「${result.modelName}」连接失败` }}
          </span>
          <Tag
            v-if="!result.result.success && result.result.category"
            class="test-tag"
            :style="{
              background: 'var(--accent-dim)',
              color: 'var(--accent)',
              borderColor: 'transparent',
            }"
          >
            {{ TEST_CATEGORY_LABELS[result.result.category] ?? result.result.category }}
          </Tag>
        </template>
        <template #description>
          <span class="test-message">{{ result.result.message }}</span>
          <p v-if="result.result.reply_excerpt" class="test-reply">
            模型回复：{{ result.result.reply_excerpt }}
          </p>
        </template>
      </Alert>
    </template>
  </div>
</template>

<style scoped lang="scss">
.test-panel {
  .test-alert {
    border-radius: 8px;
  }
}

.test-title {
  font-size: 15px;
  font-weight: 600;
}

.test-tag {
  margin-left: 8px;
  font-size: 12px;
  line-height: 20px;
}

.test-message {
  font-size: 13.5px;
  color: var(--text-secondary);
}

.test-reply {
  margin: 6px 0 0;
  padding: 8px 10px;
  font-family: var(--font-mono);
  font-size: 13px; // 代码日志规格
  line-height: 1.5;
  color: var(--text-primary);
  background: var(--bg-base);
  border: 1px solid var(--border);
  border-radius: 6px;
  white-space: pre-wrap;
  word-break: break-all;
}
</style>
