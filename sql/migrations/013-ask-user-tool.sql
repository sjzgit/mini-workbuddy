-- 013-ask-user-tool：tools 表幂等补种 ask_user 内置工具（默认启用）
-- 对应 Alembic 迁移：e1f2a3b4c5d6（backend/migrations/versions/）
-- 数据模型主定义：specs/013-ask-user-tool/data-model.md §1

INSERT INTO tools (name, enabled, created_at, updated_at)
SELECT 'ask_user', 1, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
WHERE NOT EXISTS (SELECT 1 FROM tools WHERE name = 'ask_user');
