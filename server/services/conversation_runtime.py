from __future__ import annotations

import logging
import sqlite3
import time
from concurrent.futures import Future, TimeoutError as FutureTimeout

logger = logging.getLogger(__name__)


def _safe_update_turn_dialogue_summary(
    service,
    conv_id: str,
    target_turn: int,
    summary_text: str,
) -> None:
    try:
        service.store.update_turn_dialogue_summary(conv_id, target_turn, summary_text)
    except sqlite3.OperationalError as exc:
        if "no such table" in str(exc).lower():
            logger.warning(
                "摘要后台落库跳过 conv_id=%s turn=%s reason=%s",
                conv_id,
                target_turn,
                exc,
            )
            return
        logger.exception("摘要后台落库失败 conv_id=%s turn=%s", conv_id, target_turn)
    except Exception:
        logger.exception("摘要后台落库失败 conv_id=%s turn=%s", conv_id, target_turn)


def refresh_runtime_bundle_memory(service, runtime_bundle, config: dict) -> None:
    variables = service.prompt.build_variables(config)
    runtime_bundle.seed_dialogue_summary = str(
        variables.get("dialogue_summary", "") or config.get("dialogue_summary", "")
    ).strip()
    runtime_bundle.memory_profile = str(variables.get("dialogueStartPrompt", "")).strip()
    runtime_bundle.memory_moments = str(variables.get("moments", "")).strip()


def persist_runtime_state(service, conv_id: str, config: dict) -> None:
    try:
        service.store.update_conversation_config(conv_id, config)
    except Exception:
        logger.exception("更新会话运行时配置失败 conv_id=%s", conv_id)


def ensure_runtime_state(service, config: dict, runtime_bundle, results: list[dict]) -> dict:
    runtime = config.setdefault("runtime", {})
    last_summary_turn = service._last_summary_turn(results)
    last_summary = service._last_dialogue_summary(results)
    if "latest_dialogue_summary" not in runtime:
        runtime["latest_dialogue_summary"] = last_summary or runtime_bundle.seed_dialogue_summary
    if "last_summary_turn" not in runtime:
        runtime["last_summary_turn"] = last_summary_turn
    runtime.setdefault("summary_job_status", "idle")
    runtime.setdefault("summary_job_target_turn", 0)
    runtime.setdefault("profile_job_status", "idle")
    runtime.setdefault(
        "profile_job_target_turn",
        int(runtime.get("last_profile_turn", 0) or 0),
    )
    return runtime


def resolve_dialogue_summary_for_next_turn(
    service,
    *,
    config: dict,
    results: list[dict],
    runtime_bundle,
) -> tuple[str, str]:
    runtime = ensure_runtime_state(service, config, runtime_bundle, results)
    latest_summary = str(runtime.get("latest_dialogue_summary", "")).strip()
    last_summary_turn = int(runtime.get("last_summary_turn", 0) or 0)
    last_summary = service._last_dialogue_summary(results)
    seed_summary = str(runtime_bundle.seed_dialogue_summary or "").strip()
    completed_turns = len(results or [])

    if (
        completed_turns <= 0
        and latest_summary
        and str(runtime.get("summary_job_status", "")).strip() == "completed"
    ):
        return latest_summary, "completed"
    if completed_turns <= 0:
        return seed_summary, "seed" if seed_summary else "empty"
    if latest_summary and last_summary_turn > 0:
        return latest_summary, "completed"
    if last_summary:
        return last_summary, "completed"
    if str(runtime.get("summary_job_status", "")).strip() == "pending-fallback":
        fallback = latest_summary or seed_summary
        return fallback, "pending-fallback"
    return seed_summary, "seed" if seed_summary else "empty"


def set_summary_runtime_state(
    service,
    conv_id: str,
    config: dict,
    *,
    status: str,
    target_turn: int,
    latest_dialogue_summary: str | None = None,
    last_summary_turn: int | None = None,
) -> None:
    with service._job_lock:
        runtime = config.setdefault("runtime", {})
        runtime["summary_job_status"] = status
        runtime["summary_job_target_turn"] = int(target_turn or 0)
        if latest_dialogue_summary is not None:
            runtime["latest_dialogue_summary"] = str(latest_dialogue_summary or "").strip()
        if last_summary_turn is not None:
            runtime["last_summary_turn"] = int(last_summary_turn or 0)
    persist_runtime_state(service, conv_id, config)


def set_profile_runtime_state(
    service,
    conv_id: str,
    config: dict,
    *,
    status: str,
    target_turn: int,
    profile_text: str | None = None,
    last_profile_turn: int | None = None,
) -> None:
    with service._job_lock:
        runtime = config.setdefault("runtime", {})
        runtime["profile_job_status"] = status
        runtime["profile_job_target_turn"] = int(target_turn or 0)
        if last_profile_turn is not None:
            runtime["last_profile_turn"] = int(last_profile_turn or 0)
        if profile_text is not None:
            config.setdefault("modules", {})["dialogueStartPrompt"] = str(profile_text or "").strip()
    persist_runtime_state(service, conv_id, config)


def consume_summary_job(service, conv_id: str, target_turn: int) -> str | None:
    key = (conv_id, target_turn)
    with service._job_lock:
        job = service._summary_jobs.get(key)
        if not job or job.get("consumed"):
            return None
        future: Future = job["future"]
        config = job["config"]
        if not future.done():
            return None
        try:
            summary_text = str(future.result() or "").strip()
        except Exception:
            logger.exception("摘要后台任务失败 conv_id=%s turn=%s", conv_id, target_turn)
            set_summary_runtime_state(
                service,
                conv_id,
                config,
                status="failed",
                target_turn=target_turn,
            )
            job["consumed"] = True
            service._summary_jobs.pop(key, None)
            return None

        runtime = config.setdefault("runtime", {})
        current_last_summary_turn = int(runtime.get("last_summary_turn", 0) or 0)
        if target_turn < current_last_summary_turn:
            logger.info(
                "丢弃过期摘要 conv_id=%s target_turn=%s current_last=%s",
                conv_id,
                target_turn,
                current_last_summary_turn,
            )
            set_summary_runtime_state(
                service,
                conv_id,
                config,
                status="stale",
                target_turn=target_turn,
            )
            job["consumed"] = True
            service._summary_jobs.pop(key, None)
            return None

        set_summary_runtime_state(
            service,
            conv_id,
            config,
            status="completed",
            target_turn=target_turn,
            latest_dialogue_summary=summary_text,
            last_summary_turn=target_turn,
        )
        if summary_text:
            _safe_update_turn_dialogue_summary(
                service,
                conv_id,
                target_turn,
                summary_text,
            )
        job["consumed"] = True
        service._summary_jobs.pop(key, None)
        return summary_text


def consume_profile_job(service, conv_id: str, target_turn: int) -> str | None:
    key = (conv_id, target_turn)
    with service._job_lock:
        job = service._profile_jobs.get(key)
        if not job or job.get("consumed"):
            return None
        future: Future = job["future"]
        config = job["config"]
        if not future.done():
            return None
        try:
            profile_text = str(future.result() or "").strip()
        except Exception:
            logger.exception("画像后台任务失败 conv_id=%s turn=%s", conv_id, target_turn)
            set_profile_runtime_state(
                service,
                conv_id,
                config,
                status="failed",
                target_turn=target_turn,
            )
            job["consumed"] = True
            service._profile_jobs.pop(key, None)
            return None

        runtime = config.setdefault("runtime", {})
        current_last_profile_turn = int(runtime.get("last_profile_turn", 0) or 0)
        if target_turn < current_last_profile_turn:
            logger.info(
                "丢弃过期画像 conv_id=%s target_turn=%s current_last=%s",
                conv_id,
                target_turn,
                current_last_profile_turn,
            )
            set_profile_runtime_state(
                service,
                conv_id,
                config,
                status="stale",
                target_turn=target_turn,
            )
            job["consumed"] = True
            service._profile_jobs.pop(key, None)
            return None

        if profile_text:
            set_profile_runtime_state(
                service,
                conv_id,
                config,
                status="completed",
                target_turn=target_turn,
                profile_text=profile_text,
                last_profile_turn=target_turn,
            )
        else:
            set_profile_runtime_state(
                service,
                conv_id,
                config,
                status="failed",
                target_turn=target_turn,
            )
        job["consumed"] = True
        service._profile_jobs.pop(key, None)
        return profile_text


def schedule_summary_job_if_needed(
    service,
    *,
    conv_id: str,
    config: dict,
    runtime_bundle,
    conversation_history: list[dict],
    turn_num: int,
    summary_interval: int,
    model_mini: str,
    summary_prompt_version: str,
    dry_run: bool,
) -> None:
    if turn_num <= 0 or turn_num % summary_interval != 0:
        return

    key = (conv_id, turn_num)
    with service._job_lock:
        existing = service._summary_jobs.get(key)
        if existing and not existing.get("consumed"):
            return

    history_snapshot = [dict(item) for item in (conversation_history or [])]
    future = service._background_executor.submit(
        service.generate_summary,
        history_snapshot,
        runtime_bundle.role_name,
        runtime_bundle.personal_type,
        runtime_bundle.relationship,
        model_mini,
        summary_prompt_version,
        dry_run,
    )
    with service._job_lock:
        service._summary_jobs[key] = {
            "future": future,
            "config": config,
            "consumed": False,
        }
    future.add_done_callback(lambda _: consume_summary_job(service, conv_id, turn_num))
    logger.info("摘要后台任务已调度 conv_id=%s turn=%s", conv_id, turn_num)
    set_summary_runtime_state(
        service,
        conv_id,
        config,
        status="pending",
        target_turn=turn_num,
    )


def schedule_initial_summary_job(
    service,
    *,
    conv_id: str,
    config: dict,
    runtime_bundle,
    model_mini: str,
    summary_prompt_version: str,
    dry_run: bool,
) -> None:
    key = (conv_id, 0)
    with service._job_lock:
        existing = service._summary_jobs.get(key)
        if existing and not existing.get("consumed"):
            return

    future = service._background_executor.submit(
        service.generate_summary,
        [],
        runtime_bundle.role_name,
        runtime_bundle.personal_type,
        runtime_bundle.relationship,
        model_mini,
        summary_prompt_version,
        dry_run,
    )
    with service._job_lock:
        service._summary_jobs[key] = {
            "future": future,
            "config": config,
            "consumed": False,
        }
    set_summary_runtime_state(
        service,
        conv_id,
        config,
        status="pending",
        target_turn=0,
    )
    future.add_done_callback(lambda _: consume_summary_job(service, conv_id, 0))
    logger.info("会话创建摘要预热任务已调度 conv_id=%s", conv_id)


def schedule_profile_job_if_needed(
    service,
    *,
    conv_id: str,
    config: dict,
    latest_summary: str,
    results: list[dict],
    turn_num: int,
    model_mini: str,
    dry_run: bool,
) -> None:
    if turn_num <= 0 or turn_num % 20 != 0:
        return

    key = (conv_id, turn_num)
    with service._job_lock:
        existing = service._profile_jobs.get(key)
        if existing and not existing.get("consumed"):
            return

    runtime = config.setdefault("runtime", {})
    last_profile_turn = int(runtime.get("last_profile_turn", 0) or 0)
    profile_model = str(runtime.get("profile_model_id", "")).strip() or model_mini
    new_turn_items = [
        item for item in (results or [])
        if int(item.get("turn", 0) or 0) > last_profile_turn
    ]
    new_transcript = service._format_profile_transcript(new_turn_items)
    existing_profile = str(
        dict(config.get("modules", {}) or {}).get("dialogueStartPrompt", "")
    ).strip()
    profile_prompt_version = str(runtime.get("profile_prompt_version", "")).strip()
    future = service._background_executor.submit(
        service.generate_user_profile,
        existing_profile=existing_profile,
        latest_summary=str(latest_summary or "").strip(),
        new_transcript=new_transcript,
        model_id=profile_model,
        profile_prompt_version=profile_prompt_version,
        dry_run=dry_run,
    )
    with service._job_lock:
        service._profile_jobs[key] = {
            "future": future,
            "config": config,
            "consumed": False,
        }
    future.add_done_callback(lambda _: consume_profile_job(service, conv_id, turn_num))
    logger.info("画像后台任务已调度 conv_id=%s turn=%s", conv_id, turn_num)
    set_profile_runtime_state(
        service,
        conv_id,
        config,
        status="pending",
        target_turn=turn_num,
    )


def wait_for_pending_summary(
    service,
    conv_id: str,
    config: dict,
    completed_turns: int,
    timeout_s: float,
) -> None:
    candidates: list[tuple[int, Future]] = []
    with service._job_lock:
        for (job_conv_id, target_turn), job in service._summary_jobs.items():
            if job_conv_id != conv_id or target_turn > completed_turns:
                continue
            if job.get("consumed"):
                continue
            candidates.append((target_turn, job["future"]))
    if not candidates:
        return
    target_turn, future = max(candidates, key=lambda item: item[0])
    start = time.perf_counter()
    try:
        future.result(timeout=timeout_s)
        consume_summary_job(service, conv_id, target_turn)
    except FutureTimeout:
        logger.warning(
            "摘要等待超时，转降级路径 conv_id=%s target_turn=%s timeout=%.1fs",
            conv_id,
            target_turn,
            timeout_s,
        )
        set_summary_runtime_state(
            service,
            conv_id,
            config,
            status="pending-fallback",
            target_turn=target_turn,
        )
    finally:
        elapsed = time.perf_counter() - start
        logger.info(
            "摘要等待结束 conv_id=%s target_turn=%s elapsed=%.2fs",
            conv_id,
            target_turn,
            elapsed,
        )


def wait_for_pending_profile(
    service,
    conv_id: str,
    config: dict,
    completed_turns: int,
    timeout_s: float,
) -> None:
    candidates: list[tuple[int, Future]] = []
    with service._job_lock:
        for (job_conv_id, target_turn), job in service._profile_jobs.items():
            if job_conv_id != conv_id or target_turn > completed_turns:
                continue
            if job.get("consumed"):
                continue
            candidates.append((target_turn, job["future"]))
    if not candidates:
        return
    target_turn, future = max(candidates, key=lambda item: item[0])
    start = time.perf_counter()
    try:
        future.result(timeout=timeout_s)
        consume_profile_job(service, conv_id, target_turn)
    except FutureTimeout:
        logger.warning(
            "画像等待超时，继续沿用旧画像 conv_id=%s target_turn=%s timeout=%.1fs",
            conv_id,
            target_turn,
            timeout_s,
        )
        set_profile_runtime_state(
            service,
            conv_id,
            config,
            status="pending-fallback",
            target_turn=target_turn,
        )
    finally:
        elapsed = time.perf_counter() - start
        logger.info(
            "画像等待结束 conv_id=%s target_turn=%s elapsed=%.2fs",
            conv_id,
            target_turn,
            elapsed,
        )


def await_memory_jobs(
    service,
    conv_id: str,
    config: dict,
    completed_turns: int,
    timeout_s: float,
) -> None:
    wait_for_pending_summary(service, conv_id, config, completed_turns, timeout_s)
    wait_for_pending_profile(service, conv_id, config, completed_turns, timeout_s)
