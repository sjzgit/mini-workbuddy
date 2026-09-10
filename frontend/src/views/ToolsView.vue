<script setup lang="ts">
/**
 * 工具管理页面：列表 + 空状态 + 详情抽屉 + 启停（spec FR-001~007）。
 *
 * - 列表展示：显示名称 / 工具标识 / 用途说明 / 参数概要 / 启用状态 / 系统内置
 * - 启停经 Modal.confirm 确认后生效（US2"操作需确认后生效"）
 * - 内置工具只有启停入口，无删除/修改用途入口（FR-007 的界面侧）
 * - 样式全部引用设计令牌（AGENTS.md §8）
 */
import { onMounted, ref } from 'vue'

import { Alert, Empty, Modal, Switch, Table, Tag, message } from 'ant-design-vue'
import type { TableColumnsType } from 'ant-design-vue'

import type { ToolDetail, ToolItem } from '@/api/tools'
import { toolsApi } from '@/api/tools'
import { MODULES } from '@/router/modules'
import { useToolsStore } from '@/stores/tools'
import ToolDetailDrawer from '@/components/tools/ToolDetailDrawer.vue'

const meta = MODULES.find((m) => m.path === 'tools')!
const store = useToolsStore()

// ---- 详情抽屉 ----
const detailOpen = ref(false)
const detailLoading = ref(false)
const detail = ref<ToolDetail | null>(null)

const columns: TableColumnsType = [
  { title: '显示名称', dataIndex: 'display_name', key: 'display_name', width: 130 },
  { title: '工具标识', dataIndex: 'name', key: 'name', width: 150 },
  { title: '用途说明', dataIndex: 'purpose', key: 'purpose', ellipsis: true },
  { title: '参数概要', dataIndex: 'params_summary', key: 'params_summary', ellipsis: true },
  { title: '启用状态', key: 'enabled', width: 96 },
  { title: '系统内置', key: 'is_builtin', width: 96 },
]

async function openDetail(row: ToolItem): Promise<void> {
  detailOpen.value = true
  detailLoading.value = true
  detail.value = null
  try {
    detail.value = await toolsApi.detail(row.name)
  } catch (e) {
    detailOpen.value = false
    message.error(e instanceof Error ? e.message : '读取工具详情失败')
  } finally {
    detailLoading.value = false
  }
}

/** 行点击打开详情（整行可点，列表即入口） */
function handleRowClick(record: ToolItem): void {
  void openDetail(record)
}

// ---- 启停（确认后生效，US2）----
function handleToggle(row: ToolItem, next: boolean): void {
  const action = next ? '启用' : '停用'
  Modal.confirm({
    title: `确认${action}「${row.display_name}」？`,
    content: next
      ? '启用后，该工具对后续 Agent 调用恢复可用。'
      : '停用后，该工具对后续 Agent 不可见、不可调用。',
    okText: action,
    cancelText: '取消',
    onOk: async () => {
      try {
        await store.setEnabled(row.name, next)
        message.success(`已${action}「${row.display_name}」`)
      } catch (e) {
        message.error(e instanceof Error ? e.message : `${action}失败`)
      }
    },
  })
}

onMounted(() => {
  void store.fetchTools()
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

    <Alert
      v-if="store.error"
      type="error"
      show-icon
      message="工具列表加载失败"
      :description="store.error"
      class="page__error"
    />

    <!-- 空状态（FR-002）：无工具时不显示残缺表格 -->
    <div v-if="!store.loading && store.items.length === 0 && !store.error" class="card empty-card">
      <Empty :image="Empty.PRESENTED_IMAGE_SIMPLE" description="还没有任何工具">
        <p class="empty-hint">系统内置工具（当前时间 / Shell 命令 / 文件读写）将在数据库初始化后出现在这里</p>
      </Empty>
    </div>

    <div v-else class="card">
      <Table
        :columns="columns"
        :data-source="store.items"
        :loading="store.loading"
        :pagination="false"
        row-key="name"
        size="middle"
        :custom-row="(record: ToolItem) => ({ onClick: () => handleRowClick(record) })"
      >
        <template #bodyCell="{ column, record }">
          <template v-if="column.key === 'display_name'">
            <span class="cell-name">{{ record.display_name }}</span>
          </template>
          <template v-else-if="column.key === 'name'">
            <span class="cell-mono">{{ record.name }}</span>
          </template>
          <template v-else-if="column.key === 'purpose'">
            <span class="cell-text" :title="record.purpose">{{ record.purpose }}</span>
          </template>
          <template v-else-if="column.key === 'params_summary'">
            <span class="cell-params" :title="record.params_summary">{{ record.params_summary }}</span>
          </template>
          <template v-else-if="column.key === 'enabled'">
            <!-- 点击行打开详情，开关单独拦截冒泡 -->
            <Switch
              :checked="record.enabled"
              :loading="store.togglingName === record.name"
              @click="(_checked: unknown, e: Event) => e.stopPropagation()"
              @change="(next: unknown) => handleToggle(record as ToolItem, Boolean(next))"
            />
          </template>
          <template v-else-if="column.key === 'is_builtin'">
            <Tag
              v-if="record.is_builtin"
              class="cell-tag"
              :style="{
                background: 'var(--accent-dim)',
                color: 'var(--accent)',
                borderColor: 'transparent',
              }"
            >
              内置
            </Tag>
            <span v-else class="cell-dash">—</span>
          </template>
        </template>
      </Table>
    </div>

    <ToolDetailDrawer v-model:open="detailOpen" :tool-name="null" :detail="detail" />
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
    margin: 0;
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

.cell-text {
  font-size: 13.5px;
  color: var(--text-secondary);
}

.cell-params {
  font-size: 12.5px;
  color: var(--text-tertiary);
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

:deep(.ant-table-row) {
  cursor: pointer;
}
</style>
