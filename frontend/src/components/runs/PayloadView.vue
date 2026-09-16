<script setup lang="ts">
/**
 * 载荷内容视图（011 优化②）：按 payload_type 选择渲染方式。
 * - model_output：结构化三段（思考折叠块 + 正文 markdown + 工具调用 JSON）；
 *   旧格式纯文本按 markdown 降级。
 * - compression_output：markdown。
 * - model_input：JSON 美化换行。
 * - 其余（tool_params / tool_result / compression_input）：纯文本。
 */
import { computed, nextTick, onMounted, ref, watch } from 'vue'

import { renderMarkdown } from '@/utils/markdown'

const props = defineProps<{ payloadType: string; content: string; loading?: boolean }>()

// 模型输入：代码块（payload-code 自身可滚动）默认滚到最底部——最新消息在 messages 数组末尾
const codeRef = ref<HTMLElement | null>(null)

function scrollCodeToBottom(): void {
  if (props.payloadType !== 'model_input') return
  const el = codeRef.value
  if (el) el.scrollTop = el.scrollHeight
}

onMounted(() => void nextTick(scrollCodeToBottom))
watch(
  () => [props.content, props.loading] as const,
  () => void nextTick(scrollCodeToBottom),
)

function tryParseJsonObject(raw: string): Record<string, unknown> | null {
  try {
    const obj = JSON.parse(raw)
    return typeof obj === 'object' && obj !== null && !Array.isArray(obj) ? obj : null
  } catch {
    return null
  }
}

function prettyJson(raw: string): string {
  const obj = tryParseJsonObject(raw)
  if (obj !== null) return JSON.stringify(obj, null, 2)
  try {
    const arr = JSON.parse(raw)
    if (Array.isArray(arr)) return JSON.stringify(arr, null, 2)
  } catch { /* 非 JSON，原样返回 */ }
  return raw
}

const view = computed(() => {
  const raw = props.content
  if (props.loading) return { mode: 'loading' as const }
  if (props.payloadType === 'model_input') {
    return { mode: 'text' as const, text: prettyJson(raw) }
  }
  if (props.payloadType === 'model_output') {
    const obj = tryParseJsonObject(raw)
    if (obj !== null && ('content' in obj || 'reasoning' in obj || 'tool_calls' in obj)) {
      return {
        mode: 'structured' as const,
        reasoning: (obj.reasoning as string) ?? null,
        contentHtml: typeof obj.content === 'string' ? renderMarkdown(obj.content) : '',
        toolCalls: obj.tool_calls ? JSON.stringify(obj.tool_calls, null, 2) : null,
      }
    }
    return { mode: 'markdown' as const, html: renderMarkdown(raw) }
  }
  if (props.payloadType === 'compression_output') {
    return { mode: 'markdown' as const, html: renderMarkdown(raw) }
  }
  return { mode: 'text' as const, text: raw }
})
</script>

<template>
  <div ref="rootRef">
  <template v-if="view.mode === 'loading'">加载中…</template>
  <template v-else-if="view.mode === 'structured'">
    <details v-if="view.reasoning" class="payload-reasoning">
      <summary>思考过程</summary>
      <div class="payload-reasoning-body">{{ view.reasoning }}</div>
    </details>
    <div
      v-if="view.contentHtml"
      class="payload-markdown"
      v-html="view.contentHtml"
    ></div>
    <pre v-if="view.toolCalls" class="payload-code">{{ view.toolCalls }}</pre>
  </template>
  <div
    v-else-if="view.mode === 'markdown'"
    class="payload-markdown"
    v-html="view.html"
  ></div>
  <pre v-else ref="codeRef" class="payload-code">{{ view.text }}</pre>
  </div>
</template>

<style scoped lang="scss">
.payload-markdown {
  font-size: 13.5px;
  line-height: 1.6;
  color: var(--text-primary);
  overflow-wrap: anywhere;

  :deep(pre) {
    background: var(--bg-deep, rgba(0, 0, 0, 0.03));
    padding: 8px 10px;
    border-radius: 6px;
    overflow: auto;
    font-family: var(--font-mono);
    font-size: 12.5px;
    white-space: pre-wrap;
    overflow-wrap: anywhere;
  }

  :deep(code) { font-family: var(--font-mono); font-size: 12.5px; }
}

.payload-reasoning {
  margin-bottom: 8px;

  summary {
    cursor: pointer;
    font-size: 12.5px;
    color: var(--text-tertiary);
  }
}

.payload-reasoning-body {
  margin-top: 6px;
  font-size: 12.5px;
  color: var(--text-secondary);
  line-height: 1.6;
  white-space: pre-wrap;
  overflow-wrap: anywhere;
  font-family: var(--font-mono);
}

.payload-code {
  margin: 8px 0 0;
  padding: 10px 12px;
  border: 1px solid var(--border);
  border-radius: 6px;
  background: var(--bg-subtle, rgba(0, 0, 0, 0.02));
  font-family: var(--font-mono);
  font-size: 12.5px;
  line-height: 1.5;
  max-height: 340px;
  overflow: auto;
  white-space: pre-wrap;
  overflow-wrap: anywhere;
}
</style>
