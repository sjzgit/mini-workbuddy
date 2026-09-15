-- 008-chat-conversations：新增 conversations / messages 两表
-- 对应 Alembic 迁移：backend/migrations/versions/（008 阶段生成）
-- 数据模型主定义：specs/008-chat-conversations/data-model.md §1–§2

CREATE TABLE conversations (
    id INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT,
    title VARCHAR(100) DEFAULT '新会话' NOT NULL,
    agent_id INTEGER NOT NULL,
    created_at DATETIME NOT NULL,
    updated_at DATETIME NOT NULL
);
CREATE INDEX ix_conversations_updated_at ON conversations (updated_at);

CREATE TABLE messages (
    id INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT,
    conversation_id INTEGER NOT NULL,
    role VARCHAR(10) NOT NULL,
    agent_id INTEGER,
    agent_name VARCHAR(100),
    reasoning_content TEXT,
    content TEXT DEFAULT '' NOT NULL,
    status VARCHAR(12) DEFAULT 'completed' NOT NULL,
    seq INTEGER NOT NULL,
    created_at DATETIME NOT NULL,
    FOREIGN KEY(conversation_id) REFERENCES conversations (id) ON DELETE CASCADE
);
CREATE UNIQUE INDEX uq_messages_conversation_seq ON messages (conversation_id, seq);
