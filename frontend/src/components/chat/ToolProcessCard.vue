<script setup lang="ts">
/**
 * 工具过程卡片（specs/010-tool-execution-display US1/US3）。
 * 收起态：状态徽标（文字+图标双通道 FR-027）+ 标题 + 单行摘要 + 耗时；
 * 展开态：输入参数 / 执行结果分区（T014 补充详情渲染）。
 * 标题规则（FR-003）：builtin=易读名；mcp=Server名 · 工具名；skill=加载 Skill。
 */
import { computed, ref } from 'vue'

import type { ToolCardSegment, ToolCardStatus } from '@/stores/chat'

const props = defineProps<{ card: ToolCardSegment }>()

const emit = defineEmits<{ toggle: [] }>()

/** 状态 → 文案与图标（文字与视觉标识双通道，FR-027；配色仅用令牌变量） */
const STATUS_META: Record<ToolCardStatus, { text: string; icon: string; cls: string }> = {
  running: { text: '正在执行', icon: '⟳', cls: 'st-running' },
  success: { text: '成功', icon: '✓', cls: 'st-success' },
  error: { text: '失败', icon: '✕', cls: 'st-error' },
  denied: { text: '失败', icon: '✕', cls: 'st-error' },
  cancelled: { text: '已取消', icon: '⏹', cls: 'st-cancelled' },
  unknown: { text: '状态未知', icon: '?', cls: 'st-unknown' },
}

const meta = computed(() => STATUS_META[props.card.status])

/** 标题：MCP 工具联合展示 Server 名（FR-003） */
const title = computed(() => {
  if (props.card.toolType === 'mcp' && props.card.serverName) {
    return `${props.card.serverName} · ${props.card.displayName}`
  }
  return props.card.displayName
})

/** 耗时：≥1000ms 显示秒，否则毫秒 */
const durationText = computed(() => {
  const ms = props.card.durationMs
  if (ms === null || ms === undefined) {
    return ''
  }
  return ms >= 1000 ? `${(ms / 1000).toFixed(1)} 秒` : `${ms} 毫秒`
})

/** 摘要行：运行中显示参数摘要，结束后显示结果摘要（FR-014 不调用模型） */
const summary = computed(() => {
  if (props.card.status === 'running') {
    return props.card.paramsSummary || '准备执行…'
  }
  return props.card.resultSummary || props.card.paramsSummary
})

const expanded = ref(false)
/** 详情分区独立折叠（US3） */
const paramsOpen = ref(true)
const resultOpen = ref(true)

function toggle(): void {
  expanded.value = !expanded.value
  emit('toggle')
}

// ---- 内容整理渲染（FR-010~014；一律纯文本插值，禁止 HTML 执行 FR-015）----

/** 展示层二级渲染上限（FR-013） */
const RENDER_MAX_CHARS = 20000

/** 二进制启发式：含 NUL 或控制字符占比 >30% → 不渲染正文（FR-012） */
function isBinary(text: string): boolean {
  if (!text) {
    return false
  }
  if (text.includes('\u0000')) {
    return true
  }
  const sample = text.slice(0, 2000)
  let nonPrintable = 0
  let total = 0
  for (const ch of sample) {
    total++
    const code = ch.codePointAt(0) ?? 0
    if (code < 9 || (code > 13 && code < 32) || (code >= 127 && code < 160)) {
      nonPrintable++
    }
  }
  return total > 0 && nonPrintable / total > 0.3
}

/** 结构化内容：合法 JSON 对象/数组 → 格式化缩进（FR-010）；失败按纯文本 */
function tryFormatJson(text: string): string {
  const trimmed = text.trim()
  if (!trimmed.startsWith('{') && !trimmed.startsWith('[')) {
    return text
  }
  try {
    return JSON.stringify(JSON.parse(trimmed), null, 2)
  } catch {
    return text
  }
}

/** 正文渲染：格式化 + 二级截断（后端截断标记随原文展示，FR-011） */
function renderBody(text: string): string {
  const formatted = tryFormatJson(text)
  return formatted.length > RENDER_MAX_CHARS ? formatted.slice(0, RENDER_MAX_CHARS) : formatted
}

/** 二级截断提示（FR-013 明确提示未展示全部） */
function renderNote(text: string): string {
  const formatted = tryFormatJson(text)
  return formatted.length > RENDER_MAX_CHARS ? `未展示全部（共 ${formatted.length} 字符）` : ''
}

/** 二进制内容大小提示（FR-012 只报类型与大小） */
function sizeText(text: string): string {
  const bytes = new TextEncoder().encode(text).length
  return bytes >= 1024 ? `${(bytes / 1024).toFixed(1)} KB` : `${bytes} B`
}
</script>

<template>
  <div class="tool-card" :class="[meta.cls, { 'tool-card-running': card.status === 'running' }]">
    <button type="button" class="tool-card-head" @click="toggle">
      <span class="tool-status" aria-label="状态">
        <span class="tool-status-icon" :class="{ spinning: card.status === 'running' }">{{ meta.icon }}</span>
        <span class="tool-status-text">{{ meta.text }}</span>
      </span>
      <span class="tool-title">{{ title }}</span>
      <span v-if="durationText" class="tool-duration">{{ durationText }}</span>
      <span class="tool-expand-hint">{{ expanded ? '收起' : '展开' }}</span>
    </button>
    <div class="tool-summary" :title="summary">{{ summary }}</div>
    <!-- 展开态：输入/结果独立折叠分区（FR-004；US3 内容整理） -->
    <div v-if="expanded" class="tool-detail">
      <div class="tool-section">
        <button type="button" class="tool-section-head" @click="paramsOpen = !paramsOpen">
          <span class="tool-section-caret">{{ paramsOpen ? '▾' : '▸' }}</span> 输入参数
        </button>
        <template v-if="paramsOpen">
          <div v-if="isBinary(card.paramsText)" class="tool-binary">
            二进制内容（约 {{ sizeText(card.paramsText) }}），类型未知
          </div>
          <pre v-else class="tool-body">{{ renderBody(card.paramsText) }}</pre>
          <div v-if="!isBinary(card.paramsText) && renderNote(card.paramsText)" class="tool-note">
            {{ renderNote(card.paramsText) }}
          </div>
        </template>
      </div>
      <div class="tool-section">
        <button type="button" class="tool-section-head" @click="resultOpen = !resultOpen">
          <span class="tool-section-caret">{{ resultOpen ? '▾' : '▸' }}</span> 执行结果
        </button>
        <template v-if="resultOpen">
          <div v-if="card.status === 'running'" class="tool-note">等待执行结果…</div>
          <div v-else-if="isBinary(card.resultText)" class="tool-binary">
            二进制内容（约 {{ sizeText(card.resultText) }}），类型未知
          </div>
          <pre v-else class="tool-body">{{ renderBody(card.resultText) }}</pre>
          <div v-if="card.status !== 'running' && !isBinary(card.resultText) && renderNote(card.resultText)" class="tool-note">
            {{ renderNote(card.resultText) }}
          </div>
        </template>
      </div>
    </div>
  </div>
</template>

<style scoped lang="scss">
.tool-card {
  margin: 8px 0;
  border: 1px solid var(--border);
  border-radius: 10px;
  background: var(--bg-surface);
  overflow: hidden;
}

.tool-card-head {
  display: flex;
  align-items: center;
  gap: 8px;
  width: 100%;
  border: none;
  background: transparent;
  padding: 7px 10px;
  cursor: pointer;
  font-size: 13px;
  text-align: left;
}

.tool-status {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  font-size: 12.5px;
  font-weight: 600;
  flex-shrink: 0;
}

.tool-status-icon {
  display: inline-block;
  width: 14px;
  text-align: center;

  &.spinning {
    animation: tool-spin 1s linear infinite;
  }
}

@keyframes tool-spin {
  to {
    transform: rotate(360deg);
  }
}

.tool-title {
  color: var(--text-primary);
  font-weight: 600;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.tool-duration {
  color: var(--text-tertiary);
  font-size: 12px;
  flex-shrink: 0;
}

.tool-expand-hint {
  margin-left: auto;
  color: var(--text-tertiary);
  font-size: 12px;
  flex-shrink: 0;
}

.tool-summary {
  padding: 0 10px 7px;
  color: var(--text-tertiary);
  font-size: 12.5px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

/* 展开态详情（US3） */
.tool-detail {
  border-top: 1px solid var(--border);
  padding: 4px 10px 8px;
}

.tool-section {
  margin-top: 4px;
}

.tool-section-head {
  border: none;
  background: transparent;
  padding: 3px 0;
  font-size: 12.5px;
  font-weight: 600;
  color: var(--text-secondary);
  cursor: pointer;
}

.tool-section-caret {
  display: inline-block;
  width: 12px;
  color: var(--text-tertiary);
}

.tool-body {
  margin: 2px 0 0;
  padding: 6px 8px;
  border: 1px solid var(--border);
  border-radius: 6px;
  background: var(--bg-base);
  font-family: var(--font-mono);
  font-size: 12.5px;
  line-height: 1.5;
  color: var(--text-secondary);
  white-space: pre-wrap;
  word-break: break-word;
  max-height: 320px;
  overflow-y: auto;
}

.tool-binary {
  margin-top: 2px;
  padding: 6px 8px;
  border: 1px dashed var(--border);
  border-radius: 6px;
  background: var(--bg-base);
  color: var(--text-tertiary);
  font-size: 12.5px;
}

.tool-note {
  margin-top: 2px;
  color: var(--text-tertiary);
  font-size: 12px;
}

/* 状态配色：文字+图标区分，非仅颜色（FR-027） */
.st-success .tool-status {
  color: var(--success);
}

.st-error .tool-status {
  color: var(--danger);
}

.st-cancelled .tool-status {
  color: var(--text-tertiary);
}

.st-unknown .tool-status {
  color: var(--warning);
}

.st-running .tool-status {
  color: var(--accent);
}

.tool-card-running {
  border-style: dashed;
}
</style>
