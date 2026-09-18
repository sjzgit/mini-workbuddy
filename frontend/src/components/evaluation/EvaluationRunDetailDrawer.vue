<script setup lang="ts">
/**
 * 评测运行详情抽屉（specs/012 US4，FR-020/FR-030）：汇总指标 + CaseRun 列表 + AgentRun 下钻。
 * 「查看 Agent 运行」复用运行记录页抽屉（路由 /runs?run_id=），不新建第二套轨迹查看器。
 */
import { computed, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { Button, Drawer, Empty, Spin, Tag } from 'ant-design-vue'

import {
  CASE_RUN_STATUS_META,
  EVAL_RUN_STATUS_META,
  getEvalRun,
  listEvalRunCases,
  type CaseRun,
  type EvalRun,
} from '@/api/evaluation'

const props = defineProps<{ open: boolean; run: EvalRun | null }>()
const emit = defineEmits<{ (e: 'update:open', value: boolean): void; (e: 'retry', caseRunId: number): void }>()

const router = useRouter()
const runDetail = ref<EvalRun | null>(null)
const caseRuns = ref<CaseRun[]>([])
const loading = ref(false)

// Case 明细展开
const expandedCase = ref<CaseRun | null>(null)

const summaryCards = computed(() => {
  const run = runDetail.value
  if (!run) return []
  return [
    { label: '总 Case', value: run.total_cases },
    { label: '已完成', value: `${run.completed_cases}/${run.total_cases}` },
    { label: '通过', value: run.passed_cases },
    { label: '未通过', value: run.failed_cases },
    { label: '执行失败', value: run.execution_failed_cases },
    { label: '评分失败', value: run.judge_failed_cases },
    { label: '平均分', value: run.average_score ?? '—' },
    { label: '通过率', value: run.pass_rate != null ? `${run.pass_rate}%` : '—' },
    { label: '总时长', value: formatDuration(run.total_duration_ms) },
    { label: '总 Token', value: run.total_tokens ?? '未知' },
  ]
})

watch(
  () => [props.open, props.run?.id] as const,
  async ([open]) => {
    if (open && props.run) {
      loading.value = true
      try {
        runDetail.value = await getEvalRun(props.run.id)
        caseRuns.value = await listEvalRunCases(props.run.id)
      } finally {
        loading.value = false
      }
      expandedCase.value = null
    }
  },
)

function retryable(c: CaseRun): boolean {
  return ['execution_failed', 'judge_failed', 'failed', 'cancelled'].includes(c.status)
}

function viewAgentRun(c: CaseRun): void {
  if (!c.agent_run_id) return
  // 复用运行记录页的详情抽屉（FR-030）
  void router.push({ path: '/runs', query: { run_id: c.agent_run_id } })
  emit('update:open', false)
}

function formatDuration(ms: number | null): string {
  if (ms == null) return '—'
  if (ms < 1000) return `${ms} ms`
  return `${(ms / 1000).toFixed(1)} s`
}
</script>

<template>
  <Drawer
    :open="props.open"
    :title="runDetail ? `评测运行 #${runDetail.id}` : '评测运行'"
    width="760"
    @close="emit('update:open', false)"
  >
    <Spin :spinning="loading">
      <div v-if="runDetail" class="run-detail">
        <div class="status-line">
          <Tag :color="EVAL_RUN_STATUS_META[runDetail.status].color">
            {{ EVAL_RUN_STATUS_META[runDetail.status].text }}
          </Tag>
          <span v-if="runDetail.interrupted_reason" class="interrupted-reason">
            {{ runDetail.interrupted_reason }}
          </span>
        </div>

        <div class="summary-grid">
          <div v-for="card in summaryCards" :key="card.label" class="summary-card">
            <span class="summary-value">{{ card.value }}</span>
            <span class="summary-label">{{ card.label }}</span>
          </div>
        </div>

        <h3 class="cases-title">用例明细</h3>
        <Empty v-if="caseRuns.length === 0" description="没有用例运行记录" />
        <div v-else class="case-list">
          <div v-for="c in caseRuns" :key="c.id" class="case-item">
            <div class="case-head" @click="expandedCase = expandedCase?.id === c.id ? null : c">
              <span class="case-index">#{{ (c.case_index ?? 0) + 1 }}</span>
              <span class="case-question">{{ c.snapshot_case?.user_question ?? `Case ${c.dataset_case_id}` }}</span>
              <Tag :color="CASE_RUN_STATUS_META[c.status].color">
                {{ CASE_RUN_STATUS_META[c.status].text }}
              </Tag>
              <span v-if="c.score != null" class="case-score" :class="{ low: c.score < (runDetail?.average_score ?? 60) }">
                {{ c.score }} 分
              </span>
              <span v-if="c.attempt > 1" class="attempt-badge">重试 ×{{ c.attempt - 1 }}</span>
            </div>

            <div v-if="expandedCase?.id === c.id" class="case-body">
              <div v-if="c.snapshot_case" class="case-section">
                <p v-if="c.snapshot_case.expected_answer" class="case-line">
                  <b>参考答案：</b>{{ c.snapshot_case.expected_answer }}
                </p>
                <p v-if="c.snapshot_case.scoring_criteria" class="case-line">
                  <b>评分标准：</b>{{ c.snapshot_case.scoring_criteria }}
                </p>
              </div>
              <p v-if="c.reason" class="case-line"><b>评分理由：</b>{{ c.reason }}</p>
              <p v-if="c.error_message" class="case-line error-line">
                <b>错误：</b>{{ c.error_message }}
              </p>
              <div class="case-metrics">
                <span>耗时 {{ formatDuration(c.duration_ms) }}</span>
                <span>Token {{ c.total_tokens ?? '未知' }}</span>
                <span>模型调用 {{ c.model_call_count ?? '—' }}</span>
                <span>工具调用 {{ c.tool_call_count ?? '—' }}</span>
                <span>循环 {{ c.iteration_count ?? '—' }}</span>
              </div>
              <div class="case-actions">
                <Button
                  v-if="c.agent_run_id"
                  type="link"
                  size="small"
                  @click="viewAgentRun(c)"
                >查看 Agent 运行</Button>
                <Button
                  v-if="retryable(c)"
                  type="link"
                  size="small"
                  @click="emit('retry', c.id)"
                >重试</Button>
              </div>
            </div>
          </div>
        </div>
      </div>
    </Spin>
  </Drawer>
</template>

<style scoped lang="scss">
@use '@/styles/tokens' as *;

.status-line {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 12px;
}

.interrupted-reason {
  font-size: 12.5px;
  color: var(--text-secondary);
}

.summary-grid {
  display: grid;
  grid-template-columns: repeat(5, 1fr);
  gap: 8px;
  margin-bottom: 16px;
}

.summary-card {
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 10px 8px;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 2px;
  background: var(--bg-surface);
}

.summary-value {
  font-size: 16px;
  font-weight: 600;
  color: var(--text-primary);
  font-family: var(--font-display);
}

.summary-label {
  font-size: 12px;
  color: var(--text-tertiary);
}

.cases-title {
  font-size: 14px;
  font-weight: 600;
  color: var(--text-primary);
  margin: 0 0 8px;
}

.case-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.case-item {
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 10px 12px;
  background: var(--bg-surface);
}

.case-head {
  display: flex;
  align-items: center;
  gap: 8px;
  cursor: pointer;
}

.case-index {
  color: var(--text-tertiary);
  font-size: 12.5px;
  flex-shrink: 0;
}

.case-question {
  flex: 1;
  font-size: 13.5px;
  color: var(--text-primary);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.case-score {
  font-size: 13px;
  font-weight: 600;
  color: var(--success);

  &.low {
    color: var(--danger);
  }
}

.attempt-badge {
  font-size: 12px;
  color: var(--warning);
  flex-shrink: 0;
}

.case-body {
  margin-top: 8px;
  padding-top: 8px;
  border-top: 1px dashed var(--border);
}

.case-section {
  margin-bottom: 4px;
}

.case-line {
  margin: 4px 0;
  font-size: 12.5px;
  color: var(--text-secondary);
  line-height: 1.5;

  b {
    color: var(--text-primary);
  }
}

.error-line {
  color: var(--danger);
}

.case-metrics {
  display: flex;
  flex-wrap: wrap;
  gap: 12px;
  margin: 8px 0 4px;
  font-size: 12px;
  color: var(--text-tertiary);
}

.case-actions {
  display: flex;
  justify-content: flex-end;
  gap: 4px;
}
</style>
