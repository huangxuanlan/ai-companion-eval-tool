"""
Public demo mode helpers.

用于临时公网演示场景：
- 统一读取 demo mode 开关
- 管理临时上传提示词（仅本次服务进程生命周期可见）
- 收口对话可见性，避免暴露历史数据
"""
from __future__ import annotations

import re
import shutil
import uuid
from pathlib import Path

from fastapi import HTTPException

from config import PROJECT_DIR, PUBLIC_DEMO_MODE

DEMO_RUNTIME_DIR = PROJECT_DIR / ".runtime" / "public_demo"
EPHEMERAL_PROMPT_DIR = DEMO_RUNTIME_DIR / "prompts"
_SAFE_FILENAME_RE = re.compile(r"[^0-9A-Za-z._\-\u4e00-\u9fff]+")


def is_public_demo_mode() -> bool:
    return bool(PUBLIC_DEMO_MODE)


def reset_public_demo_runtime() -> None:
    if DEMO_RUNTIME_DIR.exists():
        shutil.rmtree(DEMO_RUNTIME_DIR)
    EPHEMERAL_PROMPT_DIR.mkdir(parents=True, exist_ok=True)


def ensure_public_demo_dirs() -> None:
    EPHEMERAL_PROMPT_DIR.mkdir(parents=True, exist_ok=True)


def _sanitize_filename(filename: str) -> str:
    raw = Path(str(filename or "").strip()).name or "prompt.md"
    cleaned = _SAFE_FILENAME_RE.sub("_", raw).strip("._")
    if not cleaned.lower().endswith(".md"):
        cleaned = f"{cleaned or 'prompt'}.md"
    return cleaned or "prompt.md"


def create_ephemeral_prompt(filename: str, content: bytes) -> dict:
    ensure_public_demo_dirs()
    safe_name = _sanitize_filename(filename)
    generated_name = f"demo_prompt_{uuid.uuid4().hex[:8]}_{safe_name}"
    target = EPHEMERAL_PROMPT_DIR / generated_name
    target.write_bytes(content)
    stat = target.stat()
    return {
        "filename": generated_name,
        "original_filename": safe_name,
        "size": stat.st_size,
        "modified": stat.st_mtime,
        "is_ephemeral": True,
        "is_main_prompt": True,
        "is_latest": False,
        "is_active": False,
    }


def resolve_ephemeral_prompt_path(filename: str) -> Path | None:
    if not filename:
        return None
    candidate = EPHEMERAL_PROMPT_DIR / Path(str(filename).strip()).name
    if candidate.exists() and candidate.is_file():
        return candidate
    return None


def list_ephemeral_prompt_entries() -> list[dict]:
    if not EPHEMERAL_PROMPT_DIR.exists():
        return []
    entries = []
    for path in sorted(
        EPHEMERAL_PROMPT_DIR.glob("*.md"),
        key=lambda item: item.stat().st_mtime,
        reverse=True,
    ):
        stat = path.stat()
        entries.append(
            {
                "filename": path.name,
                "original_filename": path.name.split("_", 3)[-1] if "_" in path.name else path.name,
                "size": stat.st_size,
                "modified": stat.st_mtime,
                "is_ephemeral": True,
                "is_main_prompt": True,
                "is_latest": False,
                "is_active": False,
            }
        )
    return entries


def raise_if_demo_write_blocked(detail: str) -> None:
    if is_public_demo_mode():
        raise HTTPException(status_code=403, detail=detail)


def is_demo_conversation(conversation: dict | None) -> bool:
    if not conversation:
        return False
    runtime = dict(conversation.get("config", {}).get("runtime", {}) or {})
    return bool(runtime.get("public_demo_mode"))


def ensure_visible_conversation(conversation: dict | None, conv_id: str) -> dict:
    if not conversation:
        raise HTTPException(status_code=404, detail=f"对话不存在: {conv_id}")
    if is_public_demo_mode() and not is_demo_conversation(conversation):
        raise HTTPException(status_code=404, detail=f"对话不存在: {conv_id}")
    return conversation


def filter_visible_conversations(conversations: list[dict]) -> list[dict]:
    if not is_public_demo_mode():
        return list(conversations or [])
    return [item for item in conversations or [] if is_demo_conversation(item)]


def build_public_demo_app_config() -> dict:
    public_demo = is_public_demo_mode()
    return {
        "public_demo_mode": public_demo,
        "features": {
            "allow_prompt_upload": True,
            "allow_prompt_edit": not public_demo,
            "allow_prompt_activation": not public_demo,
            "allow_prompt_versioning": not public_demo,
            "allow_preset_save": not public_demo,
            "allow_runtime_prompt_edit": not public_demo,
            "allowed_prompt_kinds": ["chat"] if public_demo else ["chat", "summary", "scoring"],
        },
    }
