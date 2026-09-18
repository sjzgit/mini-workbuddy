-- 014-workspace-permission：conversations 表工作空间三列 + runs 表运行快照列
-- 对应 Alembic 迁移：5ece99f8a6b7（backend/migrations/versions/）
-- 数据模型主定义：specs/014-workspace-permission/data-model.md §1

ALTER TABLE conversations ADD COLUMN workspace_path VARCHAR(500);
ALTER TABLE conversations ADD COLUMN workspace_source VARCHAR(20);
ALTER TABLE conversations ADD COLUMN workspace_selected_at DATETIME;

ALTER TABLE runs ADD COLUMN workspace_path VARCHAR(500);
