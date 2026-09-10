<script setup lang="ts">
/**
 * 新增/编辑模型弹窗表单。
 *
 * - 每字段配填写说明；预填默认值标注"建议值，以服务商说明为准"（FR-005）
 * - 服务地址示例说明 /v1 写法，拦截误填完整 /chat/completions（FR-006）
 * - 编辑时密钥框留空 + "已配置，留空则保留原密钥"提示（FR-012）
 * - 校验失败在字段旁显示原因（FR-008）
 */
import { computed, reactive, ref, watch } from 'vue'

import {
  Alert,
  Form,
  FormItem,
  Input,
  InputNumber,
  InputPassword,
  Modal,
} from 'ant-design-vue'

import type { ModelDetail, ModelUpsertPayload } from '@/api/models'
import { modelsApi } from '@/api/models'
import { buildFormRules } from './formRules'

const props = defineProps<{
  /** 打开状态（v-model:open） */
  open: boolean
  /** 编辑对象；null = 新增 */
  model: ModelDetail | null
}>()

const emit = defineEmits<{
  'update:open': [value: boolean]
  /** 保存成功后通知父级刷新 */
  saved: []
}>()

const SUGGEST_CONTEXT = 8192
const SUGGEST_MAX_OUTPUT = 4096
const SUGGEST_TEMPERATURE = 0.7
const isEdit = computed(() => props.model !== null)

const formState = reactive({
  display_name: '',
  model_identifier: '',
  base_url: '',
  api_key: null as string | null,
  context_length: undefined as number | undefined,
  max_output_tokens: undefined as number | undefined,
  temperature: SUGGEST_TEMPERATURE as number | undefined,
  input_price: undefined as number | undefined,
  output_price: undefined as number | undefined,
  cached_input_price: undefined as number | undefined,
})

const submitting = ref(false)
const saveError = ref<string | null>(null)
const formRef = ref()

const rules = buildFormRules(
  () => formState.base_url,
  () => formState.context_length ?? null,
)

watch(
  () => props.open,
  (open) => {
    if (!open) return
    saveError.value = null
    const m = props.model
    if (m) {
      Object.assign(formState, {
        display_name: m.display_name,
        model_identifier: m.model_identifier,
        base_url: m.base_url,
        api_key: null, // 已配置密钥的输入框保持为空（FR-012）
        context_length: m.context_length,
        max_output_tokens: m.max_output_tokens,
        temperature: m.temperature,
        input_price: m.input_price ?? undefined,
        output_price: m.output_price ?? undefined,
        cached_input_price: m.cached_input_price ?? undefined,
      })
    } else {
      Object.assign(formState, {
        display_name: '',
        model_identifier: '',
        base_url: '',
        api_key: null,
        // 建议值（spec：默认值明确标注为建议值，以服务商说明为准）
        context_length: SUGGEST_CONTEXT,
        max_output_tokens: SUGGEST_MAX_OUTPUT,
        temperature: SUGGEST_TEMPERATURE,
        input_price: undefined,
        output_price: undefined,
        cached_input_price: undefined,
      })
    }
    formRef.value?.clearValidate()
  },
)

function handleClose(): void {
  emit('update:open', false)
}

async function handleSave(): Promise<void> {
  const valid = await formRef.value?.validate().catch(() => false)
  if (!valid) return
  submitting.value = true
  saveError.value = null
  try {
    const payload: ModelUpsertPayload = {
      display_name: formState.display_name.trim(),
      model_identifier: formState.model_identifier.trim(),
      base_url: formState.base_url.trim(),
      api_key: formState.api_key?.trim() ? formState.api_key.trim() : null,
      context_length: formState.context_length!,
      max_output_tokens: formState.max_output_tokens!,
      temperature: formState.temperature!,
      // 留空（undefined）在契约中为 null = 未配置；0 = 免费
      input_price: formState.input_price ?? null,
      output_price: formState.output_price ?? null,
      cached_input_price: formState.cached_input_price ?? null,
    }
    if (props.model) {
      await modelsApi.update(props.model.id, payload)
    } else {
      await modelsApi.create(payload)
    }
    emit('saved')
    handleClose()
  } catch (e) {
    saveError.value = e instanceof Error ? e.message : '保存失败，请稍后重试'
  } finally {
    submitting.value = false
  }
}
</script>

<template>
  <Modal
    :open="open"
    :title="isEdit ? '编辑模型' : '新增模型'"
    :confirm-loading="submitting"
    ok-text="保存"
    cancel-text="取消"
    :width="560"
    :mask-closable="false"
    @ok="handleSave"
    @cancel="handleClose"
  >
    <Form ref="formRef" :model="formState" :rules="rules" layout="vertical" class="model-form">
      <FormItem label="显示名称" name="display_name">
        <Input v-model:value="formState.display_name" placeholder="如：通义千问 Plus" />
        <span class="field-hint">用于在页面中识别模型</span>
      </FormItem>

      <FormItem label="模型标识" name="model_identifier">
        <Input v-model:value="formState.model_identifier" placeholder="如：qwen-plus" />
        <span class="field-hint">请求接口时使用的模型名称，需与服务商提供的标识一致</span>
      </FormItem>

      <FormItem label="服务地址" name="base_url">
        <Input v-model:value="formState.base_url" placeholder="https://api.example.com/v1" />
        <span class="field-hint">
          API Base URL，一般以 /v1 结尾（如 https://api.example.com/v1）；无需包含
          /chat/completions
        </span>
      </FormItem>

      <FormItem label="API Key" name="api_key">
        <InputPassword
          :value="formState.api_key ?? undefined"
          placeholder="sk-..."
          autocomplete="new-password"
          @update:value="(v: string) => (formState.api_key = v)"
        />
        <span v-if="isEdit && model?.api_key_configured" class="field-hint key-configured">
          已配置，留空则保留原密钥
        </span>
        <span v-else class="field-hint">调用模型服务所需的密钥，加密保存在本机</span>
      </FormItem>

      <div class="field-row">
        <FormItem label="上下文长度" name="context_length">
          <InputNumber
            v-model:value="formState.context_length"
            :min="1"
            :precision="0"
            class="field-number"
          />
          <span class="field-hint">
            建议值 {{ SUGGEST_CONTEXT }}，单位 token，以服务商说明为准
          </span>
        </FormItem>

        <FormItem label="最大输出长度" name="max_output_tokens">
          <InputNumber
            v-model:value="formState.max_output_tokens"
            :min="1"
            :precision="0"
            class="field-number"
          />
          <span class="field-hint">
            建议值 {{ SUGGEST_MAX_OUTPUT }}，单次生成上限，不得超过上下文长度
          </span>
        </FormItem>

        <FormItem label="温度" name="temperature">
          <InputNumber
            v-model:value="formState.temperature"
            :min="0"
            :max="2"
            :step="0.1"
            class="field-number"
          />
          <span class="field-hint">建议值 {{ SUGGEST_TEMPERATURE }}，0–2，越高输出越随机</span>
        </FormItem>
      </div>

      <div class="field-row">
        <FormItem label="输入单价" name="input_price">
          <InputNumber
            v-model:value="formState.input_price"
            :min="0"
            :step="0.1"
            class="field-number"
          />
          <span class="field-hint">元 / 百万输入 token，可留空</span>
        </FormItem>

        <FormItem label="输出单价" name="output_price">
          <InputNumber
            v-model:value="formState.output_price"
            :min="0"
            :step="0.1"
            class="field-number"
          />
          <span class="field-hint">元 / 百万输出 token，可留空</span>
        </FormItem>

        <FormItem label="缓存命中输入单价" name="cached_input_price">
          <InputNumber
            v-model:value="formState.cached_input_price"
            :min="0"
            :step="0.1"
            class="field-number"
          />
          <span class="field-hint">元 / 百万缓存命中 token，可留空</span>
        </FormItem>
      </div>

      <Alert
        v-if="saveError"
        :message="saveError"
        type="error"
        show-icon
        closable
        class="form-error"
      />
    </Form>
  </Modal>
</template>

<style scoped lang="scss">
.model-form {
  .field-hint {
    display: block;
    font-size: 12px; // 辅助说明规格
    line-height: 1.5;
    color: var(--text-tertiary);
    margin-top: 2px;
  }

  .key-configured {
    color: var(--warning);
  }

  .field-row {
    display: grid;
    grid-template-columns: repeat(3, 1fr);
    gap: 12px;
  }

  .field-number {
    width: 100%;
  }

  .form-error {
    margin-top: 8px;
  }
}
</style>
