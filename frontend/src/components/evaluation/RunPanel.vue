<script setup lang="ts">
/**
 * 运行面板（specs/012 US3/US5，FR-020/024/025）：运行列表 + 进度/汇总 + 控制 + 轮询。
 * 轮询仅在存在活跃运行（pending/running/paused）时开启。
 */
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { Button, Empty, Select, Table, Tag, message } from 'ant-design-vue'
import type { TableColumnsType } from 'ant-design-vue'

import {
  cancelEvalRun,
  EVAL_RUN_STATUSES,
  EVAL_RUN_STATUS_META,
  listEvalRuns,
  pauseEvalRun,
  resumeEvalRun,
  retryEvalRunCase,
  type EvalRun,
  type EvalRunStatus,
} from '@/api/evaluation'
import EvaluationRunDetailDrawer from './EvaluationRunDetailDrawer.vue'

const items = ref<EvalRun[]>([])
const total = ref(0)
const page = ref(1)
const pageSize = ref(20)
const loading = ref(false)
const statusFilter = ref<EvalRunStatus | undefined>(undefined)

// 详情抽屉
const detailOpen = ref(false)
const detailRun = ref<EvalRun | null>(null)

let pollTimer: number | null = null

const columns: TableColumnsType = [
  { title: '状态', key: 'status', width: 96 },
  { title: '进度', key: 'progress', width: 110 },
  { title: '通过', dataIndex: 'passed_cases', key: 'passed_cases', width: 70 },
  { title: '未通过', dataIndex: 'failed_cases', key: 'failed_cases', width: 70 },
  { title: '执行失败', dataIndex: 'execution_failed_cases', key: 'execution_failed_cases', width: 84 },
  { title: '评分失败', dataIndex: 'judge_failed_cases', key: 'judge_failed_cases', width: 84 },
  { title: '平均分', key: 'average_score', width: 80 },
  { title: '通过率', key: 'pass_rate', width: 80 },
  { title: 'Token', dataIndex: 'total_tokens', key: 'total_tokens', width: 90 },
  { title: '操作', key: 'actions', width: 170 },
]

const hasActive = computed(() =>
  items.value.some((r) => ['pending', 'running', 'paused'].includes(r.status)),
)

async function refresh(): Promise<void> {
  loading.value = true
  try {
    const result = await listEvalRuns({
      status: statusFilter.value,
      page: page.value,
      page_size: pageSize.value,
    })
    items.value = result.items
    total.value = result.total
  } finally {
    loading.value = false
  }
}

function ensurePolling(): void {
  if (pollTimer != null) return
  pollTimer = window.setInterval(() => {
    if (hasActive.value && !document.hidden) void refresh()
  }, 3000)
}

onMounted(() => {
  void refresh().then(ensurePolling)
})

onBeforeUnmount(() => {
  if (pollTimer != null) window.clearInterval(pollTimer)
})

function onStatusChange(value: unknown): void {
  statusFilter.value = (value as EvalRunStatus | undefined) ?? undefined
  page.value = 1
  void refresh()
}

function onTableChange(pag: { current?: number; pageSize?: number }): void {
  page.value = pag.current ?? 1
  pageSize.value = pag.pageSize ?? 20
  void refresh()
}

async function control(
  row: EvalRun,
  action: 'pause' | 'resume' | 'cancel',
): Promise<void> {
  try {
    if (action === 'pause') await pauseEvalRun(row.id)
    else if (action === 'resume') await resumeEvalRun(row.id)
    else await cancelEvalRun(row.id)
    await refresh()
  } catch (error) {
    message.error((error as { message?: string }).message ?? '操作失败', 6)
  }
}

async function retry(row: EvalRun, caseRunId: number): Promise<void> {
  try {
    await retryEvalRunCase(row.id, caseRunId)
    message.success('已创建重试用例')
    await refresh()
  } catch (error) {
    message.error((error as { message?: string }).message ?? '重试失败', 6)
  }
}

defineExpose({ retry, refresh })

function openDetail(row: EvalRun): void {
  detailRun.value = row
  detailOpen.value = true
}

function formatDuration(ms: number | null): string {
  if (ms == null) return '—'
  if (ms < 1000) return `${ms} ms`
  return `${(ms / 1000).toFixed(1)} s`
}
</script>

<template>
  <div class="run-panel">
    <div class="panel-toolbar">
      <Select
        placeholder="全部状态"
        allow-clear
        style="width: 140px"
        :value="statusFilter"
        :options="EVAL_RUN_STATUSES.map((s) => ({ value: s, label: EVAL_RUN_STATUS_META[s].text }))"
        @change="onStatusChange"
      />
    </div>

    <Empty v-if="!loading && items.length === 0" description="还没有评测运行" />
    <Table
      v-else
      :columns="columns"
      :data-source="items"
      :loading="loading"
      :pagination="{
        current: page,
        pageSize: pageSize,
        total: total,
        showSizeChanger: true,
        showTotal: (t: number) => `共 ${t} 条`,
      }"
      row-key="id"
      size="middle"
      :custom-row="(row: EvalRun) => ({ class: 'run-row', onClick: () => openDetail(row) })"
      @change="onTableChange"
    >
      <template #bodyCell="{ column, record }">
        <template v-if="column.key === 'status'">
          <Tag :color="EVAL_RUN_STATUS_META[(record as EvalRun).status].color">
            {{ EVAL_RUN_STATUS_META[(record as EvalRun).status].text }}
          </Tag>
        </template>
        <template v-else-if="column.key === 'progress'">
          {{ (record as EvalRun).completed_cases }}/{{ (record as EvalRun).total_cases }}
        </template>
        <template v-else-if="column.key === 'average_score'">
          {{ (record as EvalRun).average_score ?? '—' }}
        </template>
        <template v-else-if="column.key === 'pass_rate'">
          {{ (record as EvalRun).pass_rate != null ? `${record.pass_rate}%` : '—' }}
        </template>
        <template v-else-if="column.key === 'total_tokens'">
          {{ (record as EvalRun).total_tokens ?? '未知' }}
        </template>
        <template v-else-if="column.key === 'actions'">
          <template v-if="(record as EvalRun).status === 'running'">
            <Button type="link" size="small" @click.stop="control(record as EvalRun, 'pause')">暂停</Button>
            <Button type="link" size="small" danger @click.stop="control(record as EvalRun, 'cancel')">取消</Button>
          </template>
          <Button
            v-else-if="(record as EvalRun).status === 'paused'"
            type="link"
            size="small"
            @click.stop="control(record as EvalRun, 'resume')"
          >恢复</Button>
          <Button
            v-else-if="['pending', 'paused'].includes((record as EvalRun).status)"
            type="link"
            size="small"
            danger
            @click.stop="control(record as EvalRun, 'cancel')"
          >取消</Button>
          <Button type="link" size="small" @click.stop="openDetail(record as EvalRun)">详情</Button>
        </template>
      </template>
    </Table>

    <EvaluationRunDetailDrawer
      v-model:open="detailOpen"
      :run="detailRun"
      @retry="(...args: unknown[]) => retry(detailRun!, args[0] as number)"
    />
  </div>
</template>

<style scoped lang="scss">
@use '@/styles/tokens' as *;

.panel-toolbar {
  display: flex;
  justify-content: flex-end;
  margin-bottom: var(--space-3, 12px);
}

:deep(.run-row) {
  cursor: pointer;
}
</style>
