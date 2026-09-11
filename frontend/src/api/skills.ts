/**
 * Skills 管理接口封装。
 *
 * 契约主定义：specs/004-skills-mcp-management/contracts/skills-api.md
 * 类型 MUST 与契约逐字段对齐（null 不混用 undefined）。
 */

/** 列表项 */
export interface SkillItem {
  dir_name: string
  name: string
  description: string
  enabled: boolean
  updated_at: string
}

/** 详情（编辑页数据源） */
export interface SkillDetail extends SkillItem {
  instruction: string
}

/** 编辑提交体 */
export interface SkillUpdatePayload {
  name: string
  description: string
  instruction: string
}

/** 刷新响应 */
export interface SkillRefreshResult {
  items: SkillItem[]
  skipped: string[]
}

/** 删除响应 */
export interface SkillDeletedResponse {
  deleted: boolean
}

// ---- 目录树与文件在线编辑（契约 skill-files-api.md §2，005）----

/** 目录树节点（递归；文件 children 恒为 []） */
export interface SkillFileNode {
  name: string
  path: string
  type: 'file' | 'dir'
  children: SkillFileNode[]
}

/** 单文件读取响应；editable=false 时 content 恒为 null（零乱码） */
export interface SkillFileContent {
  path: string
  editable: boolean
  reason: 'not_text' | 'too_large' | null
  content: string | null
  size: number
}

/** 保存文件提交体（覆盖写，空内容合法） */
export interface SkillFileWritePayload {
  path: string
  content: string
}

/** 保存文件成功响应 */
export interface SkillFileSavedResponse {
  saved: boolean
  path: string
}

import { http } from './request'

export const skillsApi = {
  list(): Promise<SkillItem[]> {
    return http.get<SkillItem[]>('/skills')
  },
  detail(dirName: string): Promise<SkillDetail> {
    return http.get<SkillDetail>(`/skills/${encodeURIComponent(dirName)}`)
  },
  update(dirName: string, payload: SkillUpdatePayload): Promise<SkillItem> {
    return http.put<SkillItem>(`/skills/${encodeURIComponent(dirName)}`, payload)
  },
  setEnabled(dirName: string, enabled: boolean): Promise<SkillItem> {
    return http.put<SkillItem>(`/skills/${encodeURIComponent(dirName)}/enabled`, { enabled })
  },
  remove(dirName: string): Promise<SkillDeletedResponse> {
    return http.del<SkillDeletedResponse>(`/skills/${encodeURIComponent(dirName)}`)
  },
  refresh(): Promise<SkillRefreshResult> {
    return http.post<SkillRefreshResult>('/skills/refresh')
  },
  /** 目录树（US2） */
  tree(dirName: string): Promise<SkillFileNode[]> {
    return http.get<SkillFileNode[]>(`/skills/${encodeURIComponent(dirName)}/tree`)
  },
  /** 读取文件（US3）；path 经 query 传递，必须编码（防 `/` `..` 等被路由误解析） */
  readFile(dirName: string, path: string): Promise<SkillFileContent> {
    return http.get<SkillFileContent>(
      `/skills/${encodeURIComponent(dirName)}/file?path=${encodeURIComponent(path)}`,
    )
  },
  /** 保存文件（US3）：覆盖写回 */
  writeFile(dirName: string, payload: SkillFileWritePayload): Promise<SkillFileSavedResponse> {
    return http.put<SkillFileSavedResponse>(
      `/skills/${encodeURIComponent(dirName)}/file`,
      payload,
    )
  },
  /** ZIP 导入（multipart，契约 §4.7） */
  async importZip(file: File): Promise<SkillItem> {
    const form = new FormData()
    form.append('file', file)
    let response: Response
    try {
      response = await fetch('/api/skills/import', { method: 'POST', body: form })
    } catch {
      throw new (await import('./request')).ApiError(0, '网络请求失败，请检查后端服务是否已启动')
    }
    if (!response.ok) {
      let detail = `导入失败（HTTP ${response.status}）`
      try {
        const body = (await response.json()) as { detail?: string }
        if (body?.detail) detail = body.detail
      } catch {
        // 非 JSON 响应体，保留默认错误信息
      }
      throw new (await import('./request')).ApiError(response.status, detail)
    }
    return (await response.json()) as SkillItem
  },
}
