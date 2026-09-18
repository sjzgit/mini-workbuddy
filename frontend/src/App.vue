<script setup lang="ts">
/**
 * 应用根组件：Ant Design 主题与产品主色对齐（--accent 系），
 * 亮/暗算法随 ui store 的主题状态联动（CSS 令牌见 styles/tokens.scss）。
 * 布局由 WorkbenchLayout 承担（挂在路由上）。
 */
import { computed } from 'vue'
import { storeToRefs } from 'pinia'
import { ConfigProvider, theme as antdTheme } from 'ant-design-vue'

import { useUiStore } from '@/stores/ui'

const ui = useUiStore()
const { isDark } = storeToRefs(ui)

const themeConfig = computed(() => ({
  algorithm: isDark.value ? antdTheme.darkAlgorithm : antdTheme.defaultAlgorithm,
  token: {
    colorPrimary: isDark.value ? '#d4854d' : '#c2703a', // = --accent（暗色下用提亮值）
    colorInfo: isDark.value ? '#d4854d' : '#c2703a',
    colorLink: isDark.value ? '#d4854d' : '#c2703a',
    // 暗色下把 antd 表面底色调成暖色调，与令牌色系一致（= --bg-surface）
    ...(isDark.value ? { colorBgBase: '#241d18' } : {}),
    borderRadius: 6,
    fontFamily:
      "'DM Sans Variable', 'DM Sans', -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif",
    fontSize: 12.5,
  },
}))
</script>

<template>
  <ConfigProvider :theme="themeConfig">
    <router-view />
  </ConfigProvider>
</template>
