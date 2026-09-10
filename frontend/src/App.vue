<script setup lang="ts">
/**
 * 应用根组件：Ant Design 主题与产品主色对齐（--accent 系）。
 * 布局由 WorkbenchLayout 承担（挂在路由上）。
 */
import { ConfigProvider } from 'ant-design-vue'

const themeConfig = {
  token: {
    colorPrimary: '#c2703a', // = --accent
    colorInfo: '#c2703a',
    colorLink: '#c2703a',
    borderRadius: 6,
    fontFamily:
      "'DM Sans Variable', 'DM Sans', -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif",
    fontSize: 12.5,
  },
}
</script>

<template>
  <ConfigProvider :theme="themeConfig">
    <router-view />
  </ConfigProvider>
</template>
