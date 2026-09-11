"""Skills 管理 HTTP 契约测试（契约 skills-api.md；tasks T013）。

覆盖：列表 / 详情 / 编辑 / 启停 / 删除 / 刷新 + 空状态 + 404/422/400。
"""

from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

SKILL_MD = "---\nname: 会议纪要\ndescription: 整理纪要\n---\n\n# 指令\n逐步执行\n"


def _make_skill(root: Path, dir_name: str, content: str = SKILL_MD) -> Path:
    dir_path = root / dir_name
    dir_path.mkdir(parents=True)
    (dir_path / "skill.md").write_text(content, encoding="utf-8")
    return dir_path


def test_list_empty_state(client: TestClient, skills_dir: Path) -> None:
    """空目录返回 []（FR-004，前端渲染空状态）。"""
    response = client.get("/api/skills")
    assert response.status_code == 200
    assert response.json() == []


def test_list_finds_manual_dir(client: TestClient, skills_dir: Path) -> None:
    """手动放入目录后直接出现在列表（FR-002/003）。"""
    _make_skill(skills_dir, "meeting-notes")
    response = client.get("/api/skills")
    assert response.status_code == 200
    items = response.json()
    assert len(items) == 1
    item = items[0]
    assert item["dir_name"] == "meeting-notes"
    assert item["name"] == "会议纪要"
    assert item["description"] == "整理纪要"
    assert item["enabled"] is True
    assert item["updated_at"]


def test_refresh_reports_skipped_and_discovers_new(
    client: TestClient, skills_dir: Path,
) -> None:
    """刷新（FR-003/005）：新合规目录入列表，不合规目录计入 skipped。"""
    _make_skill(skills_dir, "good", SKILL_MD)
    _make_skill(skills_dir, "bad", "")  # 空 skill.md

    response = client.post("/api/skills/refresh")
    assert response.status_code == 200
    result = response.json()
    assert [item["dir_name"] for item in result["items"]] == ["good"]
    assert result["skipped"] == ["bad"]

    # 已消失目录的行被清理
    _make_skill(skills_dir, "second")
    client.post("/api/skills/refresh")
    import shutil

    shutil.rmtree(skills_dir / "good")
    result = client.post("/api/skills/refresh").json()
    assert [item["dir_name"] for item in result["items"]] == ["second"]


def test_detail_and_update(client: TestClient, skills_dir: Path) -> None:
    """详情三字段（FR-010）+ 编辑保存后读回一致（FR-011）。"""
    _make_skill(skills_dir, "demo")
    before = client.get("/api/skills/demo").json()
    assert before["instruction"].startswith("# 指令")

    response = client.put(
        "/api/skills/demo",
        json={"name": "新名称", "description": "新说明", "instruction": "# 新指令\n内容"},
    )
    assert response.status_code == 200
    item = response.json()
    assert item["name"] == "新名称"
    assert item["description"] == "新说明"

    after = client.get("/api/skills/demo").json()
    assert after["instruction"] == "# 新指令\n内容"
    # 文件同步写回（SC-002）
    raw = (skills_dir / "demo" / "skill.md").read_text(encoding="utf-8")
    assert "新名称" in raw and "新指令" in raw


def test_update_validation(client: TestClient, skills_dir: Path) -> None:
    _make_skill(skills_dir, "demo")
    # name 超长 → 422
    response = client.put("/api/skills/demo", json={"name": "x" * 101, "instruction": ""})
    assert response.status_code == 422


def test_toggle_persists(client: TestClient, skills_dir: Path, db_session: Session) -> None:
    """启停（FR-012/013）：文件保留 + 状态持久化。"""
    _make_skill(skills_dir, "demo")
    response = client.put("/api/skills/demo/enabled", json={"enabled": False})
    assert response.status_code == 200
    assert response.json()["enabled"] is False
    assert (skills_dir / "demo" / "skill.md").is_file()

    # 重新列表仍为停用（持久化语义；重启由 SQLite 承载）
    listing = {item["dir_name"]: item for item in client.get("/api/skills").json()}
    assert listing["demo"]["enabled"] is False


def test_delete_removes_dir_and_row(client: TestClient, skills_dir: Path) -> None:
    """删除（FR-014）：目录与列表同时消失。"""
    _make_skill(skills_dir, "demo")
    assert client.delete("/api/skills/demo").status_code == 200
    assert not (skills_dir / "demo").exists()
    assert client.get("/api/skills").json() == []


def test_delete_unknown_returns_404(client: TestClient, skills_dir: Path) -> None:
    assert client.delete("/api/skills/ghost").status_code == 404


def test_detail_unknown_returns_404(client: TestClient, skills_dir: Path) -> None:
    response = client.get("/api/skills/ghost")
    assert response.status_code == 404
    assert response.json()["detail"] == "Skill 不存在"


def test_import_zip_endpoint(client: TestClient, skills_dir: Path) -> None:
    """ZIP 导入端点（FR-006）：成功 / 同名 400 / 非 ZIP 422。"""
    import io
    import zipfile

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("skill.md", SKILL_MD)
    payload = buffer.getvalue()

    response = client.post(
        "/api/skills/import",
        files={"file": ("packed.zip", payload, "application/zip")},
    )
    assert response.status_code == 201
    assert response.json()["dir_name"] == "packed"

    # 同名冲突 → 400
    conflict = client.post(
        "/api/skills/import",
        files={"file": ("packed.zip", payload, "application/zip")},
    )
    assert conflict.status_code == 400
    assert "同名" in conflict.json()["detail"]

    # 非 ZIP → 422
    bad = client.post(
        "/api/skills/import",
        files={"file": ("fake.zip", b"plain text", "application/zip")},
    )
    assert bad.status_code == 422


# ---- 目录树与文件在线编辑（005，契约 skill-files-api.md；tasks T006/T009）----


def test_tree_endpoint_structure(client: TestClient, skills_dir: Path) -> None:
    """树端点（US2）：层级与磁盘一致；空目录返回 []（SC-002）。"""
    assert client.get("/api/skills/demo/tree").status_code == 404

    demo = skills_dir / "demo"
    (demo / "scripts").mkdir(parents=True)
    (demo / "skill.md").write_text(SKILL_MD, encoding="utf-8")
    (demo / "scripts" / "run.py").write_text("print(1)", encoding="utf-8")

    tree = client.get("/api/skills/demo/tree").json()
    paths = {node["path"]: node for node in tree}
    assert set(paths) == {"skill.md", "scripts"}
    assert paths["scripts"]["type"] == "dir"
    assert paths["scripts"]["children"][0]["path"] == "scripts/run.py"
    assert paths["scripts"]["children"][0]["children"] == []


def test_read_file_endpoint_branches(client: TestClient, skills_dir: Path) -> None:
    """读端点（US3）：可编辑/不可编辑/非法路径/文件不存在四分支。"""
    demo = skills_dir / "demo"
    demo.mkdir()
    (demo / "skill.md").write_text(SKILL_MD, encoding="utf-8")
    (demo / "binary.bin").write_bytes(b"\xff\xfe\x00binary")

    # 正常文本
    ok = client.get("/api/skills/demo/file", params={"path": "skill.md"}).json()
    assert ok["editable"] is True
    assert ok["content"].startswith("---")
    assert ok["reason"] is None

    # 非 UTF-8 → 200 + editable=false（正常查询结果，非错误）
    not_text = client.get("/api/skills/demo/file", params={"path": "binary.bin"})
    assert not_text.status_code == 200
    body = not_text.json()
    assert body["editable"] is False
    assert body["reason"] == "not_text"
    assert body["content"] is None

    # 非法路径 → 400（SC-004；含真实反斜杠、绝对路径、盘符三种形态）
    for bad in ("../secret.txt", "..\\evil.txt", "/etc/hosts", "C:/Windows"):
        assert client.get("/api/skills/demo/file", params={"path": bad}).status_code == 400

    # 文件不存在 → 404
    assert client.get("/api/skills/demo/file", params={"path": "no-such.txt"}).status_code == 404


def test_write_file_endpoint_and_skill_md_sync(client: TestClient, skills_dir: Path) -> None:
    """写端点（US3）：保存写回；skill.md 保存后列表 updated_at 刷新（FR-012，SC-001/SC-003）。"""
    demo = skills_dir / "demo"
    demo.mkdir()
    (demo / "skill.md").write_text(SKILL_MD, encoding="utf-8")
    (demo / "notes.txt").write_text("旧", encoding="utf-8")
    client.post("/api/skills/refresh")

    updated_before = client.get("/api/skills").json()[0]["updated_at"]

    # 保存普通文件
    saved = client.put(
        "/api/skills/demo/file", json={"path": "notes.txt", "content": "新内容"},
    )
    assert saved.status_code == 200
    assert saved.json() == {"saved": True, "path": "notes.txt"}
    assert (demo / "notes.txt").read_text(encoding="utf-8") == "新内容"

    # 保存 skill.md（改 frontmatter 名称）→ 列表名称与 updated_at 同步刷新
    client.put(
        "/api/skills/demo/file",
        json={"path": "skill.md", "content": "---\nname: 改名后\ndescription: 新说明\n---\n正文"},
    )
    listing = {item["dir_name"]: item for item in client.get("/api/skills").json()}
    assert listing["demo"]["name"] == "改名后"
    assert listing["demo"]["updated_at"] > updated_before

    # 非法路径 → 400 且目录外零落盘
    evil = client.put(
        "/api/skills/demo/file", json={"path": "..\\evil.txt", "content": "boom"},
    )
    assert evil.status_code == 400
    assert not (skills_dir.parent / "evil.txt").exists()

    # 超上限 → 422
    import app.core.config as config

    original = config.settings.file_max_bytes
    config.settings.file_max_bytes = 10
    try:
        too_big = client.put(
            "/api/skills/demo/file", json={"path": "notes.txt", "content": "x" * 100},
        )
        assert too_big.status_code == 422
    finally:
        config.settings.file_max_bytes = original

    # 空内容合法
    empty = client.put("/api/skills/demo/file", json={"path": "notes.txt", "content": ""})
    assert empty.status_code == 200
    assert (demo / "notes.txt").read_text(encoding="utf-8") == ""


def test_escape_writes_nothing_outside(client: TestClient, skills_dir: Path) -> None:
    """SC-004 专项：四类非法形态读与写全部拒绝，Skill 目录外零触碰。"""
    demo = skills_dir / "demo"
    demo.mkdir()
    (demo / "skill.md").write_text(SKILL_MD, encoding="utf-8")
    parent_before = sorted(p.name for p in skills_dir.parent.iterdir())

    escape_paths = ["../secret.txt", "..\\secret.txt", "/etc/hosts", "C:/Windows/config"]
    for bad in escape_paths:
        assert client.get("/api/skills/demo/file", params={"path": bad}).status_code == 400
        assert client.put(
            "/api/skills/demo/file", json={"path": bad, "content": "boom"},
        ).status_code == 400

    assert sorted(p.name for p in skills_dir.parent.iterdir()) == parent_before
