import { fileURLToPath, URL } from 'node:url'

import { defineConfig } from 'vitest/config'
import vue from '@vitejs/plugin-vue'
import vueDevTools from 'vite-plugin-vue-devtools'

// https://vite.dev/config/
export default defineConfig({
  plugins: [vue(), vueDevTools()],
  resolve: {
    alias: {
      '@': fileURLToPath(new URL('./src', import.meta.url)),
    },
  },
  server: {
    // 前端始终请求相对路径 /api，开发环境由 Vite 代理转发到后端（FR-005）
    proxy: {
      '/api': {
        target: 'http://127.0.0.1:8218',
        changeOrigin: true,
      },
    },
  },
  test: {
    environment: 'jsdom',
  },
})
