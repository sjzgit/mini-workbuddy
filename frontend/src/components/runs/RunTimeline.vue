<script setup lang="ts">
/**
 * 运行事件时间线（specs/011 FR-016/017）：按真实事件顺序（seq）渲染步骤。
 * 模型/工具开始与结束事件通过 call_id 配对；压缩事件独立成步；
 * estimated_* 一律标注"（估算）"。样式引用设计令牌（AGENTS.md §8）。
 * 011 优化：详细载荷内联到对应步骤下方（输入/输出/参数/结果/摘要），
 * 按需懒加载（FR-018/021 不变——默认不读，展开才请求）。
 */
import { computed, ref } from 'vue'

import type { RunEventOut, RunDetail } from '@/api/runs'
import { useRunsStore } from '@/stores/runs'
import PayloadView from '@/components/runs/PayloadView.vue'

const props = defineProps<{
  detail: RunDetail
  runId?: string | null
  /** `${callId}|${payloadType}` → 载荷元数据 id；缺省视为该步骤无载荷 */
  payloadIndex?: Record<string, number>
}>()

const runsStore = useRunsStore()

interface TimelineStep {
  key: string
  kind: 'run' | 'model' | 'tool' | 'compression' | 'error' | 'done'
  title: string
  status: 'ok' | 'error' | 'cancelled' | 'running' | 'info'
  lines: string[]
  callId: string
  /** 该步骤可展开的载荷类型（已按 payloadIndex 过滤） */
  payloadTypes: string[]
}

const PAYLOAD_LABELS: Record<string, string> = {
  model_input: '输入',
  model_output: '输出',
  tool_params: '参数',
  tool_result: '结果',
  compression_input: '摘要输入',
  compression_output: '摘要',
}

function payloadMetaId(callId: string, type: string): number | null {
  const id = props.payloadIndex?.[`${callId}|${type}`]
  return typeof id === 'number' ? id : null
}

// ---- 展开/懒加载 ----
const expanded = ref<Record<string, boolean>>({})

function togglePayload(stepKey: string, callId: string, type: string): void {
  const key = `${stepKey}:${type}`
  expanded.value[key] = !expanded.value[key]
  if (expanded.value[key] && props.runId) {
    const metaId = payloadMetaId(callId, type)
    if (metaId !== null) void runsStore.fetchPayloadContent(props.runId, metaId)
  }
}

function payloadContent(callId: string, type: string): string {
  const metaId = payloadMetaId(callId, type)
  if (metaId === null) return ''
  return runsStore.payloadContents[metaId]?.content ?? ''
}

function payloadLoading(callId: string, type: string): boolean {
  const metaId = payloadMetaId(callId, type)
  return metaId !== null && runsStore.payloadLoadingId === metaId
}

// ---- 步骤构建 ----
const steps = computed<TimelineStep[]>(() => {
  const result: TimelineStep[] = []
  const modelByCall = new Map<string, { started?: RunEventOut; completed?: RunEventOut }>()
  const toolByCall = new Map<string, { started?: RunEventOut; completed?: RunEventOut }>()

  const pickStr = (e: RunEventOut, k: string): string =>
    e.data[k] === null || e.data[k] === undefined ? '' : String(e.data[k])

  const usageText = (e: RunEventOut): string => {
    const usage = e.data.usage as Record<string, unknown> | undefined
    if (!usage) return 'Token 用量：未知'
    const p = usage.prompt_tokens, c = usage.completion_tokens, t = usage.total_tokens
    if (p == null && c == null && t == null) return 'Token 用量：未知'
    return `Token 用量：输入 ${p ?? '未知'} / 输出 ${c ?? '未知'} / 合计 ${t ?? '未知'}`
  }

  const statusOf = (s: string): TimelineStep['status'] => {
    if (s === 'ok' || s === 'success' || s === 'completed' || s === 'succeeded') return 'ok'
    if (s === 'cancelled') return 'cancelled'
    if (s === 'error' || s === 'failed' || s === 'denied') return 'error'
    if (!s) return 'running'
    return 'info'
  }

  const withPayloads = (step: TimelineStep, types: string[]): TimelineStep => ({
    ...step,
    payloadTypes: types.filter((type) => payloadMetaId(step.callId, type) !== null),
  })

  for (const event of props.detail.events) {
    if (event.event_type === 'run_started') {
      result.push({
        key: `run-${event.seq}`, kind: 'run', status: 'info', callId: '', payloadTypes: [],
        title: 'Agent 开始',
        lines: [
          `Agent：${pickStr(event, 'agent_name')}`,
          `模型：${pickStr(event, 'model_name') || '未知'}（${pickStr(event, 'model_identifier')}）`,
        ],
      })
    } else if (event.event_type === 'model_request_started') {
      modelByCall.set(pickStr(event, 'call_id'), { started: event })
    } else if (event.event_type === 'model_request_completed') {
      const callId = pickStr(event, 'call_id')
      const entry = modelByCall.get(callId) ?? {}
      entry.completed = event
      modelByCall.set(callId, entry)
      const isCompact = pickStr(event, 'purpose') === 'context_compression'
      result.push(withPayloads({
        key: `model-${event.seq}`,
        kind: 'model',
        status: statusOf(pickStr(event, 'status')),
        title: isCompact ? '模型请求（上下文压缩）' : `模型请求（第 ${event.round ?? '-'} 轮）`,
        lines: [
          `状态：${pickStr(event, 'status')}　耗时：${pickStr(event, 'duration_ms')} ms`,
          usageText(event),
          `调用标识：${callId}`,
        ],
        callId,
        payloadTypes: [],
      }, ['model_input', 'model_output']))
    } else if (event.event_type === 'tool_call_started') {
      toolByCall.set(pickStr(event, 'call_id'), { started: event })
    } else if (event.event_type === 'tool_call_completed') {
      const callId = pickStr(event, 'call_id')
      const entry = toolByCall.get(callId) ?? {}
      entry.completed = event
      toolByCall.set(callId, entry)
      const started = entry.started
      const lines = [
        `状态：${pickStr(event, 'status')}　耗时：${pickStr(event, 'duration_ms')} ms`,
        `输入摘要：${started ? pickStr(started, 'params_summary') : '（缺开始事件）'}`,
        `结果摘要：${pickStr(event, 'result_summary')}`,
      ]
      if (started && pickStr(started, 'server_name')) {
        lines.unshift(`Server：${pickStr(started, 'server_name')}`)
      }
      result.push(withPayloads({
        key: `tool-${event.seq}`,
        kind: 'tool',
        status: statusOf(pickStr(event, 'status')),
        title: started
          ? (pickStr(started, 'display_name') || pickStr(event, 'tool_name'))
          : pickStr(event, 'tool_name'),
        lines,
        callId,
        payloadTypes: [],
      }, ['tool_params', 'tool_result']))
    } else if (event.event_type === 'compression_started') {
      result.push(withPayloads({
        key: `comp-s-${event.seq}`, kind: 'compression', status: 'running', callId: event.call_id ?? '',
        title: '上下文压缩开始',
        lines: [
          `触发原因：${pickStr(event, 'trigger_reason') === 'threshold' ? '估算输入达到触发比例' : '固定内容预检'}`,
          `压缩前估算输入：≈${pickStr(event, 'estimated_input_tokens')} tokens（估算）`,
          `可用输入容量：${pickStr(event, 'available_input_tokens')} tokens`,
        ],
        payloadTypes: [],
      }, ['compression_input']))
    } else if (event.event_type === 'compression_completed') {
      result.push(withPayloads({
        key: `comp-c-${event.seq}`, kind: 'compression', status: 'ok', callId: event.call_id ?? '',
        title: '上下文压缩完成',
        lines: [
          `估算输入：≈${pickStr(event, 'estimated_tokens_before')} → ≈${pickStr(event, 'estimated_tokens_after')} tokens（估算）`,
          `处理消息 ${pickStr(event, 'messages_compressed')} 条（${pickStr(event, 'groups_compressed')} 组），保留最近 ${pickStr(event, 'kept_rounds')} 轮`,
          `分批 ${pickStr(event, 'batches')} 次　摘要 ≈${pickStr(event, 'summary_estimated_tokens')} tokens　耗时 ${pickStr(event, 'duration_ms')} ms`,
          `压缩边界推进至 seq=${pickStr(event, 'boundary_seq')}`,
        ],
        payloadTypes: [],
      }, ['compression_output']))
    } else if (event.event_type === 'compression_failed') {
      result.push(withPayloads({
        key: `comp-f-${event.seq}`, kind: 'compression', status: 'error', callId: event.call_id ?? '',
        title: '上下文压缩失败',
        lines: [
          `原因：${pickStr(event, 'reason')}`,
          `压缩前估算输入：≈${pickStr(event, 'estimated_tokens_before')} tokens（估算）　耗时 ${pickStr(event, 'duration_ms')} ms`,
        ],
        payloadTypes: [],
      }, []))
    } else if (event.event_type === 'compression_fallback') {
      result.push(withPayloads({
        key: `comp-b-${event.seq}`, kind: 'compression', status: 'info', callId: event.call_id ?? '',
        title: '备用裁剪',
        lines: [
          pickStr(event, 'reason') || '摘要不可用，已按完整消息组裁剪较早对话',
          `裁剪 ${pickStr(event, 'dropped_groups')} 组，保留 ${pickStr(event, 'kept_groups')} 组`,
          `裁剪后估算输入：≈${pickStr(event, 'estimated_tokens_after')} tokens（估算）`,
        ],
        payloadTypes: [],
      }, []))
    } else if (event.event_type === 'error') {
      result.push({
        key: `error-${event.seq}`, kind: 'error', status: 'error', callId: '', payloadTypes: [],
        title: '运行错误',
        lines: [`[${pickStr(event, 'category')}] ${pickStr(event, 'message')}`],
      })
    } else if (event.event_type === 'run_completed') {
      const status = pickStr(event, 'status')
      result.push({
        key: `done-${event.seq}`, kind: 'done',
        status: status === 'completed' ? 'ok' : status === 'max_rounds' ? 'info' : status === 'cancelled' ? 'cancelled' : 'error',
        title: `运行结束（${status === 'completed' ? '正常完成' : status === 'max_rounds' ? '达到轮数限制' : status === 'cancelled' ? '已取消' : '失败'}）`,
        lines: [pickStr(event, 'reason'), pickStr(event, 'stopped') === 'true' ? '用户主动停止' : ''].filter(Boolean),
        callId: '',
        payloadTypes: [],
      })
    }
  }
  return result
})
</script>

<template>
  <ol class="run-timeline">
    <li
      v-for="step in steps"
      :key="step.key"
      class="run-timeline__item"
      :class="`is-${step.status}`"
    >
      <span class="run-timeline__dot" aria-hidden="true"></span>
      <div class="run-timeline__body">
        <div class="run-timeline__title">{{ step.title }}</div>
        <div v-for="(line, i) in step.lines" :key="i" class="run-timeline__line">{{ line }}</div>

        <!-- 内联载荷（011 优化）：按需懒加载，与步骤对照查看 -->
        <div v-if="step.payloadTypes.length" class="step-payloads">
          <template v-for="type in step.payloadTypes" :key="`${step.key}:${type}`">
            <button
              type="button"
              class="step-payload__toggle"
              @click="togglePayload(step.key, step.callId, type)"
            >
              {{ PAYLOAD_LABELS[type] ?? type }}
              <span class="step-payload__action">{{ expanded[`${step.key}:${type}`] ? '收起' : '展开' }}</span>
            </button>
            <div v-if="expanded[`${step.key}:${type}`]" class="step-payload__body">
              <PayloadView
                :payload-type="type"
                :content="payloadContent(step.callId, type)"
                :loading="payloadLoading(step.callId, type)"
              />
            </div>
          </template>
        </div>
      </div>
    </li>
  </ol>
</template>

<style scoped lang="scss">
.run-timeline {
  list-style: none;
  margin: 0;
  padding: 0 0 0 var(--space-2, 8px);
  position: relative;

  &::before {
    content: '';
    position: absolute;
    left: 13px;
    top: 6px;
    bottom: 6px;
    width: 1px;
    background: var(--border);
  }
}

.run-timeline__item {
  position: relative;
  display: flex;
  gap: 12px;
  padding: 6px 0;
}

.run-timeline__dot {
  flex: none;
  width: 11px;
  height: 11px;
  margin-top: 4px;
  border-radius: 50%;
  background: var(--border);
  border: 2px solid var(--bg-card, #fff);
  box-sizing: content-box;

  .is-ok & { background: var(--success); }
  .is-error & { background: var(--danger); }
  .is-cancelled & { background: var(--text-tertiary, #999); }
  .is-running & { background: var(--warning); }
}

.run-timeline__body {
  min-width: 0;
  flex: 1;
}

.run-timeline__title {
  font-size: 14px;
  font-weight: 600;
  color: var(--text-primary);
}

.run-timeline__line {
  font-size: 12.5px;
  color: var(--text-secondary);
  line-height: 1.5;
  font-family: var(--font-mono);
}

.step-payloads {
  margin-top: 6px;
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.step-payload__toggle {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  align-self: flex-start;
  background: transparent;
  border: none;
  padding: 2px 0;
  cursor: pointer;
  font-size: 12.5px;
  color: var(--accent);

  &:hover { text-decoration: underline; }
}

.step-payload__action { color: var(--text-tertiary); font-size: 12px; }

.step-payload__body {
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 8px 10px;
  background: var(--bg-subtle, rgba(0, 0, 0, 0.02));
  max-height: 420px;
  overflow: auto;
}
</style>
