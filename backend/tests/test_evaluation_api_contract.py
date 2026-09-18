"""契约对齐测试（specs/012 T011）：schemas/evaluation.py 与契约文件防漂移。"""

import re
from pathlib import Path

from app.schemas import evaluation as schemas

CONTRACT = Path(__file__).parents[2] / "specs/012-agent-evaluation/contracts/evaluation-api.md"


def test_contract_file_exists():
    assert CONTRACT.exists()


def test_enum_sets_match_contract():
    """契约 §enums 的枚举集合与 schema 常量逐一对齐。"""
    text = CONTRACT.read_text(encoding="utf-8")
    # EvaluatorType
    assert 'EvaluatorType      = "llm_judge" | "exact_match"' in text
    assert schemas.EVALUATOR_TYPES == ("llm_judge", "exact_match")
    # RunStatus
    assert '"pending" | "running" | "paused" | "completed" | "cancelled" | "failed" | "interrupted"' in text
    assert set(schemas.RUN_STATUSES) == {
        "pending", "running", "paused", "completed", "cancelled", "failed", "interrupted",
    }
    # CaseRunStatus
    assert set(schemas.CASE_RUN_STATUSES) == {
        "pending", "running", "passed", "failed",
        "execution_failed", "judge_failed", "cancelled",
    }
    # 状态机：文档 §4.2（data-model）与 RUN_STATUS_TRANSITIONS 键一致
    for from_status, to_set in schemas.RUN_STATUS_TRANSITIONS.items():
        assert from_status in schemas.RUN_STATUSES
        for to_status in to_set:
            assert to_status in schemas.RUN_STATUSES


def test_retryable_statuses_match_contract():
    text = CONTRACT.read_text(encoding="utf-8")
    match = re.search(
        r"status 必须 ∈ \{([^}]+)\}", text,
    )
    assert match, "契约 retry 节缺少状态集合"
    contract_set = {s.strip() for s in match.group(1).split(",")}
    assert contract_set == set(schemas.RETRYABLE_CASE_RUN_STATUSES)


def test_api_paths_registered():
    """契约 §1-§5 的路径全部在应用路由中注册。"""
    from fastapi.testclient import TestClient

    from app.core.db import get_session
    from app.main import app

    expected = {
        ("post", "/api/evaluation/datasets"),
        ("get", "/api/evaluation/datasets"),
        ("get", "/api/evaluation/datasets/{dataset_id}"),
        ("put", "/api/evaluation/datasets/{dataset_id}"),
        ("delete", "/api/evaluation/datasets/{dataset_id}"),
        ("post", "/api/evaluation/datasets/{dataset_id}/cases"),
        ("put", "/api/evaluation/datasets/{dataset_id}/cases/{case_id}"),
        ("delete", "/api/evaluation/datasets/{dataset_id}/cases/{case_id}"),
        ("post", "/api/evaluation/datasets/{dataset_id}/import"),
        ("get", "/api/evaluation/datasets/{dataset_id}/export"),
        ("post", "/api/evaluation/tasks"),
        ("get", "/api/evaluation/tasks"),
        ("get", "/api/evaluation/tasks/{task_id}"),
        ("delete", "/api/evaluation/tasks/{task_id}"),
        ("post", "/api/evaluation/tasks/{task_id}/runs"),
        ("get", "/api/evaluation/runs"),
        ("get", "/api/evaluation/runs/{run_id}"),
        ("get", "/api/evaluation/runs/{run_id}/cases"),
        ("get", "/api/evaluation/runs/{run_id}/cases/{case_run_id}"),
        ("post", "/api/evaluation/runs/{run_id}/pause"),
        ("post", "/api/evaluation/runs/{run_id}/resume"),
        ("post", "/api/evaluation/runs/{run_id}/cancel"),
        ("post", "/api/evaluation/runs/{run_id}/retry"),
    }
    # 新版 FastAPI include_router 惰性展开：经 OpenAPI schema 校验
    actual: set[tuple[str, str]] = set()
    for route in app.router.routes:
        path = getattr(route, "path", "")
        if "evaluation" in path:
            for method in getattr(route, "methods", set()):
                actual.add((method.lower(), path))
    if not actual:  # 惰性路由：回退到 OpenAPI
        import httpx

        from app.main import app as fastapi_app

        async def _fetch_openapi():
            transport = httpx.ASGITransport(app=fastapi_app)
            async with httpx.AsyncClient(
                transport=transport, base_url="http://test",
            ) as client:
                response = await client.get("/openapi.json")
                return response.json()["paths"]

        import anyio

        openapi_paths = anyio.run(_fetch_openapi)
        for path, methods in openapi_paths.items():
            if "evaluation" in path:
                for method in methods:
                    actual.add((method.lower(), path))
    missing = expected - actual
    assert not missing, f"契约路径未注册: {missing}"
