<script setup lang="ts">
/**
 * Agent 编排列（详情 dialog 第二列，FR-011/013/014/015/004a）：
 * 模型卡片单选（无模型时引导）→ 工具/Skills/MCP"维护"弹窗选择 → 最大执行轮数 → 停用绑定区。
 */
import { computed } from 'vue'

import { Button, InputNumber, RadioButton, RadioGroup, Switch, message } from 'ant-design-vue'
import { useRouter } from 'vue-router'

import type { BindingItem, BindingOption, ModelOption, ThinkingLevel } from '@/api/agents'

const props = defineProps<{
  models: ModelOption[]
  tools: BindingOption[]
  skills: BindingOption[]
  mcpServers: BindingOption[]
  selectedModelId: number | null
  selectedToolIds: Set<number>
  selectedSkillIds: Set<number>
  selectedMcpIds: Set<number>
  maxRounds: number
  showModelError: boolean
  /** 已绑定但资源被停用的绑定（US5：标记"已停用，不可用"，可手动移除） */
  disabledBindings: BindingItem[]
}>()

const emit = defineEmits<{
  'select-model': [id: number]
  'toggle-tool': [id: number, checked: boolean]
  'toggle-skill': [id: number, checked: boolean]
  'toggle-mcp': [id: number, checked: boolean]
  /** 请求打开某类资源的维护弹窗 */
  'open-picker': [type: 'tool' | 'skill' | 'mcp']
}>()

const maxRoundsModel = defineModel<number>('maxRounds', { required: true })
const enableDeepThinkingModel = defineModel<boolean>('enableDeepThinking', { required: true })
const thinkingLevelModel = defineModel<ThinkingLevel>('thinkingLevel', { required: true })
// 011：上下文压缩配置
const autoCompactModel = defineModel<boolean>('autoCompact', { required: true })
const compactTriggerRatioModel = defineModel<number>('compactTriggerRatio', { required: true })
const compactKeepRoundsModel = defineModel<number>('compactKeepRounds', { required: true })
const compactSummaryTargetModel = defineModel<number>('compactSummaryTarget', { required: true })

const router = useRouter()

const hasModels = computed(() => props.models.length > 0)

/** 每类已选项名称（表单区概要展示用） */
const selectedToolNames = computed(
  () => props.tools.filter((t) => props.selectedToolIds.has(t.id)).map((t) => t.name),
)
const selectedSkillNames = computed(
  () => props.skills.filter((s) => props.selectedSkillIds.has(s.id)).map((s) => s.name),
)
const selectedMcpNames = computed(
  () => props.mcpServers.filter((m) => props.selectedMcpIds.has(m.id)).map((m) => m.name),
)

function onSelectModel(id: number): void {
  emit('select-model', id)
}

/** 移除一个已停用的绑定（保存时即从提交集合中消失） */
function removeDisabled(type: BindingItem['resource_type'], id: number): void {
  if (type === 'tool') {
    emit('toggle-tool', id, false)
  } else if (type === 'skill') {
    emit('toggle-skill', id, false)
  } else {
    emit('toggle-mcp', id, false)
  }
}

function goModels(): void {
  void router.push('/models')
  message.success('添加模型后返回继续配置 Agent')
}

function isSelected(type: 'tool' | 'skill' | 'mcp', id: number): boolean {
  if (type === 'tool') return props.selectedToolIds.has(id)
  if (type === 'skill') return props.selectedSkillIds.has(id)
  return props.selectedMcpIds.has(id)
}

function toggleResource(type: 'tool' | 'skill' | 'mcp', id: number, checked: boolean): void {
  if (type === 'tool') emit('toggle-tool', id, checked)
  else if (type === 'skill') emit('toggle-skill', id, checked)
  else emit('toggle-mcp', id, checked)
}
</script>

<template>
  <div class="orchestration">
    <section class="orch-section">
      <h4 class="orch-title">模型 <span class="orch-req">*</span></h4>
      <div v-if="hasModels" class="model-cards">
        <button
          v-for="model in models"
          :key="model.id"
          type="button"
          class="model-card"
          :class="{ 'model-card--selected': model.id === selectedModelId }"
          @click="onSelectModel(model.id)"
        >
          <span class="model-card__name">
            {{ model.display_name }}
            <span v-if="model.is_default" class="model-card__default">默认</span>
          </span>
          <span class="model-card__identifier">{{ model.model_identifier }}</span>
        </button>
      </div>
      <div v-else class="model-guide">
        <p class="model-guide__text">还没有可用模型，请先前往模型管理添加。</p>
        <Button type="primary" size="small" @click="goModels">前往模型管理</Button>
      </div>
      <p v-if="showModelError" class="orch-error">请选择模型</p>
    </section>

    <section class="orch-section">
      <h4 class="orch-title">深度思考</h4>
      <div class="thinking-row">
        <span class="thinking-switch-label">
          <Switch v-model:checked="enableDeepThinkingModel" size="small" />
          深度思考
        </span>
        <RadioGroup v-model:value="thinkingLevelModel" size="small" class="thinking-level">
          <RadioButton value="off">关闭</RadioButton>
          <RadioButton value="low">低</RadioButton>
          <RadioButton value="medium">中</RadioButton>
          <RadioButton value="high">高</RadioButton>
        </RadioGroup>
      </div>
    </section>

    <section class="orch-section">
      <h4 class="orch-title">上下文压缩</h4>
      <div class="compact-row">
        <span class="thinking-switch-label">
          <Switch v-model:checked="autoCompactModel" size="small" />
          自动压缩
        </span>
      </div>
      <p class="orch-hint">会话接近模型上下文容量时，自动把较早对话整理为摘要。</p>
      <template v-if="autoCompactModel">
        <div class="compact-field">
          <span class="compact-label">触发比例</span>
          <InputNumber
            v-model:value="compactTriggerRatioModel"
            :min="0.5" :max="0.95" :step="0.05" size="small"
          />
        </div>
        <p class="orch-hint">估算输入达到可用容量的该比例时触发压缩。</p>
        <div class="compact-field">
          <span class="compact-label">保留最近对话轮数</span>
          <InputNumber
            v-model:value="compactKeepRoundsModel"
            :min="1" :max="50" :precision="0" size="small"
          />
        </div>
        <p class="orch-hint">压缩时完整保留最近 N 轮对话（含工具交互）。</p>
        <div class="compact-field">
          <span class="compact-label">摘要目标长度</span>
          <InputNumber
            v-model:value="compactSummaryTargetModel"
            :min="100" :max="8000" :precision="0" size="small"
          />
        </div>
        <p class="orch-hint">生成摘要的目标长度（估算值，不保证精确等长）；小窗口模型下会自动受限。</p>
      </template>
    </section>

    <section class="orch-section">
      <h4 class="orch-title">工具</h4>
      <div class="picker-row">
        <span class="picker-summary">
          已选 {{ selectedToolIds.size }} 项<template v-if="selectedToolNames.length">：{{ selectedToolNames.join('、') }}</template>
        </span>
        <button type="button" class="maintain-btn" @click="emit('open-picker', 'tool')">维护</button>
      </div>
    </section>

    <section class="orch-section">
      <h4 class="orch-title">Skills</h4>
      <div class="picker-row">
        <span class="picker-summary">
          已选 {{ selectedSkillIds.size }} 项<template v-if="selectedSkillNames.length">：{{ selectedSkillNames.join('、') }}</template>
        </span>
        <button type="button" class="maintain-btn" @click="emit('open-picker', 'skill')">维护</button>
      </div>
    </section>

    <section class="orch-section">
      <h4 class="orch-title">MCP Server</h4>
      <div class="picker-row">
        <span class="picker-summary">
          已选 {{ selectedMcpIds.size }} 项<template v-if="selectedMcpNames.length">：{{ selectedMcpNames.join('、') }}</template>
        </span>
        <button type="button" class="maintain-btn" @click="emit('open-picker', 'mcp')">维护</button>
      </div>
    </section>

    <section class="orch-section">
      <h4 class="orch-title">最大执行轮数</h4>
      <div class="rounds-row">
        <InputNumber
          v-model:value="maxRoundsModel"
          :min="1"
          :max="100"
          :precision="0"
          class="rounds-input"
        />
        <span class="rounds-hint">正整数，1~100</span>
      </div>
    </section>

    <section v-if="disabledBindings.length" class="orch-section">
      <h4 class="orch-title">已停用的绑定</h4>
      <p class="disabled-hint">
        以下能力已被停用但仍在配置中（卡片计数包含它们）；可移除，也可保留保存。
      </p>
      <div class="disabled-list">
        <span
          v-for="binding in disabledBindings"
          :key="`${binding.resource_type}-${binding.resource_id}`"
          class="disabled-chip"
        >
          <span class="disabled-chip__name">{{ binding.name }}</span>
          <span class="disabled-chip__tag">已停用，不可用</span>
          <button
            type="button"
            class="disabled-chip__remove"
            @click="removeDisabled(binding.resource_type, binding.resource_id)"
          >移除</button>
        </span>
      </div>
    </section>
  </div>
</template>

<style scoped lang="scss">
.compact-row { display: flex; align-items: center; }

.compact-field { display: flex; align-items: center; gap: 10px; }

.compact-label {
  font-size: 13px;
  color: var(--text-secondary);
  min-width: 9em;
}

.orch-hint {
  margin: 0;
  font-size: 12px;
  color: var(--text-tertiary);
  line-height: 1.5;
}

.orchestration {
  display: flex;
  flex-direction: column;
  gap: 20px;
}

.orch-section {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.orch-title {
  margin: 0;
  font-size: 13.5px;
  font-weight: 600;
  color: var(--text-primary);
}

.orch-req {
  color: var(--danger);
}

.orch-error {
  margin: 0;
  font-size: 12.5px;
  color: var(--danger);
}

.model-cards {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.model-card {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: 2px;
  padding: 10px 12px;
  border: 1px solid var(--border);
  border-radius: 8px;
  background: var(--bg-surface);
  cursor: pointer;
  text-align: left;
  transition: border-color 0.15s ease, background 0.15s ease;

  &:hover {
    border-color: var(--border-hover);
    background: var(--bg-hover);
  }

  &--selected {
    border-color: var(--accent);
    background: var(--accent-dim);
  }
}

.model-card__name {
  font-size: 14px;
  font-weight: 600;
  color: var(--text-primary);
  display: flex;
  align-items: center;
  gap: 8px;
}

.model-card__default {
  font-size: 11px;
  font-weight: 500;
  color: var(--accent);
  border: 1px solid var(--accent);
  border-radius: 4px;
  padding: 0 4px;
  line-height: 1.4;
}

.model-card__identifier {
  font-family: var(--font-mono);
  font-size: 12.5px;
  color: var(--text-secondary);
}

.model-guide {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: 8px;
  padding: 12px;
  border: 1px dashed var(--border-strong);
  border-radius: 8px;
  background: var(--bg-base);
}

.model-guide__text {
  margin: 0;
  font-size: 13px;
  color: var(--text-secondary);
}

.picker-row {
  display: flex;
  align-items: flex-start;
  gap: 10px;
  padding: 10px 12px;
  border: 1px dashed var(--border);
  border-radius: 8px;
  background: var(--bg-base);
}

.thinking-row {
  display: flex;
  align-items: center;
  gap: 16px;
  flex-wrap: wrap;
}

.thinking-switch-label {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  font-size: 13px;
  color: var(--text-primary);
}

.thinking-level {
  display: inline-flex;
}

.picker-summary {
  flex: 1;
  min-width: 0;
  font-size: 12.5px;
  color: var(--text-secondary);
  line-height: 1.5;
  word-break: break-all;
}

.maintain-btn {
  flex: 0 0 auto;
  border: 1px solid var(--border);
  border-radius: 6px;
  background: var(--bg-surface);
  color: var(--accent);
  font-size: 12.5px;
  padding: 3px 12px;
  cursor: pointer;

  &:hover {
    border-color: var(--accent);
  }
}

.rounds-row {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
}

.rounds-input {
  width: 120px;
}

.rounds-hint {
  font-size: 12.5px;
  color: var(--text-tertiary);
}

.disabled-hint {
  margin: 0;
  font-size: 12px;
  color: var(--warning);
}

.disabled-list {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.disabled-chip {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 3px 8px;
  border: 1px dashed var(--border-strong);
  border-radius: 6px;
  background: var(--bg-hover);
}

.disabled-chip__name {
  font-size: 12.5px;
  color: var(--text-secondary);
  text-decoration: line-through;
}

.disabled-chip__tag {
  font-size: 11px;
  color: var(--warning);
}

.disabled-chip__remove {
  border: none;
  background: none;
  padding: 0;
  font-size: 12px;
  color: var(--danger);
  cursor: pointer;
}
</style>
