-- 002-model-management：新增 models 与 secrets_vault 表
-- 对应 Alembic 迁移：a1b2c3d4e5f6（backend/migrations/versions/）
-- 数据模型主定义：specs/002-model-management/data-model.md

CREATE TABLE secrets_vault (
    id INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT,
    ciphertext VARCHAR(512) NOT NULL,
    created_at DATETIME NOT NULL,
    updated_at DATETIME NOT NULL
);

CREATE TABLE models (
    id INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT,
    display_name VARCHAR(100) NOT NULL,
    model_identifier VARCHAR(200) NOT NULL,
    base_url VARCHAR(500) NOT NULL,
    secret_ref INTEGER,
    context_length INTEGER NOT NULL,
    max_output_tokens INTEGER NOT NULL,
    temperature NUMERIC(3, 1) NOT NULL,
    input_price NUMERIC(10, 4),
    output_price NUMERIC(10, 4),
    cached_input_price NUMERIC(10, 4),
    is_default BOOLEAN NOT NULL,
    created_at DATETIME NOT NULL,
    updated_at DATETIME NOT NULL,
    FOREIGN KEY(secret_ref) REFERENCES secrets_vault (id)
);

CREATE INDEX ix_models_updated_at ON models (updated_at);

-- 部分唯一索引：数据库层保证至多一个默认模型（research R2）
CREATE UNIQUE INDEX uq_models_single_default ON models (is_default) WHERE is_default = 1;
