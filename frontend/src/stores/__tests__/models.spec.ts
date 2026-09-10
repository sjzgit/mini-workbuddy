import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'

import { modelsApi } from '@/api/models'
import { useModelsStore } from '../models'

vi.mock('@/api/models', () => ({
  modelsApi: {
    list: vi.fn(),
  },
}))

const listMock = vi.mocked(modelsApi.list)

describe('models store（列表/加载/错误状态）', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    listMock.mockReset()
  })

  it('初始状态为空列表、无错误、未加载', () => {
    const store = useModelsStore()
    expect(store.items).toEqual([])
    expect(store.loading).toBe(false)
    expect(store.error).toBeNull()
  })

  it('fetchModels 成功写入列表并清除错误', async () => {
    listMock.mockResolvedValue([
      {
        id: 1,
        display_name: '模型A',
        model_identifier: 'gpt-a',
        base_url: 'https://a.example.com/v1',
        context_length: 8192,
        api_key_configured: true,
        is_default: true,
        updated_at: '2026-09-10T08:00:00Z',
      },
    ])
    const store = useModelsStore()
    await store.fetchModels()
    expect(store.items).toHaveLength(1)
    expect(store.items[0]?.display_name).toBe('模型A')
    expect(store.error).toBeNull()
    expect(store.loading).toBe(false)
  })

  it('fetchModels 失败写入人话错误，不清空已有数据', async () => {
    const store = useModelsStore()
    // 先成功一次，保留旧数据
    listMock.mockResolvedValueOnce([])
    await store.fetchModels()
    listMock.mockRejectedValueOnce(new Error('后端服务未启动'))
    await store.fetchModels()
    expect(store.error).toBe('后端服务未启动')
    expect(store.items).toEqual([])
    expect(store.loading).toBe(false)
  })

  it('请求期间 loading 为 true，结束后回落', async () => {
    let release: (value: []) => void = () => {}
    listMock.mockReturnValue(
      new Promise((resolve) => {
        release = resolve
      }) as ReturnType<typeof modelsApi.list>,
    )
    const store = useModelsStore()
    const pending = store.fetchModels()
    expect(store.loading).toBe(true)
    release([])
    await pending
    expect(store.loading).toBe(false)
  })
})
