<script setup lang="ts">
/**
 * Agent 详情/编辑全屏 dialog（FR-007~015，US1/US3/US5 前端落点）。
 * 三列：系统提示词（含版本切换）｜ Agent 编排 ｜ 预览与调试占位。
 */
import { computed, reactive, ref, watch } from 'vue'

import { Form, FormItem, Input, Modal, Select, Switch, message } from 'ant-design-vue'
import type { Rule } from 'ant-design-vue/es/form'

import {
  ENABLE_DEEP_THINKING_DEFAULT,
  AUTO_COMPACT_DEFAULT,
  COMPACT_KEEP_ROUNDS_DEFAULT,
  COMPACT_SUMMARY_TARGET_DEFAULT,
  COMPACT_TRIGGER_RATIO_DEFAULT,
  MAX_ROUNDS_DEFAULT,
  THINKING_LEVEL_DEFAULT,
  agentsApi,
  type AgentDetail,
  type BindingItem,
  type ThinkingLevel,
} from '@/api/agents'
import { useAgentsStore } from '@/stores/agents'
import AgentOrchestration from './AgentOrchestration.vue'
import ResourceSelectModal from './ResourceSelectModal.vue'

const props = defineProps<{
  open: boolean
  /** null = 新建 */
  agent: AgentDetail | null
}>()

const emit = defineEmits<{
  'update:open': [value: boolean]
  saved: [id: number]
}>()

const store = useAgentsStore()

const formRef = ref()
const saving = ref(false)
const formError = ref<string | null>(null)

const form = reactive({
  name: '',
  description: '',
  systemPrompt: '',
  modelId: null as number | null,
  maxRounds: MAX_ROUNDS_DEFAULT,
  enableDeepThinking: ENABLE_DEEP_THINKING_DEFAULT,
  thinkingLevel: THINKING_LEVEL_DEFAULT as ThinkingLevel,
  autoCompact: AUTO_COMPACT_DEFAULT,
  compactTriggerRatio: COMPACT_TRIGGER_RATIO_DEFAULT,
  compactKeepRounds: COMPACT_KEEP_ROUNDS_DEFAULT,
  compactSummaryTarget: COMPACT_SUMMARY_TARGET_DEFAULT,
  isDefault: false,
})

/** 已勾选的绑定（保存时提交）；含编辑回显的停用绑定（不可操作，只随保存保留） */
const selectedToolIds = ref(new Set<number>())
const selectedSkillIds = ref(new Set<number>())
const selectedMcpIds = ref(new Set<number>())

/** 提示词版本（编辑态来自详情；新建态空） */
const versions = ref<AgentDetail['prompt_versions']>([])
const currentVersion = ref<number | null>(null)
/** 是否正在查看历史版本（保存将生成新版本提示） */
const editingHistory = ref(false)

const rules: Record<string, Rule[]> = {
  name: [{ required: true, whitespace: true, message: '请输入 Agent 名称', trigger: 'blur' }],
  modelId: [{ required: true, message: '请选择模型', trigger: 'change' }],
  maxRounds: [{
    validator: (_rule: Rule, value: number) => {
      if (!Number.isInteger(value) || value < 1 || value > 100) {
        return Promise.reject('最大执行轮数须为 1~100 的正整数')
      }
      return Promise.resolve()
    },
    trigger: 'change',
  }],
}

const showModelError = ref(false)

const versionOptions = computed(() =>
  versions.value.map((v) => ({
    value: v.version,
    label: `v${v.version} · ${v.created_at.slice(0, 16).replace('T', ' ')}`,
  })),
)

watch(
  () => props.open,
  (open) => {
    if (open) void initialize()
  },
)

async function initialize(): Promise<void> {
  formError.value = null
  showModelError.value = false
  editingHistory.value = false
  currentVersion.value = null
  if (props.agent) {
    const detail = await agentsApi.detail(props.agent.id)
    applyDetail(detail)
    await store.loadBindingOptions(detail.id)
  } else {
    // 先拉候选（含 prompt_template 下发），再初始化表单（模板在打开时即预填，FR-009）
    const options = await store.loadBindingOptions()
    form.name = ''
    form.description = ''
    form.modelId = null
    form.maxRounds = MAX_ROUNDS_DEFAULT
    form.enableDeepThinking = ENABLE_DEEP_THINKING_DEFAULT
    form.thinkingLevel = THINKING_LEVEL_DEFAULT
    form.isDefault = false
    form.systemPrompt = options.prompt_template
    selectedToolIds.value = new Set()
    selectedSkillIds.value = new Set()
    selectedMcpIds.value = new Set()
    versions.value = []
  }
  // 新建时默认选中默认模型（FR-014）
  if (!props.agent && form.modelId === null) {
    const defaultModel = store.options?.models.find((m) => m.is_default) ?? null
    if (defaultModel) form.modelId = defaultModel.id
  }
}

function applyDetail(detail: AgentDetail): void {
  form.name = detail.name
  form.description = detail.description
  form.systemPrompt = detail.system_prompt
  form.modelId = detail.model_id
  form.maxRounds = detail.max_rounds
  form.enableDeepThinking = detail.enable_deep_thinking
  form.thinkingLevel = detail.thinking_level
  form.autoCompact = detail.auto_compact
  form.compactTriggerRatio = detail.compact_trigger_ratio
  form.compactKeepRounds = detail.compact_keep_recent_rounds
  form.compactSummaryTarget = detail.compact_summary_target_tokens
  form.isDefault = detail.is_default
  versions.value = detail.prompt_versions
  currentVersion.value = detail.prompt_versions.at(-1)?.version ?? null
  selectedToolIds.value = new Set(
    detail.bindings.filter((b) => b.resource_type === 'tool').map((b) => b.resource_id),
  )
  selectedSkillIds.value = new Set(
    detail.bindings.filter((b) => b.resource_type === 'skill').map((b) => b.resource_id),
  )
  selectedMcpIds.value = new Set(
    detail.bindings.filter((b) => b.resource_type === 'mcp').map((b) => b.resource_id),
  )
}

/** 切换版本：载入该版本内容（US3），保存将按内容判定生成新版本 */
function onVersionChange(version: number): void {
  const target = versions.value.find((v) => v.version === version)
  if (!target) return
  currentVersion.value = version // 受控 Select 的显示值同步跟随选择
  form.systemPrompt = target.content
  const latest = versions.value.at(-1)?.version ?? null
  editingHistory.value = latest !== null && version !== latest
}

/** 勾选/取消一个资源 id（返回新 Set 保持响应性） */
function toggleSet(current: Set<number>, id: number, checked: boolean): Set<number> {
  const next = new Set(current)
  if (checked) {
    next.add(id)
  } else {
    next.delete(id)
  }
  return next
}

function onToggleTool(id: number, checked: boolean): void {
  selectedToolIds.value = toggleSet(selectedToolIds.value, id, checked)
}

function onToggleSkill(id: number, checked: boolean): void {
  selectedSkillIds.value = toggleSet(selectedSkillIds.value, id, checked)
}

function onToggleMcp(id: number, checked: boolean): void {
  selectedMcpIds.value = toggleSet(selectedMcpIds.value, id, checked)
}

// ---- 能力维护弹窗（FR-004a）----
type PickerType = 'tool' | 'skill' | 'mcp'

const pickerOpen = ref(false)
const pickerType = ref<PickerType>('tool')

const pickerTitle = computed(() => {
  const labels: Record<PickerType, string> = { tool: '选择工具', skill: '选择 Skills', mcp: '选择 MCP Server' }
  return labels[pickerType.value]
})

const pickerOptions = computed(() => {
  const options = store.options
  if (!options) return []
  if (pickerType.value === 'tool') return options.tools
  if (pickerType.value === 'skill') return options.skills
  return options.mcp_servers
})

/** 弹窗需要 Set 引用；直接传当前类别的已选集合 */
const pickerSelectedIds = computed(() => {
  if (pickerType.value === 'tool') return selectedToolIds.value
  if (pickerType.value === 'skill') return selectedSkillIds.value
  return selectedMcpIds.value
})

function openPicker(type: PickerType): void {
  pickerType.value = type
  pickerOpen.value = true
}

function applyPicker(ids: Set<number>): void {
  if (pickerType.value === 'tool') {
    selectedToolIds.value = ids
  } else if (pickerType.value === 'skill') {
    selectedSkillIds.value = ids
  } else {
    selectedMcpIds.value = ids
  }
}

/** 已绑定但已停用的资源（编辑态标记"已停用，不可用"，US5） */
const disabledBindings = computed<BindingItem[]>(() => {
  if (!props.agent) return []
  return props.agent.bindings.filter(
    (b) =>
      !b.enabled &&
      ((b.resource_type === 'tool' && !selectedToolIds.value.has(b.resource_id)) ||
        (b.resource_type === 'skill' && !selectedSkillIds.value.has(b.resource_id)) ||
        (b.resource_type === 'mcp' && !selectedMcpIds.value.has(b.resource_id))),
  )
})

async function handlePublish(): Promise<void> {
  try {
    await formRef.value?.validate()
  } catch {
    return
  }
  if (form.modelId === null) {
    showModelError.value = true
    return
  }
  saving.value = true
  formError.value = null
  try {
    const detail = await store.save(
      {
        name: form.name,
        description: form.description,
        model_id: form.modelId,
        system_prompt: form.systemPrompt,
        max_rounds: form.maxRounds,
        enable_deep_thinking: form.enableDeepThinking,
        thinking_level: form.thinkingLevel,
        auto_compact: form.autoCompact,
        compact_trigger_ratio: form.compactTriggerRatio,
        compact_keep_recent_rounds: form.compactKeepRounds,
        compact_summary_target_tokens: form.compactSummaryTarget,
        is_default: form.isDefault,
        bindings: [
          ...[...selectedToolIds.value].map((id) => ({ resource_type: 'tool' as const, resource_id: id })),
          ...[...selectedSkillIds.value].map((id) => ({ resource_type: 'skill' as const, resource_id: id })),
          ...[...selectedMcpIds.value].map((id) => ({ resource_type: 'mcp' as const, resource_id: id })),
        ],
      },
      props.agent?.id,
    )
    message.success(props.agent ? 'Agent 已更新' : 'Agent 已创建')
    emit('saved', detail.id)
    emit('update:open', false)
  } catch (e) {
    formError.value = e instanceof Error ? e.message : '保存失败，请稍后重试'
  } finally {
    saving.value = false
  }
}

function handleClose(): void {
  emit('update:open', false)
}
</script>

<template>
  <Modal
    :open="open"
    :title="null"
    :footer="null"
    width="100%"
    wrap-class-name="agent-detail-fullscreen"
    :mask-closable="false"
    :closable="false"
    :body-style="{ padding: '0', height: '100vh', overflow: 'hidden' }"
    @cancel="handleClose"
  >
    <div class="detail-page">
      <header class="detail-header">
        <h3 class="detail-title">{{ agent ? '编辑 Agent' : '新建 Agent' }}</h3>
        <button type="button" class="detail-close" @click="handleClose">关闭</button>
      </header>

      <section class="detail-basic">
        <Form ref="formRef" layout="vertical" :model="form" :rules="rules" class="basic-form">
          <div class="basic-row">
            <FormItem label="名称" name="name" class="basic-item">
              <Input v-model:value="form.name" placeholder="用于识别 Agent" :maxlength="100" />
            </FormItem>
            <FormItem label="说明" name="description" class="basic-item basic-item--wide">
              <Input v-model:value="form.description" placeholder="描述 Agent 的用途和适用任务" :maxlength="500" />
            </FormItem>
            <FormItem label="默认 Agent" name="isDefault" class="basic-item basic-item--switch">
              <Switch v-model:checked="form.isDefault" size="small" />
            </FormItem>
            <div class="basic-actions">
              <button type="button" class="publish-btn" :disabled="saving" @click="handlePublish">
                {{ saving ? '发布中…' : '发布' }}
              </button>
            </div>
          </div>
        </Form>
        <p v-if="formError" class="detail-error">{{ formError }}</p>
      </section>

      <main class="detail-columns">
        <!-- 第一列：系统提示词 -->
        <section class="col col--prompt">
          <div class="col-head">
            <h4 class="col-title">系统提示词</h4>
            <div v-if="versions.length" class="version-picker">
              <Select
                :value="currentVersion ?? undefined"
                :options="versionOptions"
                size="small"
                style="width: 190px"
                @change="(value) => onVersionChange(Number(value))"
              />
            </div>
          </div>
          <p v-if="editingHistory" class="history-hint">
            正在编辑历史版本，保存后将生成新版本
          </p>
          <textarea
            v-model="form.systemPrompt"
            class="prompt-textarea"
            placeholder="填写系统提示词"
          />
        </section>

        <!-- 第二列：Agent 编排 -->
        <section class="col col--orch">
          <div class="col-head">
            <h4 class="col-title">Agent 编排</h4>
          </div>
          <div class="col-scroll">
            <AgentOrchestration
              :models="store.options?.models ?? []"
              :tools="store.options?.tools ?? []"
              :skills="store.options?.skills ?? []"
              :mcp-servers="store.options?.mcp_servers ?? []"
              :selected-model-id="form.modelId"
              :selected-tool-ids="selectedToolIds"
              :selected-skill-ids="selectedSkillIds"
              :selected-mcp-ids="selectedMcpIds"
              :show-model-error="showModelError"
              :disabled-bindings="disabledBindings"
              v-model:max-rounds="form.maxRounds"
              v-model:enable-deep-thinking="form.enableDeepThinking"
              v-model:thinking-level="form.thinkingLevel"
              v-model:auto-compact="form.autoCompact"
              v-model:compact-trigger-ratio="form.compactTriggerRatio"
              v-model:compact-keep-rounds="form.compactKeepRounds"
              v-model:compact-summary-target="form.compactSummaryTarget"
              @select-model="(id) => { form.modelId = id; showModelError = false }"
              @toggle-tool="onToggleTool"
              @toggle-skill="onToggleSkill"
              @toggle-mcp="onToggleMcp"
              @open-picker="openPicker"
            />
          </div>
        </section>

        <!-- 能力维护弹窗（FR-004a：关键词筛选 + 卡片多选） -->
        <ResourceSelectModal
          :open="pickerOpen"
          :title="pickerTitle"
          :options="pickerOptions"
          :selected-ids="pickerSelectedIds"
          @confirm="(ids) => applyPicker(ids)"
          @update:open="(v) => (pickerOpen = v)"
        />

        <!-- 第三列：预览与调试占位 -->
        <section class="col col--preview">
          <div class="col-head">
            <h4 class="col-title">预览与调试</h4>
          </div>
          <div class="preview-placeholder">
            <p class="preview-placeholder__text">本模块将在后续阶段开发</p>
            <p class="preview-placeholder__sub">Agent 完整对话功能完成后将嵌入到这里</p>
          </div>
        </section>
      </main>
    </div>
  </Modal>
</template>

<style scoped lang="scss">
.detail-page {
  display: flex;
  flex-direction: column;
  height: 100%;
  background: var(--bg-base);
}

.detail-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 14px 20px;
  border-bottom: 1px solid var(--border);
  background: var(--bg-surface);
}

.detail-title {
  margin: 0;
  font-size: 16px;
  font-weight: 600;
  color: var(--text-primary);
}

.detail-close {
  border: 1px solid var(--border);
  border-radius: 6px;
  background: var(--bg-surface);
  color: var(--text-secondary);
  font-size: 13px;
  padding: 4px 12px;
  cursor: pointer;

  &:hover {
    border-color: var(--border-hover);
    color: var(--text-primary);
  }
}

.detail-basic {
  padding: 14px 20px 4px;
}

.basic-row {
  display: flex;
  align-items: flex-start;
  gap: 14px;
}

.basic-item {
  flex: 0 0 220px;
  margin-bottom: 8px;
}

.basic-item--wide {
  flex: 1;
}

.basic-item--switch {
  flex: 0 0 auto;
  display: flex;
  flex-direction: column;
}

.basic-actions {
  display: flex;
  align-items: flex-end;
  padding-bottom: 8px;
  margin-left: auto;
}

.publish-btn {
  border: none;
  border-radius: 6px;
  background: var(--accent);
  color: var(--text-inverse);
  font-size: 13.5px;
  font-weight: 600;
  padding: 7px 22px;
  cursor: pointer;

  &:hover:not(:disabled) {
    background: var(--accent-hover);
  }

  &:disabled {
    opacity: 0.6;
    cursor: not-allowed;
  }
}

.detail-error {
  margin: 0 0 6px;
  font-size: 12.5px;
  color: var(--danger);
}

.detail-columns {
  flex: 1;
  display: grid;
  grid-template-columns: 1fr 1.15fr 1fr;
  gap: 14px;
  padding: 12px 20px 16px;
  min-height: 0;
}

.col {
  display: flex;
  flex-direction: column;
  min-height: 0;
  background: var(--bg-surface);
  border: 1px solid var(--border);
  border-radius: 10px;
  padding: 12px 14px;
}

.col-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 10px;
}

.col-title {
  margin: 0;
  font-size: 14px;
  font-weight: 600;
  color: var(--text-primary);
}

.col-scroll {
  flex: 1;
  overflow-y: auto;
  min-height: 0;
}

.history-hint {
  margin: -4px 0 8px;
  font-size: 12px;
  color: var(--warning);
}

.prompt-textarea {
  flex: 1;
  min-height: 0;
  resize: none;
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 10px 12px;
  font-size: 13px;
  font-family: var(--font-mono);
  line-height: 1.6;
  color: var(--text-primary);
  background: var(--bg-surface);

  &:focus {
    outline: none;
    border-color: var(--accent);
  }
}

.preview-placeholder {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 6px;
  border: 1px dashed var(--border-strong);
  border-radius: 8px;
  background: var(--bg-base);
}

.preview-placeholder__text {
  margin: 0;
  font-size: 14px;
  font-weight: 600;
  color: var(--text-secondary);
}

.preview-placeholder__sub {
  margin: 0;
  font-size: 12.5px;
  color: var(--text-tertiary);
}
</style>
