"""
MessageAssembler — 长文模式消息拼接核心

将易变的消息顺序、Few-shot 注入、风格隔离、深度注入等规则
集中在一个模块中，避免散落在流程型 service 里。
"""
from __future__ import annotations

import os
import re

# PRD v4.0 §3.5 #11: 历史 assistant 消息中的思考标签必须在拼接前剥离
_THINKING_CHANNEL_RE = re.compile(
    r"<\|channel>thought.*?<channel\|>\s*", re.DOTALL
)
_THINK_BLOCK_RE = re.compile(
    r"(?is)<(?:think|thought)>\s*.*?\s*</(?:think|thought)>"
)

# PRD v3.5 §3.4: 对话历史≥3轮后每轮都执行 Depth Injection
DEFAULT_INJECTION_POLICY = (3, 1)

FEW_SHOT_PREFIX_MSG = (
    "【写作风格示例开始】以下一段对话仅用于展示文学写作风格和输出格式。"
    "示例中的场景、地点、道具、事件均为虚构，与当前角色、用户及对话没有任何关联。"
    "你从未经历过这段示例对话，请勿将其中任何细节引入本次叙事。"
    "【风格示例正文如下，请仅参考格式与句式】"
)

SEPARATOR_MSG = (
    "---风格示例结束---\n"
    "【你的任务】从现在开始，完全基于下方的真实角色设定和用户输入来生成回复。"
    "你的回复场景、人物、事件必须来自当前角色设定，而非上方示例。\n"
    "---以下才是真实的对话历史---"
)

# Plan B: Few-shot 作为 system 消息内嵌（消除 Role Signal Override）
_USER_PH = "<<USER_EXAMPLE>>"
_ASST_PH = "<<ASST_EXAMPLE>>"

SYSTEM_EMBEDDED_FEW_SHOT = (
    "【写作风格示例开始】以下示例仅用于展示文学写作风格和输出格式。"
    "示例中的场景、地点、道具、事件均为虚构，与当前角色及对话无关。\n\n"
    f"用户说：{_USER_PH}\n\n"
    f"角色回应：{_ASST_PH}\n\n"
    "【写作风格示例结束】"
)

SYSTEM_EMBEDDED_FEW_SHOT_XML = (
    "<writing_style_example>\n"
    "以下示例仅用于展示文学写作风格和输出格式。"
    "示例中的场景、地点、道具、事件均为虚构，与当前角色及对话无关。\n\n"
    f"<example_user>{_USER_PH}</example_user>\n\n"
    f"<example_assistant>{_ASST_PH}</example_assistant>\n"
    "</writing_style_example>"
)

# S3: 首轮哨兵消息——利用 Recency 位置优势明确告知模型这是首次对话
FIRST_TURN_SENTINEL = (
    "⚠️ 这是你与用户的【第一次对话】。"
    "你们之前从未有过任何交流。"
    "请根据你的角色设定和当前场景，自然地回应用户的第一句话。"
)

STYLE_ISOLATION_MSG = (
    "=== 历史对话记录 ===\n"
    "以下对话仅供参考剧情上下文。你的写作风格和角色表现"
    "必须严格遵循System Prompt定义，而非继承历史回复的风格。"
)

LONGFORM_WORD_RANGE = "300-500字"
LONGFORM_OUTPUT_FORMAT = "旁白用（）包裹，对白为纯文本不带任何标记"

CORE_CONSTRAINTS_TEMPLATE = """<Core_Constraints>
- 长度：""" + LONGFORM_WORD_RANGE + """完整叙事
- 格式：""" + LONGFORM_OUTPUT_FORMAT + """
- 结尾：以带情感张力的引导性钩子收束（动作悬念/情感暗示/反问诱导/开放留白）
- 人设：使用锚点词，保持角色风格
- 去重：每轮切换感官焦点、身体语言区域和核心意象，与上一轮形成变化
- 记忆：仅基于用户画像和当前输入生成内容，不虚构共同回忆，不引用 Few-shot 示例细节
- 关系阶段：{relationship}——肢体接触和情感表达匹配当前阶段
</Core_Constraints>"""

V52_USER_CORE_CONSTRAINTS = (
    "<Core_Constraints>"
    "长度300-500字；旁白用（）包裹；对白为纯文本不带任何标记；结尾保留回话动力；"
    "只继承真实历史和记忆事实，不模仿摘要/Few-shot/异质记录格式。"
    "</Core_Constraints>"
)

V52_SUMMARY_PREFIX = (
    "（以下为角色内部认知记录，仅供上下文参考，请勿模仿此格式；"
    "这不是角色实际回复。）"
)
V52_SUMMARY_START = "=== 动态摘要开始 ==="
V52_SUMMARY_END = "=== 摘要结束 ==="
V52_SUMMARY_SUFFIX = "（内部认知记录结束。以下对话才是真实聊天。）"

SHORTFORM_HISTORY_PREFIX = (
    "❗[以下为短文模式回复记录，仅供剧情事实参考，请勿模仿字数、括号动作、语气格式]"
)
SHORTFORM_HISTORY_SUFFIX = "[短文模式记录结束]"
LONGFORM_HISTORY_PREFIX = (
    "❗[以下为长文模式回复记录，仅供剧情事实参考，请勿模仿第三人称旁白、长段落、加粗对白格式]"
)
LONGFORM_HISTORY_SUFFIX = "[长文模式记录结束]"

_SUMMARY_SECTION_RE = re.compile(
    r"(?:\n\n|^)?【历史对话摘要】\n.*?(?=\n\n【|$)",
    re.DOTALL,
)


def _is_truthy_env(name: str) -> bool:
    return str(os.environ.get(name, "")).strip().lower() in {"1", "true", "yes", "on"}


def _strip_summary_section(memory_context: str) -> str:
    text = str(memory_context or "").strip()
    if not text:
        return ""
    if V52_SUMMARY_START in text or "内部认知记录" in text:
        return ""
    return _SUMMARY_SECTION_RE.sub("", text).strip()


def _format_v52_summary_block(dialogue_summary: str, memory_context: str) -> str:
    raw_summary = str(dialogue_summary or "").strip()
    if not raw_summary:
        context = str(memory_context or "").strip()
        marker = "【历史对话摘要】"
        if marker in context:
            raw_summary = context.split(marker, 1)[1].strip()
        elif V52_SUMMARY_START in context:
            raw_summary = context
    if not raw_summary:
        return ""

    cleaned = raw_summary
    for marker in (V52_SUMMARY_PREFIX, V52_SUMMARY_START, V52_SUMMARY_END, V52_SUMMARY_SUFFIX):
        cleaned = cleaned.replace(marker, "")
    cleaned = cleaned.strip()

    return "\n".join([
        V52_SUMMARY_PREFIX,
        V52_SUMMARY_START,
        cleaned,
        V52_SUMMARY_END,
        V52_SUMMARY_SUFFIX,
    ])


def _target_mode_for_model(model_id: str) -> str:
    """根据模型 ID 隐式推断目标 mode（fallback 路径，优先用显式 mode 参数）

    P0-2 修复（cd7f186+2 hotfix，2026-05-29）：
    - 显式列出 short 系列模型白名单，避免 deepseek-v4-flash 被默认推成 long
    - 命中关键字：doubao* / *-flash / *-mini / *-lite → short
    - 其他默认 → long（保持向后兼容）
    """
    normalized = str(model_id or "").strip().lower()
    if normalized.startswith("qwen") or "qwen3.6-plus" in normalized:
        return "long"
    # P0-2 hotfix: 短文系列模型白名单（flash / mini / lite / doubao）
    if (
        "doubao" in normalized
        or "-flash" in normalized
        or "-mini" in normalized
        or "-lite" in normalized
    ):
        return "short"
    return "long"


def _v52_system_core_for_mode(target_mode: str) -> str:
    if target_mode == "short":
        return (
            "---Core_Constraints 总则---\n"
            "短文模式回复长度40-60字；输出一段自然聊天气泡；可有少量括号动作，但不得继承长文第三人称旁白、长段落、"
            "加粗对白格式；不得输出系统说明、摘要标题、内部记录标题或“以下为...”类模板语。"
        )
    return (
        "---Core_Constraints 总则---\n"
        "长文模式回复长度300-500字；旁白用（）包裹；对白为纯文本不带任何标记；结尾保留回话动力；"
        "不得输出系统说明、摘要标题、内部记录标题或“以下为...”类模板语。"
    )


def _history_source_mode(msg: dict) -> str:
    for key in ("source_mode", "message_mode", "mode", "response_mode", "generation_mode"):
        value = str(msg.get(key, "") or "").strip().lower()
        if value in {"short", "shortform", "short_form", "短文", "短文模式"}:
            return "short"
        if value in {"long", "longform", "long_form", "长文", "长文模式"}:
            return "long"
    return ""


def _wrap_cross_mode_assistant(content: str, source_mode: str, target_mode: str) -> str:
    text = str(content or "").strip()
    if not text:
        return text
    if SHORTFORM_HISTORY_PREFIX in text or LONGFORM_HISTORY_PREFIX in text:
        return text
    if source_mode == "short" and target_mode == "long":
        return f"{SHORTFORM_HISTORY_PREFIX}\n{text}\n{SHORTFORM_HISTORY_SUFFIX}"
    if source_mode == "long" and target_mode == "short":
        return f"{LONGFORM_HISTORY_PREFIX}\n{text}\n{LONGFORM_HISTORY_SUFFIX}"
    return text


class MessageAssembler:
    """按白皮书消息合同组装最终 messages。"""

    @staticmethod
    def normalize_injection_depth(injection_depth: int | str | None) -> int:
        """兼容旧三档字符串和新数值枚举，统一返回尾部倒数插入位置。"""
        legacy_map = {
            "shallow": 2,
            "standard": 4,
            "deep": 5,
        }
        if isinstance(injection_depth, str):
            raw = injection_depth.strip().lower()
            if raw in legacy_map:
                return legacy_map[raw]
            if raw.isdigit():
                injection_depth = int(raw)
            else:
                return 4
        try:
            value = int(injection_depth if injection_depth is not None else 4)
        except (TypeError, ValueError):
            return 4
        return max(2, min(5, value))

    def _inject_few_shot(
        self,
        messages: list[dict],
        full_system: str,
        injected_few_shot: list[dict],
        is_gemma: bool,
        is_qwen: bool,
    ) -> None:
        """将 Few-shot 注入 messages，按模型族选择注入策略。

        策略分支：
          - 千问: 保持 user/assistant 角色注入 + system 合并
          - 其他所有模型（Gemma/MiniMax/Kimi/豆包等）: Plan B system 内嵌
        """
        if is_qwen and injected_few_shot:
            # 千问: 保持原逻辑（user/assistant + system 合并）
            messages.append({"role": "system", "content": full_system + "\n\n" + FEW_SHOT_PREFIX_MSG})
            messages.extend(injected_few_shot)
        elif injected_few_shot:
            # Plan B: 所有非千问模型——Few-shot 作为 system 消息内嵌
            messages.append({"role": "system", "content": full_system})
            user_ex = next((m["content"] for m in injected_few_shot if m["role"] == "user"), "")
            asst_ex = next((m["content"] for m in injected_few_shot if m["role"] == "assistant"), "")
            template = SYSTEM_EMBEDDED_FEW_SHOT_XML if is_gemma else SYSTEM_EMBEDDED_FEW_SHOT
            embedded = template.replace(_USER_PH, user_ex).replace(_ASST_PH, asst_ex)
            messages.append({"role": "system", "content": embedded})
        else:
            messages.append({"role": "system", "content": full_system})

    def _build_messages_v52(
        self,
        rendered_system: str,
        system_after: str,
        few_shot_messages: list[dict],
        conversation_history: list[dict],
        dialogue_summary: str,
        memory_context: str,
        current_input: str,
        relationship: str,
        role_name: str = "",
        personality: str = "",
        model_id: str = "",
        history_source_mode: str = "",
    ) -> list[dict]:
        """实验版 v5.2 消息合同：单 system + assistant 动态摘要 + 原 role 历史。"""
        target_mode = _target_mode_for_model(model_id)
        full_system_parts = [str(rendered_system or "").strip()]
        if system_after:
            full_system_parts.append(str(system_after).strip())

        memory_facts = _strip_summary_section(memory_context)
        if memory_facts and target_mode == "long":
            full_system_parts.append("---记忆上下文---\n" + memory_facts)

        if few_shot_messages and target_mode == "long":
            user_ex = next((m.get("content", "") for m in few_shot_messages if m.get("role") == "user"), "")
            asst_ex = next((m.get("content", "") for m in few_shot_messages if m.get("role") == "assistant"), "")
            if user_ex or asst_ex:
                embedded = SYSTEM_EMBEDDED_FEW_SHOT.replace(_USER_PH, user_ex).replace(_ASST_PH, asst_ex)
                full_system_parts.append(
                    "---Few-shot 风格示例隔离规则---\n"
                    "以下 few-shot 仅用于展示长文写作风格和输出格式。示例中的人物、场景、地点、道具、事件均为虚构，"
                    "与你、当前用户和真实对话无关。你从未经历过示例内容，禁止引用、继承或改写其中任何具体细节。\n\n"
                    + embedded
                )

        if target_mode == "long":
            full_system_parts.append(
                "---风格隔离声明---\n"
                "真实回复必须来自当前角色设定、用户输入、动态摘要和真实历史。"
                "历史中的短文记录、长文记录、摘要记录、内心戏记录、唱歌/告白/求婚记录只可提取剧情事实，"
                "禁止模仿其格式、字数、标题、语气或叙事人称。"
            )
            full_system_parts.append(
                "---Depth 角色锚定规则---\n"
                f"每轮生成前默认记住：你是{role_name}，性格{personality}，当前关系阶段为{relationship}。"
                "该规则为身份锚定，不作为额外 system 消息插入历史。"
            )
            full_system_parts.append(_v52_system_core_for_mode(target_mode))

        messages: list[dict] = [{
            "role": "system",
            "content": "\n\n".join(part for part in full_system_parts if part),
        }]

        summary_block = _format_v52_summary_block(dialogue_summary, memory_context)
        if summary_block:
            messages.append({"role": "assistant", "content": summary_block})

        for msg in conversation_history:
            role = msg.get("role")
            content = str(msg.get("content", "") or "")
            if role == "assistant":
                content = _THINKING_CHANNEL_RE.sub("", content)
                content = _THINK_BLOCK_RE.sub("", content).strip()
                content = _wrap_cross_mode_assistant(
                    content,
                    _history_source_mode(msg) or str(history_source_mode or "").strip().lower(),
                    target_mode,
                )
            messages.append({"role": role, "content": content})

        current_user_content = (
            f"{V52_USER_CORE_CONSTRAINTS}\n\n<user_input>{current_input}</user_input>"
            if target_mode == "long"
            else str(current_input or "")
        )
        messages.append({"role": "user", "content": current_user_content})
        return messages

    def build_messages(
        self,
        rendered_system: str,
        system_after: str,
        few_shot_messages: list[dict],
        conversation_history: list[dict],
        dialogue_summary: str,
        memory_context: str,
        current_input: str,
        relationship: str,
        role_name: str = "",
        personality: str = "",
        turn_num: int = 1,
        injection_depth: int | str = 4,
        injection_policy: tuple[int, int] = DEFAULT_INJECTION_POLICY,
        model_id: str = "",
        history_source_mode: str = "",
    ) -> list[dict]:
        """
        按白皮书 v1.7 §4.1 消息架构组装完整 messages 数组。

        Gemma 模型适配（研报 §5.2/§6.2）：
          - Style Isolation / Depth Injection / Core Constraints
            使用 XML 闭合标签包裹，提升 Gemma 4 的指令遵循度。
          - 非 Gemma 模型保持原有 Markdown/纯文本格式。

        消息架构——Plan B 模型（Gemma/MiniMax/Kimi/豆包等，非首轮）：
          [0]   system  → L0-L4 核心 system prompt
          [1]   system  → Few-shot 内嵌（system 消息，非 user/assistant）
          [2]   system  → 风格隔离声明 + memory_context
          [2+]  user/assistant → 历史对话轮次
          [N-1] system  → Core_Constraints 重申
          [N]   user    → 当前用户输入

        消息架构——千问模型（非首轮，保持原 user/assistant 注入）：
          [0]   system  → 主 system + FEW_SHOT_PREFIX（合并）
          [1-4] user/assistant → Few-shot 示例
          [5]   system  → SEPARATOR + STYLE_ISOLATION + memory（合并）
          [5+]  user/assistant → 历史对话轮次
          [N-1] system  → Core_Constraints 重申
          [N]   user    → 当前用户输入

        首轮分支（turn_num <= 1 且 conversation_history 为空时）：
          保留 Few-shot 层，插入首次对话哨兵。
        """
        if _is_truthy_env("LONGFORM_V52_MESSAGE_CONTRACT"):
            try:
                effective_turn_num = int(turn_num or 1)
            except (TypeError, ValueError):
                effective_turn_num = 1
            injected_few_shot: list[dict] = few_shot_messages or []
            return self._build_messages_v52(
                rendered_system=rendered_system,
                system_after=system_after,
                few_shot_messages=injected_few_shot,
                conversation_history=conversation_history,
                dialogue_summary=dialogue_summary,
                memory_context=memory_context,
                current_input=current_input,
                relationship=relationship,
                role_name=role_name,
                personality=personality,
                model_id=model_id,
                history_source_mode=history_source_mode,
            )

        from services.model_adapter import ModelAdapter

        is_gemma = ModelAdapter.is_gemma_model(model_id)
        is_qwen = str(model_id or "").lower().startswith("qwen")
        messages: list[dict] = []

        full_system = rendered_system
        if system_after:
            full_system = rendered_system + "\n\n" + system_after

        # S1: Few-shot 注入策略
        # - 首轮也注入 Few-shot，首轮真实性由 FIRST_TURN_SENTINEL 和隔离声明兜住
        # - 千问仍保持 user/assistant 示例注入，其它模型使用 system 内嵌
        is_first_turn = not conversation_history
        injected_few_shot: list[dict] = few_shot_messages or []

        # 两路 Few-shot 注入（千问保持原逻辑 / 其他全部 Plan B system 内嵌）
        self._inject_few_shot(
            messages, full_system, injected_few_shot,
            is_gemma, is_qwen,
        )

        effective_memory_context = str(memory_context or "").strip() or str(dialogue_summary or "").strip()

        # S3: 首轮插入"首次对话"哨兵消息，利用 Recency 位置优势
        if is_first_turn:
            messages.append({"role": "system", "content": FIRST_TURN_SENTINEL})

        # C4: Gemma / 千问 合并 STYLE_ISOLATION + memory_context 为单条 system
        if conversation_history or effective_memory_context or (is_qwen and injected_few_shot):
            style_content = (
                f"<context_boundary>\n{STYLE_ISOLATION_MSG}\n</context_boundary>"
                if is_gemma
                else STYLE_ISOLATION_MSG
            )
            if is_gemma:
                # Gemma: 合并为单条，减少连续 system→user 映射
                merged_parts = [style_content]
                if effective_memory_context:
                    merged_parts.append(effective_memory_context)
                messages.append({"role": "system", "content": "\n\n".join(merged_parts)})
            elif is_qwen:
                # 千问: SEPARATOR + STYLE_ISOLATION + memory 合并为单条
                qwen_mid_parts = []
                if injected_few_shot:
                    qwen_mid_parts.append(SEPARATOR_MSG)
                qwen_mid_parts.append(style_content)
                if effective_memory_context:
                    qwen_mid_parts.append(effective_memory_context)
                messages.append({"role": "system", "content": "\n\n".join(qwen_mid_parts)})
            else:
                # 其他模型: 保持分离
                messages.append({"role": "system", "content": style_content})
                if effective_memory_context:
                    messages.append({"role": "system", "content": effective_memory_context})

        # C5: 对历史 assistant 消息做 thinking strip（PRD v4.0 §3.5 #11）
        cleaned_history: list[dict] = []
        for msg in conversation_history:
            if msg.get("role") == "assistant":
                content = msg.get("content", "")
                content = _THINKING_CHANNEL_RE.sub("", content)
                content = _THINK_BLOCK_RE.sub("", content).strip()
                cleaned_history.append({"role": msg["role"], "content": content})
            else:
                cleaned_history.append(msg)
        history_with_injection = list(cleaned_history)
        completed_turns = max(0, int(turn_num or 1) - 1)
        min_turns, interval = injection_policy
        injection_offset = self.normalize_injection_depth(injection_depth)
        if completed_turns >= min_turns and (completed_turns - min_turns) % interval == 0:
            inject_pos = max(0, len(history_with_injection) - injection_offset)
            # A3: Gemma 模型 Depth Injection 用 XML 包裹（§6.2 混合注意力 1024 窗口）
            raw_inject = (
                f"请记住：你是{role_name}，性格{personality}。"
                f"当前关系：{relationship}。"
                f"输出{LONGFORM_WORD_RANGE}，{LONGFORM_OUTPUT_FORMAT}，以引导性钩子结尾。"
            )
            inject_content = (
                f"<system_reminder>\n{raw_inject}\n</system_reminder>"
                if is_gemma
                else raw_inject
            )
            depth_inject_msg = {"role": "system", "content": inject_content}
            history_with_injection.insert(inject_pos, depth_inject_msg)
        messages.extend(history_with_injection)

        # A2: Gemma 模型用 <rules> 包裹 Core Constraints（§5.2 XML 遵循度最高）
        core_text = CORE_CONSTRAINTS_TEMPLATE.format(relationship=relationship)
        if is_gemma:
            core_text = f"<rules>\n{core_text}\n</rules>"
        messages.append({"role": "system", "content": core_text})

        messages.append({
            "role": "user",
            "content": f"<user_input>{current_input}</user_input>",
        })
        return messages

