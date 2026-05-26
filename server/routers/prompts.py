"""
提示词管理 API。

- kind=chat: 主对话提示词
- kind=summary: 摘要提示词
- kind=scoring: 打分提示词
- kind=profile: 画像提示词
"""
from __future__ import annotations

from fastapi import APIRouter, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel

from config import (
    PROMPT_DIR,
    get_latest_prompt_file,
    is_main_prompt_file,
    list_prompt_files,
)
from services.public_demo import (
    create_ephemeral_prompt,
    is_public_demo_mode,
    list_ephemeral_prompt_entries,
    raise_if_demo_write_blocked,
    resolve_ephemeral_prompt_path,
)
from services.prompt_version_service import VersionedPromptStore

router = APIRouter(prefix="/api/prompts", tags=["prompts"])

MAX_UPLOAD_SIZE = 5 * 1024 * 1024  # 5MB


class PromptEditRequest(BaseModel):
    content: str


class PromptVersionCreateRequest(BaseModel):
    content: str
    filename: str | None = None
    activate: bool = True


def _resolve_kind(kind: str) -> str:
    normalized = str(kind or "chat").strip().lower()
    if normalized not in {"chat", "summary", "scoring", "profile"}:
        raise HTTPException(status_code=400, detail=f"不支持的提示词类型: {kind}")
    return normalized


def _chat_prompt_path(filename: str):
    ephemeral_path = resolve_ephemeral_prompt_path(filename)
    if ephemeral_path is not None:
        return ephemeral_path
    requested = str(filename or "").strip()
    path = PROMPT_DIR / requested
    if not path.exists():
        for candidate in list_prompt_files():
            if candidate.name == requested:
                path = candidate
                break
    if not path.exists() or path.suffix.lower() != ".md":
        raise HTTPException(status_code=404, detail=f"文件不存在: {filename}")
    return path


def _list_chat_prompts() -> dict:
    files = []
    ordered_files = list_prompt_files()
    latest_filename = get_latest_prompt_file() if ordered_files else ""
    if is_public_demo_mode():
        files.extend(list_ephemeral_prompt_entries())
    if PROMPT_DIR.exists():
        for path in ordered_files:
            files.append(
                {
                    "filename": path.name,
                    "size": path.stat().st_size,
                    "modified": path.stat().st_mtime,
                    "is_main_prompt": is_main_prompt_file(path.name),
                    "is_latest": path.name == latest_filename,
                    "is_active": path.name == latest_filename,
                }
            )
    return {
        "kind": "chat",
        "prompts": files,
        "latest_filename": latest_filename,
        "active_filename": latest_filename,
    }


@router.get("")
async def list_prompts(kind: str = "chat"):
    """列出提示词版本。"""
    resolved_kind = _resolve_kind(kind)
    if resolved_kind == "chat":
        return _list_chat_prompts()
    return VersionedPromptStore(kind=resolved_kind).list_versions()


@router.get("/history")
async def list_prompt_history(kind: str = "summary"):
    """查看摘要提示词版本历史。"""
    resolved_kind = _resolve_kind(kind)
    if resolved_kind != "summary":
        raise HTTPException(status_code=400, detail="仅摘要提示词支持 history")
    return VersionedPromptStore(kind="summary").list_versions()


@router.post("/versions")
async def create_prompt_version(
    data: PromptVersionCreateRequest,
    kind: str = "summary",
):
    """保存摘要提示词新版本。"""
    raise_if_demo_write_blocked("演示模式下禁止新建正式提示词版本")
    resolved_kind = _resolve_kind(kind)
    if resolved_kind != "summary":
        raise HTTPException(status_code=400, detail="仅摘要提示词支持新建版本")
    store = VersionedPromptStore(kind="summary")
    try:
        return store.create_version(
            content=data.content,
            filename=data.filename,
            activate=data.activate,
        )
    except FileExistsError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/{filename}/activate")
async def activate_prompt(filename: str, kind: str = "summary"):
    """切换摘要提示词生效版本。"""
    raise_if_demo_write_blocked("演示模式下禁止切换正式提示词版本")
    resolved_kind = _resolve_kind(kind)
    if resolved_kind != "summary":
        raise HTTPException(status_code=400, detail="仅摘要提示词支持切换生效版本")
    store = VersionedPromptStore(kind="summary")
    try:
        return store.activate(filename)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/{filename}")
async def get_prompt(filename: str, kind: str = "chat"):
    """读取指定提示词文件内容。"""
    resolved_kind = _resolve_kind(kind)
    if resolved_kind == "chat":
        path = _chat_prompt_path(filename)
        content = path.read_text(encoding="utf-8")
        return {
            "filename": filename,
            "total_lines": content.count("\n") + 1,
            "content": content[:20000],
            "truncated": len(content) > 20000,
            "kind": "chat",
        }
    store = VersionedPromptStore(kind=resolved_kind)
    try:
        return store.read_prompt(filename)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/{filename}/download")
async def download_prompt(filename: str, kind: str = "chat"):
    """下载提示词文件。"""
    resolved_kind = _resolve_kind(kind)
    if resolved_kind == "chat":
        path = _chat_prompt_path(filename)
    else:
        store = VersionedPromptStore(kind=resolved_kind)
        try:
            path = store.download_path(filename)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
    return FileResponse(
        path=str(path),
        filename=path.name,
        media_type="text/markdown",
    )


@router.post("/upload")
async def upload_prompt(
    file: UploadFile = File(...),
    kind: str = "chat",
):
    """上传提示词文件（.md）。"""
    resolved_kind = _resolve_kind(kind)
    if not file.filename or not file.filename.endswith(".md"):
        raise HTTPException(status_code=400, detail="仅支持 .md 文件")

    content = await file.read()
    if len(content) > MAX_UPLOAD_SIZE:
        raise HTTPException(
            status_code=400,
            detail=f"文件过大（限制 {MAX_UPLOAD_SIZE // 1024 // 1024}MB）",
        )

    if resolved_kind == "chat":
        if is_public_demo_mode():
            payload = create_ephemeral_prompt(file.filename, content)
            return {
                "message": "演示模式临时上传成功",
                "filename": payload["filename"],
                "original_filename": payload["original_filename"],
                "size": payload["size"],
                "kind": "chat",
                "is_ephemeral": True,
            }
        PROMPT_DIR.mkdir(parents=True, exist_ok=True)
        dest = PROMPT_DIR / file.filename
        dest.write_bytes(content)
        return {
            "message": "上传成功",
            "filename": file.filename,
            "size": len(content),
            "kind": "chat",
        }

    raise_if_demo_write_blocked("演示模式下禁止上传正式摘要提示词")
    store = VersionedPromptStore(kind="summary")
    try:
        return store.create_version(
            content=content.decode("utf-8"),
            filename=file.filename,
            activate=True,
        )
    except UnicodeDecodeError as exc:
        raise HTTPException(status_code=400, detail="文件编码必须为 UTF-8") from exc
    except FileExistsError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.put("/{filename}")
async def edit_prompt(
    filename: str,
    data: PromptEditRequest,
    kind: str = "chat",
):
    """在线编辑并保存提示词内容。"""
    raise_if_demo_write_blocked("演示模式下禁止在线编辑正式提示词")
    resolved_kind = _resolve_kind(kind)
    if resolved_kind == "chat":
        if not filename.endswith(".md"):
            raise HTTPException(status_code=400, detail="仅支持 .md 文件")
        path = PROMPT_DIR / filename
        path.write_text(data.content, encoding="utf-8")
        return {
            "message": "保存成功",
            "filename": filename,
            "size": len(data.content.encode("utf-8")),
            "kind": "chat",
        }

    store = VersionedPromptStore(kind=resolved_kind)
    try:
        return store.save_prompt(filename, data.content)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
