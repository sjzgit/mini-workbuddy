<script setup lang="ts">
/**
 * MCP Server 新增/编辑表单（004 FR-018~020 + 006：类型文案 stdio、JSON 导入、保存校验修复）。
 * 类型切换 stdio/http 两组字段；参数列表保序；env/headers 值留空 = 保留原值（三态协议）。
 * 保存校验：Form 绑 :model + 校验型 FormItem 带 name（006 research R1——缺失即 validate 静默失败）。
 */
import { computed, reactive, ref, watch } from 'vue'

import {
  Form,
  FormItem,
  Input,
  Modal,
  RadioButton,
  RadioGroup,
  Textarea,
  message,
} from 'ant-design-vue'
import { MinusCircleOutlined, PlusOutlined } from '@ant-design/icons-vue'
import type { Rule } from 'ant-design-vue/es/form'

import type { McpServerDetail, McpServerUpsertPayload, ServerType } from '@/api/mcp'
import { mcpApi } from '@/api/mcp'
import { parseMcpJson } from '@/components/mcp/jsonImport'

const props = defineProps<{
  open: boolean
  /** null = 新增 */
  server: McpServerDetail | null
}>()
const emit = defineEmits<{
  'update:open': [value: boolean]
  saved: [id: number]
}>()

const saving = ref(false)

type KvRow = { key: string; value: string; keep: boolean }

const form = reactive({
  name: '',
  description: '',
  serverType: 'stdio' as ServerType,
  command: '',
  args: [] as string[],
  env: [] as KvRow[],
  url: '',
  headers: [] as KvRow[],
})

// JSON 导入输入框（006 US3）。必须在下方 immediate watch 之前声明——
// watch 回调会重置它，声明靠后会因 const 暂时性死区抛 ReferenceError
const jsonInput = ref('')

const modalOpen = computed({
  get: () => props.open,
  set: (value: boolean) => emit('update:open', value),
})

watch(
  () => props.server,
  (server) => {
    form.name = server?.name ?? ''
    form.description = server?.description ?? ''
    form.serverType = server?.server_type ?? 'stdio'
    form.command = server?.command ?? ''
    form.args = server?.command_args ? [...server.command_args] : []
    // 编辑时值一律留空：提交 null = 保留原值（掩码永不进表单值，FR-024）
    form.env = toKvRows(server?.env_masked ?? null)
    form.url = server?.url ?? ''
    form.headers = toKvRows(server?.headers_masked ?? null)
    jsonInput.value = ''
  },
  { immediate: true },
)

function toKvRows(masked: Record<string, string> | null): KvRow[] {
  if (!masked) return []
  return Object.keys(masked).map((key) => ({ key, value: '', keep: true }))
}

function addArg(): void {
  form.args.push('')
}

function removeArg(index: number): void {
  form.args.splice(index, 1)
}

function moveArg(index: number, delta: number): void {
  const target = index + delta
  if (target < 0 || target >= form.args.length) return
  const [row] = form.args.splice(index, 1)
  if (row === undefined) return
  form.args.splice(target, 0, row)
}

function addKv(rows: KvRow[]): void {
  rows.push({ key: '', value: '', keep: false })
}

function removeKv(rows: KvRow[], index: number): void {
  rows.splice(index, 1)
}

/** 表单行 → 三态提交体：有原值且留空 = null（保留）；新填 = 字符串 */
function kvToPayload(rows: KvRow[]): Record<string, string | null> {
  const result: Record<string, string | null> = {}
  for (const row of rows) {
    const key = row.key.trim()
    if (!key) continue
    result[key] = row.value === '' && row.keep ? null : row.value
  }
  return result
}

const nameRule: Rule[] = [
  { required: true, whitespace: true, message: '请输入名称' },
  { max: 100, message: '名称最长 100 字符' },
]

function urlRule(_rule: unknown, value: string): Promise<void> {
  if (form.serverType !== 'http' || !value) return Promise.resolve()
  try {
    const parsed = new URL(value)
    if (parsed.protocol !== 'http:' && parsed.protocol !== 'https:') {
      return Promise.reject('url 仅支持 http/https')
    }
    return Promise.resolve()
  } catch {
    return Promise.reject('url 格式不合法，如 http://127.0.0.1:9300/mcp')
  }
}

// ---- JSON 导入（006 US3，契约 json-import.md）----

const JSON_PLACEHOLDER = `{
  "name": "filesystem",
  "description": "filesystem",
  "transport": "stdio",
  "command": "npx",
  "args": ["-y", "@modelcontextprotocol/server-filesystem"],
  "env": {}
}`

function handleParseJson(): void {
  const result = parseMcpJson(jsonInput.value)
  if (!result.ok) {
    message.warning(result.reason)
    return // 表单零改动（契约 §4）
  }
  const { form: parsed } = result
  let count = 0
  if (parsed.name !== undefined) {
    form.name = parsed.name
    count += 1
  }
  if (parsed.description !== undefined) {
    form.description = parsed.description
    count += 1
  }
  if (parsed.command !== undefined) {
    form.command = parsed.command
    count += 1
  }
  if (parsed.args !== undefined) {
    form.args = [...parsed.args]
    count += 1
  }
  if (parsed.env !== undefined) {
    form.env = Object.keys(parsed.env).map((key) => ({
      key,
      value: parsed.env![key] ?? '',
      keep: false, // 导入值视为新值
    }))
    count += 1
  }
  message.success(`已导入 ${count} 个字段`)
  jsonInput.value = ''
}

const formRef = ref()

async function handleSubmit(): Promise<void> {
  const valid = await formRef.value?.validate().catch(() => false)
  if (!valid) return
  saving.value = true
  const payload: McpServerUpsertPayload = {
    name: form.name.trim(),
    description: form.description,
    server_type: form.serverType,
    command: form.serverType === 'stdio' ? form.command.trim() : null,
    command_args:
      form.serverType === 'stdio'
        ? form.args.map((arg) => arg).filter((arg) => arg !== '')
        : null,
    env: form.serverType === 'stdio' ? kvToPayload(form.env) : null,
    url: form.serverType === 'http' ? form.url.trim() : null,
    headers: form.serverType === 'http' ? kvToPayload(form.headers) : null,
  }
  try {
    if (props.server) {
      await mcpApi.update(props.server.id, payload)
      message.success(`已保存「${payload.name}」`)
      emit('saved', props.server.id)
    } else {
      const created = await mcpApi.create(payload)
      message.success(`已新增「${created.name}」，可点击「测试」验证连接`)
      emit('saved', created.id)
    }
    modalOpen.value = false
  } catch (e) {
    message.error(e instanceof Error ? e.message : '保存失败')
  } finally {
    saving.value = false
  }
}
</script>

<template>
  <Modal
    v-model:open="modalOpen"
    :title="server ? `编辑 Server：${server.name}` : '新增 MCP Server'"
    width="720"
    :confirm-loading="saving"
    ok-text="保存"
    cancel-text="取消"
    @ok="handleSubmit"
  >
    <div class="field-guide">
      各字段配置通常可以从 MCP Server 的使用说明中获取，无需理解协议细节。
    </div>

    <Form ref="formRef" :model="form" layout="vertical">
      <FormItem label="名称" name="name" :rules="nameRule" required>
        <Input v-model:value="form.name" placeholder="用于在列表中识别该 Server" />
      </FormItem>
      <FormItem label="说明" name="description">
        <Input v-model:value="form.description" placeholder="描述该 Server 的用途（可选）" />
      </FormItem>
      <FormItem label="类型" name="serverType" required>
        <RadioGroup v-model:value="form.serverType">
          <RadioButton value="stdio">stdio</RadioButton>
          <RadioButton value="http">远程 HTTP</RadioButton>
        </RadioGroup>
      </FormItem>

      <template v-if="form.serverType === 'stdio'">
        <!-- JSON 导入区（006 US3：仅 stdio 展示） -->
        <div class="json-import">
          <div class="json-import__header">JSON 导入（粘贴 stdio 配置后解析填充下方字段）</div>
          <Textarea
            v-model:value="jsonInput"
            :rows="6"
            class="json-import__input"
            :placeholder="JSON_PLACEHOLDER"
          />
          <button class="add-btn" type="button" @click="handleParseJson">
            解析 JSON
          </button>
        </div>

        <FormItem label="启动命令" name="command" required>
          <Input v-model:value="form.command" placeholder="如 npx 或 C:\tools\server.exe" />
          <div class="field-hint">可执行文件名称或路径；与参数分开保存、直接传给进程，不经 Shell 拼接。</div>
        </FormItem>
        <FormItem label="启动参数" name="args">
          <div class="arg-list">
            <div v-for="(_arg, index) in form.args" :key="index" class="arg-row">
              <Input v-model:value="form.args[index]" placeholder="一项参数，如 -y" />
              <button class="icon-btn" type="button" title="上移" :disabled="index === 0" @click="moveArg(index, -1)">↑</button>
              <button
                class="icon-btn"
                type="button"
                title="下移"
                :disabled="index === form.args.length - 1"
                @click="moveArg(index, 1)"
              >
                ↓
              </button>
              <MinusCircleOutlined class="icon-remove" @click="removeArg(index)" />
            </div>
            <button class="add-btn" type="button" @click="addArg">
              <PlusOutlined /> 添加参数
            </button>
            <div class="field-hint">按顺序逐项填写（示例：-y、@modelcontextprotocol/server-filesystem、C:\data），顺序即传参顺序。</div>
          </div>
        </FormItem>
        <FormItem label="环境变量（可选）" name="env">
          <div class="kv-list">
            <div v-for="(row, index) in form.env" :key="index" class="kv-row">
              <Input v-model:value="row.key" placeholder="键，如 API_TOKEN" class="kv-key" />
              <Input
                v-model:value="row.value"
                :placeholder="row.keep ? '已配置：留空保留原值' : '值'"
              />
              <MinusCircleOutlined class="icon-remove" @click="removeKv(form.env, index)" />
            </div>
            <button class="add-btn" type="button" @click="addKv(form.env)">
              <PlusOutlined /> 添加环境变量
            </button>
            <div class="field-hint">值可能包含密钥：保存后仅以掩码展示，编辑时留空即保留原值。</div>
          </div>
        </FormItem>
      </template>

      <template v-else>
        <FormItem
          label="url"
          name="url"
          required
          :rules="[{ validator: urlRule, trigger: 'blur' }]"
        >
          <Input v-model:value="form.url" placeholder="如 http://127.0.0.1:9300/mcp" />
          <div class="field-hint">MCP Server 地址（http/https）。</div>
        </FormItem>
        <FormItem label="请求 Header（可选）" name="headers">
          <div class="kv-list">
            <div v-for="(row, index) in form.headers" :key="index" class="kv-row">
              <Input v-model:value="row.key" placeholder="键，如 Authorization" class="kv-key" />
              <Input
                v-model:value="row.value"
                :placeholder="row.keep ? '已配置：留空保留原值' : '值'"
              />
              <MinusCircleOutlined class="icon-remove" @click="removeKv(form.headers, index)" />
            </div>
            <button class="add-btn" type="button" @click="addKv(form.headers)">
              <PlusOutlined /> 添加 Header
            </button>
            <div class="field-hint">值可能包含令牌：保存后仅以掩码展示，编辑时留空即保留原值。</div>
          </div>
        </FormItem>
      </template>
    </Form>
  </Modal>
</template>

<style scoped lang="scss">
.field-guide {
  font-size: 12.5px; // 辅助说明规格
  color: var(--text-secondary);
  background: var(--accent-dim);
  border-radius: 6px;
  padding: 8px 12px;
  margin-bottom: 16px;
}

.json-import {
  border: 1px dashed var(--border-strong);
  border-radius: 8px;
  padding: 10px 12px;
  margin-bottom: 16px;
  display: flex;
  flex-direction: column;
  gap: 8px;

  &__header {
    font-size: 13px;
    font-weight: 600;
    color: var(--text-primary);
  }

  &__input {
    font-family: var(--font-mono);
    font-size: 13px; // 代码规格
  }
}

.field-hint {
  font-size: 12px;
  color: var(--text-tertiary);
  margin-top: 4px;
}

.arg-list,
.kv-list {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.arg-row,
.kv-row {
  display: flex;
  align-items: center;
  gap: 6px;
}

.kv-key {
  max-width: 200px;
}

.icon-btn {
  background: var(--bg-surface);
  border: 1px solid var(--border);
  border-radius: 4px;
  color: var(--text-secondary);
  font-size: 12px;
  width: 26px;
  height: 26px;
  cursor: pointer;

  &:disabled {
    opacity: 0.4;
    cursor: not-allowed;
  }
}

.icon-remove {
  color: var(--text-tertiary);
  cursor: pointer;

  &:hover {
    color: var(--danger);
  }
}

.add-btn {
  align-self: flex-start;
  background: none;
  border: 1px dashed var(--border-strong);
  border-radius: 6px;
  color: var(--text-secondary);
  font-size: 13px; // 按钮规格
  padding: 4px 12px;
  cursor: pointer;
  margin-top: 4px;

  &:hover {
    color: var(--accent);
    border-color: var(--accent);
  }
}
</style>
