<script setup lang="ts">
/**
 * Agent 管理页面（specs/007，US1/US2/US4/US5）：
 * 卡片列表（顶部信息/中部绑定条目+N/底部操作）+ 空状态 + 全屏详情 + 删除/默认流程。
 * 样式全部引用设计令牌（AGENTS.md §8），与既有管理页范式一致（FR-031）。
 */
import { computed, onMounted, ref } from 'vue'

import { Empty, Modal, Spin, Tag, message } from 'ant-design-vue'
import { PlusOutlined } from '@ant-design/icons-vue'

import type { AgentDetail, AgentListItem } from '@/api/agents'
import { MODULES } from '@/router/modules'
import { parseConflictBody, useAgentsStore } from '@/stores/agents'
import AgentDetailDialog from '@/components/agents/AgentDetailDialog.vue'
import DeleteAgentModal from '@/components/agents/DeleteAgentModal.vue'

const meta = MODULES.find((m) => m.path === 'agents')!
const store = useAgentsStore()

// ---- 列表 ----
onMounted(() => {
  void store.fetchAgents()
})

const hasAgents = computed(() => store.items.length > 0)

const typeLabel: Record<string, string> = { tool: '工具', skill: '技能', mcp: 'MCP' }

interface BindingGroup {
  type: string
  label: string
  items: AgentListItem['bindings']
}

/** 绑定按 工具→技能→MCP 分组（卡片每类一行，全量展示） */
function bindingGroups(item: AgentListItem): BindingGroup[] {
  const order: Array<'tool' | 'skill' | 'mcp'> = ['tool', 'skill', 'mcp']
  return order
    .map((type) => ({
      type,
      label: typeLabel[type]!,
      items: item.bindings.filter((b) => b.resource_type === type),
    }))
    .filter((group) => group.items.length > 0)
}

function formatTime(iso: string): string {
  return iso.slice(0, 16).replace('T', ' ')
}

// ---- 新建 / 编辑 / 详情（全屏 dialog）----
const dialogOpen = ref(false)
const editingAgent = ref<AgentDetail | null>(null)

function openCreate(): void {
  editingAgent.value = null
  dialogOpen.value = true
}

async function openEdit(item: AgentListItem): Promise<void> {
  try {
    editingAgent.value = await store.fetchDetail(item.id)
    dialogOpen.value = true
  } catch (e) {
    message.error(e instanceof Error ? e.message : '读取 Agent 详情失败')
  }
}

function handleSaved(): void {
  dialogOpen.value = false
}

// ---- 删除（US4：普通确认 / 默认先选新默认 / 最后一个清空）----
const deleteTarget = ref<AgentListItem | null>(null)
const deleteOpen = ref(false)

function confirmDelete(item: AgentListItem): void {
  deleteTarget.value = item
  deleteOpen.value = true
}

async function handleDeleted(): Promise<void> {
  deleteTarget.value = null
  deleteOpen.value = false
}

// ---- 设默认（US4）----
async function handleSetDefault(item: AgentListItem): Promise<void> {
  try {
    await store.setDefault(item.id)
    message.success(`已将「${item.name}」设为默认 Agent`)
  } catch (e) {
    message.error(e instanceof Error ? e.message : '设置默认失败')
  }
}
</script>

<template>
  <div class="agents-page">
    <header class="page-header">
      <div>
        <h2 class="page-title">{{ meta.title }}</h2>
        <p class="page-sub">{{ meta.description }}</p>
      </div>
      <button v-if="hasAgents" type="button" class="new-btn" @click="openCreate">
        <PlusOutlined /> 新建 Agent
      </button>
    </header>

    <Spin :spinning="store.loading">
      <!-- 空状态（FR-002）-->
      <div v-if="!store.loading && !hasAgents" class="empty-state">
        <Empty description="还没有 Agent，创建第一个 Agent 来组合模型与能力">
          <button type="button" class="new-btn" @click="openCreate">
            <PlusOutlined /> 新建 Agent
          </button>
        </Empty>
      </div>

      <!-- 卡片列表（FR-003~005）-->
      <div v-else class="card-grid">
        <article
          v-for="item in store.items"
          :key="item.id"
          class="agent-card"
          @click="openEdit(item)"
        >
          <div class="card-top">
            <div class="card-title-row">
              <h3 class="card-name">{{ item.name }}</h3>
              <Tag v-if="item.is_default" color="warning" class="default-tag">默认</Tag>
            </div>
            <p class="card-desc">{{ item.description || '暂无说明' }}</p>
            <div class="card-meta">
              <span class="card-model">
                {{ item.model_display_name }}
                <span class="card-model-id">{{ item.model_identifier }}</span>
              </span>
              <span class="card-counts">
                工具 {{ item.tool_count }} · 技能 {{ item.skill_count }} · MCP {{ item.mcp_count }}
              </span>
              <span class="card-time">{{ formatTime(item.updated_at) }}</span>
            </div>
          </div>

          <div v-if="item.bindings.length" class="card-bindings">
            <div
              v-for="group in bindingGroups(item)"
              :key="group.type"
              class="binding-row"
            >
              <span class="binding-row__label">{{ group.label }}（{{ group.items.length }}）</span>
              <span class="binding-row__items">
                <span
                  v-for="binding in group.items"
                  :key="`${binding.resource_type}-${binding.resource_id}`"
                  class="binding-chip"
                  :class="{ 'binding-chip--disabled': !binding.enabled }"
                  :title="binding.enabled ? binding.name : `${binding.name}（已停用，不可用）`"
                >
                  {{ binding.name }}
                </span>
              </span>
            </div>
          </div>

          <footer class="card-footer">
            <div class="card-actions" @click.stop>
              <button
                v-if="!item.is_default"
                type="button"
                class="link-btn"
                @click="handleSetDefault(item)"
              >
                设为默认
              </button>
              <button type="button" class="link-btn" @click="openEdit(item)">编辑</button>
              <button type="button" class="link-btn link-btn--danger" @click="confirmDelete(item)">
                删除
              </button>
            </div>
          </footer>
        </article>
      </div>
    </Spin>

    <AgentDetailDialog
      v-model:open="dialogOpen"
      :agent="editingAgent"
      @saved="handleSaved"
    />
    <DeleteAgentModal
      v-model:open="deleteOpen"
      :agent="deleteTarget"
      @done="handleDeleted"
    />
  </div>
</template>

<style scoped lang="scss">
.agents-page {
  display: flex;
  flex-direction: column;
  gap: 16px;
  height: 100%;
  overflow-y: auto;
  padding: 20px 24px;
}

.page-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
}

.page-title {
  margin: 0;
  font-size: 22px;
  font-weight: 650;
  color: var(--text-primary);
}

.page-sub {
  margin: 4px 0 0;
  font-size: 12.5px;
  color: var(--text-secondary);
}

.new-btn {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  border: none;
  border-radius: 6px;
  background: var(--accent);
  color: var(--text-inverse);
  font-size: 13.5px;
  font-weight: 600;
  padding: 7px 16px;
  cursor: pointer;

  &:hover {
    background: var(--accent-hover);
  }
}

.empty-state {
  padding: 80px 0 40px;
}

.card-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(320px, 1fr));
  gap: 14px;
}

.agent-card {
  display: flex;
  flex-direction: column;
  gap: 10px;
  padding: 16px;
  background: var(--bg-surface);
  border: 1px solid var(--border);
  border-radius: 10px;
  cursor: pointer;
  transition: border-color 0.15s ease, box-shadow 0.15s ease;

  &:hover {
    border-color: var(--border-hover);
    box-shadow: 0 2px 10px rgba(45, 32, 23, 0.08);
  }
}

.card-title-row {
  display: flex;
  align-items: center;
  gap: 8px;
}

.card-name {
  margin: 0;
  font-size: 16px;
  font-weight: 600;
  color: var(--text-primary);
}

.default-tag {
  margin: 0;
}

.card-desc {
  margin: 6px 0 0;
  font-size: 12.5px;
  color: var(--text-secondary);
  line-height: 1.5;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}

.card-meta {
  display: flex;
  flex-direction: column;
  gap: 3px;
  margin-top: 10px;
  font-size: 12.5px;
  color: var(--text-secondary);
}

.card-model {
  color: var(--text-primary);
}

.card-model-id {
  font-family: var(--font-mono);
  font-size: 12px;
  color: var(--text-tertiary);
  margin-left: 6px;
}

.card-counts {
  color: var(--text-secondary);
}

.card-time {
  font-size: 12px;
  color: var(--text-tertiary);
}

.card-bindings {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.binding-row {
  display: flex;
  align-items: flex-start;
  gap: 8px;
  font-size: 12.5px;
}

.binding-row__label {
  flex: 0 0 auto;
  color: var(--text-tertiary);
  line-height: 22px;
}

.binding-row__items {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  min-width: 0;
}

.binding-chip {
  font-size: 12px;
  color: var(--text-secondary);
  background: var(--bg-hover);
  border: 1px solid var(--border);
  border-radius: 4px;
  padding: 1px 8px;
  max-width: 140px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;

  &--disabled {
    color: var(--warning);
    border-style: dashed;
    text-decoration: line-through;
  }
}

.card-footer {
  margin-top: auto;
  padding-top: 10px;
  border-top: 1px solid var(--border);
}

.card-actions {
  display: flex;
  gap: 14px;
}

.link-btn {
  border: none;
  background: none;
  padding: 0;
  font-size: 13px;
  color: var(--accent);
  cursor: pointer;

  &:hover {
    color: var(--accent-hover);
  }

  &--danger {
    color: var(--danger);

    &:hover {
      color: var(--danger);
      opacity: 0.85;
    }
  }
}
</style>
