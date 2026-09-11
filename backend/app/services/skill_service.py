"""Skills 管理业务逻辑：列表同步、刷新、编辑、启停、删除、ZIP 导入、目录树与文件编辑。

数据层主定义：specs/004-skills-mcp-management/data-model.md（表结构）、
            specs/005-skill-file-editor/data-model.md（零表变更声明）
文件操作经 skill_files（纯文件层）；本模块负责"目录 ↔ DB 行"同步、导入编排与文件读写编排。
"""

import io
import zipfile
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import SkillEntry
from app.schemas.skill import (
    SkillDeletedResponse,
    SkillDetail,
    SkillFileContent,
    SkillFileNode,
    SkillFileSavedResponse,
    SkillItem,
    SkillRefreshResult,
)
from app.services import skill_files


class SkillNotFoundError(LookupError):
    """Skill 不存在或不合规（路由层转 404）。"""


class SkillOperationError(ValueError):
    """Skill 操作失败且原因可对人解释（路由层转 400，如目录被占用）。"""


class SkillImportError(ValueError):
    """ZIP 导入失败且原因明确（路由层转 400，契约 skills-api.md §4 失败表）。"""


class SkillInvalidPathError(ValueError):
    """Skill 内文件路径非法或逃逸（路由层转 400，契约 skill-files-api.md §4）。"""


class SkillFileNotFoundError(LookupError):
    """Skill 内文件不存在（路由层转 404）。"""


class SkillFileTooLargeError(ValueError):
    """保存内容超过单文件上限（路由层转 422）。"""


def _to_item(entry: SkillEntry, data: skill_files.SkillFileData) -> SkillItem:
    return SkillItem(
        dir_name=entry.dir_name,
        name=data.name,
        description=data.description,
        enabled=entry.enabled,
        updated_at=data.mtime.isoformat(),
    )


def _load_compliant(session: Session) -> list[tuple[SkillEntry, skill_files.SkillFileData]]:
    """扫描目录 ⨝ DB 行：补缺行（默认启用）、跳过已消失目录的行（不删除，等 refresh 清理）。"""
    compliant_dirs, _ = skill_files.scan_skills()
    rows = {entry.dir_name: entry for entry in session.scalars(select(SkillEntry)).all()}
    result: list[tuple[SkillEntry, skill_files.SkillFileData]] = []
    dirty = False
    for dir_name in compliant_dirs:
        entry = rows.get(dir_name)
        if entry is None:
            entry = SkillEntry(dir_name=dir_name, enabled=True)
            session.add(entry)
            dirty = True
        data = skill_files.read_skill(skill_files.skills_root() / dir_name, dir_name)
        if data is None:  # 扫描与读取窗口内文件被删——按不合规跳过
            continue
        result.append((entry, data))
    if dirty:
        session.commit()
    result.sort(key=lambda pair: pair[1].mtime, reverse=True)
    return result


def list_skills(session: Session) -> list[SkillItem]:
    """列表（FR-001）：updated_at（文件 mtime）倒序；空目录 → []（前端空状态）。"""
    return [_to_item(entry, data) for entry, data in _load_compliant(session)]


def refresh(session: Session) -> SkillRefreshResult:
    """手动刷新（FR-003/005）：消失目录清行 + 返回列表与 skipped；补行统一由
    _load_compliant 承担（单一入口，避免重复插入）。"""
    compliant_dirs, skipped = skill_files.scan_skills()
    rows = {entry.dir_name: entry for entry in session.scalars(select(SkillEntry)).all()}

    existing = set(rows)
    for dir_name in existing - set(compliant_dirs):
        session.delete(rows[dir_name])
        session.commit()

    return SkillRefreshResult(items=list_skills(session), skipped=skipped)


def _find(session: Session, dir_name: str) -> tuple[SkillEntry, skill_files.SkillFileData]:
    """定位单个合规 Skill；目录缺失/不合规 → SkillNotFoundError。"""
    root = skill_files.skills_root()
    dir_path = root / dir_name
    data = skill_files.read_skill(dir_path, dir_name)
    if data is None:
        raise SkillNotFoundError(f"Skill {dir_name} 不存在")
    entry = session.scalar(select(SkillEntry).where(SkillEntry.dir_name == dir_name))
    if entry is None:
        entry = SkillEntry(dir_name=dir_name, enabled=True)
        session.add(entry)
        session.commit()
    return entry, data


def get_skill(session: Session, dir_name: str) -> SkillDetail:
    entry, data = _find(session, dir_name)
    return SkillDetail(
        **_to_item(entry, data).model_dump(),
        instruction=data.instruction,
    )


def update_skill(
    session: Session, dir_name: str, name: str, description: str, instruction: str,
) -> SkillItem:
    """编辑保存（FR-011）：重写 skill.md → 刷新 DB updated_at → 返回最新列表项。"""
    entry, _ = _find(session, dir_name)
    try:
        skill_files.write_skill(
            skill_files.skills_root() / dir_name, name, description, instruction,
        )
    except OSError as exc:
        raise SkillOperationError(f"保存失败：无法写入 Skill 文件（{exc.strerror or exc}）") from exc
    data = skill_files.read_skill(skill_files.skills_root() / dir_name, dir_name)
    assert data is not None  # 刚写回的规范文件必然合规
    session.add(entry)
    session.commit()
    return _to_item(entry, data)


def set_enabled(session: Session, dir_name: str, enabled: bool) -> SkillItem:
    """启停（FR-012/013）：只改 DB，不触碰文件。"""
    entry, data = _find(session, dir_name)
    entry.enabled = enabled
    session.add(entry)
    session.commit()
    return _to_item(entry, data)


def delete_skill(session: Session, dir_name: str) -> None:
    """删除（FR-014）：目录 + DB 行同删；目录占用等系统错误转人话 SkillOperationError。"""
    entry = session.scalar(select(SkillEntry).where(SkillEntry.dir_name == dir_name))
    dir_path = skill_files.skills_root() / dir_name
    if entry is None and not skill_files.is_compliant(dir_path):
        raise SkillNotFoundError(f"Skill {dir_name} 不存在")
    try:
        skill_files.delete_skill_dir(dir_path)
    except OSError as exc:
        raise SkillOperationError(f"删除失败：目录可能被其他程序占用（{exc.strerror or exc}）") from exc
    if entry is not None:
        session.delete(entry)
        session.commit()


# ---- ZIP 导入（US4，契约 skills-api.md §5，research R7）----

MAX_ZIP_ENTRIES = 200
ZIP_MAGIC = b"PK\x03\x04"


class _UnsafeEntry(ValueError):
    """ZIP 条目路径逃逸。"""


def _validate_zip_file(filename: str, payload: bytes) -> None:
    """双重校验：后缀 + 魔数（契约 §5.1）。"""
    if not filename.lower().endswith(".zip"):
        raise SkillImportError("导入失败：仅支持 ZIP 格式的文件")
    if not payload.startswith(ZIP_MAGIC):
        raise SkillImportError("导入失败：文件不是有效的 ZIP 压缩包")


def _safe_target(tmp_root: Path, entry_name: str) -> Path:
    """条目目标路径：黑名单（绝对路径/..）+ resolve 包含性双重校验（FR-009）。"""
    if Path(entry_name).is_absolute() or ".." in Path(entry_name).parts:
        raise _UnsafeEntry(entry_name)
    target = (tmp_root / entry_name).resolve()
    try:
        target.relative_to(tmp_root.resolve())
    except ValueError as exc:
        raise _UnsafeEntry(entry_name) from exc
    return target


def _extract_zip(payload: bytes, tmp_root: Path) -> None:
    """解压到隔离临时目录：逐条目包含性校验 + 大小/条目数上限；越界整体失败无部分落盘。"""
    with zipfile.ZipFile(io.BytesIO(payload)) as archive:
        names = archive.namelist()
        if len(names) > MAX_ZIP_ENTRIES:
            raise SkillImportError("导入失败：压缩包条目数超过上限（200）")
        total = 0
        for info in archive.infolist():
            if info.is_dir():
                continue
            total += info.file_size
            if total > skill_import_max_bytes():
                raise SkillImportError("导入失败：压缩包解压后超过大小上限（10MB）")
        for info in archive.infolist():
            target = _safe_target(tmp_root, info.filename)
            if info.is_dir():
                target.mkdir(parents=True, exist_ok=True)
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(archive.read(info))


def skill_import_max_bytes() -> int:
    """导入大小上限（从 settings 读取，便于测试 monkeypatch）。"""
    from app.core.config import settings

    return settings.skill_import_max_bytes


def _resolve_source_layout(tmp_root: Path, zip_name: str) -> tuple[Path, str]:
    """结构判定（契约 §5.5）：返回（skill.md 所在目录, 目标目录名）。"""
    if (tmp_root / skill_files.SKILL_FILE_NAME).is_file():
        stem = Path(zip_name).stem
        if not skill_files.is_valid_dir_name(stem):
            raise SkillImportError(f"导入失败：Skill 名称「{stem}」包含不支持的字符")
        return tmp_root, stem
    subdirs = [entry for entry in sorted(tmp_root.iterdir()) if entry.is_dir()]
    if len(subdirs) == 1 and (subdirs[0] / skill_files.SKILL_FILE_NAME).is_file():
        target_name = subdirs[0].name
        if not skill_files.is_valid_dir_name(target_name):
            raise SkillImportError(f"导入失败：Skill 名称「{target_name}」包含不支持的字符")
        return subdirs[0], target_name
    raise SkillImportError("导入失败：压缩包内未找到有效的 skill.md 文件")


def import_zip(session: Session, filename: str, payload: bytes) -> SkillItem:
    """ZIP 导入全流程（US4）：校验 → 隔离解压 → 结构判定 → 同名拒绝 → 原子移入 → 同步。"""
    _validate_zip_file(filename, payload)
    import tempfile

    tmp_root = Path(tempfile.mkdtemp(prefix="skill_import_"))
    try:
        try:
            _extract_zip(payload, tmp_root)
        except zipfile.BadZipFile as exc:
            raise SkillImportError("导入失败：文件不是有效的 ZIP 压缩包") from exc
        except _UnsafeEntry as exc:
            raise SkillImportError(
                f"导入失败：压缩包内包含不安全的文件路径（{exc}），已拒绝解压",
            ) from exc

        source_dir, target_name = _resolve_source_layout(tmp_root, filename)
        if not skill_files.is_compliant(source_dir):
            raise SkillImportError("导入失败：压缩包内的 skill.md 无有效内容")
        target_dir = skill_files.skills_root() / target_name
        if target_dir.exists():
            raise SkillImportError(f"导入失败：已存在同名 Skill「{target_name}」，为避免覆盖请先重命名")

        _move_dir(source_dir, target_dir)
    finally:
        import shutil

        shutil.rmtree(tmp_root, ignore_errors=True)

    result = refresh(session)
    for item in result.items:
        if item.dir_name == target_name:
            return item
    raise SkillImportError("导入失败：Skill 落地后未能在列表中发现该目录")


def _move_dir(source: Path, target: Path) -> None:
    """临时目录 → 目标目录的原子移动（同盘 rename；跨盘退化 shutil.move）。"""
    import shutil

    try:
        source.rename(target)
    except OSError:
        shutil.move(str(source), str(target))


# ---- 目录树与文件在线编辑（005，契约 skill-files-api.md，research R1–R3@005）----


def _skill_dir(session: Session, dir_name: str) -> Path:
    """定位合规 Skill 目录（只校验存在性，不解析内容）；不存在 → SkillNotFoundError。"""
    dir_path = skill_files.skills_root() / dir_name
    if not skill_files.is_compliant(dir_path):
        raise SkillNotFoundError(f"Skill {dir_name} 不存在")
    return dir_path


def _node_to_schema(node: dict) -> SkillFileNode:
    return SkillFileNode(
        name=node["name"],
        path=node["path"],
        type=node["type"],
        children=[_node_to_schema(child) for child in node.get("children", [])],
    )


def get_tree(session: Session, dir_name: str) -> list[SkillFileNode]:
    """目录树（FR-005）：实时扫描该 Skill 目录，层级与磁盘一致。"""
    dir_path = _skill_dir(session, dir_name)
    return [_node_to_schema(node) for node in skill_files.list_tree(dir_path)]


def read_file(session: Session, dir_name: str, rel_path: str) -> SkillFileContent:
    """读取文件（FR-010/011）：先判上限/编码再返回内容——不可编辑时 content 恒 None。"""
    dir_path = _skill_dir(session, dir_name)
    try:
        result = skill_files.read_text_file(dir_path, rel_path)
    except skill_files.InvalidSkillFilePath as exc:
        raise SkillInvalidPathError(rel_path) from exc
    except FileNotFoundError as exc:
        raise SkillFileNotFoundError(rel_path) from exc
    return SkillFileContent(
        path=result.path,
        editable=result.editable,
        reason=result.reason,  # type: ignore[arg-type]
        content=result.content,
        size=result.size,
    )


def write_file(
    session: Session, dir_name: str, rel_path: str, content: str,
) -> SkillFileSavedResponse:
    """保存文件（FR-009/012）：覆盖写回；目标为 skill.md 时同步列表信息与更新时间。"""
    dir_path = _skill_dir(session, dir_name)
    try:
        saved_path = skill_files.write_text_file(dir_path, rel_path, content)
    except skill_files.InvalidSkillFilePath as exc:
        raise SkillInvalidPathError(rel_path) from exc
    except FileNotFoundError as exc:
        raise SkillFileNotFoundError(rel_path) from exc
    except skill_files.SkillFileTooLarge as exc:
        raise SkillFileTooLargeError(str(exc)) from exc

    if saved_path == skill_files.SKILL_FILE_NAME:
        # frontmatter 可能被改：touch DB 行刷新 updated_at（FR-012，文件为本）
        entry = session.scalar(select(SkillEntry).where(SkillEntry.dir_name == dir_name))
        if entry is not None:
            entry.updated_at = datetime.now(timezone.utc).replace(tzinfo=None, microsecond=0)
            session.add(entry)
            session.commit()
    return SkillFileSavedResponse(path=saved_path)
