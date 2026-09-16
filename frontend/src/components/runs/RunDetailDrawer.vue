<script setup lang="ts">
/**
 * 运行详情抽屉（specs/011 FR-016~018）：运行摘要 + 事件时间线。
 * 011 优化：详细载荷内联到时间线对应步骤（输入/输出/参数/结果/摘要），
 * 展开时按需懒加载（FR-018/021：默认只读安全事件与摘要）。
 */
import { computed, ref, watch } from 'vue'

import { Drawer, Spin, Alert, Tag } from 'ant-design-vue'

import { RUN_STATUS_META } from '@/api/runs'
import { useRunsStore } from '@/stores/runs'
import RunTimeline from '@/components/runs/RunTimeline.vue'

const props = defineProps<{ open: boolean; runId: string | null }>()
const emit = defineEmits<{ (e: 'update:open', value: boolean): void }>()

const runsStore = useRunsStore()

watch(
  () => [props.open, props.runId] as const,
  ([open, runId]) => {
    if (open && runId) {
      void runsStore.fetchDetail(runId).then(() => runsStore.fetchPayloadMetas(runId))
    }
  },
  { immediate: true },
)

const detail = computed(() => runsStore.currentDetail)
const loading = computed(() => runsStore.detailLoading)

/** `${callId}|${payloadType}` → 载荷元数据 id（时间线内联展开用） */
const payloadIndex = computed<Record<string, number>>(() => {
  const metas = props.runId ? (runsStore.payloadMetas[props.runId] ?? []) : []
  const map: Record<string, number> = {}
  for (const meta of metas) {
    map[`${meta.call_id}|${meta.payload_type}`] = meta.id
  }
  return map
})

function close(): void {
  emit('update:open', false)
}

function formatDuration(ms: number | null): string {
  if (ms == null) return '—'
  if (ms < 1000) return `${ms} ms`
  return `${(ms / 1000).toFixed(1)} s`
}

function formatDateTime(iso: string | null): string {
  if (!iso) return '—'
  const date = new Date(iso)
  if (Number.isNaN(date.getTime())) return iso
  return date.toLocaleString('zh-CN', { hour12: false })
}
</script>

<template>
  <Drawer
    :open="props.open"
    title="运行详情"
    width="60vw"
    :destroy-on-close="true"
    @close="close"
  >
    <Spin :spinning="loading">
      <Alert
        v-if="runsStore.detailError"
        type="error"
        :message="runsStore.detailError"
        show-icon
        class="detail-alert"
      />
      <template v-if="detail">
        <section class="detail-summary">
          <div class="detail-summary__head">
            <Tag :color="RUN_STATUS_META[detail.summary.status].color">
              {{ RUN_STATUS_META[detail.summary.status].text }}
            </Tag>
            <span class="detail-summary__id">{{ detail.summary.run_id }}</span>
          </div>
          <dl class="detail-grid">
            <div><dt>Agent</dt><dd>{{ detail.summary.agent_name }}</dd></div>
            <div><dt>模型</dt><dd>{{ detail.summary.model_name }}</dd></div>
            <div><dt>开始时间</dt><dd>{{ formatDateTime(detail.summary.started_at) }}</dd></div>
            <div><dt>结束时间</dt><dd>{{ formatDateTime(detail.summary.finished_at) }}</dd></div>
            <div><dt>总耗时</dt><dd>{{ formatDuration(detail.summary.total_duration_ms) }}</dd></div>
            <div><dt>首个输出</dt><dd>{{ detail.summary.first_output_ms == null ? '无正文输出' : formatDuration(detail.summary.first_output_ms) }}</dd></div>
            <div><dt>模型调用</dt><dd>{{ detail.summary.model_call_count }} 次</dd></div>
            <div><dt>工具调用</dt><dd>{{ detail.summary.tool_call_count }} 次</dd></div>
            <div><dt>Token 用量</dt><dd>{{ detail.summary.total_tokens == null ? '未知 / 统计不完整' : `输入 ${detail.summary.prompt_tokens ?? '未知'} · 输出 ${detail.summary.completion_tokens ?? '未知'} · 合计 ${detail.summary.total_tokens}` }}</dd></div>
            <div v-if="detail.summary.error_summary"><dt>错误摘要</dt><dd class="is-error">{{ detail.summary.error_summary }}</dd></div>
            <div v-if="detail.summary.end_reason"><dt>结束原因</dt><dd>{{ detail.summary.end_reason }}</dd></div>
          </dl>
        </section>

        <section class="detail-section">
          <h3 class="detail-section__title">事件时间线</h3>
          <p class="detail-section__hint">
            每个步骤下方可展开"输入 / 输出 / 参数 / 结果 / 摘要"等完整载荷（脱敏后，按需加载）。
          </p>
          <RunTimeline
            :detail="detail"
            :run-id="props.runId"
            :payload-index="payloadIndex"
          />
        </section>
      </template>
    </Spin>
  </Drawer>
</template>

<style scoped lang="scss">
.detail-alert { margin-bottom: 12px; }

.detail-summary__head {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 8px;
}

.detail-summary__id {
  font-family: var(--font-mono);
  font-size: 12.5px;
  color: var(--text-tertiary);
}

.detail-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 4px 16px;
  margin: 0 0 8px;

  div { display: flex; gap: 6px; min-width: 0; }
  dt { flex: none; color: var(--text-tertiary); font-size: 12.5px; }
  dd { margin: 0; color: var(--text-primary); font-size: 13px; min-width: 0; overflow-wrap: anywhere; }
  .is-error { color: var(--danger); }
}

.detail-section { margin-top: 16px; }

.detail-section__title {
  font-size: 15px;
  font-weight: 600;
  color: var(--text-primary);
  margin: 0 0 4px;
}

.detail-section__hint {
  margin: 0 0 10px;
  font-size: 12px;
  color: var(--text-tertiary);
}
</style>
