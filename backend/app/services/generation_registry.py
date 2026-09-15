"""进程内生成任务注册表（specs/008-chat-conversations/research.md R4/R10）。

单进程假设：生成任务与 SSE 订阅解耦——订阅者先重放缓冲再实时跟随；
终态事件也入缓冲，晚到的订阅者直接收到终态。publish/subscribe/finish
均在事件循环线程内同步调用（本应用单事件循环），无需加锁。
"""

import asyncio
from dataclasses import dataclass, field

# 事件类型常量（契约 StreamEvent）
EVENT_REASONING = "reasoning_delta"
EVENT_CONTENT = "content_delta"
EVENT_DONE = "done"
EVENT_ERROR = "error"


@dataclass
class StreamEvent:
    """一条 SSE 事件：event 名 + 已序列化的 data JSON。"""

    event: str
    data: str


@dataclass
class GenerationTask:
    """一次生成任务：缓冲 + 订阅者队列 + 终态事件。"""

    conversation_id: int
    reply_message_id: int
    async_task: asyncio.Task | None = None
    buffer: list[StreamEvent] = field(default_factory=list)
    subscribers: set[asyncio.Queue] = field(default_factory=set)
    terminal_event: StreamEvent | None = None
    stopped: bool = False  # 因用户停止结束（done.stopped=true）

    def publish(self, event: StreamEvent) -> None:
        """追加缓冲并广播给所有订阅者（终态后失效）。"""
        if self.terminal_event is not None:
            return
        self.buffer.append(event)
        for queue in list(self.subscribers):
            queue.put_nowait(event)

    def subscribe(self) -> asyncio.Queue:
        """订阅：先重放缓冲，再跟随实时事件；已终态则只收到终态事件。"""
        queue: asyncio.Queue = asyncio.Queue()
        for event in self.buffer:
            queue.put_nowait(event)
        if self.terminal_event is not None:
            # 缓冲已含终态事件，不再登记为活跃订阅者
            return queue
        self.subscribers.add(queue)
        return queue

    def finish(self, terminal: StreamEvent, stopped: bool = False) -> None:
        """置终态事件并广播（终态后 publish 不再生效）。"""
        self.terminal_event = terminal
        self.stopped = stopped
        self.buffer.append(terminal)
        for queue in list(self.subscribers):
            queue.put_nowait(terminal)
        self.subscribers.clear()

    def unsubscribe(self, queue: asyncio.Queue) -> None:
        """取消订阅（流断开时清理）。"""
        self.subscribers.discard(queue)


class GenerationRegistry:
    """reply_message_id → GenerationTask；含会话维度反查（生成互斥，FR-020）。"""

    def __init__(self) -> None:
        self._tasks: dict[int, GenerationTask] = {}

    def get(self, reply_message_id: int) -> GenerationTask | None:
        return self._tasks.get(reply_message_id)

    def get_running_by_conversation(self, conversation_id: int) -> GenerationTask | None:
        """返回该会话运行中的任务（无则 None）。"""
        for task in self._tasks.values():
            if task.conversation_id == conversation_id and task.terminal_event is None:
                return task
        return None

    def register(self, task: GenerationTask) -> None:
        self._tasks[task.reply_message_id] = task

    def remove(self, reply_message_id: int) -> None:
        self._tasks.pop(reply_message_id, None)


_registry: GenerationRegistry | None = None


def get_registry() -> GenerationRegistry:
    """进程级单例（测试可直接替换 app.services.generation_registry._registry）。"""
    global _registry
    if _registry is None:
        _registry = GenerationRegistry()
    return _registry
