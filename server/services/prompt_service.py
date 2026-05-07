"""
PromptService — 提示词模板管理

从 longform_multi_turn.py 抽取的模板加载/渲染/变量注入逻辑。
"""
import re
import textwrap
from pathlib import Path

from config import (
    PROMPT_DIR,
    TEST_PROMPT_DIR,
    VARIABLE_DIR,
    NARRATIVE_VAR_DIR,
    PROJECT_DIR,
    FEW_SHOT_DIR,
    RELATIONSHIP_PRESETS,
)
from services.public_demo import resolve_ephemeral_prompt_path


class PromptService:
    """提示词模板加载、渲染、变量注入"""

    # 搜索路径：脚本目录 → 提示词目录 → 测试提示词目录
    SEARCH_PATHS = [
        PROJECT_DIR,
        PROMPT_DIR,
        TEST_PROMPT_DIR,
    ]

    FEW_SHOT_SOURCE_ROOTS = [
        NARRATIVE_VAR_DIR / "示例——长文模式",
        FEW_SHOT_DIR,
        NARRATIVE_VAR_DIR,
        VARIABLE_DIR,
    ]
    FEW_SHOT_SEARCH_PATHS = [
        *FEW_SHOT_SOURCE_ROOTS,
        PROJECT_DIR,
    ]

    NARRATIVE_STYLE_DOC = VARIABLE_DIR / "长文模式核心变量定义_v2.3.md"
    AGGREGATED_PERSONA_DOC = NARRATIVE_VAR_DIR / "longform_persona.md"
    INTIMACY_BOUNDARY_DOC = NARRATIVE_VAR_DIR / "intimacy_boundary.md"
    DIALOGUE_GUIDELINE_DOC = NARRATIVE_VAR_DIR / "longform_dialogue_guideline.md"
    FEW_SHOT_EXAMPLE_LIMIT = 2
    FEW_SHOT_SCENE_KEYWORDS = {
        "日常场景": (
            "日常", "早餐", "午餐", "晚餐", "便利店", "咖啡店", "公司",
            "办公室", "超市", "厨房", "书店", "花园", "下班", "回家",
        ),
        "亲密场景": (
            "亲密", "深夜", "夜里", "沙发", "阳台", "卧室", "清吧",
            "酒吧", "围巾", "发梢", "等他", "靠近", "并肩",
        ),
        "冲突场景": (
            "冲突", "争执", "吵架", "质问", "冷战", "误会", "停车场",
            "地库", "宴会", "淋雨", "客户", "退了", "失联",
        ),
    }
    FEW_SHOT_VERSION_RE = re.compile(
        r"（精选版）_v(?P<version>\d+)(?:_(?P<date>\d{8}))?\.md$",
        re.IGNORECASE,
    )

    @staticmethod
    def _read_optional_text(path: Path) -> str:
        if not path.exists():
            return ""
        content = path.read_text(encoding="utf-8")
        return content if content.strip() else ""

    @staticmethod
    def _split_markdown_sections(content: str, heading_pattern: str) -> list[tuple[str, str]]:
        if not content:
            return []
        matches = list(re.finditer(heading_pattern, content, flags=re.MULTILINE))
        sections = []
        for index, match in enumerate(matches):
            body_start = match.end()
            body_end = matches[index + 1].start() if index + 1 < len(matches) else len(content)
            sections.append((match.group(1).strip(), content[body_start:body_end].strip()))
        return sections

    @classmethod
    def _extract_persona_block_from_content(
        cls,
        content: str,
        gender: str,
        relationship: str,
        personal_type: str = "",
    ) -> str:
        if not content or not gender or not relationship:
            return ""

        sections = cls._split_markdown_sections(content, r"^##\s+(.+?)\s*$")
        for heading, body in sections:
            if "×" not in heading or gender not in heading:
                continue
            if personal_type and personal_type not in heading:
                continue
            match = re.search(
                rf"^###\s*{re.escape(relationship)}阶段\s*$\s*```yaml\s*(.*?)\s*```",
                body,
                re.DOTALL | re.MULTILINE,
            )
            if match and match.group(1).strip():
                return match.group(1).strip()
        return ""

    @classmethod
    def _extract_narrative_style_from_content(
        cls,
        content: str,
        personal_type: str,
    ) -> str:
        if not content or not personal_type:
            return ""

        sections = cls._split_markdown_sections(content, r"^##+\s+(.+?)\s*$")
        for heading, body in sections:
            if f"{personal_type}型" not in heading:
                continue
            match = re.search(r"```yaml\s*(.*?)\s*```", body, re.DOTALL)
            if match and match.group(1).strip():
                return match.group(1).strip()
        return ""

    @staticmethod
    def _normalize_nested_yaml_block(block: str, root_key: str) -> str:
        if not block:
            return ""
        lines = block.splitlines()
        non_empty = [line for line in lines if line.strip()]
        if non_empty and non_empty[0].strip() == f"{root_key}:":
            nested = "\n".join(lines[1:])
            return textwrap.dedent(nested).strip()
        return block.strip()

    @classmethod
    def _extract_intimacy_boundary_from_content(
        cls,
        content: str,
        relationship: str,
    ) -> str:
        if not content or not relationship:
            return ""

        sections = cls._split_markdown_sections(content, r"^##\s+(.+?)\s*$")
        for heading, body in sections:
            if relationship not in heading:
                continue
            match = re.search(r"```yaml\s*(.*?)\s*```", body, re.DOTALL)
            if match and match.group(1).strip():
                return cls._normalize_nested_yaml_block(
                    match.group(1).strip(),
                    "intimacy_boundary",
                )
        return ""

    @staticmethod
    def render_template(template: str, variables: dict) -> str:
        """将模板中的 {{variable_name}} 替换为 variables 中的值。"""
        def replacer(match):
            key = match.group(1).strip()
            return variables.get(key, match.group(0))  # 未找到保留原样
        return re.sub(r"\{\{(\s*[\w\u4e00-\u9fff]+\s*)\}\}", replacer, template)

    @classmethod
    def render_message_templates(cls, messages: list[dict], variables: dict | None = None) -> list[dict]:
        """对 few-shot 消息逐条执行变量渲染。"""
        normalized_variables = {
            str(key): str(value)
            for key, value in dict(variables or {}).items()
        }
        if not messages or not normalized_variables:
            return list(messages or [])

        rendered_messages: list[dict] = []
        for item in messages:
            rendered = dict(item)
            content = rendered.get("content")
            if isinstance(content, str) and content:
                rendered["content"] = cls.render_template(content, normalized_variables)
            rendered_messages.append(rendered)
        return rendered_messages

    @staticmethod
    def _resolve_path(path_str: str, search_paths: list[Path]) -> Path:
        p = Path(path_str)
        if p.is_absolute():
            return p
        for base in search_paths:
            candidate = base / path_str
            if candidate.exists():
                return candidate
        return p

    @staticmethod
    def _normalize_label(text: str) -> str:
        return re.sub(r"\s+", "", str(text or "")).strip()

    @classmethod
    def _match_personal_type_label(cls, title_label: str, personal_type: str) -> bool:
        if not personal_type:
            return True
        normalized_title = cls._normalize_label(title_label).replace("型", "")
        normalized_target = cls._normalize_label(personal_type).replace("型", "")
        return normalized_target in normalized_title

    @classmethod
    def _match_relationship_label(cls, title_label: str, relationship: str) -> bool:
        if not relationship:
            return True
        normalized_title = cls._normalize_label(title_label).replace("阶段", "")
        normalized_target = cls._normalize_label(relationship).replace("阶段", "")
        return normalized_target in normalized_title

    @classmethod
    def _infer_scene_preferences(cls, current_scene: str) -> list[str]:
        scene = str(current_scene or "").strip()
        if not scene:
            return []
        direct_matches = [
            label for label in cls.FEW_SHOT_SCENE_KEYWORDS.keys()
            if label in scene or label.replace("场景", "") in scene
        ]
        if direct_matches:
            return direct_matches

        scores = []
        for label, keywords in cls.FEW_SHOT_SCENE_KEYWORDS.items():
            score = sum(1 for keyword in keywords if keyword in scene)
            if score > 0:
                scores.append((label, score))
        scores.sort(key=lambda item: item[1], reverse=True)
        return [label for label, _ in scores]

    @classmethod
    def _parse_new_format_few_shot_sections(cls, content: str) -> list[dict]:
        parsed = []
        sections = re.split(r"^## 【(.+?)】\s*$", content, flags=re.MULTILINE)
        for i in range(1, len(sections) - 1, 2):
            title = sections[i].strip()
            body = re.sub(r"\n---\s*$", "", sections[i + 1].strip()).strip()
            if not body:
                continue
            parts = [p.strip() for p in re.split(r"\s*[-－]\s*", title) if p.strip()]
            parsed.append(
                {
                    "title": title,
                    "body": body,
                    "personal_type": parts[0] if len(parts) > 0 else "",
                    "relationship": parts[1] if len(parts) > 1 else "",
                    "scene": parts[2] if len(parts) > 2 else "",
                }
            )
        return parsed

    @staticmethod
    def _extract_dialogue_pair_from_few_shot_body(body: str) -> tuple[str, str]:
        if not body:
            return "", ""
        user_match = re.search(
            r"\[User\]\s*(.*?)(?=\n\s*\[Assistant\]\s*|\Z)",
            body,
            re.DOTALL | re.IGNORECASE,
        )
        assistant_match = re.search(
            r"\[Assistant\]\s*(.*)",
            body,
            re.DOTALL | re.IGNORECASE,
        )
        user_text = user_match.group(1).strip() if user_match else ""
        assistant_text = assistant_match.group(1).strip() if assistant_match else ""
        return user_text, assistant_text

    @classmethod
    def _select_new_format_few_shot_sections(
        cls,
        sections: list[dict],
        relationship: str = "",
        personal_type: str = "",
        current_scene: str = "",
    ) -> list[dict]:
        scoped = list(sections)

        personal_filtered = [
            section for section in scoped
            if cls._match_personal_type_label(section.get("personal_type", ""), personal_type)
        ]
        if personal_filtered:
            scoped = personal_filtered

        relationship_filtered = [
            section for section in scoped
            if cls._match_relationship_label(section.get("relationship", ""), relationship)
        ]
        if relationship_filtered:
            scoped = relationship_filtered

        preferred_scenes = cls._infer_scene_preferences(current_scene)
        if preferred_scenes:
            prioritized = []
            for scene_label in preferred_scenes:
                prioritized.extend(
                    section for section in scoped
                    if scene_label == section.get("scene", "")
                    and section not in prioritized
                )
            prioritized.extend(
                section for section in scoped
                if section not in prioritized
            )
            scoped = prioritized

        return scoped[: cls.FEW_SHOT_EXAMPLE_LIMIT]

    def _resolve_few_shot_file(
        self,
        few_shot_path: str,
        personal_type: str = "",
        gender: str = "",
        relationship: str = "",
    ) -> Path | None:
        resolved, _ = self.resolve_few_shot_reference(
            few_shot_path,
            personal_type=personal_type,
            gender=gender,
            relationship=relationship,
        )
        return resolved

    @classmethod
    def _match_few_shot_candidate(
        cls,
        candidate: Path,
        personal_type: str,
        gender: str,
    ) -> bool:
        name = candidate.name
        if "Few-shot" not in name or personal_type not in name:
            return False
        gender_tokens = ["男性", "男"] if "男" in gender else ["女性", "女"]
        return any(token in name for token in gender_tokens)

    @staticmethod
    def _is_archived_few_shot_candidate(candidate: Path) -> bool:
        return any("归档" in str(part) for part in candidate.parts)

    @classmethod
    def _rank_few_shot_candidate(cls, candidate: Path) -> tuple[int, int, int, str]:
        name = candidate.name
        lowered = name.lower()
        if "backup" in lowered or "备份" in name:
            return 0, 0, 0, name
        version_match = cls.FEW_SHOT_VERSION_RE.search(name)
        if version_match:
            version = int(version_match.group("version"))
            date_value = int(version_match.group("date") or "0")
            return 4, version, date_value, name
        if "（精选版）" in name:
            return 3, 0, 0, name
        return 2, 0, 0, name

    @classmethod
    def _candidate_supports_relationship(
        cls,
        candidate: Path,
        relationship: str,
    ) -> bool:
        normalized_relationship = str(relationship or "").strip()
        if not normalized_relationship:
            return True
        content = cls._read_optional_text(candidate)
        if not content:
            return False
        sections = cls._parse_new_format_few_shot_sections(content)
        if not sections:
            return True
        return any(
            cls._match_relationship_label(
                section.get("relationship", ""),
                normalized_relationship,
            )
            for section in sections
        )

    @classmethod
    def _to_display_path(cls, candidate: Path) -> str:
        for base in [
            NARRATIVE_VAR_DIR,
            VARIABLE_DIR,
        ]:
            try:
                return candidate.relative_to(base).as_posix()
            except ValueError:
                continue
        parts = list(candidate.parts)
        marker = ["长文模式", "变量", "长文模式叙事变量"]
        marker_len = len(marker)
        for index in range(len(parts) - marker_len):
            window = parts[index:index + marker_len]
            if [str(part) for part in window] == marker:
                return Path(*parts[index + marker_len:]).as_posix()
        return candidate.as_posix()

    def _find_preferred_few_shot_file(
        self,
        personal_type: str,
        gender: str,
        relationship: str = "",
    ) -> Path | None:
        if not personal_type or not gender:
            return None
        seen: set[str] = set()
        for roots in (self.FEW_SHOT_SOURCE_ROOTS, [PROJECT_DIR]):
            matches: list[Path] = []
            for base in roots:
                if not base.exists():
                    continue
                for candidate in base.rglob("*Few-shot*.md"):
                    if self._is_archived_few_shot_candidate(candidate):
                        continue
                    key = str(candidate.resolve())
                    if key in seen:
                        continue
                    if self._match_few_shot_candidate(candidate, personal_type, gender):
                        seen.add(key)
                        matches.append(candidate)
            if matches:
                matches.sort(key=self._rank_few_shot_candidate, reverse=True)
                relationship_matches = [
                    candidate
                    for candidate in matches
                    if self._candidate_supports_relationship(candidate, relationship)
                ]
                if relationship_matches:
                    return relationship_matches[0]
                return matches[0]
        return None

    def resolve_few_shot_reference(
        self,
        few_shot_path: str,
        personal_type: str = "",
        gender: str = "",
        relationship: str = "",
    ) -> tuple[Path | None, str]:
        explicit_candidate: Path | None = None
        explicit_path = Path(few_shot_path) if few_shot_path else None
        if few_shot_path:
            resolved = self._resolve_path(few_shot_path, self.FEW_SHOT_SEARCH_PATHS)
            if resolved.exists():
                explicit_candidate = resolved
                if explicit_path and explicit_path.is_absolute():
                    return resolved, self._to_display_path(resolved)
                if "（精选版）" in resolved.name:
                    return resolved, self._to_display_path(resolved)

        preferred = self._find_preferred_few_shot_file(
            personal_type,
            gender,
            relationship=relationship,
        )
        if preferred is not None:
            return preferred, self._to_display_path(preferred)
        if explicit_candidate is not None:
            return explicit_candidate, self._to_display_path(explicit_candidate)
        return None, ""

    def load_prompt_template(self, prompt_path: str) -> str:
        """加载提示词模板文件。"""
        ephemeral_path = resolve_ephemeral_prompt_path(prompt_path)
        if ephemeral_path and ephemeral_path.exists():
            return ephemeral_path.read_text(encoding="utf-8")
        p = self._resolve_path(prompt_path, self.SEARCH_PATHS)
        if not p.exists():
            raise FileNotFoundError(f"提示词文件不存在: {prompt_path}")
        content = p.read_text(encoding="utf-8")
        return content

    @staticmethod
    def extract_system_prompt(template_content: str) -> str:
        """从模板提取 messages[0] system prompt 部分。"""
        marker = "<!-- ======================== 以上为 messages[0]"
        idx = template_content.find(marker)
        if idx > 0:
            return template_content[:idx].strip()
        marker2 = "<!-- ======================== 消息架构拼接说明"
        idx2 = template_content.find(marker2)
        if idx2 > 0:
            return template_content[:idx2].strip()
        return template_content.strip()

    @staticmethod
    def strip_runtime_memory_section(system_prompt: str) -> str:
        """
        从运行时主 system prompt 中剥离记忆上下文段。

        兼容两类模板：
        1. 正式模板中的 `## 记忆上下文` 独立 section
        2. 自定义 prompt 中直接内嵌的三段记忆标题壳

        目标是让真实记忆值和空标题壳都不再进入 messages[0]，
        只保留后续独立 memory_context 的单点注入。
        """
        cleaned = str(system_prompt or "").strip()
        if not cleaned:
            return ""
        cleaned = PromptService._strip_markdown_memory_section(cleaned)
        cleaned = PromptService._strip_inline_memory_shell_block(
            cleaned,
            (
                "【长期记忆用户画像】",
                "【朋友圈记忆】",
                "【历史对话摘要】",
            ),
        )
        cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
        return cleaned.strip()

    @staticmethod
    def _strip_markdown_memory_section(system_prompt: str) -> str:
        lines = system_prompt.splitlines()
        start_idx = next(
            (idx for idx, line in enumerate(lines) if line.strip() == "## 记忆上下文"),
            -1,
        )
        if start_idx < 0:
            return system_prompt

        end_idx = len(lines)
        for idx in range(start_idx + 1, len(lines)):
            stripped = lines[idx].strip()
            if (
                stripped == "---L5 Few-shot 示例注入区---"
                or stripped.startswith("## ")
                or stripped.startswith("# ")
            ):
                end_idx = idx
                break
        return "\n".join([*lines[:start_idx], *lines[end_idx:]])

    @staticmethod
    def _strip_inline_memory_shell_block(
        system_prompt: str,
        labels: tuple[str, str, str],
    ) -> str:
        lines = system_prompt.splitlines()
        kept_lines: list[str] = []
        cursor = 0
        while cursor < len(lines):
            if lines[cursor].strip() != labels[0]:
                kept_lines.append(lines[cursor])
                cursor += 1
                continue

            block_end = PromptService._scan_inline_memory_shell_end(
                lines,
                cursor,
                labels,
            )
            if block_end is None:
                kept_lines.append(lines[cursor])
                cursor += 1
                continue

            cursor = block_end
            while cursor < len(lines) and not lines[cursor].strip():
                cursor += 1

        return "\n".join(kept_lines)

    @staticmethod
    def _scan_inline_memory_shell_end(
        lines: list[str],
        start_idx: int,
        labels: tuple[str, str, str],
    ) -> int | None:
        cursor = start_idx
        for label_index, label in enumerate(labels):
            while cursor < len(lines) and not lines[cursor].strip():
                cursor += 1
            if cursor >= len(lines) or lines[cursor].strip() != label:
                return None
            cursor += 1
            next_label = labels[label_index + 1] if label_index + 1 < len(labels) else None
            while cursor < len(lines):
                stripped = lines[cursor].strip()
                if next_label and stripped == next_label:
                    break
                if PromptService._is_memory_block_boundary(stripped):
                    return cursor if next_label is None else None
                cursor += 1
        return cursor

    @staticmethod
    def _is_memory_block_boundary(line: str) -> bool:
        stripped = str(line or "").strip()
        return (
            stripped == "---L5 Few-shot 示例注入区---"
            or stripped == "---"
            or stripped.startswith("## ")
            or stripped.startswith("# ")
            or stripped.startswith("<!--")
        )

    @staticmethod
    def split_fewshot_from_system(system_prompt: str) -> tuple:
        """
        拆分 system prompt 中的 L5 Few-shot 区域。
        返回: (system_before_fewshot, system_after_fewshot)
        """
        pattern = r"(---L5 Few-shot 示例注入区---.*?\n)(.*?)((?:\n---\n|\n---\s*\n))"
        match = re.search(pattern, system_prompt, re.DOTALL)
        if match:
            before = system_prompt[:match.start()].rstrip()
            after = system_prompt[match.end():].strip()
            return before, after
        return system_prompt, ""

    def load_few_shot_examples(
        self,
        few_shot_path: str,
        relationship: str = "",
        personal_type: str = "",
        gender: str = "",
        current_scene: str = "",
        variables: dict | None = None,
    ) -> list:
        """
        从 few-shot 文件加载示例，返回 [{role, content}, ...] 列表。
        兼容两种格式：
          - 旧格式：### 风格示例 N: + **用户说** / **你的回复**
          - 新格式：## 【类型 - 阶段 - 场景】 + 纯叙事内容
        """
        if not few_shot_path and not (personal_type and gender):
            return []
        p = self._resolve_few_shot_file(
            few_shot_path,
            personal_type=personal_type,
            gender=gender,
            relationship=relationship,
        )
        if not p or not p.exists():
            return []

        content = p.read_text(encoding="utf-8")
        messages = []

        # ── 旧格式：### 风格示例 N: ──
        old_examples = re.split(r"###\s*风格示例\s*\d+[：:]", content)
        for ex in old_examples:
            ex = ex.strip()
            if not ex:
                continue
            user_match = re.search(
                r"\*\*用户说\*\*[：:]\s*(.*?)(?:\n\n\*\*你的回复\*\*[：:]|\Z)",
                ex, re.DOTALL
            )
            reply_match = re.search(
                r"\*\*你的回复\*\*[：:]\s*(.*)", ex, re.DOTALL
            )
            if user_match and reply_match:
                messages.append(
                    {"role": "user", "content": user_match.group(1).strip()}
                )
                messages.append(
                    {"role": "assistant", "content": reply_match.group(1).strip()}
                )
        if messages:
            return self.render_message_templates(
                messages[: self.FEW_SHOT_EXAMPLE_LIMIT * 2],
                variables,
            )

        # ── 中间格式：**[User]**: ... **[Assistant]**: ... ──
        user_blocks = re.split(
            r"\*\*\[User\]\*\*\s*[：:]", content, flags=re.IGNORECASE
        )
        for block in user_blocks[1:]:  # skip preamble
            parts = re.split(
                r"\*\*\[Assistant\]\*\*\s*[：:]", block, maxsplit=1
            )
            if len(parts) == 2:
                user_text = parts[0].strip()
                # assistant 部分到下一个 --- 或文件末尾
                asst_text = re.split(r"\n---\s*$", parts[1], maxsplit=1, flags=re.MULTILINE)[0].strip()
                if user_text and asst_text:
                    messages.append({"role": "user", "content": user_text})
                    messages.append({"role": "assistant", "content": asst_text})
        if messages:
            return self.render_message_templates(
                messages[: self.FEW_SHOT_EXAMPLE_LIMIT * 2],
                variables,
            )

        # ── 新格式：## 【类型 - 阶段 - 场景】 ──
        sections = self._parse_new_format_few_shot_sections(content)
        selected_sections = self._select_new_format_few_shot_sections(
            sections,
            relationship=relationship,
            personal_type=personal_type,
            current_scene=current_scene,
        )
        for section in selected_sections:
            user_text, assistant_text = self._extract_dialogue_pair_from_few_shot_body(
                section.get("body", "")
            )
            if user_text and assistant_text:
                messages.append({"role": "user", "content": user_text})
                messages.append({"role": "assistant", "content": assistant_text})
                continue

            scene = section.get("scene") or section.get("title", "")
            messages.append({"role": "user", "content": f"（{scene}）"})
            messages.append({"role": "assistant", "content": section.get("body", "")})
        return self.render_message_templates(messages, variables)

    def load_persona_block(
        self,
        persona_path: str,
        gender: str,
        relationship: str,
        personal_type: str = "",
    ) -> str:
        """优先从新叙事变量目录读取 persona，失败后回退旧 persona 文件。"""
        if not gender or not relationship:
            return ""

        aggregated_content = self._read_optional_text(self.AGGREGATED_PERSONA_DOC)
        block = self._extract_persona_block_from_content(
            aggregated_content,
            gender,
            relationship,
            personal_type=personal_type,
        )
        if block:
            return block

        if personal_type:
            split_path = NARRATIVE_VAR_DIR / f"longform_persona_{personal_type}.md"
            split_content = self._read_optional_text(split_path)
            block = self._extract_persona_block_from_content(
                split_content,
                gender,
                relationship,
                personal_type=personal_type,
            )
            if block:
                return block

        if not persona_path:
            return ""

        p = self._resolve_path(persona_path, [VARIABLE_DIR, PROJECT_DIR])
        content = self._read_optional_text(p)
        return self._extract_persona_block_from_content(
            content,
            gender,
            relationship,
            personal_type=personal_type,
        )

    def load_narrative_style(self, personal_type: str) -> str:
        """优先从新叙事变量目录读取 narrative_style，失败后回退旧定义文件。"""
        if not personal_type:
            return ""

        standalone = NARRATIVE_VAR_DIR / "longform_narrative_style.md"
        content = self._read_optional_text(standalone)
        block = self._extract_narrative_style_from_content(content, personal_type)
        if block:
            return block

        content = self._read_optional_text(self.NARRATIVE_STYLE_DOC)
        return self._extract_narrative_style_from_content(content, personal_type)

    def load_intimacy_boundary(self, relationship: str) -> str:
        """优先从新叙事变量目录读取 intimacy_boundary，失败后回退硬编码。"""
        if not relationship:
            return ""

        content = self._read_optional_text(self.INTIMACY_BOUNDARY_DOC)
        block = self._extract_intimacy_boundary_from_content(content, relationship)
        if block:
            return block

        rel_info = RELATIONSHIP_PRESETS.get(relationship, {})
        return str(rel_info.get("intimacy_boundary", "")).strip()

    def load_dialogue_guideline(self, personal_type: str) -> str:
        """从 longform_dialogue_guideline.md 按 personal_type 提取对应 YAML 块。"""
        if not personal_type:
            return ""
        content = self._read_optional_text(self.DIALOGUE_GUIDELINE_DOC)
        block = self._extract_narrative_style_from_content(content, personal_type)
        if block:
            return self._normalize_nested_yaml_block(block, "longform_dialogue_guideline")
        return ""

    @staticmethod
    def build_variables(config: dict) -> dict:
        """从 JSON 配置组装所有模板变量。"""
        variables = {}
        # 角色变量
        char = config.get("character", {})
        for key in [
            "Role_Nickname", "gender", "age", "occupation",
            "personality", "speaking_style", "personal_type",
            "Role_info_works",
            "background", "hobby",
        ]:
            variables[key] = str(char.get(key, ""))
        if not variables.get("personal_type"):
            variables["personal_type"] = str(char.get("personality", ""))
        if variables.get("Role_Nickname") and not variables.get("角色名"):
            variables["角色名"] = variables["Role_Nickname"]

        # 上下文变量
        ctx = config.get("context", {})
        for key in [
            "relationship", "currentTime", "weekDay", "timeperiod",
            "season", "intimacy_boundary", "relation_calling",
            "relation_info", "relation_rule4", "system_module11",
            "current_scene", "last_cst_type", "完整时间信息",
        ]:
            variables[key] = str(ctx.get(key, ""))
        if not variables.get("完整时间信息"):
            parts = [
                str(ctx.get("currentTime", "")).strip(),
                str(ctx.get("weekDay", "")).strip(),
                str(ctx.get("timeperiod", "")).strip(),
                str(ctx.get("season", "")).strip(),
            ]
            variables["完整时间信息"] = " / ".join(part for part in parts if part)

        # 系统模块变量
        modules = config.get("modules", {})
        for key in [
            "system_module8", "longform_persona", "longform_narrative_style",
            "longform_dialogue_guideline",
            "system_Role_acting", "weekly_schedule", "dialogueStartPrompt",
            "longform_few_shot", "user_Nickname", "user_gender", "user_identity",
            "moments", "monthly_schedule", "voice_forbidden", "dialogue_summary",
        ]:
            variables[key] = str(modules.get(key, ctx.get(key, char.get(key, ""))))
        custom_vars = {
            str(key): str(value)
            for key, value in dict(config.get("custom_variables", {}) or {}).items()
        }
        if custom_vars:
            variables.update(custom_vars)
        return variables
