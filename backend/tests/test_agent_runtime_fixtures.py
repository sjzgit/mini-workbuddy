"""Agent Runtime 假流工厂与运行时夹具（specs/009-agent-runtime，研究 R12）。

FakeRuntimeStream：脚本化 stream_chat_completion 替身——按剧本产出
ContentDelta / ReasoningDelta / ToolCallDelta / UsageInfo 序列，记录每次调用的
messages 与 tools，支持多轮剧本（逐次调用弹出）与异常注入。
"""

import asyncio
import json
import time
from collections.abc import Iterator
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

from app.models import AgentBinding, AgentEntry, MessageEntry, ModelEntry
from app.services.openai_client import (
    ContentDelta,
    ReasoningDelta,
    ToolCallDelta,
    UsageInfo,
)

BLOCK = "__runtime_block__"


class FakeRuntimeStream:
    """可编排假流：多轮剧本、调用记录、阻塞控制。"""

    def __init__(self) -> None:
        self.scripts: list[list[object]] = []  # 每次调用弹出一组步骤
        self.calls: list[dict] = []
        self.unblocked = True

    def script(self, *rounds: object) -> None:
        """每轮一个步骤列表；也兼容直接传异常/增量（当作单步单轮）。

        script([ContentDelta("a")], [ToolCallDelta(...), ...]) 或 script(exc)
        """
        normalized: list[list[object]] = []
        for item in rounds:
            if isinstance(item, list):
                normalized.append(list(item))
            elif isinstance(item, Exception):
                normalized.append([item])
            else:
                normalized.append([item])
        self.scripts = normalized

    async def __call__(self, base_url, model_identifier, api_key, messages, **kwargs):
        self.calls.append({
            "base_url": base_url, "model": model_identifier,
            "messages": [dict(m) for m in messages], **kwargs,
        })
        steps = self.scripts.pop(0) if self.scripts else []
        for step in steps:
            if isinstance(step, Exception):
                raise step
            if step is BLOCK or step == BLOCK:
                self.unblocked = False
                while not self.unblocked:
                    await asyncio.sleep(0.01)
            else:
                yield step


def tool_call_round(name: str, arguments: str, call_id: str = "call_1") -> list[object]:
    """一轮工具调用请求的步骤（finish 前聚合完成）。"""
    return [
        ToolCallDelta(index=0, id=call_id, name=name, arguments_fragment=arguments),
    ]


def content_round(*texts: str) -> list[object]:
    """一轮正文回答的步骤。"""
    return [ContentDelta(text=t) for t in texts]


def usage_info(prompt: int | None = 10, completion: int | None = 5, total: int | None = 15) -> UsageInfo:
    return UsageInfo(prompt_tokens=prompt, completion_tokens=completion, total_tokens=total)


@pytest.fixture
def fake_runtime_stream(monkeypatch: pytest.MonkeyPatch) -> FakeRuntimeStream:
    """替换 runtime.stream_chat_completion 引用为假流。"""
    from app.services.agent_runtime import runtime

    fake = FakeRuntimeStream()
    monkeypatch.setattr(runtime, "stream_chat_completion", fake)
    return fake


@pytest.fixture
def runtime_db(
    db_session, monkeypatch: pytest.MonkeyPatch,
) -> sessionmaker:
    """把 runtime.SessionLocal 指向测试库。"""
    from app.services.agent_runtime import runtime

    factory = sessionmaker(bind=db_session.get_bind(), autoflush=False, expire_on_commit=False)
    monkeypatch.setattr(runtime, "SessionLocal", factory)
    return factory


@pytest.fixture
def runtime_tools_dir(workspace_dir: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """别名夹具：tools.py 引用 settings.authorized_dir 的场景复用 workspace_dir。"""
    return workspace_dir


def write_skill(skills_root: Path, dir_name: str, name: str, description: str, instruction: str) -> None:
    """在隔离 Skills 目录写一个合规 Skill。"""
    target = skills_root / dir_name
    target.mkdir(parents=True, exist_ok=True)
    (target / "skill.md").write_text(
        f"---\nname: {name}\ndescription: {description}\n---\n\n{instruction}\n",
        encoding="utf-8",
    )


def bind(db_session, agent_id: int, resource_type: str, resource_id: int) -> None:
    """为 Agent 追加能力绑定。"""
    db_session.add(AgentBinding(
        agent_id=agent_id, resource_type=resource_type, resource_id=resource_id,
    ))
    db_session.commit()


async def collect_events(request) -> list:
    """消费 execute_run 事件流（测试助手）。"""
    from app.services.agent_runtime import execute_run

    return [event async for event in execute_run(request)]


def run_ids(events: list) -> set[str]:
    return {e.run_id for e in events}


def event_names(events: list) -> list[str]:
    return [e.event for e in events]


def seq_list(events: list) -> list[int]:
    return [e.seq for e in events]
