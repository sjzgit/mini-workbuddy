import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'

import { toolsApi, type ToolItem } from '@/api/tools'
import { useToolsStore } from '@/stores/tools'

vi.mock('@/api/tools', () => ({
  toolsApi: {
    list: vi.fn(),
    setEnabled: vi.fn(),
  },
}))

const listMock = vi.mocked(toolsApi.list)
const setEnabledMock = vi.mocked(toolsApi.setEnabled)

const fakeItem = (overrides: Partial<ToolItem> = {}): ToolItem => ({
  name: 'shell',
  display_name: 'Shell 命令',
  purpose: '执行系统命令并返回输出与执行状态',
  params_summary: 'command（必填）',
  enabled: true,
  is_builtin: true,
  updated_at: '2026-09-10T08:00:00Z',
  ...overrides,
})

describe('tools store（列表/加载/启停状态）', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    listMock.mockReset()
    setEnabledMock.mockReset()
  })

  it('初始状态为空列表、无错误、未加载', () => {
    const store = useToolsStore()
    expect(store.items).toEqual([])
    expect(store.loading).toBe(false)
    expect(store.error).toBeNull()
    expect(store.togglingName).toBeNull()
  })

  it('fetchTools 成功写入列表并清除错误', async () => {
    listMock.mockResolvedValue([
      fakeItem({ name: 'current_time', display_name: '当前时间' }),
      fakeItem(),
    ])
    const store = useToolsStore()
    await store.fetchTools()
    expect(store.items).toHaveLength(2)
    expect(store.items[1]?.display_name).toBe('Shell 命令')
    expect(store.error).toBeNull()
    expect(store.loading).toBe(false)
  })

  it('fetchTools 空列表保持空态（后端返回 []）', async () => {
    listMock.mockResolvedValue([])
    const store = useToolsStore()
    await store.fetchTools()
    expect(store.items).toEqual([])
    expect(store.error).toBeNull()
  })

  it('fetchTools 失败写入人话错误，不清空已有数据', async () => {
    const store = useToolsStore()
    listMock.mockResolvedValueOnce([fakeItem()])
    await store.fetchTools()
    listMock.mockRejectedValueOnce(new Error('后端服务未启动'))
    await store.fetchTools()
    expect(store.error).toBe('后端服务未启动')
    expect(store.items).toHaveLength(1)
    expect(store.loading).toBe(false)
  })

  it('setEnabled 成功后同步列表中该行', async () => {
    listMock.mockResolvedValue([fakeItem()])
    const store = useToolsStore()
    await store.fetchTools()

    setEnabledMock.mockResolvedValue(
      fakeItem({ enabled: false, updated_at: '2026-09-10T09:00:00Z' }),
    )
    await store.setEnabled('shell', false)

    expect(store.items[0]?.enabled).toBe(false)
    expect(store.items[0]?.updated_at).toBe('2026-09-10T09:00:00Z')
    expect(store.togglingName).toBeNull()
  })

  it('setEnabled 失败时错误向上抛、togglingName 复位', async () => {
    listMock.mockResolvedValue([fakeItem()])
    const store = useToolsStore()
    await store.fetchTools()

    setEnabledMock.mockRejectedValueOnce(new Error('工具不存在'))
    await expect(store.setEnabled('shell', false)).rejects.toThrow('工具不存在')

    expect(store.items[0]?.enabled).toBe(true) // 原状态未被破坏
    expect(store.togglingName).toBeNull()
  })

  it('setEnabled 请求期间 togglingName 标记当前工具', async () => {
    listMock.mockResolvedValue([fakeItem()])
    const store = useToolsStore()
    await store.fetchTools()

    let release: (value: never) => void = () => {}
    setEnabledMock.mockReturnValue(
      new Promise((resolve) => {
        release = resolve as (value: never) => void
      }) as ReturnType<typeof toolsApi.setEnabled>,
    )
    const pending = store.setEnabled('shell', false)
    expect(store.togglingName).toBe('shell')
    release(fakeItem({ enabled: false }) as never)
    await pending
    expect(store.togglingName).toBeNull()
  })
})
