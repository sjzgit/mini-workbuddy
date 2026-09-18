<script setup lang="ts">
/**
 * Skill 详情大对话框（spec 005 US1–US3，FR-001~013）：
 * 上区 = 基础信息（名称/描述可编辑并单独保存——描述为文本域；启用开关即时生效；目录名/更新时间只读）。
 * 下区 = 左目录树（浏览，目录仅展开/收起——点目录不触发文件读取）+ 右 textarea 在线编辑区（保存写回文件）。
 * 替换 004 的 SkillEditDrawer（research R4@005：形态随内容升级为大 Modal）。
 */
import { computed, h, ref, watch } from 'vue'

import {
  Form,
  FormItem,
  Input,
  Modal,
  Switch,
  Textarea,
  Tree,
  message,
} from 'ant-design-vue'
import type { Rule } from 'ant-design-vue/es/form'
import type { TreeProps } from 'ant-design-vue'
import {
  FileOutlined,
  FolderOutlined,
  ReloadOutlined,
  SaveOutlined,
} from '@ant-design/icons-vue'

import type { SkillDetail, SkillFileContent, SkillFileNode, SkillItem } from '@/api/skills'
import { skillsApi } from '@/api/skills'
import { useSkillsStore } from '@/stores/skills'

const props = defineProps<{
  open: boolean
  skill: SkillDetail | null
}>()
const emit = defineEmits<{
  'update:open': [value: boolean]
  /** 基础信息保存后通知列表刷新该行 */
  basicSaved: [updated: SkillItem]
}>()

const store = useSkillsStore()

const modalOpen = computed({
  get: () => props.open,
  set: (value: boolean) => emit('update:open', value),
})

// ---- 上区：基础信息 ----
const basic = ref({ name: '', description: '' })
/** 启用状态的本地镜像（切换即时反馈，成功后与列表同步） */
const enabledLocal = ref(false)
const savingBasic = ref(false)

watch(
  () => props.skill,
  (skill) => {
    basic.value = { name: skill?.name ?? '', description: skill?.description ?? '' }
    enabledLocal.value = skill?.enabled ?? false
  },
  { immediate: true },
)

const nameRule: Rule[] = [
  { required: true, whitespace: true, message: '请输入 Skill 名称' },
  { max: 100, message: '名称最长 100 字符' },
]

async function handleSaveBasic(): Promise<void> {
  if (!props.skill) return
  savingBasic.value = true
  try {
    const updated = await skillsApi.update(props.skill.dir_name, {
      name: basic.value.name.trim(),
      description: basic.value.description,
      instruction: props.skill.instruction,
    })
    store.replaceItem(updated)
    message.success('基础信息已保存')
    emit('basicSaved', updated)
  } catch (e) {
    message.error(e instanceof Error ? e.message : '保存基础信息失败')
  } finally {
    savingBasic.value = false
  }
}

async function handleToggleEnabled(next: boolean): Promise<void> {
  if (!props.skill) return
  try {
    const updated = await skillsApi.setEnabled(props.skill.dir_name, next)
    enabledLocal.value = updated.enabled
    store.replaceItem(updated)
    message.success(next ? '已启用' : '已停用')
  } catch (e) {
    enabledLocal.value = !next // 失败回滚开关
    message.error(e instanceof Error ? e.message : '操作失败')
  }
}

// ---- 下区左：目录树 ----
const treeData = ref<SkillFileNode[]>([])
const treeLoading = ref(false)
const expandedKeys = ref<string[]>([])

interface AntTreeNode {
  key: string
  title: string
  isLeaf: boolean
  children?: AntTreeNode[]
  /** 目录/文件图标（数据级 icon，antd Tree 直接渲染，需求 3） */
  icon: ReturnType<typeof h>
}

function toAntTree(nodes: SkillFileNode[]): AntTreeNode[] {
  return nodes.map((node) => ({
    key: node.path,
    title: node.name,
    isLeaf: node.type === 'file',
    icon: h(
      node.type === 'dir' ? FolderOutlined : FileOutlined,
      { class: node.type === 'dir' ? 'tree-icon tree-icon--dir' : 'tree-icon tree-icon--file' },
    ),
    children: node.children.length > 0 ? toAntTree(node.children) : undefined,
  }))
}

async function loadTree(): Promise<void> {
  if (!props.skill) return
  treeLoading.value = true
  try {
    treeData.value = await skillsApi.tree(props.skill.dir_name)
    expandedKeys.value = collectDirKeys(treeData.value)
  } catch (e) {
    message.error(e instanceof Error ? e.message : '读取目录结构失败')
  } finally {
    treeLoading.value = false
  }
}

function collectDirKeys(nodes: SkillFileNode[]): string[] {
  const keys: string[] = []
  for (const node of nodes) {
    if (node.type === 'dir') {
      keys.push(node.path)
      keys.push(...collectDirKeys(node.children))
    }
  }
  return keys
}

watch(
  () => props.open,
  (open) => {
    if (open && props.skill) {
      void loadTree()
      selectedFile.value = null
    }
  },
)

// ---- 下区右：文件编辑区 ----
const selectedFile = ref<SkillFileContent | null>(null)
const fileContent = ref('')
const fileLoading = ref(false)
const savingFile = ref(false)
const selectedPath = ref('')

const notEditableReason: Record<string, string> = {
  not_text: '该文件不是可编辑的 UTF-8 文本文件',
  too_large: '该文件超过单文件大小上限，不可在线编辑',
}

async function handleSelectFile(keys: (string | number)[]): Promise<void> {
  if (!props.skill || keys.length === 0) return
  const path = String(keys[0])
  // 目录节点仅展开/收起：不进入文件读取（需求 3——否则后端按不存在的文件路径返回 404"文件不存在"）
  if (isDirPath(path)) {
    selectedPath.value = ''
    selectedFile.value = null
    return
  }
  selectedPath.value = path
  fileLoading.value = true
  selectedFile.value = null
  try {
    const content = await skillsApi.readFile(props.skill.dir_name, path)
    selectedFile.value = content
    fileContent.value = content.content ?? ''
  } catch (e) {
    message.error(e instanceof Error ? e.message : '读取文件失败')
  } finally {
    fileLoading.value = false
  }
}

/** 选中 key 是否为目录：树数据里的目录节点 path（或其前缀匹配，防同名文件歧义） */
function isDirPath(path: string): boolean {
  const found = findNode(treeData.value, path)
  return found?.type === 'dir'
}

function findNode(nodes: SkillFileNode[], path: string): SkillFileNode | null {
  for (const node of nodes) {
    if (node.path === path) return node
    const hit = findNode(node.children, path)
    if (hit) return hit
  }
  return null
}

async function handleSaveFile(): Promise<void> {
  if (!props.skill || !selectedFile.value?.editable) return
  savingFile.value = true
  try {
    await skillsApi.writeFile(props.skill.dir_name, {
      path: selectedFile.value.path,
      content: fileContent.value,
    })
    message.success(`已保存 ${selectedFile.value.path}`)
    // skill.md 可能被改 frontmatter：刷新树与基础信息（文件为本）
    if (selectedFile.value.path === 'skill.md') {
      void loadTree()
      const detail = await skillsApi.detail(props.skill.dir_name)
      basic.value = { name: detail.name, description: detail.description }
    }
  } catch (e) {
    message.error(e instanceof Error ? e.message : '保存失败')
  } finally {
    savingFile.value = false
  }
}

function formatTime(iso: string | undefined): string {
  return iso ? iso.replace('T', ' ').slice(0, 19) : '—'
}

const treeSelectHandler: TreeProps['onSelect'] = (keys) => {
  void handleSelectFile(keys as (string | number)[])
}
</script>

<template>
  <Modal
    v-model:open="modalOpen"
    :title="`Skill 详情：${skill?.name ?? ''}`"
    width="960px"
    :footer="null"
    class="detail-modal"
  >
    <template v-if="skill">
      <!-- 上区：基础信息（FR-002~004） -->
      <section class="basic">
        <Form :model="basic" layout="vertical" class="basic__form">
          <FormItem label="名称" name="name" :rules="nameRule" required class="basic__name">
            <Input v-model:value="basic.name" />
          </FormItem>
          <FormItem label="描述" name="description" class="basic__desc">
            <Textarea
              v-model:value="basic.description"
              :rows="3"
              placeholder="一句话说明这个 Skill 做什么"
            />
          </FormItem>
          <div class="basic__actions">
            <button
              class="btn btn--primary"
              type="button"
              :disabled="savingBasic"
              @click="handleSaveBasic"
            >
              {{ savingBasic ? '保存中…' : '保存基础信息' }}
            </button>
          </div>
        </Form>
        <div class="basic__meta">
          <span class="meta-item">
            <span class="meta-item__label">启用状态</span>
            <Switch
              :checked="enabledLocal"
              @change="(next: unknown) => handleToggleEnabled(Boolean(next))"
            />
          </span>
          <span class="meta-item">
            <span class="meta-item__label">技能目录名称</span>
            <code class="meta-item__value">{{ skill.dir_name }}</code>
          </span>
          <span class="meta-item">
            <span class="meta-item__label">更新时间</span>
            <span class="meta-item__value">{{ formatTime(skill.updated_at) }}</span>
          </span>
        </div>
      </section>

      <!-- 下区：左树右编辑区（FR-005~012） -->
      <section class="workspace">
        <aside class="workspace__tree">
          <header class="workspace__tree-header">
            <span class="workspace__tree-title">目录结构</span>
            <button
              class="icon-btn"
              type="button"
              title="刷新目录"
              :disabled="treeLoading"
              @click="loadTree"
            >
              <ReloadOutlined />
            </button>
          </header>
          <Tree
            :tree-data="toAntTree(treeData)"
            :expanded-keys="expandedKeys"
            :selected-keys="selectedPath ? [selectedPath] : []"
            :load-data="undefined"
            block-node
            show-icon
            @update:expanded-keys="(keys: (string | number)[]) => (expandedKeys = keys as string[])"
            @select="treeSelectHandler"
          />
          <div v-if="treeLoading" class="tree-loading">加载中…</div>
        </aside>

        <div class="workspace__editor">
          <div v-if="!selectedPath" class="editor-empty">在左侧选择一个文件进行查看与编辑（点击文件夹仅展开/收起）</div>
          <div v-else-if="fileLoading" class="editor-empty">加载中…</div>
          <template v-else-if="selectedFile">
            <div v-if="!selectedFile.editable" class="editor-notice">
              {{ notEditableReason[selectedFile.reason ?? ''] ?? '该文件不可编辑' }}
            </div>
            <template v-else>
              <div class="editor-toolbar">
                <code class="editor-path">{{ selectedFile.path }}</code>
                <button
                  class="btn btn--primary"
                  type="button"
                  :disabled="savingFile"
                  @click="handleSaveFile"
                >
                  <SaveOutlined />
                  {{ savingFile ? '保存中…' : '保存文件' }}
                </button>
              </div>
              <Textarea
                v-model:value="fileContent"
                :rows="18"
                class="editor-input"
              />
            </template>
          </template>
        </div>
      </section>
    </template>
  </Modal>
</template>

<style scoped lang="scss">
.basic {
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 12px 14px;
  margin-bottom: 12px;

  &__form {
    display: flex;
    flex-direction: column;
    gap: 4px;
  }

  &__name {
    max-width: 420px;
  }

  &__actions {
    display: flex;
    justify-content: flex-end; // 保存按钮独立一行、右对齐（需求 1）
  }

  &__meta {
    display: flex;
    gap: 24px;
    margin-top: 10px;
    padding-top: 10px;
    border-top: 1px dashed var(--border);
  }
}

.meta-item {
  display: inline-flex;
  align-items: center;
  gap: 6px;

  &__label {
    font-size: 12.5px; // 辅助说明规格
    color: var(--text-tertiary);
  }

  &__value {
    font-size: 13px;
    color: var(--text-secondary);
    font-family: var(--font-mono);
  }
}

.workspace {
  display: flex;
  gap: 12px;
  height: 56vh;

  &__tree {
    width: 260px;
    flex-shrink: 0;
    border: 1px solid var(--border);
    border-radius: 8px;
    padding: 8px;
    overflow-y: auto;

    &-header {
      display: flex;
      align-items: center;
      justify-content: space-between;
      margin-bottom: 6px;
    }

    &-title {
      font-size: 13px;
      font-weight: 600;
      color: var(--text-primary);
    }
  }

  &__editor {
    flex: 1;
    border: 1px solid var(--border);
    border-radius: 8px;
    padding: 10px 12px;
    display: flex;
    flex-direction: column;
    gap: 8px;
    overflow: hidden;
  }
}

.tree-icon {
  &--dir {
    color: var(--accent);
  }

  &--file {
    color: var(--text-tertiary);
  }
}

.tree-loading {
  font-size: 12.5px;
  color: var(--text-tertiary);
}

.editor-empty {
  flex: 1;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 13.5px;
  color: var(--text-tertiary);
}

.editor-notice {
  flex: 1;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 13.5px;
  color: var(--warning);
  background: color-mix(in srgb, var(--warning) 8%, transparent);
  border-radius: 6px;
  padding: 12px;
}

.editor-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
}

.editor-path {
  font-family: var(--font-mono);
  font-size: 12.5px;
  color: var(--text-tertiary);
}

.editor-input {
  flex: 1;
  font-family: var(--font-mono);
  font-size: 13px; // 代码规格
  resize: none;

  :deep(textarea) {
    height: 100% !important;
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

    &:disabled {
      opacity: 0.6;
      cursor: not-allowed;
    }
  }
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
</style>
