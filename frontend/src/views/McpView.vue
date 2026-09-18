<script setup lang="ts">
/**
 * MCP 管理页面（spec US5–US7，FR-015~034）：
 * 列表（名称/说明/类型/测试结果/工具数量/启停）+ 新增/编辑 + 测试连接 + 工具弹窗 + 删除确认。
 * 样式全部引用设计令牌（AGENTS.md §8），与既有管理页范式一致（FR-035）。
 */
import { computed, onMounted, ref } from 'vue'

import { Empty, Modal, Switch, Table, Tag, message } from 'ant-design-vue'
import type { TableColumnsType } from 'ant-design-vue'
import { PlusOutlined } from '@ant-design/icons-vue'

import type { McpServerDetail, McpServerItem, McpToolInfo } from '@/api/mcp'
import { mcpApi } from '@/api/mcp'
import { MODULES } from '@/router/modules'
import { useMcpStore } from '@/stores/mcp'
import McpServerFormModal from '@/components/mcp/McpServerFormModal.vue'
import McpToolsModal from '@/components/mcp/McpToolsModal.vue'

const meta = MODULES.find((m) => m.path === 'mcp')!
const store = useMcpStore()

const columns: TableColumnsType = [
  { title: '名称', dataIndex: 'name', key: 'name', width: 160 },
  { title: '说明', dataIndex: 'description', key: 'description', ellipsis: true },
  { title: '类型', key: 'server_type', width: 90 },
  { title: '最近一次测试结果', key: 'test', width: 200 },
  { title: '工具数量', key: 'tools', width: 90 },
  { title: '启用状态', key: 'enabled', width: 90 },
  { title: '操作', key: 'actions', width: 160 },
]

const typeLabel: Record<string, string> = { stdio: 'stdio', http: '远程' }

const testStatusMeta: Record<string, { text: string; className: string }> = {
  success: { text: '成功', className: 'status status--success' },
  failed: { text: '失败', className: 'status status--failed' },
  config_changed: { text: '配置已变更，待重新测试', className: 'status status--changed' },
}

function statusMeta(row: McpServerItem): { text: string; className: string } {
  if (row.last_test_status === null) return { text: '未测试', className: 'status status--none' }
  return testStatusMeta[row.last_test_status] ?? { text: '未知', className: 'status status--none' }
}

// ---- 新增 / 编辑（US5）----
const formOpen = ref(false)
const editing = ref<McpServerDetail | null>(null)

function openCreate(): void {
  editing.value = null
  formOpen.value = true
}

async function openEdit(row: McpServerItem): Promise<void> {
  try {
    editing.value = await mcpApi.detail(row.id)
    formOpen.value = true
  } catch (e) {
    message.error(e instanceof Error ? e.message : '读取 Server 详情失败')
  }
}

function handleSaved(_id: number): void {
  void store.fetchServers()
}

// ---- 启停（US7，确认后生效）----
function handleToggle(row: McpServerItem, next: boolean): void {
  const action = next ? '启用' : '停用'
  Modal.confirm({
    title: `确认${action}「${row.name}」？`,
    content: next
      ? '启用后，该 Server 的工具可供 Agent 使用。'
      : '停用后，该 Server 不再提供给 Agent 使用（不影响测试连接）。',
    okText: action,
    cancelText: '取消',
    onOk: async () => {
      try {
        await store.setEnabled(row.id, next)
        message.success(`已${action}「${row.name}」`)
      } catch (e) {
        message.error(e instanceof Error ? e.message : `${action}失败`)
      }
    },
  })
}

// ---- 删除（US5：确认；测试进行中后端拒绝）----
function handleDelete(row: McpServerItem): void {
  Modal.confirm({
    title: `确认删除「${row.name}」？`,
    content: '将删除该 Server 的全部配置，此操作不可恢复。',
    okText: '删除',
    okType: 'danger',
    cancelText: '取消',
    onOk: async () => {
      try {
        await store.remove(row.id)
        message.success(`已删除「${row.name}」`)
      } catch (e) {
        message.error(e instanceof Error ? e.message : '删除失败')
      }
    },
  })
}

// ---- 测试连接（US6：进行中禁用重复提交与编辑删除，FR-030）----
const testingRowId = computed(() => store.testingId)

async function handleTest(row: McpServerItem): Promise<void> {
  try {
    const result = await store.test(row.id)
    if (result.status === 'success') {
      message.success(
        result.tool_count === 0 ? result.message : `连接成功，发现 ${result.tool_count} 个工具`,
      )
    } else {
      message.warning(result.message)
    }
  } catch (e) {
    message.error(e instanceof Error ? e.message : '测试连接失败')
  }
}

function isBusy(row: McpServerItem): boolean {
  return testingRowId.value === row.id
}

// ---- 工具数量弹窗（FR-016）----
const toolsOpen = ref(false)
const toolsServerName = ref('')
const tools = ref<McpToolInfo[]>([])

async function openTools(row: McpServerItem): Promise<void> {
  try {
    const detail = await mcpApi.detail(row.id)
    tools.value = detail.tools
    toolsServerName.value = row.name
    toolsOpen.value = true
  } catch (e) {
    message.error(e instanceof Error ? e.message : '读取工具列表失败')
  }
}

function formatTime(iso: string | null): string {
  return iso ? iso.replace('T', ' ').slice(0, 19) : '—'
}

onMounted(() => {
  void store.fetchServers()
})
</script>

<template>
  <div class="page">
    <header class="page__header">
      <div>
        <h1 class="page__title">{{ meta.title }}</h1>
        <p class="page__desc">
          {{ meta.description }}（stdio 经本机启动通信；远程经 HTTP。暂不支持 OAuth 与账号授权）
        </p>
      </div>
      <button class="btn btn--primary" type="button" @click="openCreate">
        <PlusOutlined /> 新增 Server
      </button>
    </header>

    <div v-if="store.error" class="alert alert--error">列表加载失败：{{ store.error }}</div>

    <!-- 空状态 -->
    <div v-if="!store.loading && store.items.length === 0 && !store.error" class="card empty-card">
      <Empty :image="Empty.PRESENTED_IMAGE_SIMPLE" description="还没有任何 MCP Server">
        <p class="empty-hint">点击「新增 Server」登记本机启动或远程 HTTP 的 MCP Server</p>
      </Empty>
    </div>

    <div v-else class="card">
      <Table
        :columns="columns"
        :data-source="store.items"
        :loading="store.loading"
        :pagination="false"
        row-key="id"
        size="middle"
      >
        <template #bodyCell="{ column, record }">
          <template v-if="column.key === 'name'">
            <!-- 点击名称打开编辑详情（需求：名称即编辑入口） -->
            <button class="name-btn" type="button" title="点击编辑" @click="openEdit(record as McpServerItem)">
              {{ record.name }}
            </button>
          </template>
          <template v-else-if="column.key === 'description'">
            <span class="cell-text" :title="record.description">{{ record.description || '—' }}</span>
          </template>
          <template v-else-if="column.key === 'server_type'">
            <Tag
              class="cell-tag"
              :style="{
                background: record.server_type === 'stdio' ? 'var(--accent-dim)' : 'transparent',
                color: record.server_type === 'stdio' ? 'var(--accent)' : 'var(--text-secondary)',
                borderColor: record.server_type === 'stdio' ? 'transparent' : 'var(--border-strong)',
              }"
            >
              {{ typeLabel[record.server_type] ?? record.server_type }}
            </Tag>
          </template>
          <template v-else-if="column.key === 'test'">
            <div :class="statusMeta(record as McpServerItem).className">
              {{ statusMeta(record as McpServerItem).text }}
              <div v-if="record.last_test_status !== null" class="status-meta">
                {{ formatTime(record.last_test_at) }}
              </div>
            </div>
          </template>
          <template v-else-if="column.key === 'tools'">
            <button
              v-if="record.last_test_tool_count !== null"
              class="link-btn"
              type="button"
              @click="openTools(record as McpServerItem)"
            >
              {{ record.last_test_tool_count }}
            </button>
            <span v-else class="cell-dash">未知</span>
          </template>
          <template v-else-if="column.key === 'enabled'">
            <Switch
              :checked="record.enabled"
              @change="(next: unknown) => handleToggle(record as McpServerItem, Boolean(next))"
            />
          </template>
          <template v-else-if="column.key === 'actions'">
            <div class="cell-actions">
              <button
                class="link-btn"
                type="button"
                :disabled="isBusy(record as McpServerItem)"
                @click="handleTest(record as McpServerItem)"
              >
                {{ isBusy(record as McpServerItem) ? '测试中…' : '测试' }}
              </button>
              <button
                class="link-btn"
                type="button"
                :disabled="isBusy(record as McpServerItem)"
                @click="openEdit(record as McpServerItem)"
              >
                编辑
              </button>
              <button
                class="link-btn link-btn--danger"
                type="button"
                :disabled="isBusy(record as McpServerItem)"
                @click="handleDelete(record as McpServerItem)"
              >
                删除
              </button>
            </div>
          </template>
        </template>
      </Table>
    </div>

    <McpServerFormModal v-model:open="formOpen" :server="editing" @saved="handleSaved" />
    <McpToolsModal v-model:open="toolsOpen" :server-name="toolsServerName" :tools="tools" />
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

.alert {
  border-radius: 8px;
  padding: 8px 12px;
  font-size: 13.5px;

  &--error {
    background: color-mix(in srgb, var(--danger) 8%, transparent);
    color: var(--danger);
    border: 1px solid color-mix(in srgb, var(--danger) 30%, transparent);
  }
}

.cell-name {
  font-size: 14px; // 正文规格
  font-weight: 600;
  color: var(--text-primary);
}

/* 名称列可点击编辑（需求：名称即编辑入口） */
.name-btn {
  background: none;
  border: none;
  padding: 0;
  font-size: 14px; // 正文规格
  font-weight: 600;
  color: var(--text-primary);
  text-align: left;
  cursor: pointer;

  &:hover {
    color: var(--accent);
    text-decoration: underline;
  }
}

.cell-text {
  font-size: 13.5px;
  color: var(--text-secondary);
}

.cell-tag {
  font-size: 12px;
  line-height: 20px;
  border-radius: 4px;
}

.cell-dash {
  font-size: 12.5px;
  color: var(--text-tertiary);
}

.status {
  font-size: 13px;
  line-height: 1.4;

  &--success {
    color: var(--success);
  }

  &--failed {
    color: var(--danger);
  }

  &--changed {
    color: var(--warning);
  }

  &--none {
    color: var(--text-tertiary);
  }
}

.status-meta {
  font-size: 12px;
  color: var(--text-tertiary);
  font-variant-numeric: tabular-nums;
}

.cell-actions {
  display: flex;
  gap: 10px;
}

.link-btn {
  background: none;
  border: none;
  padding: 0;
  font-size: 13px; // 按钮规格
  color: var(--accent);
  cursor: pointer;

  &:hover:not(:disabled) {
    text-decoration: underline;
  }

  &:disabled {
    color: var(--text-tertiary);
    cursor: not-allowed;
  }

  &--danger {
    color: var(--danger);
  }
}

.btn {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-size: 13.5px; // 按钮规格
  line-height: 1.5;
  border-radius: 6px;
  padding: 5px 16px;
  cursor: pointer;
  border: 1px solid transparent;

  &--primary {
    background: var(--accent);
    color: var(--text-inverse);
  }
}
</style>
