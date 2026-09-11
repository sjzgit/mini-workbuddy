<script setup lang="ts">
/**
 * MCP 工具列表弹窗（spec FR-016/027）：展示最近一次成功测试发现的工具
 * 名称 / 用途 / 参数表（类型、必填、说明）。
 */
import { computed } from 'vue'

import { Empty, Modal } from 'ant-design-vue'

import type { McpToolInfo } from '@/api/mcp'

const props = defineProps<{
  open: boolean
  serverName: string
  tools: McpToolInfo[]
}>()
const emit = defineEmits<{
  'update:open': [value: boolean]
}>()

const modalOpen = computed({
  get: () => props.open,
  set: (value: boolean) => emit('update:open', value),
})
</script>

<template>
  <Modal
    v-model:open="modalOpen"
    :title="`发现工具（${serverName}）`"
    :footer="null"
    width="720"
  >
    <Empty
      v-if="tools.length === 0"
      :image="Empty.PRESENTED_IMAGE_SIMPLE"
      description="该 Server 未提供工具"
    />
    <div v-else class="tool-list">
      <section v-for="tool in tools" :key="tool.name" class="tool">
        <header class="tool__header">
          <span class="tool__name">{{ tool.name }}</span>
          <span class="tool__desc">{{ tool.description || '（未提供用途说明）' }}</span>
        </header>
        <table v-if="tool.params.length > 0" class="tool__params">
          <thead>
            <tr>
              <th>参数</th>
              <th>类型</th>
              <th>必填</th>
              <th>说明</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="param in tool.params" :key="param.name">
              <td class="param-name">{{ param.name }}</td>
              <td class="param-type">{{ param.type }}</td>
              <td :class="param.required ? 'param-required' : 'param-optional'">
                {{ param.required ? '必填' : '可选' }}
              </td>
              <td class="param-desc">{{ param.description || '—' }}</td>
            </tr>
          </tbody>
        </table>
        <p v-else class="tool__no-params">该工具无参数</p>
      </section>
    </div>
  </Modal>
</template>

<style scoped lang="scss">
.tool-list {
  display: flex;
  flex-direction: column;
  gap: 12px;
  max-height: 60vh;
  overflow-y: auto;
}

.tool {
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 10px 12px;

  &__header {
    display: flex;
    align-items: baseline;
    gap: 10px;
    margin-bottom: 8px;
  }

  &__name {
    font-family: var(--font-mono);
    font-size: 13px; // 代码规格
    font-weight: 600;
    color: var(--accent);
  }

  &__desc {
    font-size: 13.5px;
    color: var(--text-secondary);
  }

  &__no-params {
    font-size: 12.5px;
    color: var(--text-tertiary);
    margin: 0;
  }

  &__params {
    width: 100%;
    border-collapse: collapse;
    font-size: 12.5px;

    th {
      text-align: left;
      font-weight: 600;
      color: var(--text-tertiary);
      padding: 4px 8px;
      border-bottom: 1px solid var(--border);
    }

    td {
      padding: 4px 8px;
      border-bottom: 1px solid var(--border);
      color: var(--text-secondary);
    }
  }
}

.param-name {
  font-family: var(--font-mono);
  color: var(--text-primary) !important;
}

.param-type {
  font-family: var(--font-mono);
}

.param-required {
  color: var(--warning) !important;
}

.param-optional {
  color: var(--text-tertiary) !important;
}

.param-desc {
  color: var(--text-tertiary) !important;
}
</style>
