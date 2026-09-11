import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { skillsApi } from '@/api/skills'

const fetchMock = vi.fn()

beforeEach(() => {
  vi.stubGlobal('fetch', fetchMock)
})

afterEach(() => {
  vi.unstubAllGlobals()
  fetchMock.mockReset()
})

function jsonResponse(body: unknown): Response {
  return {
    ok: true,
    status: 200,
    json: () => Promise.resolve(body),
  } as unknown as Response
}

describe('skills api（005 目录树与文件编辑封装）', () => {
  it('tree 请求正确编码目录名', async () => {
    fetchMock.mockResolvedValue(jsonResponse([]))
    await skillsApi.tree('my skill')
    expect(fetchMock).toHaveBeenCalledWith('/api/skills/my%20skill/tree', expect.anything())
  })

  it('readFile 的 path 经 query 传递并完整编码（安全相关）', async () => {
    fetchMock.mockResolvedValue(
      jsonResponse({ path: 'scripts/run.py', editable: true, reason: null, content: 'x', size: 1 }),
    )
    await skillsApi.readFile('demo', 'scripts/run.py')
    const [url] = fetchMock.mock.calls[0] as [string]
    expect(url).toBe('/api/skills/demo/file?path=scripts%2Frun.py')
  })

  it('readFile 编码特殊字符（../ 与空格不落在路径段）', async () => {
    fetchMock.mockResolvedValue(jsonResponse({ path: 'x', editable: true, reason: null, content: '', size: 0 }))
    await skillsApi.readFile('demo', '../secret file.txt')
    const [url] = fetchMock.mock.calls[0] as [string]
    expect(url).toBe(
      '/api/skills/demo/file?path=..%2Fsecret%20file.txt',
    )
  })

  it('writeFile 以 PUT JSON 提交 path 与 content', async () => {
    fetchMock.mockResolvedValue(jsonResponse({ saved: true, path: 'notes.txt' }))
    await skillsApi.writeFile('demo', { path: 'notes.txt', content: '内容' })
    const [, init] = fetchMock.mock.calls[0] as [string, RequestInit]
    expect(init.method).toBe('PUT')
    expect(init.body).toBe(JSON.stringify({ path: 'notes.txt', content: '内容' }))
  })
})
