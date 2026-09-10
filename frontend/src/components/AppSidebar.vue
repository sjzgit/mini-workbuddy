<script setup lang="ts">
/**
 * 左侧导航：产品标识 + 8 个模块入口。
 * 桌面宽度固定 188px；<900px 由 WorkbenchLayout 包进抽屉。
 * 菜单顺序与文案的单一来源：router/modules.ts（spec FR-010）。
 */
import { computed } from 'vue'
import { useRoute } from 'vue-router'
import { MODULES } from '@/router/modules'

const route = useRoute()
const activePath = computed(() => String(route.meta.module?.path ?? ''))
</script>

<template>
  <nav class="sidebar" aria-label="主导航">
    <router-link to="/chat" class="brand">
      <span class="brand__mark">m</span>
      <span class="brand__name">mini-workbuddy</span>
    </router-link>

    <ul class="menu">
      <li v-for="meta in MODULES" :key="meta.path">
        <router-link
          :to="`/${meta.path}`"
          class="menu__item"
          :class="{ 'menu__item--active': activePath === meta.path }"
        >
          <component :is="meta.icon" class="menu__icon" />
          <span>{{ meta.title }}</span>
        </router-link>
      </li>
    </ul>
  </nav>
</template>

<style scoped lang="scss">
.sidebar {
  height: 100%;
  display: flex;
  flex-direction: column;
  background: var(--bg-surface);
  border-right: 1px solid var(--border);
  overflow-y: auto;
}

.brand {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 14px 12px;
  text-decoration: none;

  &__mark {
    width: 26px;
    height: 26px;
    border-radius: 50%; // 圆形字母标记
    background: var(--accent);
    color: var(--text-inverse);
    font-family: var(--font-display);
    font-size: 14px;
    font-weight: 650;
    display: inline-flex;
    align-items: center;
    justify-content: center;
    flex-shrink: 0;
  }

  &__name {
    font-family: var(--font-display);
    font-size: 14px;
    font-weight: 650;
    color: var(--text-primary);
    white-space: nowrap;
  }
}

.menu {
  list-style: none;
  margin: 4px 0 0;
  padding: 0 8px;
  display: flex;
  flex-direction: column;
  gap: 2px;

  &__item {
    height: 34px; // 导航项高度规格
    display: flex;
    align-items: center;
    gap: 8px;
    padding: 0 10px;
    border-radius: 6px;
    font-size: 13.5px; // 菜单文字规格
    color: var(--text-secondary);
    text-decoration: none;
    transition:
      background-color 0.15s ease,
      color 0.15s ease;

    &:hover {
      background: var(--bg-hover);
      color: var(--text-primary);
    }

    &--active {
      background: var(--bg-active); // 选中项背景
      color: var(--text-primary);
      font-weight: 600;
    }
  }

  &__icon {
    font-size: 15px;
    flex-shrink: 0;
  }
}
</style>
