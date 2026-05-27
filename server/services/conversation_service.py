"""
ConversationService — 对话管理核心

从 longform_multi_turn.py 抽取的消息组装、对话状态管理、摘要生成逻辑。
"""
import asyncio
from concurrent.futures import ThreadPoolExecutor
import logging
import threading

from services import (
    conversation_generation,
    conversation_runtime,
    conversation_summary,
    task_control,
)
from services.conversation_store import ConversationStore
from services.message_assembler import (
    CORE_CONSTRAINTS_TEMPLATE,
    DEFAULT_INJECTION_POLICY,
    LONGFORM_WORD_RANGE,
    SEPARATOR_MSG,
    STYLE_ISOLATION_MSG,
    MessageAssembler,
)
from services.prompt_service import PromptService
from services.model_adapter import ModelAdapter
from services.runtime_config import (
    LongformRuntimeConfig,
    RuntimeBundle,
    build_longform_variable_bundle,
)
from services.prompt_version_service import VersionedPromptStore
from services.token_trimmer import TokenTrimmer
from config import (
    DEFAULT_INJECTION_DEPTH,
    DEFAULT_PRIMARY_MODEL,
    MAX_CONCURRENT_CONVERSATIONS,
    PRESET_CHARACTERS,
    RELATIONSHIP_PRESETS,
    SUMMARY_INTERVAL,
    SUMMARY_MODEL,
    extract_preset_module_defaults,
)

SUMMARY_INJECT_TEMPLATE = """=== 之前剧情摘要 ===
- 场景：{scene_description}
- 剧情：{plot_summary}
- 悬念：{pending_hooks}
- 角色情绪：{character_emotion}
- 用户情绪：{user_emotion}
- 关系动态：{relationship_shift}
- 用户画像信号：{user_profile_signals}
=== 摘要结束 ==="""

MEMORY_WAIT_TIMEOUT_S = 5.0
__all__ = [
    "CORE_CONSTRAINTS_TEMPLATE",
    "LONGFORM_WORD_RANGE",
    "SEPARATOR_MSG",
    "STYLE_ISOLATION_MSG",
    "SUMMARY_INJECT_TEMPLATE",
    "MEMORY_WAIT_TIMEOUT_S",
    "ConversationService",
]
logger = logging.getLogger(__name__)

TRANSIENT_GENERATION_ERROR_MARKERS = (
    "connection error",
    "timed out",
    "timeout",
    "temporarily unavailable",
    "server disconnected",
    "connection reset",
    "connection aborted",
    "too many requests",
    "rate limit",
    "429",
    "502",
    "503",
    "504",
)
TURN_TRANSIENT_RETRY_DELAYS_S = (2.0,)


class ConversationService:
    """对话管理：消息组装、历史追踪、摘要生成、对话链执行"""

    def __init__(self, model_adapter: ModelAdapter = None,
                 prompt_service: PromptService = None):
        self.model = model_adapter or ModelAdapter()
        self.prompt = prompt_service or PromptService()
        self.store = ConversationStore()
        self.trimmer = TokenTrimmer()
        self.assembler = MessageAssembler()
        self.summary_prompt_store = VersionedPromptStore(kind="summary")
        self._background_executor = ThreadPoolExecutor(
            max_workers=max(8, MAX_CONCURRENT_CONVERSATIONS),
            thread_name_prefix="longform-bg",
        )
        self._summary_jobs: dict[tuple[str, int], dict] = {}
        self._profile_jobs: dict[tuple[str, int], dict] = {}
        self._job_lock = threading.RLock()

    def create_conversation(
        self,
        *,
        model_id: str,
        config: dict,
        preset_id: str | None = None,
        model_mini: str | None = None,
        prompt_version: str = "",
        mode: str = "long",
    ) -> str:
        return self.store.create_conversation(
            model_id=model_id,
            config=config,
            preset_id=preset_id,
            model_mini=model_mini,
            prompt_version=prompt_version,
            mode=mode,
        )

    def get_conversation(self, conv_id: str) -> dict | None:
        return self.store.get_conversation(conv_id)

    def list_conversations(self, **filters) -> list[dict]:
        return self.store.list_conversations(**filters)

    def update_conversation_status(self, conv_id: str, status: str) -> None:
        self.store.update_conversation_status(conv_id, status)

    def update_conversation_config(self, conv_id: str, config: dict) -> bool:
        return self.store.update_conversation_config(conv_id, config)

    def delete_conversation(self, conv_id: str) -> bool:
        return self.store.delete_conversation(conv_id)

    def set_conversation_pinned(self, conv_id: str, pinned: bool) -> bool:
        return self.store.set_conversation_pinned(conv_id, pinned)

    def set_conversation_archived(self, conv_id: str, archived: bool) -> bool:
        return self.store.set_conversation_archived(conv_id, archived)

    def delete_turn_results(self, conv_id: str) -> int:
        return self.store.delete_turn_results(conv_id)

    def delete_turn_result(self, conv_id: str, turn: int) -> int:
        return self.store.delete_turn_result(conv_id, turn)

    def insert_turn_result(self, conv_id: str, data: dict) -> int:
        return self.store.insert_turn_result(conv_id, data)

    def update_turn_dialogue_summary(
        self,
        conv_id: str,
        turn: int,
        dialogue_summary: str,
    ) -> bool:
        return self.store.update_turn_dialogue_summary(
            conv_id,
            turn,
            dialogue_summary,
        )

    def update_turn_scores(self, conv_id: str, turn: int, scores: dict) -> None:
        self.store.update_turn_scores(conv_id, turn, scores)

    def infer_conversation_channel(self, config: dict | None, prompt_ref: str = "") -> str:
        return self.store.infer_conversation_channel(config, prompt_ref)

    def get_latest_conversation_channel(
        self,
        *,
        role_name: str = "",
        exclude_conv_id: str = "",
    ) -> str:
        return self.store.get_latest_conversation_channel(
            role_name=role_name,
            exclude_conv_id=exclude_conv_id,
        )

    def get_latest_dialogue_summary(
        self,
        *,
        role_name: str = "",
        exclude_conv_id: str = "",
    ) -> str:
        return self.store.get_latest_dialogue_summary(
            role_name=role_name,
            exclude_conv_id=exclude_conv_id,
        )

    @staticmethod
    def _normalize_injection_depth(injection_depth: int | str | None) -> int:
        """兼容旧三档字符串和新数值枚举，统一返回尾部倒数插入位置。"""
        return MessageAssembler.normalize_injection_depth(injection_depth)

    @staticmethod
    def _resolve_injection_policy() -> tuple[int, int]:
        """深度注入的触发节奏由后端运行时策略控制，不再由前端枚举控制。"""
        return DEFAULT_INJECTION_POLICY

    def build_config_from_preset(self, preset_id: str,
                                  relationship: str = None) -> dict:
        """从预设角色 ID 构建完整配置"""
        preset = PRESET_CHARACTERS.get(preset_id)
        if not preset:
            raise ValueError(f"未知预设角色: {preset_id}")

        rel = relationship or preset["default_relationship"]
        gender = preset.get("gender", "")
        personal_type = preset["type"]
        char_defaults = preset.get("character_defaults", {})
        variable_bundle = build_longform_variable_bundle(
            personality=personal_type,
            relationship=rel,
            gender=gender,
            persona_file=preset.get("persona_file", ""),
            few_shot_file=preset.get("few_shot_file", ""),
            preset_characters=PRESET_CHARACTERS,
            relationship_presets=RELATIONSHIP_PRESETS,
            prompt_service=self.prompt,
        )

        return {
            "prompt_file": preset.get("prompt_file", ""),
            "character": {
                "Role_Nickname": preset["name"],
                "gender": gender,
                "personal_type": personal_type,
                "personality": char_defaults.get("personality", personal_type),
                "speaking_style": char_defaults.get("speaking_style", ""),
                "background": char_defaults.get("background", ""),
                "age": char_defaults.get("age", ""),
                "occupation": char_defaults.get("occupation", ""),
                "Role_info_works": char_defaults.get(
                    "Role_info_works",
                    char_defaults.get("role_info_works", char_defaults.get("works", "")),
                ),
                "hobby": char_defaults.get("hobby", ""),
            },
            "context": {
                "relationship": rel,
                "intimacy_boundary": variable_bundle["intimacy_boundary"],
                "relation_calling": variable_bundle["relation_calling"],
                "relation_info": variable_bundle["relation_info"],
            },
            "modules": {
                **extract_preset_module_defaults(preset),
                "longform_persona": variable_bundle["longform_persona"],
                "longform_narrative_style": variable_bundle["longform_narrative_style"],
                "longform_dialogue_guideline": variable_bundle.get("longform_dialogue_guideline", ""),
                "longform_few_shot": variable_bundle["longform_few_shot"],
            },
            "few_shot_file": variable_bundle["longform_few_shot"],
        }

    def _prepare_runtime_bundle(
        self,
        config: dict,
        web_search: bool = False,
    ) -> RuntimeBundle:
        """加载模板、Few-shot 和渲染后的 system prompt，供批量/交互式共用。"""
        runtime_config = LongformRuntimeConfig.from_dict(config, web_search=web_search)
        modules = dict(config.get("modules", {}) or {})
        custom_system_prompt = str(modules.get("system_prompt", "")).strip()
        if custom_system_prompt:
            system_template = custom_system_prompt
        else:
            template_raw = self.prompt.load_prompt_template(runtime_config.prompt_file)
            system_template = self.prompt.extract_system_prompt(template_raw)
        system_template = self.prompt.strip_runtime_memory_section(system_template)
        system_before, system_after = self.prompt.split_fewshot_from_system(
            system_template
        )

        render_config = dict(config)
        render_config["modules"] = runtime_config.modules
        render_config["custom_variables"] = dict(config.get("custom_variables", {}) or {})
        variables = self.prompt.build_variables(render_config)
        few_shot_messages = self.prompt.load_few_shot_examples(
            runtime_config.few_shot_file,
            relationship=runtime_config.relationship,
            personal_type=runtime_config.personal_type,
            gender=runtime_config.gender,
            current_scene=runtime_config.current_scene,
            variables=variables,
        )
        system_variables = dict(variables)
        system_variables["dialogueStartPrompt"] = ""
        system_variables["moments"] = ""
        system_variables["dialogue_summary"] = ""
        rendered_system = self.prompt.render_template(system_before, system_variables)
        rendered_after = (
            self.prompt.render_template(system_after, system_variables)
            if system_after else ""
        )

        return RuntimeBundle(
            few_shot_messages=few_shot_messages,
            rendered_system=rendered_system,
            rendered_after=rendered_after,
            relationship=runtime_config.relationship,
            role_name=runtime_config.role_name,
            personal_type=runtime_config.personal_type,
            personality=runtime_config.personality,
            injection_depth=runtime_config.injection_depth,
            memory_profile=str(variables.get("dialogueStartPrompt", "")).strip(),
            memory_moments=str(variables.get("moments", "")).strip(),
            seed_dialogue_summary=runtime_config.seed_dialogue_summary,
        )

    def _build_request_payload_snapshot(
        self,
        config: dict,
        runtime_bundle: RuntimeBundle,
        messages: list[dict],
        model_id: str,
        memory_context_snapshot: dict | None = None,
        summary_source: str = "",
        web_search: bool = False,
        thinking_enabled: bool | None = None,
        thinking_effort: str = "disabled",
        max_tokens: int | None = None,
        temperature: float | None = None,
        top_p: float | None = None,
    ) -> dict:
        return conversation_generation.build_request_payload_snapshot(
            self,
            config=config,
            runtime_bundle=runtime_bundle,
            messages=messages,
            model_id=model_id,
            memory_context_snapshot=memory_context_snapshot,
            summary_source=summary_source,
            web_search=web_search,
            thinking_enabled=thinking_enabled,
            thinking_effort=thinking_effort,
            max_tokens=max_tokens,
            temperature=temperature,
            top_p=top_p,
        )

    @staticmethod
    def _build_history_from_results(results: list[dict]) -> list[dict]:
        """从已保存轮次恢复真实对话历史。"""
        history = []
        for item in results or []:
            user_input = str(item.get("user_input", "")).strip()
            ai_output = str(item.get("ai_output", "")).strip()
            mode = item.get("mode", "")
            if user_input:
                history.append({"role": "user", "content": user_input, "source_mode": mode})
            if ai_output:
                history.append({"role": "assistant", "content": ai_output, "source_mode": mode})
        return history

    @staticmethod
    def _last_dialogue_summary(results: list[dict]) -> str:
        for item in reversed(results or []):
            summary = str(item.get("dialogue_summary", "")).strip()
            if summary:
                return summary
        return ""

    @staticmethod
    def _last_summary_turn(results: list[dict]) -> int:
        for item in reversed(results or []):
            summary = str(item.get("dialogue_summary", "")).strip()
            if summary:
                return int(item.get("turn", 0) or 0)
        return 0

    @staticmethod
    def _build_memory_context_block(
        profile: str,
        moments: str,
        dialogue_summary: str,
        switch_state: str = "",
    ) -> tuple[str, dict]:
        return conversation_generation.build_memory_context_block(
            profile,
            moments,
            dialogue_summary,
            switch_state,
        )

    def _refresh_runtime_bundle_memory(
        self,
        runtime_bundle: RuntimeBundle,
        config: dict,
    ) -> None:
        conversation_runtime.refresh_runtime_bundle_memory(
            self,
            runtime_bundle,
            config,
        )

    def _ensure_runtime_state(
        self,
        config: dict,
        runtime_bundle: RuntimeBundle,
        results: list[dict],
    ) -> dict:
        return conversation_runtime.ensure_runtime_state(
            self,
            config,
            runtime_bundle,
            results,
        )

    def _resolve_dialogue_summary_for_next_turn(
        self,
        config: dict,
        results: list[dict],
        runtime_bundle: RuntimeBundle,
    ) -> tuple[str, str]:
        return conversation_runtime.resolve_dialogue_summary_for_next_turn(
            self,
            config=config,
            results=results,
            runtime_bundle=runtime_bundle,
        )

    def _persist_runtime_state(self, conv_id: str, config: dict) -> None:
        conversation_runtime.persist_runtime_state(self, conv_id, config)

    def _set_summary_runtime_state(
        self,
        conv_id: str,
        config: dict,
        *,
        status: str,
        target_turn: int,
        latest_dialogue_summary: str | None = None,
        last_summary_turn: int | None = None,
    ) -> None:
        conversation_runtime.set_summary_runtime_state(
            self,
            conv_id,
            config,
            status=status,
            target_turn=target_turn,
            latest_dialogue_summary=latest_dialogue_summary,
            last_summary_turn=last_summary_turn,
        )

    def _set_profile_runtime_state(
        self,
        conv_id: str,
        config: dict,
        *,
        status: str,
        target_turn: int,
        profile_text: str | None = None,
        last_profile_turn: int | None = None,
    ) -> None:
        conversation_runtime.set_profile_runtime_state(
            self,
            conv_id,
            config,
            status=status,
            target_turn=target_turn,
            profile_text=profile_text,
            last_profile_turn=last_profile_turn,
        )

    def _consume_summary_job(self, conv_id: str, target_turn: int) -> str | None:
        return conversation_runtime.consume_summary_job(self, conv_id, target_turn)

    def _consume_profile_job(self, conv_id: str, target_turn: int) -> str | None:
        return conversation_runtime.consume_profile_job(self, conv_id, target_turn)

    def _on_summary_job_done(self, conv_id: str, target_turn: int):
        self._consume_summary_job(conv_id, target_turn)

    def _on_profile_job_done(self, conv_id: str, target_turn: int):
        self._consume_profile_job(conv_id, target_turn)

    def _schedule_summary_job_if_needed(
        self,
        *,
        conv_id: str,
        config: dict,
        runtime_bundle: RuntimeBundle,
        conversation_history: list[dict],
        turn_num: int,
        summary_interval: int,
        model_mini: str,
        summary_prompt_version: str,
        dry_run: bool,
    ) -> None:
        conversation_runtime.schedule_summary_job_if_needed(
            self,
            conv_id=conv_id,
            config=config,
            runtime_bundle=runtime_bundle,
            conversation_history=conversation_history,
            turn_num=turn_num,
            summary_interval=summary_interval,
            model_mini=model_mini,
            summary_prompt_version=summary_prompt_version,
            dry_run=dry_run,
        )

    def schedule_initial_summary_job(
        self,
        *,
        conv_id: str,
        config: dict,
        model_mini: str,
        dry_run: bool = False,
    ) -> None:
        runtime_bundle = self._prepare_runtime_bundle(config)
        summary_prompt_version = str(
            config.get("runtime", {}).get("summary_prompt_version", "")
        ).strip()
        conversation_runtime.schedule_initial_summary_job(
            self,
            conv_id=conv_id,
            config=config,
            runtime_bundle=runtime_bundle,
            model_mini=model_mini,
            summary_prompt_version=summary_prompt_version,
            dry_run=dry_run,
        )

    def _schedule_profile_job_if_needed(
        self,
        *,
        conv_id: str,
        config: dict,
        latest_summary: str,
        results: list[dict],
        turn_num: int,
        model_mini: str,
        dry_run: bool,
    ) -> None:
        conversation_runtime.schedule_profile_job_if_needed(
            self,
            conv_id=conv_id,
            config=config,
            latest_summary=latest_summary,
            results=results,
            turn_num=turn_num,
            model_mini=model_mini,
            dry_run=dry_run,
        )

    def _wait_for_pending_summary(
        self,
        conv_id: str,
        config: dict,
        completed_turns: int,
        timeout_s: float,
    ) -> None:
        conversation_runtime.wait_for_pending_summary(
            self,
            conv_id,
            config,
            completed_turns,
            timeout_s,
        )

    def _wait_for_pending_profile(
        self,
        conv_id: str,
        config: dict,
        completed_turns: int,
        timeout_s: float,
    ) -> None:
        conversation_runtime.wait_for_pending_profile(
            self,
            conv_id,
            config,
            completed_turns,
            timeout_s,
        )

    def _await_memory_jobs(
        self,
        conv_id: str,
        config: dict,
        completed_turns: int,
        timeout_s: float = MEMORY_WAIT_TIMEOUT_S,
    ) -> None:
        conversation_runtime.await_memory_jobs(
            self,
            conv_id,
            config,
            completed_turns,
            timeout_s,
        )

    def _execute_single_turn(
        self,
        runtime_bundle: RuntimeBundle,
        conversation_history: list[dict],
        dialogue_summary: str,
        current_input: str,
        turn_num: int,
        model_id: str,
        summary_source: str = "",
        config: dict | None = None,
        dry_run: bool = False,
        web_search: bool = False,
        thinking_enabled: bool | None = None,
        thinking_effort: str = "disabled",
        temperature: float | None = None,
        top_p: float | None = None,
        switch_state: str = "",
    ) -> dict:
        return conversation_generation.execute_single_turn(
            self,
            runtime_bundle=runtime_bundle,
            conversation_history=conversation_history,
            dialogue_summary=dialogue_summary,
            summary_source=summary_source,
            current_input=current_input,
            turn_num=turn_num,
            model_id=model_id,
            config=config,
            dry_run=dry_run,
            web_search=web_search,
            thinking_enabled=thinking_enabled,
            thinking_effort=thinking_effort,
            temperature=temperature,
            top_p=top_p,
            switch_state=switch_state,
        )

    @staticmethod
    def _is_transient_generation_error(error: Exception) -> bool:
        message = str(error or "").strip().lower()
        if not message:
            return False
        return any(marker in message for marker in TRANSIENT_GENERATION_ERROR_MARKERS)

    async def _execute_turn_with_retry(
        self,
        *,
        runtime_bundle: RuntimeBundle,
        conversation_history: list[dict],
        dialogue_summary: str,
        current_input: str,
        turn_num: int,
        model_id: str,
        summary_source: str = "",
        config: dict | None = None,
        dry_run: bool = False,
        web_search: bool = False,
        thinking_enabled: bool | None = None,
        thinking_effort: str = "disabled",
        temperature: float | None = None,
        top_p: float | None = None,
        switch_state: str = "",
    ) -> dict:
        for attempt, delay_s in enumerate((0.0, *TURN_TRANSIENT_RETRY_DELAYS_S), start=1):
            if delay_s > 0:
                await asyncio.sleep(delay_s)
            try:
                return await asyncio.to_thread(
                    self._execute_single_turn,
                    runtime_bundle,
                    conversation_history,
                    dialogue_summary,
                    current_input,
                    turn_num,
                    model_id,
                    summary_source,
                    config,
                    dry_run,
                    web_search,
                    thinking_enabled,
                    thinking_effort,
                    temperature,
                    top_p,
                    switch_state,
                )
            except Exception as exc:
                is_last_attempt = attempt > len(TURN_TRANSIENT_RETRY_DELAYS_S)
                if dry_run or is_last_attempt or not self._is_transient_generation_error(exc):
                    raise
                logger.warning(
                    "单轮生成出现瞬时错误，准备重试 conv_turn=%s model=%s attempt=%s error=%s",
                    turn_num,
                    model_id,
                    attempt,
                    exc,
                )
        raise RuntimeError("单轮生成重试逻辑异常退出")

    def generate_interactive_turn(
        self,
        conv_id: str,
        conversation: dict,
        user_input: str,
        model_id: str = "",
        model_mini: str = "",
        dry_run: bool = False,
        web_search: bool = False,
        thinking_enabled: bool | None = None,
        thinking_effort: str = "disabled",
        temperature: float | None = None,
        top_p: float | None = None,
    ) -> dict:
        """按当前会话配置生成一轮交互式回复，并落库保存真实消息栈。"""
        config = conversation.get("config", {})
        runtime_bundle = self._prepare_runtime_bundle(config, web_search=web_search)
        results = conversation.get("results", [])
        conversation_history = self._build_history_from_results(results)
        self._ensure_runtime_state(config, runtime_bundle, results)
        summary_interval = max(
            1,
            int(config.get("runtime", {}).get("summary_interval", SUMMARY_INTERVAL)),
        )
        summary_prompt_version = str(
            config.get("runtime", {}).get("summary_prompt_version", "")
        ).strip()
        use_model_id = model_id or conversation.get("model_id", DEFAULT_PRIMARY_MODEL)
        use_model_mini = model_mini or conversation.get("model_mini", SUMMARY_MODEL)
        self._await_memory_jobs(
            conv_id,
            config,
            len(results),
            MEMORY_WAIT_TIMEOUT_S,
        )
        refreshed_conversation = self.get_conversation(conv_id) or {}
        if refreshed_conversation:
            config = refreshed_conversation.get("config", config)
            results = refreshed_conversation.get("results", results)
            conversation_history = self._build_history_from_results(results)
            runtime_bundle = self._prepare_runtime_bundle(config, web_search=web_search)
        else:
            self._refresh_runtime_bundle_memory(runtime_bundle, config)
        dialogue_summary, summary_source = self._resolve_dialogue_summary_for_next_turn(
            config=config,
            results=results,
            runtime_bundle=runtime_bundle,
        )
        turn_num = len(results) + 1
        runtime = config.setdefault("runtime", {})
        switch_state = str(runtime.get("switch_state", "") or "").strip()
        switch_state_status = str(runtime.get("switch_state_status", "") or "").strip().lower()
        active_switch_state = (
            switch_state
            if switch_state and switch_state_status not in {"consumed", "cleared"}
            else ""
        )

        self.update_conversation_status(conv_id, "running")
        turn_data = self._execute_single_turn(
            config=config,
            runtime_bundle=runtime_bundle,
            conversation_history=conversation_history,
            dialogue_summary=dialogue_summary,
            summary_source=summary_source,
            current_input=user_input,
            turn_num=turn_num,
            model_id=use_model_id,
            dry_run=dry_run,
            web_search=web_search,
            thinking_enabled=thinking_enabled,
            thinking_effort=thinking_effort,
            temperature=temperature,
            top_p=top_p,
            switch_state=active_switch_state,
        )
        turn_data["mode"] = conversation.get("mode", "long")
        self.insert_turn_result(conv_id, turn_data)
        if active_switch_state:
            runtime["switch_state"] = ""
            runtime["switch_state_status"] = "consumed"
            runtime["switch_state_consumed_turn"] = turn_num
            self.update_conversation_config(conv_id, config)
        updated_results = [*results, turn_data]
        updated_history = self._build_history_from_results(updated_results)
        self._schedule_summary_job_if_needed(
            conv_id=conv_id,
            config=config,
            runtime_bundle=runtime_bundle,
            conversation_history=updated_history,
            turn_num=turn_num,
            summary_interval=summary_interval,
            model_mini=use_model_mini,
            summary_prompt_version=summary_prompt_version,
            dry_run=dry_run,
        )
        latest_summary = str(
            dict(config.get("runtime", {}) or {}).get("latest_dialogue_summary", "")
            or dialogue_summary
        ).strip()
        self._schedule_profile_job_if_needed(
            conv_id=conv_id,
            config=config,
            latest_summary=latest_summary,
            results=updated_results,
            turn_num=turn_num,
            model_mini=use_model_mini,
            dry_run=dry_run,
        )
        return turn_data

    def _build_messages_internal(
        self,
        rendered_system: str,
        system_after: str,
        few_shot_messages: list,
        conversation_history: list,
        dialogue_summary: str,
        memory_context: str,
        current_input: str,
        relationship: str,
        role_name: str = "",
        personality: str = "",
        turn_num: int = 1,
        injection_depth: int | str = DEFAULT_INJECTION_DEPTH,
        model_id: str = "",
        history_source_mode: str = "",
    ) -> list:
        """兼容旧调用入口，实际拼接逻辑委托给 MessageAssembler。"""
        return self.assembler.build_messages(
            rendered_system=rendered_system,
            system_after=system_after,
            few_shot_messages=few_shot_messages,
            conversation_history=conversation_history,
            dialogue_summary=dialogue_summary,
            memory_context=memory_context,
            current_input=current_input,
            relationship=relationship,
            role_name=role_name,
            personality=personality,
            turn_num=turn_num,
            injection_depth=injection_depth,
            injection_policy=self._resolve_injection_policy(),
            model_id=model_id,
            history_source_mode=history_source_mode,
        )

    def generate_summary(
        self,
        conversation_history: list,
        role_name: str,
        personal_type: str,
        relationship: str,
        model_id: str = SUMMARY_MODEL,
        prompt_version: str = "",
        dry_run: bool = False,
    ) -> str:
        return conversation_summary.generate_summary(
            self,
            conversation_history=conversation_history,
            role_name=role_name,
            personal_type=personal_type,
            relationship=relationship,
            model_id=model_id,
            prompt_version=prompt_version,
            dry_run=dry_run,
            summary_template=SUMMARY_INJECT_TEMPLATE,
        )

    @staticmethod
    def _format_profile_transcript(turn_items: list[dict]) -> str:
        return conversation_summary.format_profile_transcript(turn_items)

    @staticmethod
    def _read_user_profile_prompt_template(profile_prompt_version: str = "") -> str:
        return conversation_summary.read_user_profile_prompt_template(
            profile_prompt_version
        )

    def generate_user_profile(
        self,
        *,
        existing_profile: str,
        latest_summary: str,
        new_transcript: str,
        model_id: str,
        profile_prompt_version: str = "",
        dry_run: bool = False,
    ) -> str:
        return conversation_summary.generate_user_profile(
            self,
            existing_profile=existing_profile,
            latest_summary=latest_summary,
            new_transcript=new_transcript,
            model_id=model_id,
            profile_prompt_version=profile_prompt_version,
            dry_run=dry_run,
        )

    async def run_conversation(
        self,
        conv_id: str,
        config: dict,
        turns: list[str],
        model_id: str = DEFAULT_PRIMARY_MODEL,
        model_mini: str = SUMMARY_MODEL,
        summary_interval: int | None = None,
        dry_run: bool = False,
        on_turn_complete=None,
        on_turn_start=None,
    ) -> list[dict]:
        """
        执行多轮对话链。

        Args:
            conv_id: 对话 ID
            config: 完整配置
            turns: 用户输入列表
            model_id: 主模型 ID
            model_mini: 摘要模型 ID
            summary_interval: 摘要生成间隔轮数
            dry_run: 仅验证消息结构
            on_turn_complete: 每轮完成的回调（用于 WebSocket 推送）
            on_turn_start: 每轮开始前的回调（用于实时进度推送）

        Returns:
            list[TurnResult dict]
        """
        runtime_bundle = await asyncio.to_thread(
            self._prepare_runtime_bundle,
            config,
        )

        conversation = self.get_conversation(conv_id) or {}
        if str(conversation.get("status", "")).strip() != "paused":
            self.update_conversation_status(conv_id, "running")

        use_summary_interval = max(1, int(summary_interval or SUMMARY_INTERVAL))
        summary_prompt_version = str(
            config.get("runtime", {}).get("summary_prompt_version", "")
        ).strip()
        runtime = dict(config.get("runtime", {}) or {})
        runtime_temperature = runtime.get("temperature")
        runtime_top_p = runtime.get("top_p")
        runtime_thinking_enabled = runtime.get("thinking_enabled", None)
        runtime_thinking_effort = str(runtime.get("thinking_effort", "")).strip()
        conversation = self.get_conversation(conv_id) or {}
        existing_results = list(conversation.get("results", []))
        conversation_history = self._build_history_from_results(existing_results)
        self._ensure_runtime_state(config, runtime_bundle, existing_results)
        results = list(existing_results)
        completed_turns = len(existing_results)

        for i, user_input in enumerate(turns, start=1):
            # S1.2: 每轮开始前检查暂停/取消信号
            ctrl = task_control.get(conv_id)
            if ctrl:
                await ctrl.checkpoint()
            turn_num = completed_turns + i
            if on_turn_start:
                await on_turn_start(turn_num, len(turns) + completed_turns, user_input)
            await asyncio.to_thread(
                self._await_memory_jobs,
                conv_id,
                config,
                turn_num - 1,
                MEMORY_WAIT_TIMEOUT_S,
            )
            self._refresh_runtime_bundle_memory(runtime_bundle, config)
            dialogue_summary, summary_source = await asyncio.to_thread(
                self._resolve_dialogue_summary_for_next_turn,
                config,
                results,
                runtime_bundle,
            )
            turn_data = await self._execute_turn_with_retry(
                runtime_bundle=runtime_bundle,
                conversation_history=conversation_history,
                dialogue_summary=dialogue_summary,
                current_input=user_input,
                turn_num=turn_num,
                model_id=model_id,
                summary_source=summary_source,
                config=config,
                dry_run=dry_run,
                web_search=False,
                thinking_enabled=runtime_thinking_enabled,
                thinking_effort=runtime_thinking_effort,
                temperature=runtime_temperature,
                top_p=runtime_top_p,
            )
            ai_output = turn_data["ai_output"]

            # 保存到数据库
            turn_data["mode"] = conversation.get("mode", "long")
            self.insert_turn_result(conv_id, turn_data)
            results.append(turn_data)

            # 回调推送
            if on_turn_complete:
                await on_turn_complete(turn_data)

            # 更新历史
            conversation_history = self._build_history_from_results(results)

            self._schedule_summary_job_if_needed(
                conv_id=conv_id,
                config=config,
                runtime_bundle=runtime_bundle,
                conversation_history=conversation_history,
                turn_num=turn_num,
                summary_interval=use_summary_interval,
                model_mini=model_mini,
                summary_prompt_version=summary_prompt_version,
                dry_run=dry_run,
            )
            latest_summary = str(
                dict(config.get("runtime", {}) or {}).get("latest_dialogue_summary", "")
                or dialogue_summary
            ).strip()
            self._schedule_profile_job_if_needed(
                conv_id=conv_id,
                config=config,
                latest_summary=latest_summary,
                results=results,
                turn_num=turn_num,
                model_mini=model_mini,
                dry_run=dry_run,
            )

        self.update_conversation_status(conv_id, "completed")
        return results
