import { defineStore } from 'pinia'
import { computed, ref } from 'vue'

export type ThemeMode = 'light' | 'dark'

const THEME_STORAGE_KEY = 'mini-workbuddy:theme'

function readStoredTheme(): ThemeMode {
  try {
    const saved = localStorage.getItem(THEME_STORAGE_KEY)
    if (saved === 'light' || saved === 'dark') return saved
  } catch {
    // localStorage 不可用时保持默认亮色
  }
  return 'light'
}

function applyToDocument(mode: ThemeMode): void {
  document.documentElement.dataset.theme = mode
}

/** UI 全局状态：窄屏抽屉菜单开关 + 亮/暗主题。 */
export const useUiStore = defineStore('ui', () => {
  /** 窄屏抽屉菜单是否打开 */
  const drawerOpen = ref(false)

  function openDrawer(): void {
    drawerOpen.value = true
  }

  function closeDrawer(): void {
    drawerOpen.value = false
  }

  function toggleDrawer(): void {
    drawerOpen.value = !drawerOpen.value
  }

  /** 当前主题（默认亮色；选择持久化到 localStorage，并同步到 html[data-theme]） */
  const theme = ref<ThemeMode>(readStoredTheme())
  const isDark = computed(() => theme.value === 'dark')
  applyToDocument(theme.value)

  function setTheme(next: ThemeMode): void {
    theme.value = next
    applyToDocument(next)
    try {
      localStorage.setItem(THEME_STORAGE_KEY, next)
    } catch {
      // 持久化失败不影响本次会话内的主题生效
    }
  }

  function toggleTheme(): void {
    setTheme(theme.value === 'dark' ? 'light' : 'dark')
  }

  return {
    drawerOpen,
    openDrawer,
    closeDrawer,
    toggleDrawer,
    theme,
    isDark,
    setTheme,
    toggleTheme,
  }
})
