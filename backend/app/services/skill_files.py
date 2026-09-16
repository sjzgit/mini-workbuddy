"""Skill 文件层：skill.md 读写、frontmatter 解析、合规判定、目录扫描。

文件格式主定义：specs/004-skills-mcp-management/contracts/skills-api.md §2
职责（research R1/R2）：Skill 内容以文件为本体，本模块是文件的唯一读写入口，
不含任何 DB 依赖（可独立单测）；"宽松读、严格写"——解析容错，保存一律重写为规范格式。
"""

import re
import shutil
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path, PurePosixPath

from app.core.config import settings

SKILL_FILE_NAME = "SKILL.md"

# 目录名合法字符集（契约 skills-api.md §1；data-model.md 校验规则）
_DIR_NAME_RE = re.compile(r"^[0-9A-Za-z][0-9A-Za-z._-]{0,99}$")

_FRONTMATTER_KEY_RE = re.compile(r"^([A-Za-z_][A-Za-z0-9_-]*)\s*:\s*(.*)$")


class InvalidSkillFilePath(ValueError):
    """Skill 内文件相对路径非法或逃逸 Skill 目录（路由层转 400，契约 skill-files-api.md §4）。"""


class SkillFileTooLarge(ValueError):
    """文件超过单文件大小上限（settings.file_max_bytes，路由层转 422）。"""


@dataclass
class SkillFileData:
    """单个 Skill 文件的解析结果。"""

    name: str
    description: str
    instruction: str
    mtime: datetime


def skills_root() -> Path:
    """Skill 目录根（settings.skills_dir），首次访问自动创建。"""
    root = Path(settings.skills_dir)
    root.mkdir(parents=True, exist_ok=True)
    return root


def is_valid_dir_name(dir_name: str) -> bool:
    """目录名是否合法（字母开头，仅字母数字 . _ -，1–100 字符）。"""
    return bool(_DIR_NAME_RE.fullmatch(dir_name))


def is_compliant(dir_path: Path) -> bool:
    """合规判定（契约 §2）：目录内存在非空 skill.md 即合规。"""
    skill_file = dir_path / SKILL_FILE_NAME
    try:
        return skill_file.is_file() and skill_file.stat().st_size > 0
    except OSError:
        return False


def parse_frontmatter(text: str) -> tuple[str | None, str | None, str]:
    """解析 frontmatter，返回 (name, description, instruction)。

    宽松读：无 frontmatter → 全文视作指令、两键为 None（调用方按目录名/空串兜底）；
    未知键忽略；键值取行内首个冒号之后的内容并去除首尾空白。
    """
    lines = text.split("\n")
    if not lines or lines[0].strip() != "---":
        return None, None, text.strip("\n")

    name: str | None = None
    description: str | None = None
    body_start = len(lines)  # 无闭合 --- 时视作无 frontmatter
    for index in range(1, len(lines)):
        line = lines[index]
        if line.strip() == "---":
            body_start = index + 1
            break
        match = _FRONTMATTER_KEY_RE.match(line)
        if match is None:
            continue
        key, value = match.group(1), match.group(2).strip()
        if key == "name" and name is None:
            name = value
        elif key == "description" and description is None:
            description = value
    else:
        return None, None, text.strip("\n")

    instruction = "\n".join(lines[body_start:]).strip("\n")
    return name, description, instruction


def _render_frontmatter(name: str, description: str, instruction: str) -> str:
    """严格写：frontmatter 仅 name/description 两键 + 正文（契约 §2）。"""
    return f"---\nname: {name}\ndescription: {description}\n---\n\n{instruction.rstrip()}\n"


def read_skill(dir_path: Path, fallback_name: str) -> SkillFileData | None:
    """读取单个 Skill 文件；不合规（缺失/空文件/IO 错误）返回 None。

    name 缺省取目录名兜底、description 缺省空串（宽松读，research R1）。
    """
    skill_file = dir_path / SKILL_FILE_NAME
    try:
        raw = skill_file.read_text(encoding="utf-8")
        mtime = datetime.fromtimestamp(skill_file.stat().st_mtime)
    except (OSError, UnicodeDecodeError):
        return None
    if not raw.strip():
        return None
    name, description, instruction = parse_frontmatter(raw)
    return SkillFileData(
        name=name or fallback_name,
        description=description or "",
        instruction=instruction,
        mtime=mtime,
    )


def write_skill(dir_path: Path, name: str, description: str, instruction: str) -> None:
    """重写单个 Skill 文件为规范格式（编辑保存，FR-011）。目录不存在则创建。"""
    dir_path.mkdir(parents=True, exist_ok=True)
    (dir_path / SKILL_FILE_NAME).write_text(
        _render_frontmatter(name, description, instruction), encoding="utf-8", newline="\n",
    )


def scan_skills() -> tuple[list[str], list[str]]:
    """扫描目录根，返回（合规目录名列表, 跳过的不合规目录名列表）。

    仅统计目录（忽略散文件）；非法目录名计入 skipped（不纳入列表，契约 §1）。
    """
    root = skills_root()
    compliant: list[str] = []
    skipped: list[str] = []
    for entry in sorted(root.iterdir()):
        if not entry.is_dir():
            continue
        if is_valid_dir_name(entry.name) and is_compliant(entry):
            compliant.append(entry.name)
        else:
            skipped.append(entry.name)
    return compliant, skipped


def delete_skill_dir(dir_path: Path) -> None:
    """删除整个 Skill 目录（FR-014）；系统级失败（目录占用等）向上抛 OSError。"""
    if dir_path.exists():
        shutil.rmtree(dir_path)


# ---- 目录树与文件在线编辑（005，契约 skill-files-api.md）----

_DRIVE_RE = re.compile(r"^[A-Za-z]:")


def _resolve_skill_file(dir_path: Path, rel_path: str) -> Path:
    """相对路径 → Skill 目录内的绝对路径；非法/逃逸抛 InvalidSkillFilePath。

    双重校验（research R2@005）：黑名单（.. 片段 / 绝对路径 / 盘符 / 空串）+
    resolve 包含性（防符号链接等解析层逃逸）。读取与保存共用（SC-004）。
    """
    rel = (rel_path or "").strip().replace("\\", "/")
    if not rel:
        raise InvalidSkillFilePath("文件路径不能为空")
    if rel.startswith("/") or _DRIVE_RE.match(rel):
        raise InvalidSkillFilePath("不允许使用绝对路径")
    parts = PurePosixPath(rel).parts
    if not parts or any(part == ".." for part in parts):
        raise InvalidSkillFilePath("路径不允许包含 .. 片段")
    root = dir_path.resolve()
    target = (dir_path / rel).resolve()
    try:
        target.relative_to(root)
    except ValueError as exc:
        raise InvalidSkillFilePath("路径解析后超出该 Skill 目录") from exc
    return target


def list_tree(dir_path: Path, prefix: str = "") -> list[dict]:
    """递归目录树（契约 §2 SkillFileNode 嵌套结构）：目录在前、同类型名称字典序。

    prefix 为相对 Skill 根的当前层前缀（"scripts/"），保证各级 path 相对 Skill 根。
    """
    nodes: list[dict] = []
    try:
        entries = sorted(dir_path.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower()))
    except OSError:
        return []
    for entry in entries:
        rel = f"{prefix}{entry.name}"
        if entry.is_dir():
            nodes.append({
                "name": entry.name,
                "path": rel,
                "type": "dir",
                "children": list_tree(entry, prefix=f"{rel}/"),
            })
        elif entry.is_file():
            nodes.append({
                "name": entry.name,
                "path": rel,
                "type": "file",
                "children": [],
            })
    return nodes


@dataclass
class FileReadResult:
    """单个文件的读取结果（editable=false 时 content 恒 None，零乱码保证）。"""

    path: str
    editable: bool
    reason: str | None = None
    content: str | None = None
    size: int = 0


def read_text_file(dir_path: Path, rel_path: str) -> FileReadResult:
    """读取文本文件：先判上限、再判编码——都通过才返回内容（research R3@005）。"""
    target = _resolve_skill_file(dir_path, rel_path)
    rel = target.relative_to(dir_path.resolve()).as_posix()
    try:
        payload = target.read_bytes()
    except OSError as exc:
        raise FileNotFoundError(rel) from exc
    max_bytes = settings.file_max_bytes
    if len(payload) > max_bytes:
        return FileReadResult(path=rel, editable=False, reason="too_large", size=len(payload))
    try:
        text = payload.decode("utf-8")
    except UnicodeDecodeError:
        return FileReadResult(path=rel, editable=False, reason="not_text", size=len(payload))
    return FileReadResult(path=rel, editable=True, content=text, size=len(payload))


def write_text_file(dir_path: Path, rel_path: str, content: str) -> str:
    """覆盖写回文本文件（UTF-8）；超上限抛 SkillFileTooLarge；返回相对路径。"""
    target = _resolve_skill_file(dir_path, rel_path)
    if not target.is_file():
        raise FileNotFoundError(target.relative_to(dir_path.resolve()).as_posix())
    encoded = content.encode("utf-8")
    if len(encoded) > settings.file_max_bytes:
        raise SkillFileTooLarge(
            f"文件内容超过 {settings.file_max_bytes} 字节上限，无法保存"
        )
    target.write_bytes(encoded)
    return target.relative_to(dir_path.resolve()).as_posix()
