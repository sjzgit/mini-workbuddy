"""统一上下文构造器（specs/011 阶段优化：ContextBuilder）。

运行时发送给模型的完整上下文由本类统一负责组装与演化：

    System Prompt
    + Skill Instructions          （并入 system 消息）
    + Tool Definitions            （tools_payload，随请求发送，不占 messages）
    + Summary                     （已有会话摘要，role=user 会话背景）
    + History                     （边界过滤后的有效历史）
    + Current Input               （本次用户消息，已在 History 末位或显式追加）
    + Current Tool Results        （运行内工具交互，按轮追加）

Runtime 主循环只经本类读写上下文；压缩（compression.py）通过
apply_compaction 重写上下文，不再直接操作消息列表。
"""

from typing import Any

NL2 = "\n\n"


class ContextBuilder:
    """一次运行的模型上下文（messages + tools_payload）唯一持有者。

    prefix_len = 固定前缀（system + summary）长度；压缩边界/估算依赖该值。
    """

    def __init__(self) -> None:
        self.messages: list[dict[str, Any]] = []
        self.tools_payload: list[dict[str, Any]] | None = None
        self.prefix_len: int = 0
        self.summary_text: str = ""

    # ---- 组装（运行启动时按序调用）----

    def set_fixed_prefix(
        self,
        system_parts: list[str],
        summary_text: str,
        summary_role: str = "user",
    ) -> None:
        """System Prompt + Skill Instructions（并入 system）+ Summary。"""
        if system_parts:
            self.messages.append({"role": "system", "content": NL2.join(system_parts)})
        if summary_text:
            self.messages.append({"role": summary_role, "content": summary_text})
        self.summary_text = summary_text
        self.prefix_len = len(self.messages)

    def set_history(self, history_messages: list[dict[str, Any]]) -> None:
        """有效历史（边界过滤后，seq 升序）；本次用户消息已在末位或由 append_current_input 追加。"""
        self.messages.extend(history_messages)

    def append_current_input(self, content: str) -> None:
        """Current Input：直接调用 Runtime（评测）场景，本次输入不在历史中时追加一次。"""
        if content:
            self.messages.append({"role": "user", "content": content})

    def set_tools(self, tools_payload: list[dict[str, Any]] | None) -> None:
        """Tool Definitions（OpenAI function calling 格式，随请求发送）。"""
        self.tools_payload = tools_payload

    # ---- 运行期演化 ----

    def append_tool_exchange(
        self,
        assistant_message: dict[str, Any],
        tool_messages: list[dict[str, Any]],
    ) -> None:
        """一轮工具交互：先 assistant(tool_calls)，后逐个 tool 结果（顺序敏感）。"""
        self.messages.append(assistant_message)
        self.messages.extend(tool_messages)

    def apply_compaction(self, new_summary: str, kept_messages: list[dict[str, Any]], summary_role: str = "user") -> None:
        """压缩重写：固定前缀（system）+ 新摘要 + 保留消息；prefix_len 同步推进。"""
        prefix = self.messages[: 1] if (self.messages and self.messages[0].get("role") == "system") else []
        summary_part: list[dict[str, Any]] = []
        if new_summary:
            summary_part = [{"role": summary_role, "content": new_summary}]
        # 原地改写：外部持有的同一 list 引用（ctx.messages）保持有效
        self.messages[:] = prefix + summary_part + list(kept_messages)
        self.summary_text = new_summary
        self.prefix_len = len(prefix) + len(summary_part)

    def prefix(self) -> list[dict[str, Any]]:
        """固定前缀消息（system + summary）。"""
        return self.messages[: self.prefix_len]

    def snapshot(self) -> list[dict[str, Any]]:
        """本次请求实际发送内容的快照（浅拷贝列表，dict 不深拷贝）。"""
        return list(self.messages)
