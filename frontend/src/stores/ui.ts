import { defineStore } from 'pinia'
import { ref } from 'vue'

/** UI 全局状态：窄屏抽屉菜单的开关。 */
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

  return { drawerOpen, openDrawer, closeDrawer, toggleDrawer }
})
