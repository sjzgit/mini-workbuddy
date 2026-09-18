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

describe('ui store（主题切换）', () => {
  beforeEach(() => {
    localStorage.clear()
    setActivePinia(createPinia())
  })

  it('默认亮色并同步到 html[data-theme]', () => {
    const ui = useUiStore()
    expect(ui.theme).toBe('light')
    expect(ui.isDark).toBe(false)
    expect(document.documentElement.dataset.theme).toBe('light')
  })

  it('toggleTheme 在亮/暗间切换，写 localStorage 与 data-theme', () => {
    const ui = useUiStore()

    ui.toggleTheme()
    expect(ui.theme).toBe('dark')
    expect(ui.isDark).toBe(true)
    expect(localStorage.getItem('mini-workbuddy:theme')).toBe('dark')
    expect(document.documentElement.dataset.theme).toBe('dark')

    ui.toggleTheme()
    expect(ui.theme).toBe('light')
    expect(localStorage.getItem('mini-workbuddy:theme')).toBe('light')
    expect(document.documentElement.dataset.theme).toBe('light')
  })

  it('localStorage 已存 dark 时初始即为暗色', () => {
    localStorage.setItem('mini-workbuddy:theme', 'dark')
    const ui = useUiStore()
    expect(ui.theme).toBe('dark')
    expect(ui.isDark).toBe(true)
    expect(document.documentElement.dataset.theme).toBe('dark')
  })

  it('localStorage 存有非法值时回退亮色', () => {
    localStorage.setItem('mini-workbuddy:theme', 'blue')
    const ui = useUiStore()
    expect(ui.theme).toBe('light')
  })

  it('setTheme 可直接指定目标主题', () => {
    const ui = useUiStore()
    ui.setTheme('dark')
    expect(ui.isDark).toBe(true)
    ui.setTheme('dark') // 重复设置幂等
    expect(ui.isDark).toBe(true)
  })
})
