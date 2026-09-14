"""Skills 管理路由层（只做 HTTP 编排）。

契约主定义：specs/004-skills-mcp-management/contracts/skills-api.md
错误统一 {"detail": 人话信息}，不含堆栈、内部路径与文件内容。
"""

from fastapi import APIRouter, Depends, HTTPException, UploadFile, status
from sqlalchemy.orm import Session

from app.core.db import get_session
from app.schemas.skill import (
    SkillDeletedResponse,
    SkillDetail,
    SkillFileContent,
    SkillFileNode,
    SkillFileSavedResponse,
    SkillFileWriteRequest,
    SkillItem,
    SkillRefreshResult,
    SkillToggleRequest,
    SkillUpdateRequest,
)
from app.services import skill_service
from app.services.agent_references import ReferencedByAgentError
from app.services.skill_service import (
    SkillFileNotFoundError,
    SkillFileTooLargeError,
    SkillImportError,
    SkillInvalidPathError,
    SkillNotFoundError,
    SkillOperationError,
)

router = APIRouter(prefix="/api/skills", tags=["skills"])

# 导入上传体上限（与契约 §5 大小上限一致，留少量封装余量）
_IMPORT_MAX_BYTES = 10 * 1024 * 1024


@router.get("", response_model=list[SkillItem])
def list_skills(session: Session = Depends(get_session)) -> object:
    return skill_service.list_skills(session)


@router.post("/refresh", response_model=SkillRefreshResult)
def refresh_skills(session: Session = Depends(get_session)) -> object:
    return skill_service.refresh(session)


@router.post("/import", response_model=SkillItem, status_code=status.HTTP_201_CREATED)
async def import_skill(file: UploadFile, session: Session = Depends(get_session)) -> object:
    """ZIP 导入（US4）。失败 → 400 人话原因；非 ZIP/超限 → 422。"""
    filename = file.filename or ""
    payload = await file.read()
    if len(payload) > _IMPORT_MAX_BYTES + 1024:
        raise HTTPException(status_code=422, detail="导入失败：压缩包超过大小上限（10MB）")
    if not payload.startswith(b"PK"):
        raise HTTPException(status_code=422, detail="导入失败：仅支持 ZIP 格式的文件")
    try:
        return skill_service.import_zip(session, filename, payload)
    except SkillImportError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    finally:
        await file.close()


@router.get("/{dir_name}", response_model=SkillDetail)
def get_skill(dir_name: str, session: Session = Depends(get_session)) -> object:
    try:
        return skill_service.get_skill(session, dir_name)
    except SkillNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Skill 不存在") from exc


@router.put("/{dir_name}", response_model=SkillItem)
def update_skill(
    dir_name: str, payload: SkillUpdateRequest, session: Session = Depends(get_session),
) -> object:
    try:
        return skill_service.update_skill(
            session, dir_name, payload.name.strip(), payload.description, payload.instruction,
        )
    except SkillNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Skill 不存在") from exc
    except SkillOperationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.put("/{dir_name}/enabled", response_model=SkillItem)
def set_skill_enabled(
    dir_name: str, payload: SkillToggleRequest, session: Session = Depends(get_session),
) -> object:
    try:
        return skill_service.set_enabled(session, dir_name, payload.enabled)
    except SkillNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Skill 不存在") from exc


@router.delete("/{dir_name}", response_model=SkillDeletedResponse)
def delete_skill(dir_name: str, session: Session = Depends(get_session)) -> SkillDeletedResponse:
    try:
        skill_service.delete_skill(session, dir_name)
    except ReferencedByAgentError as exc:
        raise HTTPException(status_code=409, detail={
            "detail": str(exc),
            "referenced_by_agents": exc.referenced_by,
        }) from exc
    except SkillNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Skill 不存在") from exc
    except SkillOperationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return SkillDeletedResponse()


# ---- 目录树与文件在线编辑（005，契约 skill-files-api.md §3）----


@router.get("/{dir_name}/tree", response_model=list[SkillFileNode])
def get_skill_tree(dir_name: str, session: Session = Depends(get_session)) -> object:
    """目录树（FR-005）：实时扫描该 Skill 目录。"""
    try:
        return skill_service.get_tree(session, dir_name)
    except SkillNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Skill 不存在") from exc


@router.get("/{dir_name}/file", response_model=SkillFileContent)
def read_skill_file(
    dir_name: str, path: str, session: Session = Depends(get_session),
) -> object:
    """读取文件（FR-010）：editable=false 是正常查询结果（200），非错误。"""
    try:
        return skill_service.read_file(session, dir_name, path)
    except SkillInvalidPathError as exc:
        raise HTTPException(status_code=400, detail=f"非法的文件路径：{path}") from exc
    except SkillFileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="文件不存在") from exc
    except SkillNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Skill 不存在") from exc


@router.put("/{dir_name}/file", response_model=SkillFileSavedResponse)
def write_skill_file(
    dir_name: str, payload: SkillFileWriteRequest, session: Session = Depends(get_session),
) -> object:
    """保存文件（FR-009/012）：覆盖写回；skill.md 额外同步列表信息。"""
    try:
        return skill_service.write_file(session, dir_name, payload.path, payload.content)
    except SkillInvalidPathError as exc:
        raise HTTPException(status_code=400, detail=f"非法的文件路径：{payload.path}") from exc
    except SkillFileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="文件不存在") from exc
    except SkillFileTooLargeError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except SkillNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Skill 不存在") from exc
