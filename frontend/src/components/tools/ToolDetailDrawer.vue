<script setup lang="ts">
/**
 * 工具详情抽屉（research R8）。
 *
 * 分节展示：参数表（名称/类型/必填/含义）+ 适用场景 / 输入要求 / 使用限制
 * （契约 §1/§3 的完整内容，FR-003/004）。
 */
import { Drawer, Descriptions, DescriptionsItem, Table, Tag } from 'ant-design-vue'
import type { TableColumnsType } from 'ant-design-vue'

import type { ToolParam } from '@/api/tools'

const props = defineProps<{
  open: boolean
  toolName: string | null
  detail: null | {
    display_name: string
    purpose: string
    params: ToolParam[]
    usage_scenarios: string
    input_requirements: string
    restrictions: string
  }
}>()

const emit = defineEmits<{ 'update:open': [value: boolean] }>()

const columns: TableColumnsType = [
  { title: '参数', dataIndex: 'name', key: 'name', width: 110 },
  { title: '类型', dataIndex: 'type', key: 'type', width: 70 },
  { title: '必填', dataIndex: 'required', key: 'required', width: 64 },
  { title: '含义与填写说明', dataIndex: 'description', key: 'description' },
]
</script>

<template>
  <Drawer
    :open="props.open"
    width="560"
    :title="props.detail ? `工具详情：${props.detail.display_name}` : '工具详情'"
    @close="emit('update:open', false)"
  >
    <div v-if="props.detail" class="tool-detail">
      <Descriptions :column="1" size="small" class="detail-brief" bordered>
        <DescriptionsItem label="用途">
          {{ props.detail.purpose }}
        </DescriptionsItem>
      </Descriptions>

      <section class="detail-section">
        <h3 class="section-title">参数说明</h3>
        <Table
          :columns="columns"
          :data-source="props.detail.params"
          :pagination="false"
          size="small"
          row-key="name"
        >
          <template #bodyCell="{ column, record }">
            <template v-if="column.key === 'name'">
              <span class="param-mono">{{ record.name }}</span>
            </template>
            <template v-else-if="column.key === 'type'">
              <span class="param-type">{{ record.type }}</span>
            </template>
            <template v-else-if="column.key === 'required'">
              <Tag
                class="param-tag"
                :style="record.required
                  ? { color: 'var(--accent)', borderColor: 'var(--accent)' }
                  : { color: 'var(--text-tertiary)', borderColor: 'var(--border-strong)' }"
              >
                {{ record.required ? '必填' : '可选' }}
              </Tag>
            </template>
            <template v-else-if="column.key === 'description'">
              <span class="param-desc">{{ record.description }}</span>
            </template>
          </template>
        </Table>
      </section>

      <section class="detail-section">
        <h3 class="section-title">适用场景</h3>
        <p class="section-text">{{ props.detail.usage_scenarios }}</p>
      </section>

      <section class="detail-section">
        <h3 class="section-title">输入要求</h3>
        <p class="section-text">{{ props.detail.input_requirements }}</p>
      </section>

      <section class="detail-section">
        <h3 class="section-title">使用限制</h3>
        <p class="section-text section-text--warn">{{ props.detail.restrictions }}</p>
      </section>
    </div>
  </Drawer>
</template>

<style scoped lang="scss">
.tool-detail {
  display: flex;
  flex-direction: column;
  gap: 18px;
}

.detail-brief {
  border-radius: 8px;
}

.detail-section {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.section-title {
  margin: 0;
  font-size: 16px; // 卡片标题规格
  font-weight: 600;
  color: var(--text-primary);
}

.section-text {
  margin: 0;
  font-size: 14px; // 正文规格
  line-height: 1.5;
  color: var(--text-secondary);

  &--warn {
    padding: 10px 12px;
    background: var(--bg-base);
    border: 1px solid var(--border);
    border-radius: 6px;
    color: var(--text-primary);
  }
}

.param-mono {
  font-family: var(--font-mono);
  font-size: 13px; // 代码规格
  color: var(--text-primary);
}

.param-type {
  font-size: 12.5px;
  color: var(--text-tertiary);
}

.param-tag {
  font-size: 12px;
  line-height: 20px;
  border-radius: 4px;
  background: transparent;
}

.param-desc {
  font-size: 13px;
  line-height: 1.5;
  color: var(--text-secondary);
}
</style>
