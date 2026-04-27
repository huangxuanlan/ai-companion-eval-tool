"""
导出路由: /api/export
"""
from datetime import datetime

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

import database as db
from config import PROJECT_DIR
from services.export_service import ExportService
from services.public_demo import ensure_visible_conversation

router = APIRouter(prefix="/api/export", tags=["export"])

_export_service = ExportService()
OUTPUT_DIR = PROJECT_DIR / "output"
OUTPUT_DIR.mkdir(exist_ok=True)


@router.get("/{conv_id}")
async def export_conversation(conv_id: str, summary: bool = False):
    """导出对话结果 Excel。"""
    conversation = ensure_visible_conversation(db.get_conversation(conv_id), conv_id)

    results = conversation.get("results", [])
    if not results:
        raise HTTPException(status_code=400, detail="对话无结果数据")

    config = conversation.get("config", {})
    role_name = config.get("character", {}).get("Role_Nickname", "unknown")
    safe_name = _export_service.safe_filename_part(role_name, fallback="conversation")
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    suffix = "评分摘要" if summary else "待打分"
    filename = f"{safe_name}_{timestamp}_{suffix}.xlsx"
    output_path = OUTPUT_DIR / filename

    _export_service.export_to_excel(
        results, config, str(output_path), summary=summary
    )
    return FileResponse(
        path=str(output_path),
        filename=filename,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
