<script setup lang="ts">
/**
 * Skills 管理页面（spec US1–US3，FR-001~014）：
 * 列表（名称/说明/启停/更新时间）+ 手动刷新（重扫目录）+ ZIP 导入 + 编辑抽屉 + 删除确认。
 * 样式全部引用设计令牌（AGENTS.md §8），与既有管理页范式一致（FR-035）。
 */
import { computed, onMounted, ref } from 'vue'

import { Empty, Modal, Switch, Table, Upload, message } from 'ant-design-vue'
import type { TableColumnsType, UploadProps } from 'ant-design-vue'
import { InboxOutlined, ReloadOutlined } from '@ant-design/icons-vue'

import type { SkillDetail, SkillItem } from '@/api/skills'
import { skillsApi } from '@/api/skills'
import { MODULES } from '@/router/modules'
import { useSkillsStore } from '@/stores/skills'
import SkillDetailModal from '@/components/skills/SkillDetailModal.vue'

const meta = MODULES.find((m) => m.path === 'skills')!
const store = useSkillsStore()

const columns: TableColumnsType = [
  { title: '名称', dataIndex: 'name', key: 'name', width: 180 },
  { title: '用途说明', dataIndex: 'description', key: 'description', ellipsis: true },
  { title: '启用状态', key: 'enabled', width: 96 },
  { title: '更新时间', dataIndex: 'updated_at', key: 'updated_at', width: 170 },
  { title: '操作', key: 'actions', width: 130 },
]

// ---- 刷新（US1：重扫目录，无需重启服务）----
async function handleRefresh(): Promise<void> {
  const skipped = await store.refresh()
  if (store.error) return
  if (skipped.length > 0) {
    message.warning(`已跳过 ${skipped.length} 个结构不合规的 Skill 目录：${skipped.join('、')}`)
  } else {
    message.success('已重新扫描 Skills 目录')
  }
}

// ---- 详情对话框（005：大对话框替换原抽屉，US1）----
const editOpen = ref(false)
const editing = ref<SkillDetail | null>(null)

async function openEdit(row: SkillItem): Promise<void> {
  try {
    editing.value = await skillsApi.detail(row.dir_name)
    editOpen.value = true
  } catch (e) {
    message.error(e instanceof Error ? e.message : '读取 Skill 详情失败')
  }
}

function handleBasicSaved(_updated: SkillItem): void {
  void store.fetchSkills()
}

// ---- 启停（US3：确认后生效）----
function handleToggle(row: SkillItem, next: boolean): void {
  const action = next ? '启用' : '停用'
  Modal.confirm({
    title: `确认${action}「${row.name}」？`,
    content: next
      ? '启用后，该 Skill 提供给 Agent 使用。'
      : '停用后，Skill 文件继续保留，但不再提供给 Agent 使用。',
    okText: action,
    cancelText: '取消',
    onOk: async () => {
      try {
        await store.setEnabled(row.dir_name, next)
        message.success(`已${action}「${row.name}」`)
      } catch (e) {
        message.error(e instanceof Error ? e.message : `${action}失败`)
      }
    },
  })
}

// ---- 删除（US3：确认后删除目录）----
function handleDelete(row: SkillItem): void {
  Modal.confirm({
    title: `确认删除「${row.name}」？`,
    content: `将删除 Skill 目录 ${row.dir_name} 及其全部文件，此操作不可恢复。`,
    okText: '删除',
    okType: 'danger',
    cancelText: '取消',
    onOk: async () => {
      try {
        await store.remove(row.dir_name)
        message.success(`已删除「${row.name}」`)
      } catch (e) {
        message.error(e instanceof Error ? e.message : '删除失败')
      }
    },
  })
}

// ---- ZIP 导入（US4）----
const importing = ref(false)
const beforeUpload: UploadProps['beforeUpload'] = (file) => {
  void (async () => {
    importing.value = true
    try {
      const item = await skillsApi.importZip(file)
      await store.fetchSkills()
      message.success(`已导入「${item.name}」`)
    } catch (e) {
      message.error(e instanceof Error ? e.message : '导入失败')
    } finally {
      importing.value = false
    }
  })()
  return false // 拦截默认上传，手动提交
}

const uploading = computed(() => importing.value)

function formatTime(iso: string): string {
  return iso.replace('T', ' ').slice(0, 19)
}

onMounted(() => {
  void store.fetchSkills()
})
</script>

<template>
  <div class="page">
    <header class="page__header">
      <div>
        <h1 class="page__title">{{ meta.title }}</h1>
        <p class="page__desc">{{ meta.description }}（Skill 统一保存在项目 workspace/skills 目录下）</p>
      </div>
      <div class="page__actions">
        <Upload
          :show-upload-list="false"
          :before-upload="beforeUpload"
          accept=".zip"
          :disabled="uploading"
        >
          <button class="btn btn--ghost" type="button" :disabled="uploading">
            <InboxOutlined />
            {{ uploading ? '导入中…' : '导入 ZIP' }}
          </button>
        </Upload>
        <button class="btn btn--primary" type="button" :disabled="store.refreshing" @click="handleRefresh">
          <ReloadOutlined />
          {{ store.refreshing ? '刷新中…' : '刷新' }}
        </button>
      </div>
    </header>

    <div v-if="store.error" class="alert alert--error">列表加载失败：{{ store.error }}</div>

    <!-- 空状态（FR-004） -->
    <div v-if="!store.loading && store.items.length === 0 && !store.error" class="card empty-card">
      <Empty :image="Empty.PRESENTED_IMAGE_SIMPLE" description="还没有任何 Skill">
        <p class="empty-hint">
          可点击「导入 ZIP」导入 Skill 包，或在项目 workspace/skills 目录下手动创建目录后点击「刷新」
        </p>
      </Empty>
    </div>

    <div v-else class="card">
      <Table
        :columns="columns"
        :data-source="store.items"
        :loading="store.loading"
        :pagination="false"
        row-key="dir_name"
        size="middle"
      >
        <template #bodyCell="{ column, record }">
          <template v-if="column.key === 'name'">
            <!-- 点击名称打开详情（需求：名称即编辑入口） -->
            <button class="name-btn" type="button" title="点击打开详情" @click="openEdit(record as SkillItem)">
              <div class="cell-name">{{ record.name }}</div>
              <div class="cell-dir">{{ record.dir_name }}</div>
            </button>
          </template>
          <template v-else-if="column.key === 'description'">
            <span class="cell-text" :title="record.description">{{ record.description || '—' }}</span>
          </template>
          <template v-else-if="column.key === 'enabled'">
            <Switch
              :checked="record.enabled"
              @change="(next: unknown) => handleToggle(record as SkillItem, Boolean(next))"
            />
          </template>
          <template v-else-if="column.key === 'updated_at'">
            <span class="cell-time">{{ formatTime(record.updated_at) }}</span>
          </template>
          <template v-else-if="column.key === 'actions'">
            <div class="cell-actions">
              <button class="link-btn" type="button" @click="openEdit(record as SkillItem)">编辑</button>
              <button class="link-btn link-btn--danger" type="button" @click="handleDelete(record as SkillItem)">
                删除
              </button>
            </div>
          </template>
        </template>
      </Table>
    </div>

    <SkillDetailModal v-model:open="editOpen" :skill="editing" @basic-saved="handleBasicSaved" />
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

  &__actions {
    display: flex;
    gap: 8px;
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
    max-width: 420px;
    text-align: center;
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

/* 名称列可点击打开详情 */
.name-btn {
  background: none;
  border: none;
  padding: 0;
  text-align: left;
  cursor: pointer;

  &:hover .cell-name {
    color: var(--accent);
    text-decoration: underline;
  }
}

.cell-dir {
  font-family: var(--font-mono);
  font-size: 12px;
  color: var(--text-tertiary);
}

.cell-text {
  font-size: 13.5px;
  color: var(--text-secondary);
}

.cell-time {
  font-size: 12.5px;
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

  &:hover {
    text-decoration: underline;
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
    color: #fff;

    &:disabled {
      opacity: 0.6;
      cursor: not-allowed;
    }
  }

  &--ghost {
    background: var(--bg-surface);
    color: var(--text-secondary);
    border-color: var(--border);

    &:hover:not(:disabled) {
      color: var(--text-primary);
      border-color: var(--border-strong);
    }
  }
}
</style>
