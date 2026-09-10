# API Contract: 项目初始化（第一阶段）

**Feature**: 001-project-init | **Date**: 2026-09-10

## 概述

本阶段对外接口仅一个健康检查端点，用于验证：FastAPI 应用存活、`/api` 前缀挂载正确、SQLite 数据库连接可用。它是前端 `request.ts` 封装与 Vite 代理链路的验证锚点。

**契约主定义**：本文件 → `backend/app/schemas/health.py`（Pydantic 实现）→ `frontend/src/api/health.ts`（TypeScript 类型派生）。实现侧 MUST 与本契约一致（宪法 II/III）。

## 端点

### GET /api/health

健康检查。执行一次数据库连接探测（`SELECT 1`）。

**请求**：无参数、无请求体。

**响应**

| 状态码 | 条件 | 响应体 |
|--------|------|--------|
| 200 | 应用与数据库连接均正常 | `{ "status": "ok" }` |
| 503 | 数据库连接失败 | `{ "status": "unhealthy", "detail": "<简短原因描述>" }` |

**响应体字段**

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| status | `"ok"` \| `"unhealthy"` | 是 | 健康状态 |
| detail | string | 仅 503 | 数据库不可用的简短原因，供运维排查，不暴露内部细节 |

**示例**

```json
// 200
{ "status": "ok" }

// 503
{ "status": "unhealthy", "detail": "database unavailable" }
```

## 通用约定（本阶段确立，后续端点遵循）

- 所有接口路径以 `/api` 为前缀；开发环境由 Vite 代理转发（FR-005）
- 请求/响应体均为 `application/json`
- Pydantic Schema 定义于 `backend/app/schemas/`，是字段与类型的唯一权威；OpenAPI 由 FastAPI 自动生成
- 前端接口模块位于 `frontend/src/api/`，类型从本契约派生，禁止手工漂移

## 变更流程

契约变更 MUST 先更新本文件并经过审查（宪法 III），再同步 Pydantic Schema 与前端类型。
