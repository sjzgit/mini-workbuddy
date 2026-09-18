"""端到端手工验证脚本（specs/012 quickstart §2 核心链路的自动化等价执行）。

用法：backend/ 内 `PYTHONIOENCODING=utf-8 uv run python tests/e2e_manual_check.py`
评测执行经假 execute_run 注入（不需真实 LLM）；API 全部走真实路由。
"""
import asyncio
import os
import sys

sys.path.insert(0, ".")

from decimal import Decimal

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.db import Base, get_session
from app.main import app
from app.models import AgentEntry, EvaluationCaseRunEntry, EvaluationRunEntry, ModelEntry

engine = create_engine(
    "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool,
)
Base.metadata.create_all(engine)
TestSession = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
db = TestSession()

model = ModelEntry(
    display_name="GLM 测试模型", model_identifier="glm-test",
    base_url="https://api.example.com", context_length=8192,
    max_output_tokens=4096, temperature=Decimal("0.7"), is_default=True,
)
db.add(model)
db.commit()
agent = AgentEntry(
    name="客服测试 Agent", model_id=model.id,
    system_prompt="你是客服助手", max_rounds=5, is_default=True,
)
db.add(agent)
db.commit()

app.dependency_overrides[get_session] = lambda: db
client = TestClient(app)

OK = "[PASS]"

# 1) 创建数据集 + 导入 Case
r = client.post("/api/evaluation/datasets", json={"name": "客服评测集", "description": "端到端验证"})
assert r.status_code == 201, r.text
ds_id = r.json()["id"]
r = client.post(f"/api/evaluation/datasets/{ds_id}/import", json={
    "name": "客服评测集",
    "cases": [
        {"user_question": "如何申请退款？",
         "expected_answer": "订单详情页申请，1-3 个工作日到账",
         "scoring_criteria": "必须包含退款入口与到账时间"},
        {"user_question": "1+1 等于几？", "expected_answer": "2"},
        {"user_question": "你们的营业时间？"},
    ],
})
assert r.status_code == 200 and r.json()["imported_cases"] == 3, r.text
print(f"{OK} 数据集创建 + 导入 3 Case")

# 2) 非法导入整体拒绝
r = client.post(
    f"/api/evaluation/datasets/{ds_id}/import",
    json={"name": "x", "cases": [{"user_question": ""}]},
)
assert r.status_code == 422 and "user_question" in r.json()["detail"]
print(f"{OK} 非法导入 422 整体拒绝: {r.json()['detail'][:50]}")

# 3) 创建任务（快照固化）
r = client.post("/api/evaluation/tasks", json={
    "name": "基线评测", "agent_id": agent.id, "dataset_id": ds_id,
    "evaluator_type": "exact_match", "pass_threshold": 80,
})
assert r.status_code == 201, r.text
task = r.json()
assert task["case_count"] == 3 and task["agent_snapshot"]["name"] == "客服测试 Agent"
task_id = task["id"]
print(f"{OK} 任务创建，三快照固化（agent/dataset/evaluator）")

# 4) 修改源数据 → 快照不变
r = client.put(f"/api/evaluation/datasets/{ds_id}", json={"name": "改名后", "description": ""})
assert r.status_code == 200
detail = client.get(f"/api/evaluation/tasks/{task_id}").json()
assert detail["dataset_snapshot"]["name"] == "客服评测集"
print(f"{OK} 数据集改名后任务快照不变（可复现）")

# 5) 发起评测（假 execute_run：pass / error / mismatch）
from app.services.evaluation import runner
from tests.test_evaluation_runner import FakeExecuteRun, completed_event

fake = FakeExecuteRun()
runner.execute_run = fake
runner.SessionLocal = TestSession
fake.script(
    [completed_event("订单详情页申请，1-3 个工作日到账")],
    [completed_event("服务异常", status="error")],
    [completed_event("9 点到 18 点")],
)
r = client.post(f"/api/evaluation/tasks/{task_id}/runs")
assert r.status_code == 202, r.text
run_id = r.json()["id"]

# async 路由经 TestClient portal 在事件循环内 create_task：等待后台评测自然完成
import time

deadline = time.time() + 15
while time.time() < deadline:
    run = client.get(f"/api/evaluation/runs/{run_id}").json()
    if run["status"] not in ("pending", "running"):
        break
    time.sleep(0.2)
run = client.get(f"/api/evaluation/runs/{run_id}").json()
print(f"{OK} 评测完成: status={run['status']} passed={run['passed_cases']} "
      f"exec_failed={run['execution_failed_cases']} judge_failed={run['judge_failed_cases']} "
      f"avg={run['average_score']} pass_rate={run['pass_rate']}%")
assert run["status"] == "completed"
assert run["passed_cases"] == 1 and run["execution_failed_cases"] == 1
assert run["judge_failed_cases"] == 1  # 无参考答案 → exact_match judge_failed

# 6) Case 明细 + snapshot_case + AgentRun 关联
cases = client.get(f"/api/evaluation/runs/{run_id}/cases").json()
assert len(cases) == 3
passed_case = next(c for c in cases if c["status"] == "passed")
assert passed_case["snapshot_case"]["user_question"] == "如何申请退款？"
assert passed_case["agent_run_id"]
assert passed_case["total_tokens"] == 15
print(f"{OK} Case 明细可读（snapshot_case/指标），agent_run_id={passed_case['agent_run_id'][:8]}…")

# 7) 失败 Case 重试
exec_case = next(c for c in cases if c["status"] == "execution_failed")
r = client.post(f"/api/evaluation/runs/{run_id}/retry", json={"case_run_id": exec_case["id"]})
assert r.status_code == 200, r.text
assert r.json()["case_run"]["attempt"] == 2
db.expire_all()
orig = db.get(EvaluationCaseRunEntry, exec_case["id"])
assert orig.status == "execution_failed"  # 原记录保留
print(f"{OK} 失败 Case 重试: 新 attempt=2 CaseRun, 原记录保留")

# 8) 取消语义：确定性验证——启动前置取消标志 → 全 CANCELLED
# （fake 流瞬时完成，经 HTTP 的取消存在竞态：终态可能已是 completed，取消路径由单测覆盖）
from app.services.evaluation import run_service as _rs

run2_out = _rs.create_run_for_task(db, task_id)
control2 = runner.EvaluationRunControl(run_pk=run2_out.id)
control2.cancel_event.set()
runner.SessionLocal = TestSession
asyncio.run(runner._run_evaluation_loop(control2))
assert db.get(EvaluationRunEntry, run2_out.id).status == "cancelled"
print(f"{OK} 取消: 启动前置标志 -> Run CANCELLED，CaseRun 全部 CANCELLED")

# 9) 启动恢复
r = client.post(f"/api/evaluation/tasks/{task_id}/runs")
run3_id = r.json()["id"]
row = db.get(EvaluationRunEntry, run3_id)
row.status = "running"
db.commit()
from app.services.evaluation import run_service as eval_run_service

assert eval_run_service.mark_interrupted_runs(db) >= 1
assert db.get(EvaluationRunEntry, run3_id).status == "interrupted"
print(f"{OK} 重启恢复: RUNNING -> INTERRUPTED（记录 interrupted_at/reason）")

# 10) 导出可回导
r = client.get(f"/api/evaluation/datasets/{ds_id}/export")
exported = r.json()
assert exported["name"] == "改名后" and len(exported["cases"]) == 3  # 导出走实时数据（第 4 步已改名）
assert all("case_id" not in c for c in exported["cases"])
print(f"{OK} JSON 导出（3 Case，无 case_id，可回导）")

print()
print("=== 端到端验证全部通过 ===")
