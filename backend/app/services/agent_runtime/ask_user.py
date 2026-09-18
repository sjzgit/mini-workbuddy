"""Ask User 挂起注册表（specs/013-ask-user-tool/contracts/ask-user-api.md）。

进程内 {call_id: PendingAsk}（先例：generation_registry 的单进程假设）：
runtime 的 ask_user 分支注册等待，回答端点 submit_answer 写入答案并唤醒。
等待中的运行暂停推进（FR-010）；取消/超时不经回答路径（FR-011/013）。
"""

import asyncio
from dataclasses import dataclass, field


@dataclass
class PendingAsk:
    """一次等待中的询问。answer 语义：selected=选中的选项文本（顺序），text=手动输入。"""

    answered: asyncio.Event = field(default_factory=asyncio.Event)
    selected: list[str] = field(default_factory=list)
    text: str | None = None


_registry: dict[str, PendingAsk] = {}


def register(call_id: str) -> PendingAsk:
    """注册一个等待中的询问（同 call_id 重复注册覆盖——理论上不发生）。"""
    pending = PendingAsk()
    _registry[call_id] = pending
    return pending


def get(call_id: str) -> PendingAsk | None:
    """查询等待中的询问；不存在或已消费后移除则 None。"""
    return _registry.get(call_id)


def remove(call_id: str) -> None:
    """移除挂起项（finally 兜底：运行结束零残留）。"""
    _registry.pop(call_id, None)


def submit_answer(call_id: str, selected: list[str], text: str | None) -> bool:
    """提交回答并唤醒挂起的运行；call_id 未命中（已答/已超时/不存在）返回 False。"""
    pending = _registry.get(call_id)
    if pending is None or pending.answered.is_set():
        return False
    pending.selected = list(selected or [])
    pending.text = text
    pending.answered.set()
    return True


def format_answer_text(selected: list[str], text: str | None) -> str:
    """回答 → 交还模型的文本（契约 §4 格式主定义）。

    - 仅选项：按顺序"、"连接
    - 仅文本（开放式/仅"其他"）：文本本身
    - 选项 + 文本：`选项A、选项B；其他：自定义文本`
    """
    has_selected = bool(selected)
    has_text = bool(text and text.strip())
    if has_selected and has_text:
        return "、".join(selected) + f"；其他：{text.strip()}"
    if has_selected:
        return "、".join(selected)
    return (text or "").strip()


def pending_count() -> int:
    """当前挂起数量（测试断言零残留用）。"""
    return len(_registry)


def first_pending_call_id() -> str | None:
    """首个挂起询问的 call_id（测试辅助；无挂起返回 None）。"""
    for call_id in _registry:
        return call_id
    return None
