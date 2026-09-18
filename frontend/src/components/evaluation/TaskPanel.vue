<script setup lang="ts">
/**
 * 任务面板（specs/012 US2，FR-004~008）：任务列表 + 创建（快照固化）+ 删除 + 发起评测。
 */
import { computed, onMounted, ref } from 'vue'
import { Button, Empty, Modal, Select, Table, Tag, message } from 'ant-design-vue'
import type { TableColumnsType } from 'ant-design-vue'

import { agentsApi, type AgentListItem } from '@/api/agents'
import { modelsApi, type ModelItem } from '@/api/models'
import {
  createEvalTask,
  deleteEvalTask,
  EVALUATOR_TYPES,
  getEvalTask,
  listDatasets,
  listEvalTasks,
  startEvalRun,
  type Dataset,
  type EvalTask,
  type EvaluatorType,
} from '@/api/evaluation'

const emit = defineEmits<{ (e: 'goto-runs', taskId: number): void }>()

const items = ref<EvalTask[]>([])
const loading = ref(false)
const agents = ref<AgentListItem[]>([])
const datasets = ref<Dataset[]>([])
const models = ref<ModelItem[]>([])

// 创建模态
const createOpen = ref(false)
const formName = ref('')
const formAgentId = ref<number | null>(null)
const formDatasetId = ref<number | null>(null)
const formEvaluatorType = ref<EvaluatorType>('exact_match')
const formModelId = ref<number | null>(null)
const formThreshold = ref(80)

// 快照查看
const snapshotOpen = ref(false)
const snapshotTask = ref<EvalTask | null>(null)
const snapshotText = ref('')

const columns: TableColumnsType = [
  { title: '任务', dataIndex: 'name', key: 'name', ellipsis: true },
  { title: 'Agent', dataIndex: 'agent_name', key: 'agent_name', width: 130, ellipsis: true },
  { title: '数据集', dataIndex: 'dataset_name', key: 'dataset_name', width: 130, ellipsis: true },
  { title: '评分器', key: 'evaluator_type', width: 100 },
  { title: '阈值', dataIndex: 'pass_threshold', key: 'pass_threshold', width: 70 },
  { title: 'Case 数', dataIndex: 'case_count', key: 'case_count', width: 80 },
  { title: '最近运行', key: 'last_run', width: 100 },
  { title: '操作', key: 'actions', width: 250 },
]

const canSubmitCreate = computed(
  () =>
    formName.value.trim().length > 0 &&
    formAgentId.value != null &&
    formDatasetId.value != null &&
    (formEvaluatorType.value === 'exact_match' || formModelId.value != null),
)

async function refresh(): Promise<void> {
  loading.value = true
  try {
    items.value = await listEvalTasks()
  } finally {
    loading.value = false
  }
}

async function openCreate(): Promise<void> {
  formName.value = ''
  formAgentId.value = null
  formDatasetId.value = null
  formEvaluatorType.value = 'exact_match'
  formModelId.value = null
  formThreshold.value = 80
  const [agentList, datasetList, modelList] = await Promise.all([
    agentsApi.list(),
    listDatasets(),
    modelsApi.list(),
  ])
  agents.value = agentList
  datasets.value = datasetList
  models.value = modelList
  createOpen.value = true
}

async function submitCreate(): Promise<void> {
  if (!canSubmitCreate.value) {
    message.warning('请完整填写任务配置')
    return
  }
  try {
    const task = await createEvalTask({
      name: formName.value.trim(),
      agent_id: formAgentId.value!,
      dataset_id: formDatasetId.value!,
      evaluator_type: formEvaluatorType.value,
      evaluator_config:
        formEvaluatorType.value === 'llm_judge'
          ? { model_model_id: formModelId.value! }
          : {},
      pass_threshold: formThreshold.value,
    })
    message.success(`任务已创建，三快照已固化（${task.case_count} 个 Case）`)
    createOpen.value = false
    await refresh()
  } catch (error) {
    message.error((error as { message?: string }).message ?? '创建失败', 6)
  }
}

function confirmDelete(row: EvalTask): void {
  Modal.confirm({
    title: `删除任务「${row.name}」？`,
    content: '将同时删除该任务的全部评测运行记录。',
    okText: '删除',
    okType: 'danger',
    cancelText: '取消',
    async onOk() {
      await deleteEvalTask(row.id)
      message.success('已删除')
      await refresh()
    },
  })
}

async function startRun(row: EvalTask): Promise<void> {
  try {
    const run = await startEvalRun(row.id)
    message.success(`评测已发起（运行 #${run.id}）`)
    emit('goto-runs', row.id)
  } catch (error) {
    message.error((error as { message?: string }).message ?? '发起失败', 6)
  }
}

async function openSnapshots(row: EvalTask): Promise<void> {
  const detail = await getEvalTask(row.id)
  snapshotTask.value = detail
  snapshotText.value = JSON.stringify(
    {
      agent_snapshot: detail.agent_snapshot ?? null,
      dataset_snapshot: detail.dataset_snapshot ?? null,
      evaluator_snapshot: detail.evaluator_snapshot ?? null,
    },
    null,
    2,
  )
  snapshotOpen.value = true
}

function evaluatorLabel(type: string): string {
  return type === 'llm_judge' ? 'LLM 评分' : '精确匹配'
}

function formatDateTime(iso: string): string {
  const date = new Date(iso)
  if (Number.isNaN(date.getTime())) return iso
  return date.toLocaleString('zh-CN', {
    month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', hour12: false,
  })
}

onMounted(() => {
  void refresh()
})

defineExpose({ refresh })
</script>

<template>
  <div class="task-panel">
    <div class="panel-toolbar">
      <Button type="primary" @click="openCreate">新建评测任务</Button>
    </div>

    <Empty v-if="!loading && items.length === 0" description="还没有评测任务" />
    <Table
      v-else
      :columns="columns"
      :data-source="items"
      :loading="loading"
      :pagination="false"
      row-key="id"
      size="middle"
    >
      <template #bodyCell="{ column, record }">
        <template v-if="column.key === 'evaluator_type'">
          <Tag>{{ evaluatorLabel((record as EvalTask).evaluator_type) }}</Tag>
        </template>
        <template v-else-if="column.key === 'last_run'">
          <Tag v-if="(record as EvalTask).last_run_status" :color="record.last_run_status === 'completed' ? 'success' : record.last_run_status === 'running' ? 'processing' : 'default'">
            {{ (record as EvalTask).last_run_status }}
          </Tag>
          <span v-else class="muted">未运行</span>
        </template>
        <template v-else-if="column.key === 'actions'">
          <Button type="primary" size="small" @click="startRun(record as EvalTask)">发起评测</Button>
          <Button type="link" size="small" @click="openSnapshots(record as EvalTask)">查看快照</Button>
          <Button type="link" size="small" danger @click="confirmDelete(record as EvalTask)">删除</Button>
        </template>
      </template>
    </Table>

    <!-- 创建模态 -->
    <Modal
      v-model:open="createOpen"
      title="新建评测任务"
      ok-text="创建"
      cancel-text="取消"
      @ok="submitCreate"
    >
      <div class="form-field">
        <label class="form-label">任务名称</label>
        <input v-model="formName" class="form-input" placeholder="例如：客服 Agent 基线评测" />
      </div>
      <div class="form-field">
        <label class="form-label">被测 Agent</label>
        <Select
          :value="formAgentId ?? undefined"
          placeholder="选择 Agent"
          style="width: 100%"
          :options="agents.map((a) => ({ value: a.id, label: a.name }))"
          @change="(v: unknown) => (formAgentId = (v as number) ?? null)"
        />
      </div>
      <div class="form-field">
        <label class="form-label">评测数据集</label>
        <Select
          :value="formDatasetId ?? undefined"
          placeholder="选择数据集"
          style="width: 100%"
          :options="datasets.map((d) => ({ value: d.id, label: `${d.name}（${d.case_count} Case）` }))"
          @change="(v: unknown) => (formDatasetId = (v as number) ?? null)"
        />
      </div>
      <div class="form-field">
        <label class="form-label">评分器</label>
        <Select
          :value="formEvaluatorType"
          style="width: 100%"
          :options="EVALUATOR_TYPES.map((t) => ({ value: t, label: evaluatorLabel(t) }))"
          @change="(v: unknown) => (formEvaluatorType = v as EvaluatorType)"
        />
      </div>
      <div v-if="formEvaluatorType === 'llm_judge'" class="form-field">
        <label class="form-label">评分模型</label>
        <Select
          :value="formModelId ?? undefined"
          placeholder="用于自动评分的模型"
          style="width: 100%"
          :options="models.map((m) => ({ value: m.id, label: m.display_name }))"
          @change="(v: unknown) => (formModelId = (v as number) ?? null)"
        />
      </div>
      <div class="form-field">
        <label class="form-label">通过阈值（0–100）</label>
        <input v-model.number="formThreshold" class="form-input" type="number" min="0" max="100" />
      </div>
      <p class="form-hint">创建时将固化 Agent / 数据集 / 评分器三类配置快照，历史评测可复现。</p>
    </Modal>

    <!-- 快照查看 -->
    <Modal
      v-model:open="snapshotOpen"
      :title="`配置快照 — ${snapshotTask?.name ?? ''}`"
      :footer="null"
      :width="680"
    >
      <pre class="snapshot-pre">{{ snapshotText }}</pre>
    </Modal>
  </div>
</template>

<style scoped lang="scss">
@use '@/styles/tokens' as *;

.panel-toolbar {
  display: flex;
  justify-content: flex-end;
  margin-bottom: var(--space-3, 12px);
}

.muted {
  color: var(--text-tertiary);
  font-size: 12.5px;
}

.form-field {
  display: flex;
  flex-direction: column;
  gap: 4px;
  margin-bottom: 12px;
}

.form-label {
  font-size: 12.5px;
  color: var(--text-secondary);
}

.form-input {
  border: 1px solid var(--border);
  border-radius: 6px;
  padding: 6px 10px;
  font-size: 14px;
  color: var(--text-primary);
  background: var(--bg-surface);
  font-family: var(--font-body);

  &:focus {
    outline: none;
    border-color: var(--accent);
  }
}

.form-hint {
  font-size: 12px;
  color: var(--text-tertiary);
  margin: 0;
}

.snapshot-pre {
  max-height: 480px;
  overflow: auto;
  font-size: 12px;
  font-family: var(--font-mono);
  background: var(--bg-subtle, var(--bg-surface));
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 12px;
}
</style>
