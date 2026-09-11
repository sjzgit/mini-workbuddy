import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'

import { mcpApi, type McpServerItem, type McpTestResult } from '@/api/mcp'
import { useMcpStore } from '@/stores/mcp'

vi.mock('@/api/mcp', () => ({
  mcpApi: {
    list: vi.fn(),
    detail: vi.fn(),
    create: vi.fn(),
    update: vi.fn(),
    remove: vi.fn(),
    setEnabled: vi.fn(),
    test: vi.fn(),
  },
}))

const listMock = vi.mocked(mcpApi.list)
const setEnabledMock = vi.mocked(mcpApi.setEnabled)
const removeMock = vi.mocked(mcpApi.remove)
const testMock = vi.mocked(mcpApi.test)

const fakeItem = (overrides: Partial<McpServerItem> = {}): McpServerItem => ({
  id: 1,
  name: 'fs-demo',
  description: '文件系统 Server',
  server_type: 'stdio',
  enabled: true,
  last_test_status: null,
  last_test_message: null,
  last_test_tool_count: null,
  last_test_at: null,
  updated_at: '2026-09-10T08:00:00',
  ...overrides,
})

describe('mcp store（列表/加载/启停/删除/测试状态）', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    listMock.mockReset()
    setEnabledMock.mockReset()
    removeMock.mockReset()
    testMock.mockReset()
  })

  it('初始状态为空列表、无错误、无进行中测试', () => {
    const store = useMcpStore()
    expect(store.items).toEqual([])
    expect(store.loading).toBe(false)
    expect(store.error).toBeNull()
    expect(store.testingId).toBeNull()
  })

  it('fetchServers 成功写入列表并清除错误', async () => {
    listMock.mockResolvedValue([fakeItem()])
    const store = useMcpStore()
    await store.fetchServers()
    expect(store.items).toHaveLength(1)
    expect(store.error).toBeNull()
  })

  it('fetchServers 空列表保持空态', async () => {
    listMock.mockResolvedValue([])
    const store = useMcpStore()
    await store.fetchServers()
    expect(store.items).toEqual([])
  })

  it('fetchServers 失败写入人话错误，不清空已有数据', async () => {
    const store = useMcpStore()
    listMock.mockResolvedValueOnce([fakeItem()])
    await store.fetchServers()
    listMock.mockRejectedValueOnce(new Error('后端服务未启动'))
    await store.fetchServers()
    expect(store.error).toBe('后端服务未启动')
    expect(store.items).toHaveLength(1)
  })

  it('setEnabled 成功后就地替换该行', async () => {
    listMock.mockResolvedValue([fakeItem()])
    const store = useMcpStore()
    await store.fetchServers()

    setEnabledMock.mockResolvedValue(fakeItem({ enabled: false }))
    await store.setEnabled(1, false)
    expect(store.items[0]?.enabled).toBe(false)
  })

  it('remove 成功后移除该行', async () => {
    listMock.mockResolvedValue([fakeItem(), fakeItem({ id: 2 })])
    const store = useMcpStore()
    await store.fetchServers()

    removeMock.mockResolvedValue({ deleted: true })
    await store.remove(1)
    expect(store.items).toHaveLength(1)
    expect(store.items[0]?.id).toBe(2)
  })

  it('test 期间 testingId 置位，完成后复位并以 item 替换行（FR-030）', async () => {
    listMock.mockResolvedValue([fakeItem()])
    const store = useMcpStore()
    await store.fetchServers()

    const result: McpTestResult = {
      status: 'success',
      category: null,
      message: '连接成功，发现 2 个工具',
      tool_count: 2,
      tools: [],
      item: fakeItem({
        last_test_status: 'success',
        last_test_message: '连接成功，发现 2 个工具',
        last_test_tool_count: 2,
      }),
    }
    let release: (value: McpTestResult) => void = () => {}
    testMock.mockReturnValue(
      new Promise<McpTestResult>((resolve) => {
        release = resolve
      }),
    )
    const pending = store.test(1)
    expect(store.testingId).toBe(1)
    release(result)
    await pending
    expect(store.testingId).toBeNull()
    expect(store.items[0]?.last_test_status).toBe('success')
    expect(store.items[0]?.last_test_tool_count).toBe(2)
  })

  it('test 失败时 testingId 仍复位', async () => {
    listMock.mockResolvedValue([fakeItem()])
    const store = useMcpStore()
    await store.fetchServers()

    testMock.mockRejectedValue(new Error('该 Server 正在测试中'))
    await expect(store.test(1)).rejects.toThrow('该 Server 正在测试中')
    expect(store.testingId).toBeNull()
  })
})
