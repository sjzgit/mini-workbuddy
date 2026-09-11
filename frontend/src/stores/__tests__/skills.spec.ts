import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'

import { skillsApi, type SkillItem } from '@/api/skills'
import { useSkillsStore } from '@/stores/skills'

vi.mock('@/api/skills', () => ({
  skillsApi: {
    list: vi.fn(),
    detail: vi.fn(),
    update: vi.fn(),
    setEnabled: vi.fn(),
    remove: vi.fn(),
    refresh: vi.fn(),
    importZip: vi.fn(),
  },
}))

const listMock = vi.mocked(skillsApi.list)
const setEnabledMock = vi.mocked(skillsApi.setEnabled)
const removeMock = vi.mocked(skillsApi.remove)
const refreshMock = vi.mocked(skillsApi.refresh)

const fakeItem = (overrides: Partial<SkillItem> = {}): SkillItem => ({
  dir_name: 'meeting-notes',
  name: '会议纪要整理',
  description: '把口述草稿整理成结构化纪要',
  enabled: true,
  updated_at: '2026-09-10T08:00:00',
  ...overrides,
})

describe('skills store（列表/加载/刷新/启停/删除状态）', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    listMock.mockReset()
    setEnabledMock.mockReset()
    removeMock.mockReset()
    refreshMock.mockReset()
  })

  it('初始状态为空列表、无错误、未加载', () => {
    const store = useSkillsStore()
    expect(store.items).toEqual([])
    expect(store.loading).toBe(false)
    expect(store.refreshing).toBe(false)
    expect(store.error).toBeNull()
  })

  it('fetchSkills 成功写入列表并清除错误', async () => {
    listMock.mockResolvedValue([fakeItem()])
    const store = useSkillsStore()
    await store.fetchSkills()
    expect(store.items).toHaveLength(1)
    expect(store.items[0]?.name).toBe('会议纪要整理')
    expect(store.error).toBeNull()
    expect(store.loading).toBe(false)
  })

  it('fetchSkills 空列表保持空态（FR-004）', async () => {
    listMock.mockResolvedValue([])
    const store = useSkillsStore()
    await store.fetchSkills()
    expect(store.items).toEqual([])
    expect(store.error).toBeNull()
  })

  it('fetchSkills 失败写入人话错误，不清空已有数据', async () => {
    const store = useSkillsStore()
    listMock.mockResolvedValueOnce([fakeItem()])
    await store.fetchSkills()
    listMock.mockRejectedValueOnce(new Error('后端服务未启动'))
    await store.fetchSkills()
    expect(store.error).toBe('后端服务未启动')
    expect(store.items).toHaveLength(1)
  })

  it('refresh 返回 skipped 列表并更新列表（FR-005）', async () => {
    refreshMock.mockResolvedValue({
      items: [fakeItem({ dir_name: 'good' })],
      skipped: ['bad-skill'],
    })
    const store = useSkillsStore()
    const skipped = await store.refresh()
    expect(skipped).toEqual(['bad-skill'])
    expect(store.items[0]?.dir_name).toBe('good')
    expect(store.refreshing).toBe(false)
  })

  it('refresh 失败返回空 skipped 且写入错误', async () => {
    refreshMock.mockRejectedValue(new Error('刷新失败'))
    const store = useSkillsStore()
    const skipped = await store.refresh()
    expect(skipped).toEqual([])
    expect(store.error).toBe('刷新失败')
  })

  it('setEnabled 成功后就地替换该行（US3）', async () => {
    listMock.mockResolvedValue([fakeItem()])
    const store = useSkillsStore()
    await store.fetchSkills()

    setEnabledMock.mockResolvedValue(fakeItem({ enabled: false, updated_at: '2026-09-10T09:00:00' }))
    await store.setEnabled('meeting-notes', false)

    expect(store.items[0]?.enabled).toBe(false)
    expect(store.items[0]?.updated_at).toBe('2026-09-10T09:00:00')
  })

  it('remove 成功后移除该行（US3）', async () => {
    listMock.mockResolvedValue([fakeItem(), fakeItem({ dir_name: 'other' })])
    const store = useSkillsStore()
    await store.fetchSkills()

    removeMock.mockResolvedValue({ deleted: true })
    await store.remove('meeting-notes')

    expect(store.items).toHaveLength(1)
    expect(store.items[0]?.dir_name).toBe('other')
  })
})
