"""统一脱敏（specs/011-context-compression-run-records，FR-020/021）。

写入 run_payloads / runs.error_summary / 持久化事件前的最后一道防线：
密钥、认证头、环境变量赋值、用户设备绝对路径不进入持久化记录。
幂等：已脱敏文本再次经过本模块结果不变（*** 不会再被匹配改写）。
"""

import re

# 密钥形态：OpenAI 风格 sk- 前缀 token（含 URL-safe 变体）
_KEY_PATTERN = re.compile(r"sk-[A-Za-z0-9_-]{8,}")
# Bearer / Authorization 头形态
_BEARER_PATTERN = re.compile(r"(?i)bearer\s+[A-Za-z0-9._~+/=-]{8,}")
_AUTH_HEADER_PATTERN = re.compile(
    r"(?i)(authorization\s*[:=]\s*).+",
)
# 常见 secret 赋值形态：api_key=xxx / "api_key": "xxx" / token: xxx
_SECRET_ASSIGN_PATTERN = re.compile(
    r"(?i)((?:api[_-]?key|secret|token|password|access[_-]?key)(?:\s*[\"']?\s*[:=]\s*[\"']?))"
    r"([^\"',\s}{\]]+)",
)
# 环境变量整行赋值：KEY=value（KEY 全大写下划线）
_ENV_ASSIGN_PATTERN = re.compile(
    r"(?m)^([A-Z][A-Z0-9_]{2,}=)[^\s]+$"
)

# 用户设备绝对路径 → 占位符
_WINDOWS_PATH_PATTERN = re.compile(
    r"[A-Za-z]:\\(?:[^\\/:*?\"<>|\r\n]+\\)*[^\\/:*?\"<>|\r\n]+"
)
_UNIX_PATH_PATTERN = re.compile(
    r"(?<![\w:])/(?:home|Users|root|mnt|opt|var)/[\w.\-/]+"
)

_MASK = "***"
# workspace 目录占位（运行时按实际授权目录前缀替换，见 sanitize_workspace_path）
WORKSPACE_PLACEHOLDER = "${workspace}"
PATH_PLACEHOLDER = "${path}"


def sanitize_text(text: str, workspace_prefix: str | None = None) -> str:
    """对任意文本脱敏：密钥/认证头/secret 赋值/环境变量值/绝对路径。

    workspace_prefix 提供（通常为 authorized_dir 绝对路径）时，该前缀开头
    的路径替换为 ${workspace}；其余绝对路径替换为 ${path}。
    """
    if not text:
        return text
    result = _KEY_PATTERN.sub(_MASK, text)
    result = _BEARER_PATTERN.sub("Bearer " + _MASK, result)
    result = _AUTH_HEADER_PATTERN.sub(lambda m: m.group(1) + _MASK, result)
    result = _SECRET_ASSIGN_PATTERN.sub(lambda m: m.group(1) + _MASK, result)
    result = _ENV_ASSIGN_PATTERN.sub(lambda m: m.group(1) + _MASK, result)
    if workspace_prefix:
        escaped = re.escape(workspace_prefix.rstrip("\\/"))
        result = re.sub(
            escaped + r"[\\/][^\s\"'，。）}{\]]*",
            WORKSPACE_PLACEHOLDER,
            result,
        )
    result = _WINDOWS_PATH_PATTERN.sub(PATH_PLACEHOLDER, result)
    result = _UNIX_PATH_PATTERN.sub(PATH_PLACEHOLDER, result)
    return result


def sanitize_messages(
    messages: list[dict], workspace_prefix: str | None = None,
) -> list[dict]:
    """对 messages 数组逐条脱敏（run_payloads model_input 写入前调用）。

    只处理字符串值（content/tool_call_id 等）；结构保持原样，JSON 可序列化。
    """
    sanitized: list[dict] = []
    for message in messages:
        item: dict = {}
        for key, value in message.items():
            if isinstance(value, str):
                item[key] = sanitize_text(value, workspace_prefix)
            elif isinstance(value, list):
                item[key] = [
                    _sanitize_tool_call(call, workspace_prefix)
                    if isinstance(call, dict) else call
                    for call in value
                ]
            else:
                item[key] = value
        sanitized.append(item)
    return sanitized


def _sanitize_tool_call(call: dict, workspace_prefix: str | None) -> dict:
    out: dict = {}
    for key, value in call.items():
        if key == "function" and isinstance(value, dict):
            out[key] = {
                fk: sanitize_text(fv, workspace_prefix) if isinstance(fv, str) else fv
                for fk, fv in value.items()
            }
        elif isinstance(value, str):
            out[key] = sanitize_text(value, workspace_prefix)
        else:
            out[key] = value
    return out
