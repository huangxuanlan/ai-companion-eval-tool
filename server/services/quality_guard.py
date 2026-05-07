"""
QualityGuard — 质量保障流水线

PRD v5.1 §4.9: 每轮 AI 输出后执行自动检查与后处理。
"""
import re


class QualityGuard:
    """
    AI 输出质量守卫。

    检查项（按优先级）：
      1. 字数 <300 → 需要重试
      2. 字数 >500 → 按段落边界截断至 450 字
      3. 格式归一到 v4.9：旁白（）包裹 + 对白纯文本
      4. Emoji → 移除
      5. 推理过程前缀 → 剥离
    """

    MIN_WORDS = 300
    MAX_WORDS = 500
    TARGET_WORDS = 450
    MAX_RETRIES = 2
    # v4.9: 旁白用（）包裹
    NARRATION_PAREN_PATTERN = re.compile(r'（[^）\n]{4,}）')
    # 旧版对白格式（用于剥离）
    OLD_DIALOGUE_PATTERN = re.compile(r'\*\*"[^"\n]+?"\*\*')
    # 旧版对白行匹配（用于剥离星号和引号）
    OLD_DIALOGUE_LINE_PATTERN = re.compile(
        r'^(?P<lead>\s*)(?:\*\*)?(?:["“”「])(?:\*\*)?(?P<body>.+?)(?:\*\*)?(?:["“”」])(?:\*\*)?(?P<trail>\s*)$'
    )
    OLD_DANGLING_DIALOGUE_LINE_PATTERN = re.compile(
        r'^(?P<lead>\s*)(?:\*\*)?(?:["“”「])(?:\*\*)?(?P<body>.+?)(?P<trail>\s*)$'
    )
    OLD_WRAPPED_NARRATION_PATTERN = re.compile(
        r"(?m)^(?P<lead>\s*)\*(?!\*)(?P<body>[^*\n].*?[^*\n])\*(?P<trail>\s*)$"
    )
    SOFT_BREAK_PATTERN = re.compile(
        r'\n\s*\n+|\n|[。！？!?；;](?:["”」』】])?'
    )

    # 思考通道标记（PRD §3.5 #11 / §6.1）
    THINKING_CHANNEL_PATTERN = re.compile(
        r"<\|channel>thought.*?<channel\|>\s*",
        re.DOTALL,
    )

    # 模型幻觉的伪 XML / JSON 标签前缀（如 `"dialogue">"..."`、`dialogue: "..."`、
    # `<dialogue>"..."</dialogue>`）。
    # 仅匹配段/行首的 dialogue|narration 伪标记，避免误伤正文中的普通文本。
    PSEUDO_XML_TAG_PATTERN = re.compile(
        r"<\s*/?\s*(?:dialogue|narration)\s*>",
        re.IGNORECASE,
    )
    # 覆盖行首伪前缀的真实变体，保留正文部分继续走对白/旁白归一。
    # 例：`"dialogue">"..."`、`dialogue: ...`、`<narration>: ...`
    PSEUDO_XML_PREFIX_PATTERN = re.compile(
        r'(?m)^(?P<lead>[\s\u3000]*)(?:[\u0022\u201C\u201D\uFF02「]\s*)?(?:<\s*)?'
        r'(?P<tag>dialogue|narration)\s*(?:[\u0022\u201C\u201D\uFF02」]\s*)?'
        r'[>:\uFF1E\uFF1A]\s*(?P<body>.*)$',
        re.IGNORECASE,
    )

    # 推理过程前缀模式
    REASONING_PREFIXES = re.compile(
        r"^(让我思考|好的，|嗯，让我|我来|我需要|首先，我|"
        r"OK,|Okay,|Let me|Sure,|Alright).*?\n",
        re.MULTILINE,
    )

    # Emoji 正则（覆盖常见 Unicode Emoji 区段）
    EMOJI_PATTERN = re.compile(
        "["
        "\U0001F600-\U0001F64F"  # 表情
        "\U0001F300-\U0001F5FF"  # 符号与象形
        "\U0001F680-\U0001F6FF"  # 交通
        "\U0001F1E0-\U0001F1FF"  # 国旗
        "\U00002702-\U000027B0"  # Dingbats
        "\U0000FE00-\U0000FE0F"  # 变体选择器
        "\U0001F900-\U0001F9FF"  # 补充表情
        "\U0001FA00-\U0001FA6F"  # 棋牌符号
        "\U0001FA70-\U0001FAFF"  # 扩展A
        "\U00002600-\U000026FF"  # 杂项符号
        "\U0000200D"             # ZWJ
        "\U00002B50"             # ⭐
        "]+",
        re.UNICODE,
    )

    # 颜文字模式
    KAOMOJI_PATTERN = re.compile(
        r"[（(][>＞<＜≧≦╥╬○●◎◇◆□■△▽☆★♡♥ﾟ゜·.。°˘ω"
        r"ᴗ◕‿⁰ₒ̥̈́̌̀ˊˋ´`^~_＿ーT皿Д∀з人ノ丿"
        r"つっ∇∠∩≡∝≈♪♫♬✧✦✿❀❁❃❋✾✽✼]{2,}[)）]"
    )

    def check(self, text: str) -> dict:
        """
        检查 AI 输出质量，返回检查结果。

        Returns:
            {
                "needs_retry": bool,
                "retry_reason": str,
                "processed_text": str,  # 后处理修复后的文本
                "fixes_applied": list[str],
            }
        """
        fixes = []
        processed = text

        # 0. 剥离思考通道标记（PRD §3.5 #11）
        cleaned = self.THINKING_CHANNEL_PATTERN.sub("", processed)
        if cleaned != processed:
            processed = cleaned.lstrip()
            fixes.append("剥离思考通道标记")

        # 0.5 剥离模型幻觉的伪 XML 标签与行首伪标记（"dialogue">"..." 等）
        cleaned = self.PSEUDO_XML_TAG_PATTERN.sub("", processed)
        if cleaned != processed:
            processed = cleaned
            fixes.append("剥离伪XML标签")
        cleaned, pseudo_prefix_changed = self._strip_pseudo_xml_line_prefixes(processed)
        if pseudo_prefix_changed:
            processed = cleaned.lstrip()
            fixes.append("剥离伪XML行首标记")

        # 1. 剥离推理过程前缀
        cleaned = self.REASONING_PREFIXES.sub("", processed)
        if cleaned != processed:
            processed = cleaned.lstrip()
            fixes.append("剥离推理过程前缀")

        # 2. 移除 Emoji
        cleaned = self.EMOJI_PATTERN.sub("", processed)
        if cleaned != processed:
            processed = cleaned
            fixes.append("移除Emoji")

        # 3. 移除颜文字
        cleaned = self.KAOMOJI_PATTERN.sub("", processed)
        if cleaned != processed:
            processed = cleaned
            fixes.append("移除颜文字")

        # 4. 字数检查
        word_count = len(processed)
        if word_count < self.MIN_WORDS:
            return {
                "needs_retry": True,
                "retry_reason": f"输出过短({word_count}字<{self.MIN_WORDS}字)",
                "processed_text": processed,
                "fixes_applied": fixes,
            }

        # 5. 字数过长 → 截断
        if word_count > self.MAX_WORDS:
            processed = self._truncate_by_paragraph(
                processed, self.TARGET_WORDS
            )
            fixes.append(
                f"字数截断({word_count}→{len(processed)}字)"
            )

        # 6. 格式补全 / 格式重试
        processed, fmt_fixes, format_retry_reason = self._fix_format(processed)
        fixes.extend(fmt_fixes)
        if format_retry_reason:
            return {
                "needs_retry": True,
                "retry_reason": format_retry_reason,
                "processed_text": processed,
                "fixes_applied": fixes,
            }

        return {
            "needs_retry": False,
            "retry_reason": "",
            "processed_text": processed,
            "fixes_applied": fixes,
        }

    def get_retry_prompt(self, reason: str) -> str:
        """生成重试时追加的系统消息。"""
        return (
            f"上次输出不符合要求（{reason}），"
            '请严格按要求重新生成300-500字完整叙事，旁白用（）包裹，对白为纯文本不带任何标记。'
        )

    @classmethod
    def _truncate_by_paragraph(cls, text: str, target: int) -> str:
        """
        优先按自然断点截断到目标字数附近。

        历史实现只按双换行截断；当模型输出只有单换行时会完全失效，
        导致 >500 字的真实输出原样漏过。这里改为：
        1. 优先找 [300, target] 内的双换行 / 单换行 / 句末标点断点
        2. 其次找 [300, 500] 内的自然断点
        3. 最差兜底硬截到 500 字
        """
        if len(text) <= cls.MAX_WORDS:
            return text.rstrip()

        candidates = sorted(
            {
                match.end()
                for match in cls.SOFT_BREAK_PATTERN.finditer(text)
                if match.end() <= cls.MAX_WORDS
            }
        )

        preferred = [
            idx for idx in candidates if cls.MIN_WORDS <= idx <= target
        ]
        if preferred:
            return text[: preferred[-1]].rstrip()

        acceptable = [
            idx for idx in candidates if cls.MIN_WORDS <= idx <= cls.MAX_WORDS
        ]
        if acceptable:
            return text[: acceptable[-1]].rstrip()

        return text[: cls.MAX_WORDS].rstrip()

    @staticmethod
    def _normalize_dialogue_body(body: str) -> str:
        candidate = body.strip()
        changed = True
        while candidate and changed:
            changed = False
            if candidate.startswith("**"):
                candidate = candidate[2:].strip()
                changed = True
            if candidate.endswith("**"):
                candidate = candidate[:-2].strip()
                changed = True
            if candidate[:1] in {'"', "“", "「"}:
                candidate = candidate[1:].strip()
                changed = True
            if candidate[-1:] in {'"', "”", "」"}:
                candidate = candidate[:-1].strip()
                changed = True
        return candidate

    @classmethod
    def _strip_pseudo_xml_line_prefixes(cls, text: str) -> tuple[str, bool]:
        changed = False

        def repl(match: re.Match[str]) -> str:
            nonlocal changed
            changed = True
            lead = match.group("lead") or ""
            body = (match.group("body") or "").lstrip()
            return f"{lead}{body}"

        return cls.PSEUDO_XML_PREFIX_PATTERN.sub(repl, text), changed

    @staticmethod
    def _strip_old_dialogue_marks(text: str) -> tuple[str, bool]:
        """v4.9: 剥离旧版 **""** 对白标记，转为纯文本。"""
        changed = False
        normalized_lines = []
        for line in text.splitlines():
            match = QualityGuard.OLD_DIALOGUE_LINE_PATTERN.match(line)
            if not match:
                match = QualityGuard.OLD_DANGLING_DIALOGUE_LINE_PATTERN.match(line)
                if not match:
                    normalized_lines.append(line)
                    continue
            body = QualityGuard._normalize_dialogue_body(match.group("body"))
            if not body:
                normalized_lines.append(line)
                continue
            # v4.9: 对白为纯文本，去掉所有标记
            normalized_line = (
                f'{match.group("lead")}{body}{match.group("trail")}'
            )
            if normalized_line != line:
                changed = True
            normalized_lines.append(normalized_line)
        return "\n".join(normalized_lines), changed

    @staticmethod
    def _fix_format(text: str) -> tuple[str, list[str], str]:
        """检查并修复旁白/对白格式（v4.9：旁白（）+ 对白纯文本）。"""
        fixes = []
        processed = text.strip()
        retry_reason = ""

        # 1. 剥离旧版 **""** 对白标记 → 纯文本
        normalized, dialogue_changed = QualityGuard._strip_old_dialogue_marks(processed)
        if dialogue_changed:
            processed = normalized
            fixes.append('剥离旧版 **""** 对白标记→纯文本')

        # 2. 旧版 *旁白* 转换为 v4.9 的（旁白）
        normalized = QualityGuard.OLD_WRAPPED_NARRATION_PATTERN.sub(
            r"\g<lead>（\g<body>）\g<trail>", processed
        )
        if normalized != processed:
            processed = normalized
            fixes.append("旧版*旁白*转换为（）旁白")

        # 3. v4.9 格式检查：确认包含（旁白）格式
        if not QualityGuard.NARRATION_PAREN_PATTERN.search(processed):
            retry_reason = '格式错误(缺少（旁白）括号包裹)'
            fixes.append('格式重试:缺少（）旁白包裹')

        return processed, fixes, retry_reason
