from __future__ import annotations

import json
import logging
import time
import asyncio
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor
from typing import Any

import database as db
from config import DEFAULT_PRIMARY_MODEL, DEFAULT_PRIMARY_MODEL_SHORTFORM
from services.conversation_service import ConversationService
from services.scoring_service import ScoringService, invoke_score_turn_compat
from services.format_lint_core import (
    bridge_history,
    detect_format_leakage,
    calc_ngram_overlap,
    count_cjk_chars,
    count_paren_pairs,
)
from services.conversation_generation import build_memory_context_block
from services.quality_guard import QualityGuard

logger = logging.getLogger(__name__)

# 全局内存跟踪摘要生成状态 (P1-2 hotfix: LRU 限容防长期内存泄漏)
# 容量上限 1000; 超出时淘汰最旧 entry (FIFO 顺序)
_MAX_SUMMARY_TASKS = 1000
_summary_tasks: "OrderedDict[int, str]" = OrderedDict()


def _set_summary_task(switch_id: int, status: str) -> None:
    """LRU 写入 _summary_tasks: 满容量时淘汰最旧 entry.

    P1-2 hotfix (cd7f186+2, 2026-05-29): 原 dict 写入永不清理,
    长期运行可能内存泄漏. 改 OrderedDict 限容 1000 条.
    """
    if switch_id in _summary_tasks:
        _summary_tasks.move_to_end(switch_id)
    _summary_tasks[switch_id] = status
    while len(_summary_tasks) > _MAX_SUMMARY_TASKS:
        _summary_tasks.popitem(last=False)


# 线程池用于异步摘要生成
_summary_executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix="bridge-summary")


def map_api_mode_to_db(mode: str) -> str:
    m = str(mode or "").strip().lower()
    if m in {"shortform", "short"}:
        return "short"
    if m in {"longform", "long"}:
        return "long"
    raise ValueError(f"无效的模式: {mode}")


def map_db_mode_to_api(mode: str) -> str:
    m = str(mode or "").strip().lower()
    if m == "short":
        return "shortform"
    if m == "long":
        return "longform"
    return mode


class BridgeService:
    def __init__(self):
        self.conv_service = ConversationService()
        self.scoring_service = ScoringService()

    def create_bridge_session(
        self,
        from_mode: str,
        to_mode: str,
        source_conversation_id: str,
        target_model: str | None = None,
        bridge_turns: int = 20,
        summary_interval: int = 10,
        scenario_name: str | None = None,
        triggered_by: str = "user_click",
    ) -> dict:
        db_from_mode = map_api_mode_to_db(from_mode)
        db_to_mode = map_api_mode_to_db(to_mode)

        if db_from_mode == db_to_mode:
            raise ValueError("源模式和目标模式不能相同")

        # 默认模型解析 (ADR-004): P0-3 hotfix 从 config 常量取值, 避免与 ADR-004 矩阵分叉
        if not target_model:
            target_model = (
                DEFAULT_PRIMARY_MODEL if db_to_mode == "long"
                else DEFAULT_PRIMARY_MODEL_SHORTFORM
            )

        # 1. 在数据库中创建记录获取 switch_id
        switch_id = db.create_mode_switch(
            from_mode=db_from_mode,
            to_mode=db_to_mode,
            source_conversation_id=source_conversation_id,
            target_model=target_model,
            triggered_by=triggered_by,
            summary_interval=summary_interval,
            bridge_turns_requested=bridge_turns,
        )

        # 2. 异步/同步计算历史桥接元数据并更新
        try:
            results = db.get_turn_results(source_conversation_id)
            history = self.conv_service._build_history_from_results(results)
            bridged_messages, bridge_meta = bridge_history(history, db_to_mode, bridge_turns)

            db.update_mode_switch_meta(
                switch_id=switch_id,
                turns_requested=bridge_turns,
                effective_turns=bridge_meta["bridge_effective_turns"],
                payload_messages=bridge_meta["bridge_messages"],
                hetero_assistant_wrapped=bridge_meta["hetero_assistant_wrapped"],
                source_counts=bridge_meta["source_message_counts"],
                total_available_messages=bridge_meta["bridge_total_available_messages"],
            )
        except Exception as e:
            logger.exception("计算桥接历史元数据失败 switch_id=%s: %s", switch_id, e)

        return {
            "session_id": f"br_{switch_id}",
            "switch_id": switch_id,
            "status": "created",
            "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }

    def get_bridge_session(self, session_id: str) -> dict | None:
        try:
            switch_id = int(session_id.replace("br_", ""))
        except ValueError:
            return None

        row = db.get_mode_switch(switch_id)
        if not row:
            return None

        # 映射 source_counts_json
        source_message_counts = {}
        if row.get("source_counts_json"):
            try:
                raw_counts = json.loads(row["source_counts_json"])
                for k, v in raw_counts.items():
                    source_message_counts[map_db_mode_to_api(k)] = v
            except Exception:
                pass

        # 格式问题解析
        format_issues = []
        if row.get("first_response_format_issues_json"):
            try:
                format_issues = json.loads(row["first_response_format_issues_json"])
            except Exception:
                pass

        # 计算总可用轮数
        total_avail_msgs = row.get("bridge_total_available_messages", 0)

        # 动态判定会话状态
        summary_val = row.get("switch_summary")
        delayed_val = bool(row.get("summary_delayed", 0))
        target_id_val = row.get("target_conversation_id")

        status = "pending_summary"
        if target_id_val:
            status = "completed"
        elif summary_val:
            status = "pending_first_response"
        elif delayed_val:
            status = "delayed"

        return {
            "session_id": session_id,
            "switch_id": switch_id,
            "status": status,
            "basic": {
                "from_mode": map_db_mode_to_api(row["from_mode"]),
                "to_mode": map_db_mode_to_api(row["to_mode"]),
                "source_conversation_id": row["source_conversation_id"],
                "target_conversation_id": row.get("target_conversation_id"),
                "target_model": row["target_model"],
                "triggered_by": row["triggered_by"],
                "created_at": row.get("created_at"),
            },
            "summary": {
                "switch_summary": row.get("switch_summary"),
                "summary_model": row.get("summary_model"),
                "summary_char_count": row.get("summary_char_count", 0),
                "summary_token_count": row.get("summary_token_count", 0),
                "summary_latency_ms": row.get("summary_latency_ms", 0),
                "summary_delayed": bool(row.get("summary_delayed", 0)),
            },
            "bridge_meta": {
                "bridge_turns_requested": row.get("bridge_turns_requested", 20),
                "bridge_effective_turns": row.get("bridge_effective_turns", 0),
                "bridge_payload_messages": row.get("bridge_payload_messages", 0),
                "hetero_assistant_wrapped": row.get("hetero_assistant_wrapped", 0),
                "source_message_counts": source_message_counts,
                "bridge_total_available_messages": total_avail_msgs,
            },
            "first_response": {
                "first_response_cjk_chars": row.get("first_response_cjk_chars", 0),
                "first_response_paren_pairs": row.get("first_response_paren_pairs", 0),
                "first_response_ngram_max_recent_pct": row.get("first_response_ngram_max_recent_pct", 0.0),
                "first_response_format_issues_json": format_issues,
            },
            "verification_result": row.get("verification_result", "fail"),
        }

    def trigger_async_summary(
        self,
        session_id: str,
        summary_model: str = "deepseek-v4-flash",
        delay_until_turn: int = 0,
    ) -> dict:
        try:
            switch_id = int(session_id.replace("br_", ""))
        except ValueError:
            raise ValueError(f"无效的 session_id: {session_id}")

        row = db.get_mode_switch(switch_id)
        if not row:
            raise ValueError(f"切换会话不存在: {switch_id}")

        # 检查是否重复触发
        status = _summary_tasks.get(switch_id, "pending")
        if status in {"generating", "completed"}:
            return {
                "session_id": session_id,
                "summary_status": status,
                "message": "摘要生成任务已经在运行中或已完成",
            }

        # 延迟生成处理 (S14 场景模拟)
        if delay_until_turn > 0:
            db.update_mode_switch_summary(
                switch_id=switch_id,
                summary="",
                summary_model=summary_model,
                char_count=0,
                token_count=0,
                latency_ms=0,
                delayed=True,
            )
            _set_summary_task(switch_id, "delayed")
            return {
                "session_id": session_id,
                "summary_status": "delayed",
                "estimated_latency_s": 0.0,
            }

        _set_summary_task(switch_id, "generating")

        # 派发到线程池执行
        _summary_executor.submit(
            self._generate_summary_worker,
            switch_id=switch_id,
            source_conv_id=row["source_conversation_id"],
            to_mode=row["to_mode"],
            bridge_turns=row["bridge_turns_requested"],
            summary_model=summary_model,
        )

        return {
            "session_id": session_id,
            "summary_status": "generating",
            "estimated_latency_s": 2.5,
        }

    def get_summary_status(self, session_id: str) -> dict:
        try:
            switch_id = int(session_id.replace("br_", ""))
        except ValueError:
            raise ValueError(f"无效的 session_id: {session_id}")

        row = db.get_mode_switch(switch_id)
        if not row:
            raise ValueError(f"切换会话不存在: {switch_id}")

        status = _summary_tasks.get(switch_id, "pending")

        # 如果数据库中已经有摘要，直接更新为 completed
        if row.get("switch_summary"):
            status = "completed"
        elif bool(row.get("summary_delayed", 0)):
            status = "delayed"

        return {
            "session_id": session_id,
            "summary_status": status,
            "switch_summary": row.get("switch_summary"),
            "summary_model": row.get("summary_model"),
            "summary_char_count": row.get("summary_char_count", 0),
            "summary_token_count": row.get("summary_token_count", 0),
            "summary_latency_ms": row.get("summary_latency_ms", 0),
            "summary_delayed": bool(row.get("summary_delayed", 0)),
        }

    def _generate_summary_worker(
        self,
        switch_id: int,
        source_conv_id: str,
        to_mode: str,
        bridge_turns: int,
        summary_model: str,
    ):
        try:
            # 1. 读取源会话历史
            results = db.get_turn_results(source_conv_id)
            history = self.conv_service._build_history_from_results(results)

            # 2. 桥接历史
            bridged_history, _ = bridge_history(history, to_mode, bridge_turns)

            # 3. 读取配置渲染必要角色变量
            source_conv = db.get_conversation(source_conv_id)
            if not source_conv:
                raise ValueError(f"源会话 {source_conv_id} 不存在")
            config = json.loads(source_conv["config_json"])
            char = config.get("character", {})
            ctx = config.get("context", {})
            role_name = char.get("Role_Nickname", "")
            personal_type = char.get("personal_type", "")
            relationship = ctx.get("relationship", "")

            # 4. 生成摘要
            start_time = time.time()
            summary_text = self.conv_service.generate_summary(
                conversation_history=bridged_history,
                role_name=role_name,
                personal_type=personal_type,
                relationship=relationship,
                model_id=summary_model,
            )

            latency_ms = int((time.time() - start_time) * 1000)
            char_count = len(summary_text)
            token_count = int(char_count * 0.75)

            # 5. 写入数据库
            db.update_mode_switch_summary(
                switch_id=switch_id,
                summary=summary_text,
                summary_model=summary_model,
                char_count=char_count,
                token_count=token_count,
                latency_ms=latency_ms,
                delayed=False,
            )

            _set_summary_task(switch_id, "completed")
        except Exception as e:
            logger.exception("异步生成摘要工作线程发生异常 switch_id=%s: %s", switch_id, e)
            db.update_mode_switch_summary(
                switch_id=switch_id,
                summary=f"Error generating summary: {str(e)}",
                summary_model=summary_model,
                char_count=0,
                token_count=0,
                latency_ms=0,
                delayed=False,
            )
            _set_summary_task(switch_id, "failed")

    async def generate_first_response_and_score(
        self,
        session_id: str,
        user_input: str,
        thinking_level: str = "high",
    ) -> dict:
        try:
            switch_id = int(session_id.replace("br_", ""))
        except ValueError:
            raise ValueError(f"无效的 session_id: {session_id}")

        row = db.get_mode_switch(switch_id)
        if not row:
            raise ValueError(f"切换会话不存在: {switch_id}")

        source_conv_id = row["source_conversation_id"]
        to_mode = row["to_mode"]
        target_model = row["target_model"]
        bridge_turns = row["bridge_turns_requested"]

        # 1. 确保目标会话已创建
        target_conversation_id = row.get("target_conversation_id")
        source_conv = db.get_conversation(source_conv_id)
        if not source_conv:
            raise ValueError(f"源会话 {source_conv_id} 不存在")

        config = json.loads(source_conv["config_json"])

        if not target_conversation_id:
            # 创建新会话
            target_conversation_id = self.conv_service.create_conversation(
                model_id=target_model,
                config=config,
                preset_id=source_conv.get("preset_id"),
                model_mini=source_conv.get("model_mini"),
                prompt_version=source_conv.get("prompt_version", ""),
                mode=to_mode,
            )
            db.update_mode_switch_first_response(
                switch_id=switch_id,
                target_conversation_id=target_conversation_id,
                cjk_chars=0,
                paren_pairs=0,
                ngram_max=0.0,
                format_issues=[],
                verification_result="fail",
            )

        # 2. 加载渲染运行束
        runtime_bundle = await asyncio.to_thread(
            self.conv_service._prepare_runtime_bundle,
            config,
        )

        # 3. 准备历史与摘要
        results = db.get_turn_results(source_conv_id)
        history = self.conv_service._build_history_from_results(results)
        bridged_history, _ = bridge_history(history, to_mode, bridge_turns)

        dialogue_summary = row.get("switch_summary") or ""
        summary_source = "bridge" if dialogue_summary else ""

        # 4. 构建上下文块
        memory_context, memory_context_snapshot = build_memory_context_block(
            profile=runtime_bundle.memory_profile,
            moments=runtime_bundle.memory_moments,
            dialogue_summary=dialogue_summary,
            switch_state="",
        )

        if summary_source == "seed" and not runtime_bundle.memory_profile and not runtime_bundle.memory_moments:
            memory_context = ""

        # 5. 构建 messages
        messages = self.conv_service._build_messages_internal(
            rendered_system=runtime_bundle.rendered_system,
            system_after=runtime_bundle.rendered_after,
            few_shot_messages=runtime_bundle.few_shot_messages,
            conversation_history=bridged_history,
            dialogue_summary=dialogue_summary,
            memory_context=memory_context,
            current_input=user_input,
            relationship=runtime_bundle.relationship,
            role_name=runtime_bundle.role_name,
            personality=runtime_bundle.personality,
            turn_num=1,
            model_id=target_model,
        )

        # 6. 模型调用
        # 解析思考层级为 thinking_effort
        thinking_effort = "high" if thinking_level == "high" else "disabled"
        
        result = await asyncio.to_thread(
            self.conv_service.model.chat,
            target_model,
            messages,
            thinking_effort=thinking_effort,
        )

        if not result.success:
            raise RuntimeError(result.error or f"模型 {target_model} 聊天生成失败")

        ai_output = str(result.content or "").strip()

        # 质量清洗 (Quality Guard)
        qa = QualityGuard()
        qa_result = qa.check(ai_output)
        ai_output = qa_result["processed_text"]

        # 7. 计算指标
        cjk_chars = count_cjk_chars(ai_output)
        paren_pairs = count_paren_pairs(ai_output)

        prev_text = ""
        if bridged_history:
            prev_text = bridged_history[-1]["content"]

        ngram_overlap_val = calc_ngram_overlap(prev_text, ai_output)
        ngram_pct = round(ngram_overlap_val * 100, 2)

        format_issues = detect_format_leakage(ai_output, to_mode)

        # 校验通过判定
        if to_mode == "long":
            is_cjk_ok = cjk_chars >= 280
            is_paren_ok = paren_pairs >= 3
        else:
            is_cjk_ok = 30 <= cjk_chars <= 120
            is_paren_ok = paren_pairs < 3

        is_ngram_ok = ngram_pct <= 30.0
        is_format_ok = len(format_issues) == 0

        verification_result = "pass" if (is_cjk_ok and is_paren_ok and is_ngram_ok and is_format_ok) else "fail"

        # 8. 打分 (ADR-004 Default scoring model: qwen3.7-max)
        turn_payload = {
            "turn": 1,
            "user_input": user_input,
            "ai_output": ai_output,
            "role_name": runtime_bundle.role_name,
            "personality": runtime_bundle.personality,
            "relationship": runtime_bundle.relationship,
            "prompt_name": config.get("prompt_file", ""),
            "dialogueStartPrompt": runtime_bundle.memory_profile,
            "moments": runtime_bundle.memory_moments,
            "dialogue_summary": dialogue_summary,
        }

        scoring_result = await invoke_score_turn_compat(
            self.scoring_service,
            turn_payload,
            model_id="qwen3.7-max",
        )

        scores = scoring_result.get("scores", {})
        score_total = scoring_result.get("mapped_total", scores.get("total", 0.0))
        score_reasoning = scoring_result.get("reasoning", "")

        # 9. 写入对话历史表
        turn_data = {
            "turn": 1,
            "user_input": user_input,
            "ai_output": ai_output,
            "word_count": len(ai_output),
            "dialogue_summary": dialogue_summary,
            "msg_count": len(messages),
            "input_tokens": result.input_tokens,
            "output_tokens": result.output_tokens,
            "latency_s": round(result.latency_s, 2),
            "has_deep_injection": any("请记住：你是" in m.get("content", "") for m in messages),
            "has_style_isolation": any("遵循System Prompt" in m.get("content", "") for m in messages),
            "has_cooldown_reinject": False,
            "token_trim_level": 0,
            "quality_retries": 0,
            "messages_snapshot": messages,
            "request_payload_snapshot": {},
            "memory_context_snapshot": memory_context_snapshot,
            "summary_source": summary_source,
            "model_id": target_model,
            "mode": to_mode,
        }
        self.conv_service.insert_turn_result(target_conversation_id, turn_data)

        # 写入评分数据
        scores_data = {
            "persona_fidelity": scores.get("persona_fidelity", 0.0),
            "narrative_immersion": scores.get("narrative_immersion", 0.0),
            "emotional_tension": scores.get("emotional_tension", 0.0),
            "boundary_memory": scores.get("boundary_memory", 0.0),
            "format_compliance": scores.get("format_compliance", 0.0),
            "context_coherence": scores.get("context_coherence", 0.0),
            "mapped_total": score_total,
            "reasoning": score_reasoning,
            "score_status": "scored" if scoring_result.get("success", False) else "failed",
        }
        self.conv_service.update_turn_scores(target_conversation_id, 1, scores_data)

        # 10. 更新 mode_switches 表
        db.update_mode_switch_first_response(
            switch_id=switch_id,
            target_conversation_id=target_conversation_id,
            cjk_chars=cjk_chars,
            paren_pairs=paren_pairs,
            ngram_max=ngram_pct,
            format_issues=format_issues,
            verification_result=verification_result,
        )

        return {
            "session_id": session_id,
            "target_conversation_id": target_conversation_id,
            "ai_output": ai_output,
            "metrics": {
                "first_response_cjk_chars": cjk_chars,
                "first_response_paren_pairs": paren_pairs,
                "first_response_ngram_max_recent_pct": ngram_pct,
                "first_response_format_issues": format_issues,
            },
            "scoring": {
                "score_persona_fidelity": scores_data["persona_fidelity"],
                "score_narrative_immersion": scores_data["narrative_immersion"],
                "score_emotional_tension": scores_data["emotional_tension"],
                "score_boundary_memory": scores_data["boundary_memory"],
                "score_format_compliance": scores_data["format_compliance"],
                "score_context_coherence": scores_data["context_coherence"],
                "score_total": scores_data["mapped_total"],
            },
            "verification_result": verification_result,
        }
