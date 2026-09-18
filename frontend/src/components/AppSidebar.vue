<script setup lang="ts">
/**
 * 左侧导航：产品标识 + 8 个模块入口。
 * 桌面宽度固定 188px；<900px 由 WorkbenchLayout 包进抽屉。
 * 菜单顺序与文案的单一来源：router/modules.ts（spec FR-010）。
 */
import { computed } from 'vue'
import { useRoute } from 'vue-router'
import { MODULES } from '@/router/modules'
import { useUiStore } from '@/stores/ui'

const route = useRoute()
const ui = useUiStore()
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

    <!-- 左下角：亮色/暗色主题切换（桌面常驻侧栏与窄屏抽屉共用本组件） -->
    <div class="sidebar-footer">
      <button
        class="theme-toggle"
        type="button"
        :title="ui.isDark ? '切换为亮色模式' : '切换为暗色模式'"
        @click="ui.toggleTheme()"
      >
        <!-- 内联 SVG（Feather 风格，MIT）：antd 图标集无日/月图标 -->
        <svg
          v-if="ui.isDark"
          class="theme-toggle__icon"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          stroke-width="2"
          stroke-linecap="round"
          aria-hidden="true"
        >
          <circle cx="12" cy="12" r="4" />
          <path
            d="M12 2v2M12 20v2M4.93 4.93l1.41 1.41M17.66 17.66l1.41 1.41M2 12h2M20 12h2M6.34 17.66l-1.41 1.41M19.07 4.93l-1.41 1.41"
          />
        </svg>
        <svg
          v-else
          class="theme-toggle__icon"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          stroke-width="2"
          stroke-linecap="round"
          stroke-linejoin="round"
          aria-hidden="true"
        >
          <path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z" />
        </svg>
        <span>{{ ui.isDark ? '亮色模式' : '暗色模式' }}</span>
      </button>
    </div>
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

.sidebar-footer {
  margin-top: auto; // 固定在侧栏底部（左下角）
  padding: 8px;
  border-top: 1px solid var(--border);
}

.theme-toggle {
  width: 100%;
  height: 34px;
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 0 10px;
  border: none;
  border-radius: 6px;
  background: transparent;
  font-size: 13.5px;
  color: var(--text-secondary);
  cursor: pointer;
  transition:
    background-color 0.15s ease,
    color 0.15s ease;

  &:hover {
    background: var(--bg-hover);
    color: var(--text-primary);
  }

  &__icon {
    width: 15px;
    height: 15px;
    flex-shrink: 0;
  }
}
</style>
