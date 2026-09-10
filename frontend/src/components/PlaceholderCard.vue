<script setup lang="ts">
/**
 * 统一占位卡片：写明"本模块将在后续阶段开发"，
 * 并告知使用者当前阶段先完成什么。
 * 禁止虚构统计数字、对话和列表（spec FR-014）。
 */
defineProps<{
  /** 模块标题（页面主标题 18px / 650） */
  title: string
  /** 一句简短说明 */
  description: string
  /** 当前阶段先完成什么 */
  currentStage: string
}>()
</script>

<template>
  <div class="page">
    <header class="page__header">
      <h1 class="page__title">{{ title }}</h1>
      <p class="page__desc">{{ description }}</p>
    </header>

    <div class="card">
      <p class="card__title">本模块将在后续阶段开发</p>
      <p class="card__stage">当前阶段先完成：{{ currentStage }}</p>
    </div>
  </div>
</template>

<style scoped lang="scss">
.page {
  display: flex;
  flex-direction: column;
  gap: 16px;

  &__header {
    display: flex;
    flex-direction: column;
    gap: 2px;
  }

  &__title {
    font-size: 22px; // 页面主标题规格
    font-weight: 650;
  }

  &__desc {
    font-size: 12.5px; // 辅助说明规格
    color: var(--text-secondary);
  }
}

.card {
  background: var(--bg-surface);
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 24px;
  display: flex;
  flex-direction: column;
  gap: 8px;

  &__title {
    font-size: 16.5px; // 卡片标题规格（16–17px）
    font-weight: 600;
  }

  &__stage {
    font-size: 14px;
    color: var(--text-secondary);
  }
}
</style>
