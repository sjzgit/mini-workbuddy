import { createRouter, createWebHistory } from 'vue-router'

import WorkbenchLayout from '@/layouts/WorkbenchLayout.vue'
import { MODULES, type ModuleMeta } from './modules'

declare module 'vue-router' {
  interface RouteMeta {
    /** 命中模块时的元数据（侧栏高亮与页面内容来源） */
    module?: ModuleMeta
  }
}

/** 由模块元数据生成布局子路由（懒加载，每个模块独立 chunk） */
const moduleRoutes = MODULES.map((meta) => ({
  path: meta.path,
  name: meta.path,
  component: () => import(`@/views/${viewName(meta.path)}.vue`),
  meta: { module: meta },
}))

/** chat → ChatView / mcp → McpView / evaluations → EvaluationsView */
function viewName(path: string): string {
  return (
    path
      .split('-')
      .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
      .join('') + 'View'
  )
}

const router = createRouter({
  history: createWebHistory(import.meta.env.BASE_URL),
  routes: [
    {
      path: '/',
      component: WorkbenchLayout,
      children: [
        { path: '', redirect: '/chat' },
        ...moduleRoutes,
      ],
    },
    {
      path: '/:pathMatch(.*)*',
      name: 'not-found',
      component: () => import('@/views/NotFoundView.vue'),
    },
  ],
})

export default router
