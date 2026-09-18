<script setup lang="ts">
/**
 * 评测工作台（specs/012 US6）：数据集 / 任务 / 运行三 Tab。
 * 任务面板发起评测后自动跳到运行 Tab 并按任务过滤。
 */
import { ref } from 'vue'
import { Tabs } from 'ant-design-vue'

import { MODULES } from '@/router/modules'
import DatasetPanel from '@/components/evaluation/DatasetPanel.vue'
import TaskPanel from '@/components/evaluation/TaskPanel.vue'
import RunPanel from '@/components/evaluation/RunPanel.vue'

const meta = MODULES.find((m) => m.path === 'evaluations')!

const activeTab = ref('datasets')
const taskPanelRef = ref<InstanceType<typeof TaskPanel> | null>(null)
const runPanelRef = ref<InstanceType<typeof RunPanel> | null>(null)

function onGotoRuns(taskId: number): void {
  activeTab.value = 'runs'
  void runPanelRef.value?.refresh()
}
</script>

<template>
  <div class="page evaluations-page">
    <header class="page__header">
      <div>
        <h1 class="page__title">{{ meta.title }}</h1>
        <p class="page__desc">{{ meta.description }}</p>
      </div>
    </header>

    <div class="card evaluations-card">
      <Tabs v-model:active-key="activeTab">
        <Tabs.TabPane key="datasets" tab="数据集">
          <DatasetPanel />
        </Tabs.TabPane>
        <Tabs.TabPane key="tasks" tab="评测任务">
          <TaskPanel ref="taskPanelRef" @goto-runs="onGotoRuns" />
        </Tabs.TabPane>
        <Tabs.TabPane key="runs" tab="评测运行">
          <RunPanel ref="runPanelRef" />
        </Tabs.TabPane>
      </Tabs>
    </div>
  </div>
</template>

<style scoped lang="scss">
@use '@/styles/tokens' as *;

.evaluations-page {
  display: flex;
  flex-direction: column;
  height: 100%;
  overflow: auto;
}

.evaluations-card {
  flex: 1;
  min-height: 0;
  padding: 4px 16px 16px;
}
</style>
