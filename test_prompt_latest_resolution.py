"""
最新提示词自动加载回归测试。
"""
from __future__ import annotations

import asyncio
import importlib
import sys
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent
SERVER_DIR = PROJECT_DIR / "server"

if str(SERVER_DIR) not in sys.path:
    sys.path.insert(0, str(SERVER_DIR))

from config import (  # noqa: E402
    DEFAULT_SUMMARY_MODEL,
    build_prompt_alias_map,
    get_latest_prompt_file,
    is_main_prompt_file,
    list_main_prompt_files,
    parse_main_prompt_version,
)


def _import_router(module_name: str):
    """延迟导入路由模块，避免在测试收集阶段污染 sys.path 顺序。"""
    module = importlib.import_module(module_name)
    server_dir = str(SERVER_DIR)
    if server_dir in sys.path:
        sys.path.remove(server_dir)
    sys.path.insert(0, server_dir)
    return module


def test_parse_main_prompt_version_and_ignore_non_prompt_docs(tmp_path: Path):
    (tmp_path / "星朋友长文模式_提示词_v2.0.md").write_text("v2.0", encoding="utf-8")
    (tmp_path / "星朋友长文模式_提示词_v2.2_20260324_1808.md").write_text("v2.2", encoding="utf-8")
    (tmp_path / "星朋友长文模式_提示词_v2.3_20260324.md").write_text("v2.3", encoding="utf-8")
    (tmp_path / "长文模式提示词_迭代路径_V1.0-V2.0.md").write_text("doc", encoding="utf-8")
    archive_dir = tmp_path / "长文模式提示词归档"
    archive_dir.mkdir()
    (archive_dir / "星朋友长文模式_提示词_v9.9_20260324.md").write_text("archive", encoding="utf-8")

    assert parse_main_prompt_version("星朋友长文模式_提示词_v2.3_20260324.md") == (2, 3, 20260324, 0)
    assert not is_main_prompt_file("长文模式提示词_迭代路径_V1.0-V2.0.md")

    ordered = [path.name for path in list_main_prompt_files(tmp_path)]
    assert ordered == [
        "星朋友长文模式_提示词_v2.3_20260324.md",
        "星朋友长文模式_提示词_v2.2_20260324_1808.md",
        "星朋友长文模式_提示词_v2.0.md",
    ]
    assert get_latest_prompt_file(tmp_path, fallback="fallback.md") == "星朋友长文模式_提示词_v2.3_20260324.md"


def test_prompt_alias_map_prefers_latest_same_short_version(tmp_path: Path):
    (tmp_path / "星朋友长文模式_提示词_v2.3_20260323.md").write_text("older", encoding="utf-8")
    (tmp_path / "星朋友长文模式_提示词_v2.3_20260324.md").write_text("latest", encoding="utf-8")
    (tmp_path / "星朋友长文模式_提示词_v2.0.md").write_text("v2.0", encoding="utf-8")

    alias_map = build_prompt_alias_map(tmp_path)
    assert alias_map["v2.3"] == "星朋友长文模式_提示词_v2.3_20260324.md"
    assert alias_map["v2.0"] == "星朋友长文模式_提示词_v2.0.md"


def test_build_runtime_config_defaults_to_latest_when_unspecified(monkeypatch):
    conversations_router = _import_router("routers.conversations")
    latest = "星朋友长文模式_提示词_v2.3_20260324.md"
    monkeypatch.setattr(conversations_router, "get_latest_prompt_file", lambda: latest)

    config = {"character": {}, "context": {}, "modules": {}}
    prompt_name, model_mini = conversations_router._build_runtime_config(
        config=config,
        model_id="doubao-pro",
        model_mini="",
        prompt_version=None,
        summary_interval=5,
        injection_depth=2,
    )

    assert config["prompt_file"] == latest
    assert prompt_name == latest
    assert model_mini == DEFAULT_SUMMARY_MODEL


def test_build_runtime_config_forces_latest_versioned_prompts_when_unspecified(monkeypatch):
    conversations_router = _import_router("routers.conversations")

    latest_calls = []

    class _StubStore:
        def __init__(self, *, kind: str):
            self.kind = kind

        def resolve_filename(self, filename):
            latest_calls.append((self.kind, filename))
            return f"{self.kind}-latest.md"

    monkeypatch.setattr(conversations_router, "VersionedPromptStore", _StubStore)
    monkeypatch.setattr(conversations_router, "get_latest_prompt_file", lambda: "星朋友长文模式_提示词_v9.9.md")

    config = {"character": {}, "context": {}, "modules": {}}
    conversations_router._build_runtime_config(
        config=config,
        model_id="doubao-pro",
        model_mini="",
        prompt_version="",
        summary_prompt_version="",
        scoring_prompt_version="",
        profile_prompt_version="",
        summary_interval=5,
        injection_depth=2,
    )

    assert latest_calls == [
        ("summary", "latest"),
        ("scoring", "latest"),
        ("profile", "latest"),
    ]
    assert config["runtime"]["summary_prompt_version"] == "summary-latest.md"
    assert config["runtime"]["scoring_prompt_version"] == "scoring-latest.md"
    assert config["runtime"]["profile_prompt_version"] == "profile-latest.md"


def test_build_runtime_config_preserves_existing_prompt_when_unspecified(monkeypatch):
    conversations_router = _import_router("routers.conversations")
    monkeypatch.setattr(
        conversations_router,
        "get_latest_prompt_file",
        lambda: "星朋友长文模式_提示词_v2.3_20260324.md",
    )

    config = {"prompt_file": "星朋友长文模式_提示词_v2.0.md"}
    prompt_name, _ = conversations_router._build_runtime_config(
        config=config,
        model_id="doubao-pro",
        model_mini="doubao-mini",
        prompt_version="",
        summary_interval=5,
        injection_depth=2,
    )

    assert config["prompt_file"] == "星朋友长文模式_提示词_v2.0.md"
    assert prompt_name == "星朋友长文模式_提示词_v2.0.md"


def test_resolve_requested_prompt_supports_latest_auto_and_short_alias():
    conversations_router = _import_router("routers.conversations")
    latest = get_latest_prompt_file()
    assert conversations_router._resolve_requested_prompt("latest") == latest
    assert conversations_router._resolve_requested_prompt("auto") == latest
    assert conversations_router._resolve_requested_prompt("v2.0") == "星朋友长文模式_提示词_v2.0.md"
    assert conversations_router._resolve_requested_prompt("v2.3") == "星朋友长文模式_提示词_v2.3_20260324.md"


def test_prompt_list_api_exposes_latest_metadata():
    prompts_router = _import_router("routers.prompts")
    payload = asyncio.run(prompts_router.list_prompts())
    latest = get_latest_prompt_file()

    assert payload["latest_filename"] == latest
    assert payload["prompts"], "提示词列表不应为空"

    latest_rows = [item for item in payload["prompts"] if item.get("is_latest")]
    assert len(latest_rows) == 1
    assert latest_rows[0]["filename"] == latest
    assert latest_rows[0]["is_main_prompt"] is True


def test_frontend_no_longer_hardcodes_v20_as_latest():
    html = (SERVER_DIR / "static" / "index.html").read_text(encoding="utf-8")
    js = (SERVER_DIR / "static" / "js" / "legacy_bundle.js").read_text(encoding="utf-8")

    assert 'v2.0（最新）' not in html
    assert html.count('自动加载最新提示词（服务器判定）') >= 4
    assert "|| 'v2.0'" not in js
    assert "p.is_latest" in js
    assert "sel.value = currentValue || '';" in js
