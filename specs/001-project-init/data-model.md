# Data Model: 项目初始化（第一阶段）

**Feature**: 001-project-init | **Date**: 2026-09-10

## 概述

本阶段（工程初始化）**不含任何业务数据实体**。数据库侧仅建立：

1. 正式的 SQLite 连接（SQLAlchemy engine + session，见 `backend/app/core/db.py`）
2. Alembic 迁移环境与**空基线迁移**（`alembic_version` 表由 Alembic 自管理，为唯一自动产生的持久化结构）

## 实体清单

| 实体 | 状态 | 说明 |
|------|------|------|
| （无业务实体） | — | 业务实体（Agent、模型配置、对话、运行记录等）将在后续各模块 feature 的 `data-model.md` 中定义，并遵循宪法 II：spec 数据模型 → SQLAlchemy ORM 实现 |

## 数据访问约定（本阶段确立，后续模块遵循）

- 所有 ORM 模型统一继承 `backend/app/models/`（首个业务模块建立）中声明的 `Base`
- Alembic `env.py` 的 `target_metadata` 指向该 `Base.metadata`，后续建表全部经 `uv run alembic revision --autogenerate` 产生迁移
- Session 以 FastAPI 依赖注入方式提供给路由层，禁止在路由内直接创建 engine/session
- 数据库文件默认 `backend/app.db`，经配置项 `DATABASE_URL` 覆盖（见 research.md D6）

## 验证规则

- 本阶段验收仅要求：迁移命令可执行且可重复执行（SC-006）、健康检查能通过 session 执行 `SELECT 1`（见 [contracts/api-contract.md](contracts/api-contract.md)）
