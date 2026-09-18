<script setup lang="ts">
/**
 * 数据集面板（specs/012 US1，FR-001~003）：列表 + 创建/编辑/删除 + Case 管理 + 导入导出。
 * 样式全部引用设计令牌（tokens.scss），不写裸色值（AGENTS.md §8）。
 */
import { onMounted, ref } from 'vue'
import { Button, Card, Empty, Modal, Table, Tag, message } from 'ant-design-vue'
import type { TableColumnsType } from 'ant-design-vue'

import {
  createDataset,
  deleteDataset,
  exportDatasetUrl,
  listDatasets,
  updateDataset,
  type Dataset,
} from '@/api/evaluation'
import DatasetCasesDrawer from './DatasetCasesDrawer.vue'

const items = ref<Dataset[]>([])
const loading = ref(false)

// 编辑模态
const editOpen = ref(false)
const editId = ref<number | null>(null)
const editName = ref('')
const editDescription = ref('')

// Case 抽屉
const casesOpen = ref(false)
const casesDataset = ref<Dataset | null>(null)

const columns: TableColumnsType = [
  { title: '名称', dataIndex: 'name', key: 'name', ellipsis: true },
  { title: '描述', dataIndex: 'description', key: 'description', ellipsis: true },
  { title: 'Case 数', dataIndex: 'case_count', key: 'case_count', width: 90 },
  { title: '更新时间', key: 'updated_at', width: 160 },
  { title: '操作', key: 'actions', width: 300 },
]

async function refresh(): Promise<void> {
  loading.value = true
  try {
    items.value = await listDatasets()
  } finally {
    loading.value = false
  }
}

function openCreate(): void {
  editId.value = null
  editName.value = ''
  editDescription.value = ''
  editOpen.value = true
}

function openEdit(row: Dataset): void {
  editId.value = row.id
  editName.value = row.name
  editDescription.value = row.description
  editOpen.value = true
}

async function submitEdit(): Promise<void> {
  const name = editName.value.trim()
  if (!name) {
    message.warning('数据集名称不能为空白')
    return
  }
  if (editId.value == null) {
    await createDataset({ name, description: editDescription.value })
    message.success('数据集已创建')
  } else {
    await updateDataset(editId.value, { name, description: editDescription.value })
    message.success('数据集已更新')
  }
  editOpen.value = false
  await refresh()
}

function confirmDelete(row: Dataset): void {
  Modal.confirm({
    title: `删除数据集「${row.name}」？`,
    content: '将同时删除其中全部评测用例；历史评测运行不受影响。',
    okText: '删除',
    okType: 'danger',
    cancelText: '取消',
    async onOk() {
      await deleteDataset(row.id)
      message.success('已删除')
      await refresh()
    },
  })
}

function openCases(row: Dataset): void {
  casesDataset.value = row
  casesOpen.value = true
}

function onCasesChanged(): void {
  void refresh()
}

function exportDataset(row: Dataset): void {
  window.open(exportDatasetUrl(row.id), '_blank')
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
  <div class="dataset-panel">
    <div class="panel-toolbar">
      <Button type="primary" @click="openCreate">新建数据集</Button>
    </div>

    <Empty v-if="!loading && items.length === 0" description="还没有评测数据集" />
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
        <template v-if="column.key === 'case_count'">
          <Tag>{{ (record as Dataset).case_count }}</Tag>
        </template>
        <template v-else-if="column.key === 'updated_at'">
          {{ formatDateTime((record as Dataset).updated_at) }}
        </template>
        <template v-else-if="column.key === 'actions'">
          <Button type="link" size="small" @click="openCases(record as Dataset)">用例管理</Button>
          <Button type="link" size="small" @click="openEdit(record as Dataset)">编辑</Button>
          <Button type="link" size="small" @click="exportDataset(record as Dataset)">导出</Button>
          <Button type="link" size="small" danger @click="confirmDelete(record as Dataset)">删除</Button>
        </template>
      </template>
    </Table>

    <!-- 创建/编辑模态 -->
    <Modal
      v-model:open="editOpen"
      :title="editId == null ? '新建数据集' : '编辑数据集'"
      ok-text="保存"
      cancel-text="取消"
      @ok="submitEdit"
    >
      <div class="form-field">
        <label class="form-label">名称</label>
        <input v-model="editName" class="form-input" placeholder="例如：客服评测集" />
      </div>
      <div class="form-field">
        <label class="form-label">描述</label>
        <textarea v-model="editDescription" class="form-textarea" rows="3" placeholder="可选" />
      </div>
    </Modal>

    <DatasetCasesDrawer
      v-model:open="casesOpen"
      :dataset="casesDataset"
      @changed="onCasesChanged"
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

.form-input,
.form-textarea {
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

.form-textarea {
  resize: vertical;
}
</style>
