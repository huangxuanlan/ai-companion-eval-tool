"""
TokenTrimmer — 8 级渐进 Token 裁剪

PRD v3.0 §4.8: 当 messages 总 token 超出模型上下文窗口时，
按优先级从低到高逐步裁剪。
"""
import tiktoken


class TokenTrimmer:
    """
    8 级渐进裁剪策略。

    级别含义（从 0 到 7，越高裁剪越激进）：
      0: 无裁剪
      1: 移除 background（角色背景细节）
      2: 移除 Few-shot 示例
      3: 压缩早期 conversation_history（保留最近 50%）
      4: 移除 weekly_schedule / system_module8
      5: 压缩 dialogue_summary（仅保留 scene + plot）
      6: 仅保留最近 4 轮历史
      7: 仅保留最近 2 轮历史 + 精简 system prompt
    """

    def __init__(self, context_window: int = 128000, reserve_ratio: float = 0.85):
        """
        Args:
            context_window: 模型上下文窗口大小（tokens）
            reserve_ratio: 安全系数（默认使用 85% 的窗口）
        """
        self.context_window = context_window
        self.max_tokens = int(context_window * reserve_ratio)
        try:
            self._enc = tiktoken.get_encoding("cl100k_base")
        except Exception:
            self._enc = None

    def count_tokens(self, text: str) -> int:
        """估算文本 token 数"""
        if self._enc:
            return len(self._enc.encode(text))
        # 兜底：中文约 1.5 字/token
        return int(len(text) * 0.7)

    def count_messages_tokens(self, messages: list[dict]) -> int:
        """计算 messages 数组的总 token 数"""
        total = 0
        for msg in messages:
            total += self.count_tokens(msg.get("content", ""))
            total += 4  # role + 格式开销
        return total

    def trim_messages(
        self,
        messages: list[dict],
        few_shot_messages: list[dict],
        conversation_history: list[dict],
        dialogue_summary: str,
        memory_profile: str,
        memory_moments: str,
        system_prompt: str,
        system_after: str,
        current_input: str,
        relationship: str,
        role_name: str = "",
        personality: str = "",
        turn_num: int = 1,
        injection_depth: int | str = 2,
        max_output_tokens: int = 4096,
        model_id: str = "",
    ) -> tuple[list[dict], int]:
        """
        对 messages 执行渐进裁剪，直到总 token 落入安全范围。

        Returns:
            (trimmed_messages, trim_level)
        """
        available = self.max_tokens - max_output_tokens

        # Level 0: 先检查是否需要裁剪
        total = self.count_messages_tokens(messages)
        if total <= available:
            return messages, 0

        # Level 1-7: 逐步裁剪并重新构建
        # 这里采用标记裁剪策略，对原始组件逐步削减
        trim_level = 0
        trimmed_few_shot = list(few_shot_messages)
        trimmed_history = list(conversation_history)
        trimmed_summary = dialogue_summary

        for level in range(1, 8):
            trim_level = level

            if level == 1:
                # 移除 background 字段内容（约 200-500 tokens）
                import re
                system_prompt = re.sub(
                    r'\{\{background\}\}.*?(?=\n\{\{|\n---|\'\'\'|$)',
                    '', system_prompt, flags=re.DOTALL
                )
                # 也移除已渲染的 background 长文本段落
                system_prompt = re.sub(
                    r'- 背景[：:].{100,}?(?=\n-|\n\n|$)',
                    '- 背景：（已精简）', system_prompt
                )

            elif level == 2:
                # 移除 Few-shot
                trimmed_few_shot = []

            elif level == 3:
                # 压缩历史：保留最近 50%
                keep = max(4, len(trimmed_history) // 2)
                # 确保保留偶数条（user/assistant 成对）
                keep = keep + (keep % 2)
                trimmed_history = trimmed_history[-keep:]

            elif level == 4:
                # 移除 weekly_schedule 和 system_module8 内容
                import re
                system_prompt = re.sub(
                    r'\{\{weekly_schedule\}\}.*?(?=\n\{\{|\n---|\'\'\'|$)',
                    '', system_prompt, flags=re.DOTALL
                )
                system_prompt = re.sub(
                    r'\{\{system_module8\}\}.*?(?=\n\{\{|\n---|\'\'\'|$)',
                    '', system_prompt, flags=re.DOTALL
                )
                # 移除已渲染的大段日程/模块文本
                for marker in ['日程安排', 'weekly_schedule',
                               'module8', '系统模块8']:
                    system_prompt = re.sub(
                        rf'.*{marker}.*?(?=\n\n|$)',
                        '', system_prompt, flags=re.DOTALL
                    )

            elif level == 5:
                # 精简摘要：只保留场景和剧情
                if trimmed_summary:
                    lines = trimmed_summary.split("\n")
                    keep_lines = [l for l in lines if any(
                        k in l for k in ["场景", "剧情", "==="]
                    )]
                    trimmed_summary = "\n".join(keep_lines) if keep_lines else ""

            elif level == 6:
                # 仅保留最近 4 轮（8 条消息）
                trimmed_history = trimmed_history[-8:]

            elif level == 7:
                # 仅保留最近 2 轮（4 条消息）
                trimmed_history = trimmed_history[-4:]

            # 重新估算
            estimated = (
                self.count_tokens(system_prompt)
                + self.count_tokens(system_after)
                + sum(self.count_tokens(m.get("content", ""))
                      for m in trimmed_few_shot)
                + sum(self.count_tokens(m.get("content", ""))
                      for m in trimmed_history)
                + self.count_tokens(trimmed_summary)
                + self.count_tokens(current_input)
                + 200  # 固定消息开销（分隔符/隔离/Core_Constraints）
            )

            if estimated <= available:
                break

        return self._rebuild_messages(
            system_prompt, system_after, trimmed_few_shot,
            trimmed_history, trimmed_summary, memory_profile, memory_moments, current_input,
            relationship, role_name, personality, turn_num, injection_depth, model_id
        ), trim_level

    @staticmethod
    def _compose_memory_context(
        profile: str,
        moments: str,
        summary: str,
    ) -> str:
        sections: list[str] = []
        if str(profile or "").strip():
            sections.append(f"【长期记忆用户画像】\n{str(profile).strip()}")
        if str(moments or "").strip():
            sections.append(f"【朋友圈记忆】\n{str(moments).strip()}")
        if str(summary or "").strip():
            sections.append(f"【历史对话摘要】\n{str(summary).strip()}")
        return "\n\n".join(sections)

    def _rebuild_messages(
        self,
        system_prompt: str,
        system_after: str,
        few_shot_messages: list,
        history: list,
        summary: str,
        memory_profile: str,
        memory_moments: str,
        current_input: str,
        relationship: str,
        role_name: str,
        personality: str,
        turn_num: int,
        injection_depth: int | str,
        model_id: str = "",
    ) -> list[dict]:
        """根据裁剪后的组件重新构建 messages 数组"""
        from services.message_assembler import MessageAssembler

        assembler = MessageAssembler()
        return assembler.build_messages(
            system_prompt, system_after, few_shot_messages,
            history, summary,
            self._compose_memory_context(memory_profile, memory_moments, summary),
            current_input, relationship,
            role_name=role_name,
            personality=personality,
            turn_num=turn_num,
            injection_depth=injection_depth,
            model_id=model_id,
        )
