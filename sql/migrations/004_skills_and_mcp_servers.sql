// SQL 存档：specs/004-skills-mcp-management（与 Alembic 迁移 0ec5128a2206 对应）
// 建表：skills（Skill 启用状态）、mcp_servers（MCP Server 配置与测试快照）
// SQLite 方言；实际迁移以 backend/migrations/versions/0ec5128a2206_add_skills_and_mcp_servers_tables.py 为准

CREATE TABLE skills (
    id INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT,
    dir_name VARCHAR(100) NOT NULL,
    enabled BOOLEAN NOT NULL DEFAULT 1,
    created_at DATETIME NOT NULL,
    updated_at DATETIME NOT NULL
);
CREATE UNIQUE INDEX uq_skills_dir_name ON skills (dir_name);

CREATE TABLE mcp_servers (
    id INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT,
    name VARCHAR(100) NOT NULL,
    description VARCHAR(500) NOT NULL DEFAULT '',
    server_type VARCHAR(10) NOT NULL,
    command VARCHAR(500),
    command_args JSON,
    env_secret_ref INTEGER REFERENCES secrets_vault (id),
    url VARCHAR(500),
    headers_secret_ref INTEGER REFERENCES secrets_vault (id),
    enabled BOOLEAN NOT NULL DEFAULT 1,
    last_test_status VARCHAR(20),
    last_test_message VARCHAR(2000),
    last_test_tool_count INTEGER,
    last_test_at DATETIME,
    tools_json VARCHAR(100000),
    created_at DATETIME NOT NULL,
    updated_at DATETIME NOT NULL
);
CREATE UNIQUE INDEX uq_mcp_servers_name ON mcp_servers (name);
CREATE INDEX ix_mcp_servers_updated_at ON mcp_servers (updated_at);
