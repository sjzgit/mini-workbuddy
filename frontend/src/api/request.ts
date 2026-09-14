/**
 * 统一请求封装。
 *
 * - 始终请求相对路径 `/api`（开发环境由 Vite 代理转发到后端，FR-005）
 * - 统一 JSON 解析与错误语义
 * - 禁止在前端代码硬编码后端绝对地址
 */

export class ApiError extends Error {
  constructor(
    public readonly status: number,
    message: string,
    /** 原始响应体（409 等结构化错误体用；undefined = 无） */
    public readonly body?: unknown,
  ) {
    super(message)
    this.name = 'ApiError'
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response
  try {
    response = await fetch(`/api${path}`, {
      headers: { Accept: 'application/json', ...init?.headers },
      ...init,
    })
  } catch {
    throw new ApiError(0, '网络请求失败，请检查后端服务是否已启动')
  }

  if (!response.ok) {
    let detail: string | { [key: string]: unknown } = `请求失败（HTTP ${response.status}）`
    let rawBody: unknown
    try {
      const body = (await response.json()) as { detail?: string | { [key: string]: unknown } }
      rawBody = body
      if (typeof body?.detail === 'string') {
        detail = body.detail
      } else if (body?.detail && typeof body.detail === 'object') {
        // 结构化错误体（如 409 requires_new_default）：顶层字段进 body，message 取内层 detail
        const inner = body.detail as { detail?: string }
        detail = inner.detail ?? `请求失败（HTTP ${response.status}）`
      }
    } catch {
      // 非 JSON 响应体，保留默认错误信息
    }
    throw new ApiError(response.status, detail, rawBody)
  }

  return (await response.json()) as T
}

export const http = {
  get<T>(path: string): Promise<T> {
    return request<T>(path)
  },
  post<T>(path: string, body?: unknown): Promise<T> {
    return request<T>(path, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: body === undefined ? undefined : JSON.stringify(body),
    })
  },
  put<T>(path: string, body?: unknown): Promise<T> {
    return request<T>(path, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: body === undefined ? undefined : JSON.stringify(body),
    })
  },
  del<T>(path: string): Promise<T> {
    return request<T>(path, { method: 'DELETE' })
  },
}
