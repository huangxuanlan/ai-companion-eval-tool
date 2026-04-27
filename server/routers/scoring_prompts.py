"""
打分提示词版本管理 API。
"""
from __future__ import annotations

from fastapi import APIRouter, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel

from services.prompt_version_service import VersionedPromptStore
from services.public_demo import raise_if_demo_write_blocked

router = APIRouter(prefix="/api/scoring-prompts", tags=["scoring-prompts"])

MAX_UPLOAD_SIZE = 5 * 1024 * 1024  # 5MB


class PromptEditRequest(BaseModel):
    content: str


class PromptVersionCreateRequest(BaseModel):
    content: str
    filename: str | None = None
    activate: bool = True


def _store() -> VersionedPromptStore:
    return VersionedPromptStore(kind="scoring")


@router.get("")
async def list_scoring_prompts():
    return _store().list_versions()


@router.get("/history")
async def list_scoring_prompt_history():
    return _store().list_versions()


@router.post("/versions")
async def create_scoring_prompt_version(data: PromptVersionCreateRequest):
    raise_if_demo_write_blocked("演示模式下禁止新建正式打分提示词版本")
    try:
        return _store().create_version(
            content=data.content,
            filename=data.filename,
            activate=data.activate,
        )
    except FileExistsError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/{filename}/activate")
async def activate_scoring_prompt(filename: str):
    raise_if_demo_write_blocked("演示模式下禁止切换正式打分提示词版本")
    try:
        return _store().activate(filename)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/{filename}")
async def get_scoring_prompt(filename: str):
    try:
        return _store().read_prompt(filename)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/{filename}/download")
async def download_scoring_prompt(filename: str):
    try:
        path = _store().download_path(filename)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return FileResponse(
        path=str(path),
        filename=path.name,
        media_type="text/markdown",
    )


@router.put("/{filename}")
async def edit_scoring_prompt(filename: str, data: PromptEditRequest):
    raise_if_demo_write_blocked("演示模式下禁止编辑正式打分提示词")
    try:
        return _store().save_prompt(filename, data.content)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/upload")
async def upload_scoring_prompt(file: UploadFile = File(...)):
    raise_if_demo_write_blocked("演示模式下禁止上传正式打分提示词")
    if not file.filename or not file.filename.endswith(".md"):
        raise HTTPException(status_code=400, detail="仅支持 .md 文件")
    content = await file.read()
    if len(content) > MAX_UPLOAD_SIZE:
        raise HTTPException(
            status_code=400,
            detail=f"文件过大（限制 {MAX_UPLOAD_SIZE // 1024 // 1024}MB）",
        )
    try:
        return _store().create_version(
            content=content.decode("utf-8"),
            filename=file.filename,
            activate=True,
        )
    except UnicodeDecodeError as exc:
        raise HTTPException(status_code=400, detail="文件编码必须为 UTF-8") from exc
    except FileExistsError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
