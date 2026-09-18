/**
 * 评测 API 封装（specs/012，契约主定义 specs/012-agent-evaluation/contracts/evaluation-api.md）。
 * 类型 MUST 与后端 schemas/evaluation.py 逐字段对齐，变更先改契约。
 */
import { http } from './request'

// ---- 枚举与常量（契约唯一主定义，实现侧只消费）----

export type EvaluatorType = 'llm_judge' | 'exact_match'
export const EVALUATOR_TYPES: EvaluatorType[] = ['llm_judge', 'exact_match']

export type EvalRunStatus =
  | 'pending' | 'running' | 'paused'
  | 'completed' | 'cancelled' | 'failed' | 'interrupted'
export const EVAL_RUN_STATUSES: EvalRunStatus[] = [
  'pending', 'running', 'paused', 'completed', 'cancelled', 'failed', 'interrupted',
]

export type CaseRunStatus =
  | 'pending' | 'running' | 'passed' | 'failed'
  | 'execution_failed' | 'judge_failed' | 'cancelled'

export const EVAL_RUN_STATUS_META: Record<EvalRunStatus, { text: string; color: string }> = {
  pending: { text: '待运行', color: 'default' },
  running: { text: '运行中', color: 'processing' },
  paused: { text: '已暂停', color: 'warning' },
  completed: { text: '已完成', color: 'success' },
  cancelled: { text: '已取消', color: 'default' },
  failed: { text: '失败', color: 'error' },
  interrupted: { text: '已中断', color: 'warning' },
}

export const CASE_RUN_STATUS_META: Record<CaseRunStatus, { text: string; color: string }> = {
  pending: { text: '待执行', color: 'default' },
  running: { text: '执行中', color: 'processing' },
  passed: { text: '通过', color: 'success' },
  failed: { text: '未通过', color: 'error' },
  execution_failed: { text: '执行失败', color: 'error' },
  judge_failed: { text: '评分失败', color: 'warning' },
  cancelled: { text: '已取消', color: 'default' },
}

// ---- 数据结构 ----

export interface Dataset {
  id: number
  name: string
  description: string
  case_count: number
  created_at: string
  updated_at: string
}

export interface DatasetCase {
  id: number
  dataset_id: number
  user_question: string
  expected_answer: string | null
  scoring_criteria: string | null
  created_at: string
  updated_at: string
}

export interface ImportResult {
  imported_cases: number
  skipped_cases: number
  errors: string[]
}

export interface SnapshotCase {
  case_id: number
  user_question: string
  expected_answer: string | null
  scoring_criteria: string | null
}

export interface EvalTask {
  id: number
  name: string
  agent_id: number
  agent_name: string
  dataset_id: number
  dataset_name: string
  evaluator_type: string
  evaluator_config: Record<string, unknown>
  pass_threshold: number
  status: string
  case_count: number
  last_run_id: number | null
  last_run_status: string | null
  created_at: string
  updated_at: string
  // 详情专有（三快照）
  agent_snapshot?: Record<string, unknown>
  dataset_snapshot?: { cases?: SnapshotCase[] } & Record<string, unknown>
  evaluator_snapshot?: Record<string, unknown>
}

export interface EvalTaskSaveRequest {
  name: string
  agent_id: number
  dataset_id: number
  evaluator_type: EvaluatorType
  evaluator_config: { model_model_id?: number; temperature?: number; max_tokens?: number; prompt_template?: string | null }
  pass_threshold: number
}

export interface EvalRun {
  id: number
  task_id: number
  run_id: string
  status: EvalRunStatus
  started_at: string | null
  finished_at: string | null
  interrupted_at: string | null
  interrupted_reason: string | null
  total_cases: number
  completed_cases: number
  passed_cases: number
  failed_cases: number
  execution_failed_cases: number
  judge_failed_cases: number
  cancelled_cases: number
  average_score: number | null
  pass_rate: number | null
  total_duration_ms: number | null
  total_tokens: number | null
  created_at: string
}

export interface EvalRunListResponse {
  items: EvalRun[]
  total: number
  page: number
  page_size: number
}

export interface CaseRun {
  id: number
  evaluation_run_id: number
  dataset_case_id: number
  status: CaseRunStatus
  agent_run_id: string | null
  score: number | null
  reason: string | null
  evaluator_type: string | null
  evaluator_metadata: Record<string, unknown> | null
  duration_ms: number | null
  input_tokens: number | null
  output_tokens: number | null
  total_tokens: number | null
  tool_call_count: number | null
  model_call_count: number | null
  iteration_count: number | null
  error_type: string | null
  error_message: string | null
  attempt: number
  started_at: string | null
  finished_at: string | null
  case_index: number | null
  snapshot_case: SnapshotCase | null
}

// ---- 数据集 ----

export async function listDatasets(): Promise<Dataset[]> {
  return http.get<Dataset[]>('/evaluation/datasets')
}

export async function createDataset(payload: { name: string; description: string }): Promise<Dataset> {
  return http.post<Dataset>('/evaluation/datasets', payload)
}

export async function updateDataset(id: number, payload: { name: string; description: string }): Promise<Dataset> {
  return http.put<Dataset>(`/evaluation/datasets/${id}`, payload)
}

export async function deleteDataset(id: number): Promise<void> {
  await http.del(`/evaluation/datasets/${id}`)
}

export async function listDatasetCases(datasetId: number): Promise<DatasetCase[]> {
  return http.get<DatasetCase[]>(`/evaluation/datasets/${datasetId}/cases`)
}

export async function createDatasetCase(
  datasetId: number,
  payload: { user_question: string; expected_answer?: string | null; scoring_criteria?: string | null },
): Promise<DatasetCase> {
  return http.post<DatasetCase>(`/evaluation/datasets/${datasetId}/cases`, payload)
}

export async function updateDatasetCase(
  datasetId: number,
  caseId: number,
  payload: { user_question: string; expected_answer?: string | null; scoring_criteria?: string | null },
): Promise<DatasetCase> {
  return http.put<DatasetCase>(`/evaluation/datasets/${datasetId}/cases/${caseId}`, payload)
}

export async function deleteDatasetCase(datasetId: number, caseId: number): Promise<void> {
  await http.del(`/evaluation/datasets/${datasetId}/cases/${caseId}`)
}

export async function importDatasetCases(datasetId: number, payload: unknown): Promise<ImportResult> {
  return http.post<ImportResult>(`/evaluation/datasets/${datasetId}/import`, payload)
}

export function exportDatasetUrl(datasetId: number): string {
  return `/api/evaluation/datasets/${datasetId}/export`
}

// ---- 评测任务 ----

export async function listEvalTasks(): Promise<EvalTask[]> {
  return http.get<EvalTask[]>('/evaluation/tasks')
}

export async function createEvalTask(payload: EvalTaskSaveRequest): Promise<EvalTask> {
  return http.post<EvalTask>('/evaluation/tasks', payload)
}

export async function getEvalTask(id: number): Promise<EvalTask> {
  return http.get<EvalTask>(`/evaluation/tasks/${id}`)
}

export async function deleteEvalTask(id: number): Promise<void> {
  await http.del(`/evaluation/tasks/${id}`)
}

// ---- 评测运行 ----

export interface EvalRunListParams {
  task_id?: number
  status?: EvalRunStatus
  page?: number
  page_size?: number
}

export async function listEvalRuns(params: EvalRunListParams = {}): Promise<EvalRunListResponse> {
  const search = new URLSearchParams()
  if (params.task_id != null) search.set('task_id', String(params.task_id))
  if (params.status) search.set('status', params.status)
  if (params.page != null) search.set('page', String(params.page))
  if (params.page_size != null) search.set('page_size', String(params.page_size))
  const query = search.toString()
  return http.get<EvalRunListResponse>(`/evaluation/runs${query ? `?${query}` : ''}`)
}

export async function getEvalRun(id: number): Promise<EvalRun> {
  return http.get<EvalRun>(`/evaluation/runs/${id}`)
}

export async function listEvalRunCases(runId: number): Promise<CaseRun[]> {
  return http.get<CaseRun[]>(`/evaluation/runs/${runId}/cases`)
}

export async function getEvalRunCase(runId: number, caseRunId: number): Promise<CaseRun> {
  return http.get<CaseRun>(`/evaluation/runs/${runId}/cases/${caseRunId}`)
}

export async function startEvalRun(taskId: number): Promise<EvalRun> {
  return http.post<EvalRun>(`/evaluation/tasks/${taskId}/runs`)
}

export async function pauseEvalRun(runId: number): Promise<EvalRun> {
  return http.post<EvalRun>(`/evaluation/runs/${runId}/pause`)
}

export async function resumeEvalRun(runId: number): Promise<EvalRun> {
  return http.post<EvalRun>(`/evaluation/runs/${runId}/resume`)
}

export async function cancelEvalRun(runId: number): Promise<EvalRun> {
  return http.post<EvalRun>(`/evaluation/runs/${runId}/cancel`)
}

export async function retryEvalRunCase(runId: number, caseRunId: number): Promise<{ run: EvalRun; case_run: CaseRun }> {
  return http.post(`/evaluation/runs/${runId}/retry`, { case_run_id: caseRunId })
}
