import { beforeEach, describe, expect, it } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'

import { useUiStore } from '../ui'

describe('ui store（窄屏抽屉菜单状态）', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
  })

  it('初始为关闭', () => {
    const ui = useUiStore()
    expect(ui.drawerOpen).toBe(false)
  })

  it('openDrawer / closeDrawer / toggleDrawer 正确迁移状态', () => {
    const ui = useUiStore()

    ui.openDrawer()
    expect(ui.drawerOpen).toBe(true)

    ui.closeDrawer()
    expect(ui.drawerOpen).toBe(false)

    ui.toggleDrawer()
    expect(ui.drawerOpen).toBe(true)

    ui.toggleDrawer()
    expect(ui.drawerOpen).toBe(false)
  })
})
