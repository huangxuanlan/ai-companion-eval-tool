from __future__ import annotations

import json
import logging
import re
import time

from services.model_adapter import ModelAdapter
from services.prompt_version_service import VersionedPromptStore

logger = logging.getLogger(__name__)


def generate_summary(
    service,
    conversation_history: list,
    role_name: str,
    personal_type: str,
    relationship: str,
    model_id: str,
    prompt_version: str,
    dry_run: bool,
    summary_template: str,
) -> str:
    """调用摘要模型生成结构化 dialogue_summary。"""
    started_at = time.perf_counter()
    if dry_run:
        return (
            "=== 之前剧情摘要 ===\n"
            "- 场景：[dry-run 模拟场景]\n"
            "- 剧情：[dry-run 模拟剧情]\n"
            "- 悬念：[dry-run 模拟悬念]\n"
            "- 角色情绪：[dry-run 模拟角色情绪]\n"
            "- 用户情绪：[dry-run 模拟用户情绪]\n"
            "- 关系动态：[dry-run 模拟关系]\n"
            "- 用户画像信号：[dry-run 模拟画像]\n"
            "=== 摘要结束 ==="
        )

    conv_lines = []
    for msg in conversation_history:
        label = "用户" if msg["role"] == "user" else "角色"
        conv_lines.append(f"[{label}]: {msg['content'][:500]}")
    conversation_text = "\n".join(conv_lines)

    prompt_template = service.summary_prompt_store.read_prompt(
        prompt_version or None
    )["content"]
    prompt_text = prompt_template
    replacements = {
        "{role_name}": role_name,
        "{personal_type}": personal_type,
        "{relationship}": relationship,
        "{conversation_text}": conversation_text,
    }
    for placeholder, value in replacements.items():
        prompt_text = prompt_text.replace(placeholder, value)

    if ModelAdapter.is_gemma_model(model_id):
        system_content = (
            "<role>你是一个专业的对话分析助手。</role>\n"
            "<output_format>请严格按JSON格式输出，不要包含任何额外说明文字。</output_format>"
        )
    else:
        system_content = "你是一个专业的对话分析助手。请严格按JSON格式输出。"
    messages = [
        {"role": "system", "content": system_content},
        {"role": "user", "content": prompt_text},
    ]

    result = service.model.chat(model_id, messages, max_tokens=800)
    if not result.success:
        logger.warning(
            "摘要生成失败 model=%s latency=%.2fs error=%s",
            model_id,
            time.perf_counter() - started_at,
            result.error,
        )
        return ""

    raw = result.content.strip()
    try:
        clean = raw
        if clean.startswith("```"):
            clean = re.sub(r"^```\w*\n?", "", clean)
            clean = re.sub(r"\n?```$", "", clean)
        data = json.loads(clean)
    except json.JSONDecodeError:
        logger.info(
            "摘要生成返回非 JSON，按原文包裹 model=%s latency=%.2fs",
            model_id,
            time.perf_counter() - started_at,
        )
        return f"=== 之前剧情摘要 ===\n{raw}\n=== 摘要结束 ==="

    summary_text = summary_template.format(
        scene_description=data.get("scene_description", "未知"),
        plot_summary=data.get("plot_summary", "无"),
        pending_hooks=data.get("pending_hooks", "无"),
        character_emotion=data.get("character_emotion", "未知"),
        user_emotion=data.get("user_emotion", "未知"),
        relationship_shift=data.get("relationship_shift", "未知"),
        user_profile_signals=data.get("user_profile_signals", ""),
    )
    logger.info(
        "摘要生成完成 model=%s latency=%.2fs history_messages=%s",
        model_id,
        time.perf_counter() - started_at,
        len(conversation_history or []),
    )
    return summary_text


def format_profile_transcript(turn_items: list[dict]) -> str:
    lines: list[str] = []
    for item in turn_items or []:
        turn_num = int(item.get("turn", 0) or 0)
        user_input = str(item.get("user_input", "")).strip()
        ai_output = str(item.get("ai_output", "")).strip()
        if user_input:
            lines.append(f"[Turn {turn_num}][user] {user_input}")
        if ai_output:
            lines.append(f"[Turn {turn_num}][assistant] {ai_output}")
    return "\n".join(lines)


def read_user_profile_prompt_template(profile_prompt_version: str = "") -> str:
    """读取画像提示词模板，优先显式版本，否则读取 active 版本。"""
    store = VersionedPromptStore(kind="profile")
    if profile_prompt_version:
        try:
            result = store.read_prompt(profile_prompt_version)
            return result.get("content", "")
        except Exception:
            pass
    try:
        result = store.read_prompt()
        return result.get("content", "")
    except Exception:
        return ""


def generate_user_profile(
    service,
    *,
    existing_profile: str,
    latest_summary: str,
    new_transcript: str,
    model_id: str,
    profile_prompt_version: str,
    dry_run: bool,
) -> str:
    started_at = time.perf_counter()
    if dry_run:
        return (
            "【用户画像信息】\n"
            "- 身份：\n"
            "- 年龄：\n"
            "- 生日：\n"
            "- 偏爱：\n"
            "- 讨厌：\n"
            "- 用户近期基本信息：\n"
            "- 用户近期烦恼的事情：\n"
            "- 用户近期开心的事情：\n"
            "- 用户近期的计划：\n"
            "- 用户与角色的情况：\n"
            "- 用户身边人情况：\n"
            "- 用户纠正你的事情：\n"
            "- 场景偏好（长文专属）：\n"
            "- 情绪模式（长文专属）：\n"
            "- 互动偏好（长文专属）：\n"
            "- 敏感触点（长文专属）：\n\n"
            "【上次对话时间】\n"
            "dry-run\n\n"
            "【本次对话智能摘要】\n"
            "[dry-run] 用户画像抽取链路已触发\n\n"
            "【用户核心记忆点】\n"
            "[dry-run] profile\n"
        )

    template = read_user_profile_prompt_template(profile_prompt_version)
    if not template.strip():
        return ""

    prompt_text = template
    prompt_text = prompt_text.replace("{{existing_profile}}", existing_profile or "")
    prompt_text = prompt_text.replace("{{latest_summary}}", latest_summary or "")
    prompt_text = prompt_text.replace("{{new_transcript}}", new_transcript or "")

    messages = [
        {
            "role": "system",
            "content": "你是一个严谨的用户画像与记忆提取专家。禁止输出任何思考过程。",
        },
        {"role": "user", "content": prompt_text},
    ]
    result = service.model.chat(model_id, messages, max_tokens=1600)
    if not result.success:
        logger.warning(
            "画像生成失败 model=%s latency=%.2fs error=%s",
            model_id,
            time.perf_counter() - started_at,
            result.error,
        )
        return ""
    profile_text = result.content.strip()
    logger.info(
        "画像生成完成 model=%s latency=%.2fs transcript_chars=%s",
        model_id,
        time.perf_counter() - started_at,
        len(new_transcript or ""),
    )
    return profile_text
