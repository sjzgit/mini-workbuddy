import { describe, expect, it } from 'vitest'
import { createMemoryHistory, createRouter } from 'vue-router'

import WorkbenchLayout from '@/layouts/WorkbenchLayout.vue'
import { MODULES } from '../modules'
import router from '../index'

describe('模块元数据（FR-010 顺序）', () => {
  it('按固定顺序提供 8 个入口', () => {
    expect(MODULES.map((m) => m.title)).toEqual([
      '聊天',
      'Agent 管理',
      '模型管理',
      '工具管理',
      'MCP 管理',
      'Skills 管理',
      '运行记录',
      'Agent 评测',
    ])
  })

  it('每个入口都有路径、说明与当前阶段提示', () => {
    for (const meta of MODULES) {
      expect(meta.path).toBeTruthy()
      expect(meta.description).toBeTruthy()
      expect(meta.currentStage).toBeTruthy()
    }
  })
})

describe('工作台路由（SC-002：8 地址可达、刷新不白屏）', () => {
  it('8 个模块路径均解析到布局子路由', () => {
    for (const meta of MODULES) {
      const resolved = router.resolve(`/${meta.path}`)
      expect(resolved.matched.length).toBeGreaterThan(0)
      expect(resolved.matched[0]?.components?.default).toBe(WorkbenchLayout)
      // 模块元数据挂到路由上（供侧栏高亮）
      expect(resolved.meta.module?.path).toBe(meta.path)
    }
  })

  it('根路径重定向到 /chat（默认聊天页）', async () => {
    const testRouter = createRouter({
      history: createMemoryHistory(),
      routes: router.options.routes,
    })
    await testRouter.push('/')
    await testRouter.isReady()
    expect(testRouter.currentRoute.value.redirectedFrom?.fullPath).toBe('/')
    expect(testRouter.currentRoute.value.fullPath).toBe('/chat')
  })

  it('未知地址命中 NotFound 兜底，不白屏', async () => {
    const resolved = router.resolve('/definitely/not/exist')
    expect(resolved.name).toBe('not-found')
    // 懒加载路由组件解析后确为 NotFoundView
    const lazy = resolved.matched[resolved.matched.length - 1]?.components
      ?.default as unknown as () => Promise<Record<string, unknown>>
    const mod = await lazy()
    const loaded = (mod.default ?? mod) as { __name?: string }
    expect(loaded.__name).toBe('NotFoundView')
  })
})
