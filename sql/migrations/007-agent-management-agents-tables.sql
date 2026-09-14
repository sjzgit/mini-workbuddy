-- 007-agent-management：新增 agents / agent_bindings / agent_prompt_versions 三表
-- 对应 Alembic 迁移：d4e5f6a7b8c9（backend/migrations/versions/）
-- 数据模型主定义：specs/007-agent-management/data-model.md §1–§3

CREATE TABLE agents (
    id INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT,
    name VARCHAR(100) NOT NULL,
    description VARCHAR(500) DEFAULT '' NOT NULL,
    model_id INTEGER NOT NULL,
    system_prompt TEXT NOT NULL,
    max_rounds INTEGER DEFAULT 10 NOT NULL,
    enable_deep_thinking BOOLEAN DEFAULT 0 NOT NULL,
    thinking_level VARCHAR(10) DEFAULT 'off' NOT NULL,
    is_default BOOLEAN NOT NULL,
    created_at DATETIME NOT NULL,
    updated_at DATETIME NOT NULL
);
CREATE UNIQUE INDEX uq_agents_single_default ON agents (is_default) WHERE is_default = 1;
CREATE INDEX ix_agents_updated_at ON agents (updated_at);

CREATE TABLE agent_bindings (
    id INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT,
    agent_id INTEGER NOT NULL,
    resource_type VARCHAR(10) NOT NULL,
    resource_id INTEGER NOT NULL,
    created_at DATETIME NOT NULL,
    FOREIGN KEY(agent_id) REFERENCES agents (id) ON DELETE CASCADE
);
CREATE UNIQUE INDEX uq_agent_bindings_unique ON agent_bindings (agent_id, resource_type, resource_id);
CREATE INDEX ix_agent_bindings_resource ON agent_bindings (resource_type, resource_id);

CREATE TABLE agent_prompt_versions (
    id INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT,
    agent_id INTEGER NOT NULL,
    version INTEGER NOT NULL,
    content TEXT NOT NULL,
    created_at DATETIME NOT NULL,
    FOREIGN KEY(agent_id) REFERENCES agents (id) ON DELETE CASCADE
);
CREATE UNIQUE INDEX uq_agent_prompt_versions ON agent_prompt_versions (agent_id, version);
