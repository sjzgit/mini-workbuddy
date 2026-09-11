"""Skill 文件层单元测试（契约 skills-api.md §2；tasks T010/T020）。

覆盖：frontmatter 解析 / 合规判定 / 目录扫描 / 规范重写 / ZIP 导入安全。
"""

import zipfile
from pathlib import Path

import pytest

from app.services import skill_files


@pytest.fixture
def root(skills_dir: Path) -> Path:
    return skill_files.skills_root()


def _make_skill(root: Path, dir_name: str, content: str) -> Path:
    dir_path = root / dir_name
    dir_path.mkdir(parents=True)
    (dir_path / "skill.md").write_text(content, encoding="utf-8")
    return dir_path


# ---- frontmatter 解析（宽松读）----


def test_parse_standard_frontmatter() -> None:
    text = "---\nname: 会议纪要\ndescription: 整理纪要\n---\n\n# 指令\n逐步执行\n"
    name, description, instruction = skill_files.parse_frontmatter(text)
    assert name == "会议纪要"
    assert description == "整理纪要"
    assert instruction.startswith("# 指令")


def test_parse_description_with_colon() -> None:
    text = "---\nname: A\ndescription: 用途: 整理\n---\n正文\n"
    name, description, instruction = skill_files.parse_frontmatter(text)
    assert name == "A"
    assert description == "用途: 整理"
    assert instruction == "正文"


def test_parse_no_frontmatter_falls_back() -> None:
    name, description, instruction = skill_files.parse_frontmatter("直接正文")
    assert name is None
    assert description is None
    assert instruction == "直接正文"


def test_parse_unclosed_frontmatter_falls_back() -> None:
    text = "---\nname: A\n没有闭合"
    name, _description, _instruction = skill_files.parse_frontmatter(text)
    assert name is None  # 无闭合视为无 frontmatter


def test_parse_unknown_keys_ignored() -> None:
    text = "---\nname: A\nalias: B\n---\n正文"
    name, description, _ = skill_files.parse_frontmatter(text)
    assert name == "A"
    assert description is None


# ---- 合规判定 ----


def test_compliance_missing_file(root: Path) -> None:
    dir_path = root / "no-file"
    dir_path.mkdir()
    assert not skill_files.is_compliant(dir_path)


def test_compliance_empty_file(root: Path) -> None:
    dir_path = _make_skill(root, "empty", "")
    assert not skill_files.is_compliant(dir_path)


def test_compliance_valid(root: Path) -> None:
    dir_path = _make_skill(root, "ok", "---\nname: X\n---\n正文")
    assert skill_files.is_compliant(dir_path)


# ---- 目录扫描 ----


def test_scan_returns_compliant_and_skipped(root: Path) -> None:
    _make_skill(root, "good-skill", "---\nname: 好\n---\n正文")
    _make_skill(root, "bad-skill", "")  # 空 skill.md
    (root / "stray.txt").write_text("散文件忽略")
    compliant, skipped = skill_files.scan_skills()
    assert compliant == ["good-skill"]
    assert skipped == ["bad-skill"]


def test_scan_invalid_dir_name_skipped(root: Path) -> None:
    _make_skill(root, "bad name!", "---\nname: X\n---\n正文")
    compliant, skipped = skill_files.scan_skills()
    assert compliant == []
    assert skipped == ["bad name!"]


# ---- 读取与规范重写 ----


def test_read_skill_fallback_name(root: Path) -> None:
    _make_skill(root, "dir-name", "纯正文无frontmatter")
    data = skill_files.read_skill(root / "dir-name", "dir-name")
    assert data is not None
    assert data.name == "dir-name"
    assert data.description == ""
    assert data.instruction == "纯正文无frontmatter"


def test_read_skill_missing_returns_none(root: Path) -> None:
    (root / "empty-dir").mkdir()
    assert skill_files.read_skill(root / "empty-dir", "empty-dir") is None


def test_write_then_read_roundtrip(root: Path) -> None:
    skill_files.write_skill(root / "demo", "演示", "说明", "# 步骤\n1. 做")
    data = skill_files.read_skill(root / "demo", "demo")
    assert data is not None
    assert data.name == "演示"
    assert data.description == "说明"
    assert data.instruction == "# 步骤\n1. 做"
    # 重写幂等：再次写同内容读回一致
    skill_files.write_skill(root / "demo", "演示", "说明", "# 步骤\n1. 做")
    again = skill_files.read_skill(root / "demo", "demo")
    assert again is not None
    assert again.instruction == data.instruction


def test_write_normalizes_unknown_frontmatter_keys(root: Path) -> None:
    dir_path = _make_skill(root, "legacy", "---\nname: 旧\nsecret_key: x\n---\n正文")
    skill_files.write_skill(dir_path, "旧", "", "正文")
    raw = (dir_path / "skill.md").read_text(encoding="utf-8")
    assert "secret_key" not in raw
    assert raw.startswith("---\nname: 旧\n")


# ---- ZIP 导入（skill_service 层，任务 T020）----

from app.services import skill_service  # noqa: E402


def _zip_bytes(entries: dict[str, bytes]) -> bytes:
    import io

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for name, payload in entries.items():
            archive.writestr(name, payload)
    return buffer.getvalue()


VALID_SKILL_MD = "---\nname: 导入的技能\ndescription: 来自 ZIP\n---\n指令正文"


class TestImportZip:
    def test_import_root_layout(self, db_session, skills_dir: Path) -> None:
        payload = _zip_bytes({"skill.md": VALID_SKILL_MD.encode("utf-8")})
        item = skill_service.import_zip(db_session, "my-skill.zip", payload)
        assert item.dir_name == "my-skill"
        assert item.name == "导入的技能"
        assert item.enabled is True
        assert (skills_dir / "my-skill" / "skill.md").is_file()

    def test_import_single_dir_layout(self, db_session, skills_dir: Path) -> None:
        payload = _zip_bytes({"pack/skill.md": VALID_SKILL_MD.encode("utf-8")})
        item = skill_service.import_zip(db_session, "whatever.zip", payload)
        assert item.dir_name == "pack"

    def test_import_non_zip_rejected(self, db_session, skills_dir: Path) -> None:
        with pytest.raises(skill_service.SkillImportError, match="不是有效的 ZIP"):
            skill_service.import_zip(db_session, "fake.zip", b"not a zip at all")

    def test_import_no_zip_suffix_rejected(self, db_session, skills_dir: Path) -> None:
        payload = _zip_bytes({"skill.md": VALID_SKILL_MD.encode("utf-8")})
        with pytest.raises(skill_service.SkillImportError, match="ZIP 格式"):
            skill_service.import_zip(db_session, "pack.txt", payload)

    def test_import_path_escape_rejected_and_target_untouched(
        self, db_session, skills_dir: Path, tmp_path: Path,
    ) -> None:
        payload = _zip_bytes({
            "skill.md": VALID_SKILL_MD.encode("utf-8"),
            "../evil.txt": b"boom",
        })
        with pytest.raises(skill_service.SkillImportError, match="不安全的文件路径"):
            skill_service.import_zip(db_session, "evil.zip", payload)
        assert not (tmp_path / "evil.txt").exists()
        assert list(skills_dir.iterdir()) == []  # 目标目录零落盘

    def test_import_structure_missing_rejected(self, db_session, skills_dir: Path) -> None:
        payload = _zip_bytes({"readme.txt": b"no skill here"})
        with pytest.raises(skill_service.SkillImportError, match="未找到有效的 skill.md"):
            skill_service.import_zip(db_session, "empty.zip", payload)

    def test_import_same_name_rejected_and_original_kept(
        self, db_session, skills_dir: Path,
    ) -> None:
        existing = skills_dir / "dup"
        existing.mkdir()
        (existing / "skill.md").write_text("---\nname: 原有\n---\n原内容", encoding="utf-8")
        payload = _zip_bytes({"skill.md": VALID_SKILL_MD.encode("utf-8")})
        with pytest.raises(skill_service.SkillImportError, match="同名"):
            skill_service.import_zip(db_session, "dup.zip", payload)
        assert (existing / "skill.md").read_text(encoding="utf-8").endswith("原内容")

    def test_import_oversize_rejected(
        self, db_session, skills_dir: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr("app.core.config.settings.skill_import_max_bytes", 10)
        payload = _zip_bytes({"skill.md": b"x" * 100})
        with pytest.raises(skill_service.SkillImportError, match="大小上限"):
            skill_service.import_zip(db_session, "big.zip", payload)

    def test_import_too_many_entries_rejected(self, db_session, skills_dir: Path) -> None:
        entries = {f"f{i}.txt": b"x" for i in range(201)}
        entries["skill.md"] = VALID_SKILL_MD.encode("utf-8")
        payload = _zip_bytes(entries)
        with pytest.raises(skill_service.SkillImportError, match="条目数"):
            skill_service.import_zip(db_session, "many.zip", payload)

    def test_import_invalid_dir_name_rejected(self, db_session, skills_dir: Path) -> None:
        payload = _zip_bytes({"skill.md": VALID_SKILL_MD.encode("utf-8")})
        with pytest.raises(skill_service.SkillImportError, match="不支持的字符"):
            skill_service.import_zip(db_session, "bad name!.zip", payload)


# ---- 目录树与文件在线编辑（005，tasks T007/T008）----


class TestListTree:
    def test_multi_level_structure(self, root: Path) -> None:
        (root / "demo" / "scripts" / "sub").mkdir(parents=True)
        (root / "demo" / "skill.md").write_text("---\nname: X\n---\n正文", encoding="utf-8")
        (root / "demo" / "scripts" / "run.py").write_text("print(1)", encoding="utf-8")
        (root / "demo" / "notes.txt").write_text("hi", encoding="utf-8")

        tree = skill_files.list_tree(root / "demo")
        names = [(node["path"], node["type"]) for node in tree]
        assert ("notes.txt", "file") in names
        assert ("scripts", "dir") in names
        assert ("skill.md", "file") in names
        # 目录在前、同类型字典序
        assert tree[0]["type"] == "dir"

        scripts = next(node for node in tree if node["path"] == "scripts")
        child_paths = [child["path"] for child in scripts["children"]]
        assert child_paths == ["scripts/sub", "scripts/run.py"]  # 目录在前（契约 §2）

        sub = scripts["children"][0]
        assert sub["children"] == []  # 空目录为无子节点

    def test_file_nodes_have_no_children(self, root: Path) -> None:
        (root / "solo").mkdir()
        (root / "solo" / "skill.md").write_text("x", encoding="utf-8")
        tree = skill_files.list_tree(root / "solo")
        assert tree[0]["children"] == []
        assert tree[0]["path"] == "skill.md"


class TestPathSafety:
    """路径逃逸（SC-004）：读取与保存共用 _resolve_skill_file。"""

    @pytest.mark.parametrize("bad_path", [
        "../secret.txt",
        "..\\secret.txt",
        "a/../../secret.txt",
        "/etc/hosts",
        "C:/Windows/system32/config",
        "C:\\Windows",
        "",
    ])
    def test_invalid_paths_rejected(self, root: Path, bad_path: str) -> None:
        demo = root / "demo"
        demo.mkdir(exist_ok=True)
        (demo / "skill.md").write_text("x", encoding="utf-8")
        with pytest.raises(skill_files.InvalidSkillFilePath):
            skill_files._resolve_skill_file(demo, bad_path)
        # 保存同样拒绝
        with pytest.raises(skill_files.InvalidSkillFilePath):
            skill_files.write_text_file(demo, bad_path, "boom")

    def test_escape_writes_nothing_outside(self, root: Path, tmp_path: Path) -> None:
        demo = root / "demo"
        demo.mkdir()
        with pytest.raises(skill_files.InvalidSkillFilePath):
            skill_files.write_text_file(demo, "../evil.txt", "boom")
        assert not (tmp_path / "evil.txt").exists()
        assert not (root.parent / "evil.txt").exists()


class TestReadWriteFile:
    def test_read_write_roundtrip(self, root: Path) -> None:
        demo = root / "demo"
        demo.mkdir()
        (demo / "notes.txt").write_text("第一版", encoding="utf-8")

        result = skill_files.read_text_file(demo, "notes.txt")
        assert result.editable is True
        assert result.content == "第一版"
        assert result.reason is None

        skill_files.write_text_file(demo, "notes.txt", "第二版\n更新")
        again = skill_files.read_text_file(demo, "notes.txt")
        assert again.content == "第二版\n更新"

    def test_read_non_utf8_is_not_text(self, root: Path) -> None:
        demo = root / "demo"
        demo.mkdir()
        (demo / "binary.bin").write_bytes(b"\xff\xfe\x00\x01binary")
        result = skill_files.read_text_file(demo, "binary.bin")
        assert result.editable is False
        assert result.reason == "not_text"
        assert result.content is None  # 零乱码（SC-005）

    def test_read_oversize_is_too_large(
        self, root: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr("app.core.config.settings.file_max_bytes", 10)
        demo = root / "demo"
        demo.mkdir()
        (demo / "big.txt").write_text("x" * 100, encoding="utf-8")
        result = skill_files.read_text_file(demo, "big.txt")
        assert result.editable is False
        assert result.reason == "too_large"
        assert result.content is None

    def test_write_empty_content_allowed(self, root: Path) -> None:
        demo = root / "demo"
        demo.mkdir()
        (demo / "notes.txt").write_text("旧内容", encoding="utf-8")
        skill_files.write_text_file(demo, "notes.txt", "")
        assert (demo / "notes.txt").read_text(encoding="utf-8") == ""

    def test_write_oversize_rejected(
        self, root: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr("app.core.config.settings.file_max_bytes", 10)
        demo = root / "demo"
        demo.mkdir()
        (demo / "notes.txt").write_text("ok", encoding="utf-8")
        with pytest.raises(skill_files.SkillFileTooLarge):
            skill_files.write_text_file(demo, "notes.txt", "x" * 100)
        assert (demo / "notes.txt").read_text(encoding="utf-8") == "ok"  # 原内容未破坏

    def test_write_missing_file_rejected(self, root: Path) -> None:
        demo = root / "demo"
        demo.mkdir()
        with pytest.raises(FileNotFoundError):
            skill_files.write_text_file(demo, "no-such.txt", "x")
