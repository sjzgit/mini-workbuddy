"""压缩摘要提示词模板（specs/011 FR-029/030：任务清单式、前版摘要合并）。

摘要作为会话背景注入上下文（role=user，FR-031），不替代系统提示词。
"""

import json

SUMMARY_ROLE = "user"  # 摘要在上下文中的角色（会话背景，FR-031）

_PROMPT_HEADER = (
    "你是一名会话记录整理助手。请把下面「待整理对话」与「已有摘要」合并为一份新的会话摘要，"
    "供后续对话作为背景资料使用。要求：\n"
    "1. 按任务清单方式整理，保留：用户目标、已确认事实、重要工具结果、明确限制、未完成事项。\n"
    "2. 闲聊、重复表述和失效的中间过程可以缩短或忽略。\n"
    "3. 不得虚构未出现的信息；沿用对话中的原始关键数值与结论。\n"
)
_PROMPT_FOOTER = "\n\n直接输出摘要正文，不要额外解释。"


def format_group_text(group_messages: list[dict]) -> str:
    """把一组消息渲染为可读文本（工具结果完整保留，供模型提炼）。"""
    lines: list[str] = []
    for message in group_messages:
        role = message.get("role", "")
        content = message.get("content") or ""
        if role == "user":
            lines.append(f"[用户] {content}")
        elif role == "assistant":
            tool_calls = message.get("tool_calls")
            if tool_calls:
                lines.append(f"[助手·工具调用] {json.dumps(tool_calls, ensure_ascii=False)}")
            elif content:
                lines.append(f"[助手] {content}")
        elif role == "tool":
            lines.append(f"[工具结果] {content}")
    return "\n".join(lines)


def build_summary_prompt(
    previous_summary: str,
    group_texts: list[str],
    *,
    target_tokens: int,
) -> str:
    """组装摘要请求的完整输入（提示词 + 前版摘要 + 待压缩内容）。"""
    parts = [_PROMPT_HEADER]
    parts.append(f"目标长度：约 {target_tokens} tokens（软目标，按内容完整优先，不强制等长）。")
    if previous_summary.strip():
        parts.append("\n【已有摘要（作为更新基础，须保留其全部有效信息）】")
        parts.append(previous_summary.strip())
    parts.append("\n【待整理对话（按时间顺序）】")
    parts.append("\n\n".join(group_texts))
    parts.append(_PROMPT_FOOTER)
    return "\n".join(parts)


def extract_summary_text(text: str) -> str:
    """摘要后处理：目前仅去除首尾空白（预留后续清理钩子）。"""
    return text.strip()
