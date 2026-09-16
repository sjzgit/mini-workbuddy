"""sanitize 模块单元测试（011 FR-020/021，SC-004 的单点保证）。"""

from app.services.sanitize import sanitize_messages, sanitize_text

MASK = "***"


def test_mask_openai_style_key() -> None:
    text = "调用失败：密钥 sk-abc123XYZ_def-456ghi 无效"
    assert "sk-abc123XYZ_def-456ghi" not in sanitize_text(text)
    assert MASK in sanitize_text(text)


def test_mask_bearer_and_authorization_header() -> None:
    text = "Authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9xxx"
    sanitized = sanitize_text(text)
    assert "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9xxx" not in sanitized
    assert MASK in sanitized


def test_mask_secret_assignment_forms() -> None:
    text = 'api_key = "my-secret-value"\n{"api_key": "another-secret"}'
    sanitized = sanitize_text(text)
    assert "my-secret-value" not in sanitized
    assert "another-secret" not in sanitized


def test_mask_env_assignment_line() -> None:
    text = "OPENAI_API_KEY=supersecretvalue123\n其他内容保持"
    sanitized = sanitize_text(text)
    assert "supersecretvalue123" not in sanitized
    assert "OPENAI_API_KEY=" in sanitized  # 键名保留，值打码


def test_windows_path_replaced_with_placeholder() -> None:
    text = r"读取文件 C:\Users\Administrator.DESKTOP-69S2QHR\secret.txt 失败"
    sanitized = sanitize_text(text)
    assert "Administrator" not in sanitized
    assert "${path}" in sanitized


def test_workspace_path_uses_workspace_placeholder() -> None:
    text = r"写入 F:\工作备忘录\修炼\叶小钗\AI-10\mini-workbuddy\backend\workspace\skills\a\skill.md"
    sanitized = sanitize_text(
        text,
        workspace_prefix=r"F:\工作备忘录\修炼\叶小钗\AI-10\mini-workbuddy\backend\workspace",
    )
    assert "F:\\" not in sanitized
    assert "${workspace}" in sanitized


def test_plain_text_unchanged() -> None:
    text = "今天天气不错，工具执行成功，共返回 12 条记录。"
    assert sanitize_text(text) == text


def test_sanitize_is_idempotent() -> None:
    text = "key=sk-abcdef123456789 C:\\Users\\someone\\file.txt"
    once = sanitize_text(text)
    assert sanitize_text(once) == once


def test_sanitize_messages_structure_preserved() -> None:
    messages = [
        {"role": "system", "content": "你使用的密钥是 sk-abcdef123456789"},
        {"role": "assistant", "content": "好的", "tool_calls": [
            {"id": "call_1", "type": "function",
             "function": {"name": "shell", "arguments": "{\"cmd\": \"echo sk-abcdef123456789\"}"}},
        ]},
        {"role": "tool", "tool_call_id": "call_1", "content": r"输出 C:\Users\me\log.txt"},
    ]
    sanitized = sanitize_messages(messages)
    assert sanitized[0]["role"] == "system"
    assert "sk-abcdef123456789" not in sanitized[0]["content"]
    assert "sk-abcdef123456789" not in sanitized[1]["tool_calls"][0]["function"]["arguments"]
    assert sanitized[1]["tool_calls"][0]["function"]["name"] == "shell"
    assert "C:\\Users" not in sanitized[2]["content"]
