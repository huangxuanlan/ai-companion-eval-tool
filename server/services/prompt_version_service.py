"""
版本化提示词管理服务。

为摘要提示词、打分提示词提供：
- 初始化默认版本
- 当前生效版本记录
- 列表 / 读取 / 保存 / 新建版本 / 激活
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from config import (
    COMPARE_REPORT_PROMPT_FILE_RE,
    DEFAULT_COMPARE_REPORT_PROMPT_FILE,
    DEFAULT_SCORING_REPORT_PROMPT_FILE,
    DEFAULT_SUMMARY_PROMPT_FILE,
    PROFILE_PROMPT_DIR,
    PROFILE_PROMPT_FILE_RE,
    PROMPT_DIR,
    SCORING_PROMPT_DIR,
    SCORING_REPORT_PROMPT_FILE_RE,
    SUMMARY_PROMPT_DIR,
    SCORING_PROMPT_FILE_RE,
    SUMMARY_PROMPT_FILE_RE,
    get_latest_prompt_file,
    list_prompt_markdown_files,
    list_prompt_files,
    parse_named_prompt_version,
)

SUMMARY_PROMPT_SEED = """你是一个对话分析助手。请根据以下多轮对话历史，生成结构化的剧情摘要。

## 要求
1. 严格按以下 7 字段 JSON 格式输出，不要输出任何其他文字
2. 每个字段尽量精简（总量控制在 300 tokens 以内）
3. 仅基于实际对话内容提取，不虚构
4. P0 字段必须填写，P1 字段可为空字符串

## 输出格式
{{
    "scene_description": "[P0] 当前场景位置 + 1-2个感官锚点",
    "plot_summary": "[P0] 关键事件因果链（≤3句，用→连接）",
    "pending_hooks": "[P0] 未兑现的承诺/未完成动作/悬念线索",
    "character_emotion": "[P0] 角色当前情绪 + 触发原因",
    "user_emotion": "[P0] 用户当前情绪 + 触发原因",
    "relationship_shift": "[P1] 关系阶段 + 本轮微变化",
    "user_profile_signals": "[P1] 可沉淀的用户行为模式/偏好"
}}

## 角色信息
- 角色名：{role_name}
- 性格类型：{personal_type}
- 当前关系阶段：{relationship}

## 最近对话历史
{conversation_text}

请输出 JSON："""


def _normalize_filename(filename: str) -> str:
    return str(filename or "").strip()


class VersionedPromptStore:
    """管理摘要/打分提示词目录内的版本文件与激活状态。"""

    def __init__(self, *, kind: str):
        self.kind = kind
        if kind == "summary":
            self.dir_path = SUMMARY_PROMPT_DIR
            self.pattern = SUMMARY_PROMPT_FILE_RE
            self.seed_filename = DEFAULT_SUMMARY_PROMPT_FILE
            self.seed_content = SUMMARY_PROMPT_SEED
            self.meta_filename = ".prompt_meta.json"
        elif kind == "scoring":
            self.dir_path = SCORING_PROMPT_DIR
            self.pattern = SCORING_PROMPT_FILE_RE
            self.seed_filename = "长文模式打分提示词_v2.0.md"
            self.seed_content = ""
            self.meta_filename = ".prompt_meta.json"
        elif kind == "scoring_report":
            self.dir_path = SCORING_PROMPT_DIR
            self.pattern = SCORING_REPORT_PROMPT_FILE_RE
            self.seed_filename = DEFAULT_SCORING_REPORT_PROMPT_FILE
            self.seed_content = ""
            self.meta_filename = ".scoring_report_prompt_meta.json"
        elif kind == "compare_report":
            self.dir_path = SCORING_PROMPT_DIR
            self.pattern = COMPARE_REPORT_PROMPT_FILE_RE
            self.seed_filename = DEFAULT_COMPARE_REPORT_PROMPT_FILE
            self.seed_content = ""
            self.meta_filename = ".compare_report_prompt_meta.json"
        elif kind == "profile":
            self.dir_path = PROFILE_PROMPT_DIR
            self.pattern = PROFILE_PROMPT_FILE_RE
            self.seed_filename = "长期记忆画像抽取提示词_统一版_v0.3.md"
            self.seed_content = ""
            self.meta_filename = ".prompt_meta.json"
        else:
            raise ValueError(f"不支持的提示词类型: {kind}")
        self.meta_path = self.dir_path / self.meta_filename

    def ensure_initialized(self) -> None:
        self.dir_path.mkdir(parents=True, exist_ok=True)
        if self.kind == "summary" and not self._list_files():
            (self.dir_path / self.seed_filename).write_text(
                self.seed_content,
                encoding="utf-8",
            )
        if self.kind in {"scoring", "scoring_report", "compare_report"}:
            target = self.dir_path / self.seed_filename
            if not target.exists():
                candidates = self._list_files()
                if candidates:
                    self.seed_filename = candidates[0].name
        active_filename = self.get_active_filename()
        if active_filename:
            self._write_meta({"active_filename": active_filename})

    def _read_meta(self) -> dict:
        if not self.meta_path.exists():
            return {}
        try:
            return json.loads(self.meta_path.read_text(encoding="utf-8"))
        except Exception:
            return {}

    def _write_meta(self, data: dict) -> None:
        self.dir_path.mkdir(parents=True, exist_ok=True)
        self.meta_path.write_text(
            json.dumps(data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def _version_key(self, path: Path) -> tuple:
        parsed = parse_named_prompt_version(path.name, self.pattern)
        if parsed:
            return (1, *parsed, path.name.lower())
        return (0, 0, 0, 0, path.name.lower())

    def _is_version_file(self, path: Path) -> bool:
        return parse_named_prompt_version(path.name, self.pattern) is not None

    def _list_files(self) -> list[Path]:
        if not self.dir_path.exists():
            return []
        files = [
            path
            for path in list_prompt_markdown_files(self.dir_path)
            if self._is_version_file(path)
        ]
        files.sort(key=self._version_key, reverse=True)
        return files

    def _path_for_filename(self, filename: str) -> Path:
        requested = _normalize_filename(filename)
        direct = self.dir_path / requested
        if direct.exists():
            return direct
        for path in self._list_files():
            if path.name == requested:
                return path
        return direct

    def get_active_filename(self) -> str:
        self.ensure_dir_only()
        meta = self._read_meta()
        active_filename = _normalize_filename(meta.get("active_filename", ""))
        if active_filename and self._path_for_filename(active_filename).exists():
            return active_filename
        files = self._list_files()
        return files[0].name if files else ""

    def ensure_dir_only(self) -> None:
        self.dir_path.mkdir(parents=True, exist_ok=True)

    def list_versions(self) -> dict:
        self.ensure_initialized()
        active_filename = self.get_active_filename()
        files = self._list_files()
        prompts = []
        for path in files:
            prompts.append(
                {
                    "filename": path.name,
                    "size": path.stat().st_size,
                    "modified": path.stat().st_mtime,
                    "is_active": path.name == active_filename,
                    "version": self._format_version(path.name),
                }
            )
        return {
            "kind": self.kind,
            "prompts": prompts,
            "active_filename": active_filename,
            "latest_filename": files[0].name if files else "",
        }

    def _format_version(self, filename: str) -> str:
        parsed = parse_named_prompt_version(filename, self.pattern)
        if not parsed:
            return ""
        major, minor, _, _ = parsed
        return f"v{major}.{minor}"

    def resolve_filename(self, filename: str | None = None) -> str:
        self.ensure_initialized()
        requested = _normalize_filename(filename)
        if not requested:
            active = self.get_active_filename()
            if not active:
                raise FileNotFoundError(f"{self.kind} 提示词目录为空")
            return active

        lowered = requested.lower()
        if lowered == "active":
            active = self.get_active_filename()
            if not active:
                raise FileNotFoundError(f"{self.kind} 提示词目录为空")
            return active

        if lowered in {"latest", "auto"}:
            files = self._list_files()
            if not files:
                raise FileNotFoundError(f"{self.kind} 提示词目录为空")
            return files[0].name

        target = self._path_for_filename(requested)
        if not target.exists():
            raise FileNotFoundError(f"{self.kind} 提示词不存在: {requested}")
        return requested

    def read_prompt(self, filename: str | None = None) -> dict:
        resolved = self.resolve_filename(filename)
        path = self._path_for_filename(resolved)
        content = path.read_text(encoding="utf-8")
        return {
            "filename": resolved,
            "content": content,
            "total_lines": content.count("\n") + 1,
            "truncated": False,
            "is_active": resolved == self.get_active_filename(),
            "kind": self.kind,
        }

    def save_prompt(self, filename: str, content: str) -> dict:
        resolved = self.resolve_filename(filename)
        path = self._path_for_filename(resolved)
        path.write_text(content, encoding="utf-8")
        return {
            "message": "保存成功",
            "filename": resolved,
            "size": len(content.encode("utf-8")),
            "kind": self.kind,
        }

    def create_version(
        self,
        *,
        content: str,
        filename: str | None = None,
        activate: bool = True,
    ) -> dict:
        self.ensure_initialized()
        target_name = _normalize_filename(filename) or self._next_version_filename()
        if not target_name.endswith(".md"):
            target_name += ".md"
        target = self.dir_path / target_name
        if target.exists():
            raise FileExistsError(f"版本已存在: {target_name}")
        target.write_text(content, encoding="utf-8")
        if activate:
            self.activate(target_name)
        return {
            "message": "新版本已保存",
            "filename": target_name,
            "active_filename": self.get_active_filename(),
            "kind": self.kind,
        }

    def activate(self, filename: str) -> dict:
        resolved = self.resolve_filename(filename)
        self._write_meta({"active_filename": resolved})
        return {
            "message": "已切换生效版本",
            "filename": resolved,
            "kind": self.kind,
        }

    def download_path(self, filename: str) -> Path:
        resolved = self.resolve_filename(filename)
        return self._path_for_filename(resolved)

    def _next_version_filename(self) -> str:
        files = self._list_files()
        latest_named = next(
            (path for path in files if parse_named_prompt_version(path.name, self.pattern)),
            None,
        )
        if latest_named:
            major, minor, _, _ = parse_named_prompt_version(
                latest_named.name,
                self.pattern,
            )
            return latest_named.name.replace(
                f"v{major}.{minor}",
                f"v{major}.{minor + 1}",
                1,
            )
        timestamp = datetime.now().strftime("%Y%m%d_%H%M")
        prefix_map = {
            "summary": "长文模式摘要提示词",
            "scoring": "长文模式打分提示词",
            "scoring_report": "长文模式评分摘要报告提示词",
            "compare_report": "长文模式对比摘要报告提示词",
            "profile": "长期记忆画像抽取提示词_统一版",
        }
        prefix = prefix_map.get(self.kind, self.kind)
        return f"{prefix}_v1.0_{timestamp}.md"


def list_chat_prompts() -> dict:
    ordered_files = list_prompt_files()
    latest_filename = get_latest_prompt_file() if ordered_files else ""
    prompts = []
    if PROMPT_DIR.exists():
        for path in ordered_files:
            prompts.append(
                {
                    "filename": path.name,
                    "size": path.stat().st_size,
                    "modified": path.stat().st_mtime,
                    "is_main_prompt": True if path.name == latest_filename else False,
                    "is_latest": path.name == latest_filename,
                    "is_active": path.name == latest_filename,
                    "version": "",
                }
            )
    return {
        "kind": "chat",
        "prompts": prompts,
        "latest_filename": latest_filename,
        "active_filename": latest_filename,
    }
