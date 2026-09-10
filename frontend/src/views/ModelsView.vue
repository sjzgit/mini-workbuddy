<script setup lang="ts">
/**
 * 模型管理页面：列表 + 空状态 + 新增/编辑/删除/测试连接/设默认（spec FR-001~003）。
 * 样式全部引用设计令牌（AGENTS.md §8）。
 */
import { computed, onMounted, ref } from 'vue'

import { Alert, Button, Empty, Table, Tag, message } from 'ant-design-vue'
import type { TableColumnsType } from 'ant-design-vue'

import type { ModelDetail, ModelItem, TestConnectionResult } from '@/api/models'
import { modelsApi } from '@/api/models'
import { MODULES } from '@/router/modules'
import { useModelsStore } from '@/stores/models'
import DeleteModelModal from '@/components/models/DeleteModelModal.vue'
import ModelFormModal from '@/components/models/ModelFormModal.vue'
import TestConnectionPanel from '@/components/models/TestConnectionPanel.vue'

const meta = MODULES.find((m) => m.path === 'models')!
const store = useModelsStore()

// ---- 新增 / 编辑 ----
const formOpen = ref(false)
const editingModel = ref<ModelDetail | null>(null)

// ---- 删除 ----
const deleteOpen = ref(false)
const deleteTarget = ref<ModelItem | null>(null)
const deleteOthers = computed(() =>
  store.items.filter((m) => m.id !== deleteTarget.value?.id),
)

// ---- 测试连接 ----
const testingId = ref<number | null>(null)
const testResult = ref<{ modelName: string; result: TestConnectionResult } | null>(null)
const testingModelName = computed(
  () => store.items.find((m) => m.id === testingId.value)?.display_name ?? null,
)

const columns: TableColumnsType = [
  { title: '显示名称', dataIndex: 'display_name', key: 'display_name' },
  { title: '模型标识', dataIndex: 'model_identifier', key: 'model_identifier' },
  { title: '服务地址', dataIndex: 'base_url', key: 'base_url', ellipsis: true },
  { title: '上下文长度', dataIndex: 'context_length', key: 'context_length', width: 110 },
  { title: '密钥', key: 'api_key_configured', width: 86 },
  { title: '默认', key: 'is_default', width: 70 },
  { title: '最后更新', key: 'updated_at', width: 150 },
  { title: '操作', key: 'actions', width: 220 },
]

function formatDateTime(iso: string): string {
  const date = new Date(iso)
  if (Number.isNaN(date.getTime())) return iso
  return date.toLocaleString('zh-CN', {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  })
}

function openCreate(): void {
  editingModel.value = null
  formOpen.value = true
}

async function openEdit(row: ModelItem): Promise<void> {
  try {
    editingModel.value = await modelsApi.detail(row.id)
    formOpen.value = true
  } catch (e) {
    message.error(e instanceof Error ? e.message : '读取模型详情失败')
  }
}

async function refresh(): Promise<void> {
  await store.fetchModels()
}

function openDelete(row: ModelItem): void {
  deleteTarget.value = row
  deleteOpen.value = true
}

async function handleSetDefault(row: ModelItem): Promise<void> {
  try {
    await modelsApi.setDefault(row.id)
    message.success(`已将「${row.display_name}」设为默认模型`)
    await refresh()
  } catch (e) {
    message.error(e instanceof Error ? e.message : '设置默认模型失败')
  }
}

async function handleTestConnection(row: ModelItem): Promise<void> {
  if (testingId.value !== null) return // 测试中禁止重复提交（FR-014）
  testingId.value = row.id
  testResult.value = null
  try {
    const result = await modelsApi.testConnection(row.id)
    testResult.value = { modelName: row.display_name, result }
  } catch (e) {
    testResult.value = {
      modelName: row.display_name,
      result: {
        success: false,
        category: null,
        message: e instanceof Error ? e.message : '测试请求发送失败',
        reply_excerpt: null,
      },
    }
  } finally {
    testingId.value = null
  }
}

onMounted(() => {
  void refresh()
})
</script>

<template>
  <div class="page">
    <header class="page__header">
      <div>
        <h1 class="page__title">{{ meta.title }}</h1>
        <p class="page__desc">{{ meta.description }}</p>
      </div>
      <Button v-if="store.items.length > 0" type="primary" @click="openCreate">
        添加模型
      </Button>
    </header>

    <Alert
      v-if="store.error"
      type="error"
      show-icon
      message="模型列表加载失败"
      :description="store.error"
      class="page__error"
    />

    <!-- 空状态（FR-002）：无模型时展示添加入口 -->
    <div v-if="!store.loading && store.items.length === 0 && !store.error" class="card empty-card">
      <Empty :image="Empty.PRESENTED_IMAGE_SIMPLE" description="还没有任何模型">
        <Button type="primary" @click="openCreate">添加模型</Button>
      </Empty>
      <p class="empty-hint">本阶段支持兼容 OpenAI Chat Completions 接口的模型服务</p>
    </div>

    <template v-else>
      <div class="card">
        <Table
          :columns="columns"
          :data-source="store.items"
          :loading="store.loading"
          :pagination="false"
          row-key="id"
          size="middle"
        >
          <template #bodyCell="{ column, record }">
            <template v-if="column.key === 'display_name'">
              <span class="cell-name">{{ record.display_name }}</span>
            </template>
            <template v-else-if="column.key === 'model_identifier'">
              <span class="cell-mono">{{ record.model_identifier }}</span>
            </template>
            <template v-else-if="column.key === 'base_url'">
              <span class="cell-mono cell-url" :title="record.base_url">
                {{ record.base_url }}
              </span>
            </template>
            <template v-else-if="column.key === 'context_length'">
              {{ record.context_length.toLocaleString() }}
            </template>
            <template v-else-if="column.key === 'api_key_configured'">
              <Tag
                class="cell-tag"
                :style="record.api_key_configured
                  ? { color: 'var(--success)', borderColor: 'var(--success)' }
                  : { color: 'var(--warning)', borderColor: 'var(--warning)' }"
              >
                {{ record.api_key_configured ? '已配置' : '未配置' }}
              </Tag>
            </template>
            <template v-else-if="column.key === 'is_default'">
              <Tag
                v-if="record.is_default"
                class="cell-tag"
                :style="{
                  background: 'var(--accent-dim)',
                  color: 'var(--accent)',
                  borderColor: 'transparent',
                }"
              >
                默认
              </Tag>
              <span v-else class="cell-dash">—</span>
            </template>
            <template v-else-if="column.key === 'updated_at'">
              <span class="cell-time">{{ formatDateTime(record.updated_at) }}</span>
            </template>
            <template v-else-if="column.key === 'actions'">
              <div class="cell-actions">
                <Button type="link" size="small" @click="openEdit(record as ModelItem)">
                  编辑
                </Button>
                <Button
                  type="link"
                  size="small"
                  :loading="testingId === record.id"
                  :disabled="testingId !== null && testingId !== record.id"
                  @click="handleTestConnection(record as ModelItem)"
                >
                  测试连接
                </Button>
                <Button
                  v-if="!record.is_default"
                  type="link"
                  size="small"
                  @click="handleSetDefault(record as ModelItem)"
                >
                  设为默认
                </Button>
                <Button
                  type="link"
                  size="small"
                  danger
                  @click="openDelete(record as ModelItem)"
                >
                  删除
                </Button>
              </div>
            </template>
          </template>
        </Table>
      </div>

      <TestConnectionPanel :testing-model-name="testingModelName" :result="testResult" />
    </template>

    <ModelFormModal v-model:open="formOpen" :model="editingModel" @saved="refresh" />
    <DeleteModelModal
      v-model:open="deleteOpen"
      :model="deleteTarget"
      :others="deleteOthers"
      @done="refresh"
    />
  </div>
</template>

<style scoped lang="scss">
.page {
  display: flex;
  flex-direction: column;
  gap: 16px;

  &__header {
    display: flex;
    align-items: flex-end;
    justify-content: space-between;
    gap: 12px;
  }

  &__title {
    font-size: 22px; // 页面主标题规格
    font-weight: 650;
  }

  &__desc {
    font-size: 12.5px; // 辅助说明规格
    color: var(--text-secondary);
  }

  &__error {
    border-radius: 8px;
  }
}

.card {
  background: var(--bg-surface);
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 8px 12px;
}

.empty-card {
  padding: 40px 24px;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 12px;

  .empty-hint {
    font-size: 12.5px;
    color: var(--text-tertiary);
  }
}

.cell-name {
  font-size: 14px; // 正文规格
  font-weight: 600;
  color: var(--text-primary);
}

.cell-mono {
  font-family: var(--font-mono);
  font-size: 13px; // 代码规格
  color: var(--text-secondary);
}

.cell-url {
  max-width: 100%;
}

.cell-tag {
  font-size: 12px;
  line-height: 20px;
  border-radius: 4px;
  background: transparent;
}

.cell-dash {
  color: var(--text-tertiary);
}

.cell-time {
  font-size: 12.5px;
  color: var(--text-tertiary);
}

.cell-actions {
  display: flex;
  align-items: center;
  gap: 2px;

  :global(.ant-btn-link) {
    padding-inline: 4px;
    font-size: 13px; // 按钮规格
  }
}
</style>
