/**
 * 健康检查接口。
 *
 * 契约主定义：specs/001-project-init/contracts/api-contract.md
 * 本文件类型从契约派生，字段与后端 Pydantic Schema（backend/app/schemas/health.py）对齐。
 */
import { http } from './request'

export type HealthStatus = 'ok' | 'unhealthy'

export interface HealthResponse {
  status: HealthStatus
  detail?: string
}

export function getHealth(): Promise<HealthResponse> {
  return http.get<HealthResponse>('/health')
}
