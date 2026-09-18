<script setup lang="ts">
/**
 * 数据集用例抽屉（specs/012 US1，FR-002/003）：Case 列表 + 增删改 + JSON 导入导出。
 */
import { computed, ref, watch } from 'vue'
import { Button, Drawer, Empty, Modal, Tag, message } from 'ant-design-vue'

import {
  createDatasetCase,
  deleteDatasetCase,
  importDatasetCases,
  listDatasetCases,
  updateDatasetCase,
  type Dataset,
  type DatasetCase,
} from '@/api/evaluation'

const props = defineProps<{ open: boolean; dataset: Dataset | null }>()
const emit = defineEmits<{ (e: 'update:open', value: boolean): void; (e: 'changed'): void }>()

const cases = ref<DatasetCase[]>([])
const loading = ref(false)

// 编辑模态
const editOpen = ref(false)
const editId = ref<number | null>(null)
const editQuestion = ref('')
const editExpected = ref('')
const editCriteria = ref('')

// 导入模态
const importOpen = ref(false)
const importText = ref('')

const hasExpected = computed(() => cases.value.some((c) => c.expected_answer))

watch(
  () => [props.open, props.dataset?.id] as const,
  ([open]) => {
    if (open && props.dataset) void refresh()
  },
)

async function refresh(): Promise<void> {
  if (!props.dataset) return
  loading.value = true
  try {
    cases.value = await listDatasetCases(props.dataset.id)
  } finally {
    loading.value = false
  }
}

function openCreate(): void {
  editId.value = null
  editQuestion.value = ''
  editExpected.value = ''
  editCriteria.value = ''
  editOpen.value = true
}

function openEdit(row: DatasetCase): void {
  editId.value = row.id
  editQuestion.value = row.user_question
  editExpected.value = row.expected_answer ?? ''
  editCriteria.value = row.scoring_criteria ?? ''
  editOpen.value = true
}

async function submitEdit(): Promise<void> {
  if (!props.dataset) return
  const question = editQuestion.value.trim()
  if (!question) {
    message.warning('用户问题不能为空白')
    return
  }
  const payload = {
    user_question: question,
    expected_answer: editExpected.value.trim() || null,
    scoring_criteria: editCriteria.value.trim() || null,
  }
  if (editId.value == null) {
    await createDatasetCase(props.dataset.id, payload)
    message.success('用例已添加')
  } else {
    await updateDatasetCase(props.dataset.id, editId.value, payload)
    message.success('用例已更新')
  }
  editOpen.value = false
  await refresh()
  emit('changed')
}

function confirmDelete(row: DatasetCase): void {
  if (!props.dataset) return
  Modal.confirm({
    title: '删除该用例？',
    okText: '删除',
    okType: 'danger',
    cancelText: '取消',
    async onOk() {
      if (!props.dataset) return
      await deleteDatasetCase(props.dataset.id, row.id)
      message.success('已删除')
      await refresh()
      emit('changed')
    },
  })
}

async function submitImport(): Promise<void> {
  if (!props.dataset) return
  let payload: unknown
  try {
    payload = JSON.parse(importText.value)
  } catch {
    message.error('不是合法的 JSON')
    return
  }
  try {
    const result = await importDatasetCases(props.dataset.id, payload)
    message.success(`成功导入 ${result.imported_cases} 条用例`)
    importOpen.value = false
    importText.value = ''
    await refresh()
    emit('changed')
  } catch (error) {
    const detail = (error as { message?: string }).message ?? '导入失败'
    message.error(detail, 6)
  }
}

const drawerTitle = computed(() =>
  props.dataset ? `用例管理 — ${props.dataset.name}` : '用例管理',
)

defineExpose({ refresh })
</script>

<template>
  <Drawer
    :open="props.open"
    :title="drawerTitle"
    width="640"
    @close="emit('update:open', false)"
  >
    <div class="cases-toolbar">
      <Button type="primary" size="small" @click="openCreate">新增用例</Button>
      <Button size="small" @click="importOpen = true">JSON 导入</Button>
    </div>

    <Empty v-if="!loading && cases.length === 0" description="还没有用例" />
    <div v-else class="case-list">
      <div v-for="(row, index) in cases" :key="row.id" class="case-item">
        <div class="case-head">
          <span class="case-index">#{{ index + 1 }}</span>
          <span class="case-question">{{ row.user_question }}</span>
          <Tag v-if="row.expected_answer" class="case-tag">有参考答案</Tag>
        </div>
        <p v-if="row.expected_answer" class="case-line">参考：{{ row.expected_answer }}</p>
        <p v-if="row.scoring_criteria" class="case-line">标准：{{ row.scoring_criteria }}</p>
        <div class="case-actions">
          <Button type="link" size="small" @click="openEdit(row)">编辑</Button>
          <Button type="link" size="small" danger @click="confirmDelete(row)">删除</Button>
        </div>
      </div>
    </div>

    <!-- 用例编辑模态 -->
    <Modal
      v-model:open="editOpen"
      :title="editId == null ? '新增用例' : '编辑用例'"
      ok-text="保存"
      cancel-text="取消"
      @ok="submitEdit"
    >
      <div class="form-field">
        <label class="form-label">用户问题（必填）</label>
        <textarea v-model="editQuestion" class="form-textarea" rows="2" />
      </div>
      <div class="form-field">
        <label class="form-label">参考答案（可选）</label>
        <textarea v-model="editExpected" class="form-textarea" rows="2" />
      </div>
      <div class="form-field">
        <label class="form-label">评分标准（可选）</label>
        <textarea v-model="editCriteria" class="form-textarea" rows="2" />
      </div>
    </Modal>

    <!-- JSON 导入模态 -->
    <Modal
      v-model:open="importOpen"
      title="JSON 导入用例"
      ok-text="导入"
      cancel-text="取消"
      :width="560"
      @ok="submitImport"
    >
      <p class="import-hint">
        格式：<code>{ "name": "…", "cases": [{ "user_question": "…", "expected_answer": "…",
        "scoring_criteria": "…" }] }</code>；校验失败将整体拒绝导入。
      </p>
      <textarea v-model="importText" class="form-textarea import-text" rows="12" />
    </Modal>
  </Drawer>
</template>

<style scoped lang="scss">
@use '@/styles/tokens' as *;

.cases-toolbar {
  display: flex;
  gap: 8px;
  margin-bottom: 12px;
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
}

.case-index {
  color: var(--text-tertiary);
  font-size: 12.5px;
  flex-shrink: 0;
}

.case-question {
  font-size: 14px;
  color: var(--text-primary);
  flex: 1;
}

.case-tag {
  flex-shrink: 0;
}

.case-line {
  margin: 4px 0 0;
  font-size: 12.5px;
  color: var(--text-secondary);
}

.case-actions {
  margin-top: 4px;
  display: flex;
  justify-content: flex-end;
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

.form-textarea {
  border: 1px solid var(--border);
  border-radius: 6px;
  padding: 6px 10px;
  font-size: 13px;
  color: var(--text-primary);
  background: var(--bg-surface);
  font-family: var(--font-mono);
  resize: vertical;

  &:focus {
    outline: none;
    border-color: var(--accent);
  }
}

.import-hint {
  font-size: 12.5px;
  color: var(--text-secondary);
  margin-bottom: 8px;
}

.import-text {
  width: 100%;
}
</style>
