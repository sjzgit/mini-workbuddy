/**
 * Skills 列表全局状态（Pinia）。
 * 文件为本（research R1）：列表 = 目录扫描 ⨝ DB 启停状态；变更动作由视图调用 api 后重拉。
 */
import { defineStore } from 'pinia'
import { ref } from 'vue'

import { skillsApi, type SkillItem } from '@/api/skills'

export const useSkillsStore = defineStore('skills', () => {
  /** Skill 列表（更新时间倒序，由后端保证） */
  const items = ref<SkillItem[]>([])
  /** 是否加载中 */
  const loading = ref(false)
  /** 手动刷新进行中 */
  const refreshing = ref(false)
  /** 加载错误（人话信息；null = 无错误） */
  const error = ref<string | null>(null)

  /** 拉取列表；失败时写入 error，不清空已有数据 */
  async function fetchSkills(): Promise<void> {
    loading.value = true
    error.value = null
    try {
      items.value = await skillsApi.list()
    } catch (e) {
      error.value = e instanceof Error ? e.message : '加载 Skills 列表失败'
    } finally {
      loading.value = false
    }
  }

  /** 手动刷新：重扫目录；返回被跳过的不合规目录名（FR-003/005） */
  async function refresh(): Promise<string[]> {
    refreshing.value = true
    error.value = null
    try {
      const result = await skillsApi.refresh()
      items.value = result.items
      return result.skipped
    } catch (e) {
      error.value = e instanceof Error ? e.message : '刷新 Skills 列表失败'
      return []
    } finally {
      refreshing.value = false
    }
  }

  /** 启停（调用方确认后触发）；成功就地把行替换 */
  async function setEnabled(dirName: string, enabled: boolean): Promise<void> {
    const updated = await skillsApi.setEnabled(dirName, enabled)
    replaceItem(updated)
  }

  /** 删除（调用方确认后触发）；成功就移除该行 */
  async function remove(dirName: string): Promise<void> {
    await skillsApi.remove(dirName)
    items.value = items.value.filter((item) => item.dir_name !== dirName)
  }

  /** 编辑保存后同步最新列表项（文件 mtime 变化 → updated_at 刷新） */
  function replaceItem(updated: SkillItem): void {
    const index = items.value.findIndex((item) => item.dir_name === updated.dir_name)
    if (index >= 0) items.value.splice(index, 1, updated)
    else items.value.unshift(updated)
  }

  return { items, loading, refreshing, error, fetchSkills, refresh, setEnabled, remove, replaceItem }
})
