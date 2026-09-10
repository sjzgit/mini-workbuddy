-- 003-tool-management：新增 tools 表并播种内置工具
-- 对应 Alembic 迁移：b7c8d9e0f1a2（backend/migrations/versions/）
-- 数据模型主定义：specs/003-tool-management/data-model.md

CREATE TABLE tools (
    id INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT,
    name VARCHAR(50) NOT NULL,
    enabled BOOLEAN NOT NULL,
    created_at DATETIME NOT NULL,
    updated_at DATETIME NOT NULL
);

CREATE UNIQUE INDEX uq_tools_name ON tools (name);

-- 播种三条内置工具（默认启用；时间戳由迁移写入 UTC）
INSERT INTO tools (name, enabled, created_at, updated_at) VALUES
    ('current_time', 1, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP),
    ('file_read_write', 1, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP),
    ('shell', 1, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP);
