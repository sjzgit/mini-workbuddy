<script setup lang="ts">
/**
 * 工作台布局：桌面左侧固定 188px 侧栏 + 右侧内容区；
 * <900px 侧栏收起为抽屉（spec FR-008/FR-009/FR-012）。
 * 整页占满浏览器高度，无整页横向滚动。
 */
import { onBeforeUnmount, onMounted, ref } from 'vue'
import { useRoute } from 'vue-router'
import { Drawer } from 'ant-design-vue'
import { MenuOutlined } from '@ant-design/icons-vue'
import AppSidebar from '@/components/AppSidebar.vue'
import { useUiStore } from '@/stores/ui'

const NARROW_BREAKPOINT = 900 // px

const route = useRoute()
const ui = useUiStore()
const isNarrow = ref(false)

function onResize(): void {
  isNarrow.value = window.innerWidth < NARROW_BREAKPOINT
  if (!isNarrow.value) ui.closeDrawer()
}

onMounted(() => {
  onResize()
  window.addEventListener('resize', onResize)
})

onBeforeUnmount(() => {
  window.removeEventListener('resize', onResize)
})
</script>

<template>
  <div class="workbench">
    <!-- 桌面：常驻侧栏 -->
    <aside v-if="!isNarrow" class="workbench__aside">
      <AppSidebar />
    </aside>

    <!-- 窄屏：抽屉侧栏 -->
    <template v-else>
      <button
        class="workbench__menu-btn"
        type="button"
        aria-label="打开导航菜单"
        @click="ui.openDrawer()"
      >
        <MenuOutlined />
      </button>
      <Drawer
        :open="ui.drawerOpen"
        placement="left"
        :width="188"
        :closable="false"
        :body-style="{ padding: 0 }"
        @close="ui.closeDrawer()"
      >
        <AppSidebar />
      </Drawer>
    </template>

    <main class="workbench__main">
      <router-view v-slot="{ Component }">
        <component :is="Component" :key="route.path" />
      </router-view>
    </main>
  </div>
</template>

<style scoped lang="scss">
.workbench {
  height: 100%; // 整页占满浏览器高度
  display: flex;
  overflow: hidden; // 无整页横向滚动

  &__aside {
    width: 188px; // 桌面侧栏固定宽度
    flex-shrink: 0;
  }

  &__main {
    flex: 1;
    min-width: 0; // 防止内容撑破横向
    background: var(--bg-base);
    padding: 20px 24px;
    overflow-y: auto;
  }

  &__menu-btn {
    position: fixed;
    top: 12px;
    left: 12px;
    z-index: 100;
    width: 32px;
    height: 32px;
    display: inline-flex;
    align-items: center;
    justify-content: center;
    border: 1px solid var(--border);
    border-radius: 6px;
    background: var(--bg-surface);
    color: var(--text-secondary);
    cursor: pointer;

    &:hover {
      border-color: var(--border-hover);
      color: var(--text-primary);
    }
  }
}

// 窄屏时给悬浮按钮让位
@media (max-width: 899px) {
  .workbench__main {
    padding-top: 52px;
  }
}
</style>
