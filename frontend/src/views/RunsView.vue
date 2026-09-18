<script setup lang="ts">
/**
 * 运行记录页面（specs/011 US2/US3）：列表 + 筛选 + 后端分页 + 详情抽屉。
 * 展示字段全部来自 runs 行快照（恒定查询次数由后端保证，SC-003）；
 * Token 未知显示"未知"而非 0，无正文输出显示"无正文输出"（FR-015）。
 */
import { onMounted, ref } from 'vue'
import { useRoute } from 'vue-router'

import { Alert, Button, Empty, Select, Table, Tag } from 'ant-design-vue'
import type { TableColumnsType } from 'ant-design-vue'

import {
  RUN_STATUSES,
  RUN_STATUS_META,
  type RunStatus,
  type RunSummary,
} from '@/api/runs'
import { MODULES } from '@/router/modules'
import { useAgentsStore } from '@/stores/agents'
import { useRunsStore } from '@/stores/runs'
import RunDetailDrawer from '@/components/runs/RunDetailDrawer.vue'

const meta = MODULES.find((m) => m.path === 'runs')!
const store = useRunsStore()
const agentsStore = useAgentsStore()
const route = useRoute()

// 会话入口：/runs?conversation_id=N 预置筛选
const conversationFilter = ref<number | null>(null)

const columns: TableColumnsType = [
  { title: '状态', key: 'status', width: 96 },
  { title: 'Agent', dataIndex: 'agent_name', key: 'agent_name', width: 140, ellipsis: true },
  { title: '模型', dataIndex: 'model_name', key: 'model_name', width: 140, ellipsis: true },
  { title: '开始时间', key: 'started_at', width: 150 },
  { title: '总耗时', key: 'total_duration_ms', width: 90 },
  { title: '模型调用', dataIndex: 'model_call_count', key: 'model_call_count', width: 90 },
  { title: '工具调用', dataIndex: 'tool_call_count', key: 'tool_call_count', width: 90 },
  { title: 'Token 用量', key: 'tokens', width: 110 },
  { title: '错误摘要', dataIndex: 'error_summary', key: 'error_summary', ellipsis: true },
]

function formatDateTime(iso: string): string {
  const date = new Date(iso)
  if (Number.isNaN(date.getTime())) return iso
  return date.toLocaleString('zh-CN', {
    month: '2-digit', day: '2-digit',
    hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false,
  })
}

function formatDuration(ms: number | null): string {
  if (ms == null) return '—'
  if (ms < 1000) return `${ms} ms`
  return `${(ms / 1000).toFixed(1)} s`
}

function onStatusChange(value: unknown): void {
  void store.fetchList({ status: (value as RunStatus | undefined) ?? undefined })
}

function onAgentChange(value: unknown): void {
  void store.fetchList({ agent_id: (value as number | undefined) ?? undefined })
}

function onTableChange(pagination: { current?: number; pageSize?: number }): void {
  store.setPage(pagination.current ?? 1, pagination.pageSize ?? 20)
}

// ---- 详情抽屉 ----
const drawerOpen = ref(false)
const detailRunId = ref<string | null>(null)

function openDetail(row: RunSummary): void {
  detailRunId.value = row.run_id
  drawerOpen.value = true
}

onMounted(() => {
  const raw = route.query.conversation_id
  const parsed = typeof raw === 'string' ? Number(raw) : Number.NaN
  if (Number.isInteger(parsed) && parsed > 0) conversationFilter.value = parsed
  void store.fetchList(
    conversationFilter.value != null ? { conversation_id: conversationFilter.value } : {},
  )
  void agentsStore.fetchAgents()
  // 评测 Case 明细下钻入口（specs/012 FR-030）：/runs?run_id=xxx 直开详情抽屉
  const runIdRaw = route.query.run_id
  if (typeof runIdRaw === 'string' && runIdRaw) {
    detailRunId.value = runIdRaw
    drawerOpen.value = true
  }
})
</script>

<template>
  <div class="page">
    <header class="page__header">
      <div>
        <h1 class="page__title">{{ meta.title }}</h1>
        <p class="page__desc">{{ meta.description }}</p>
      </div>
    </header>

    <Alert v-if="store.error" type="error" :message="store.error" show-icon class="runs-alert" />

    <div class="runs-toolbar">
      <Select
        placeholder="全部状态"
        allow-clear
        style="width: 140px"
        :value="store.filters.status ?? undefined"
        :options="RUN_STATUSES.map((s) => ({ value: s, label: RUN_STATUS_META[s].text }))"
        @change="onStatusChange"
      />
      <Select
        placeholder="全部 Agent"
        allow-clear
        style="width: 180px"
        :value="store.filters.agent_id ?? undefined"
        :options="agentsStore.items.map((a) => ({ value: a.id, label: a.name }))"
        @change="onAgentChange"
      />
      <Tag v-if="conversationFilter != null" color="blue" closable @close.prevent>
        会话 #{{ conversationFilter }}
      </Tag>
      <span class="runs-toolbar__spacer"></span>
      <Button @click="() => store.fetchList()">刷新</Button>
    </div>

    <div class="card">
      <Table
        :columns="columns"
        :data-source="store.items"
        :loading="store.loading"
        :pagination="{
          current: store.page,
          pageSize: store.pageSize,
          total: store.total,
          showSizeChanger: true,
          pageSizeOptions: ['10', '20', '50'],
          showTotal: (t: number) => `共 ${t} 条`,
        }"
        row-key="run_id"
        size="middle"
        :custom-row="(row: RunSummary) => ({ class: 'runs-row', onClick: () => openDetail(row) })"
        @change="onTableChange"
      >
        <template #bodyCell="{ column, record }">
          <template v-if="column.key === 'status'">
            <Tag :color="RUN_STATUS_META[record.status as RunStatus].color">
              {{ RUN_STATUS_META[record.status as RunStatus].text }}
            </Tag>
          </template>
          <template v-else-if="column.key === 'started_at'">
            <span class="cell-time">{{ formatDateTime(record.started_at) }}</span>
          </template>
          <template v-else-if="column.key === 'total_duration_ms'">
            {{ formatDuration(record.total_duration_ms) }}
          </template>
          <template v-else-if="column.key === 'tokens'">
            <span v-if="record.total_tokens == null" class="cell-muted">未知</span>
            <span v-else>{{ record.total_tokens }}</span>
          </template>
          <template v-else-if="column.key === 'error_summary'">
            <span v-if="record.error_summary" class="cell-error">{{ record.error_summary }}</span>
            <span v-else class="cell-muted">—</span>
          </template>
        </template>
        <template #emptyText>
          <Empty :image="Empty.PRESENTED_IMAGE_SIMPLE" description="暂无运行记录" />
        </template>
      </Table>
    </div>

    <RunDetailDrawer v-model:open="drawerOpen" :run-id="detailRunId" />
  </div>
</template>

<style scoped lang="scss">
.runs-alert { margin-bottom: 12px; }

.runs-toolbar {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 12px;

  &__spacer { flex: 1; }
}

:deep(.runs-row) {
  cursor: pointer;

  &:hover { background: var(--bg-hover, rgba(0, 0, 0, 0.03)); }
}

.cell-time { font-size: 13px; color: var(--text-secondary); }
.cell-muted { color: var(--text-tertiary); }
.cell-error { color: var(--danger); font-size: 12.5px; }
</style>
