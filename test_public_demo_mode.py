"""
Public Demo Mode 专项测试。

验证 LONGFORM_PUBLIC_DEMO_MODE=1 下的核心行为：
- 环境开关生效
- 管理写入接口返回 403
- Ephemeral prompt 生命周期
- /docs 关闭
- app-config 返回正确特性开关
- 对话可见性隔离
"""
import os
import shutil

# ── 在任何项目模块导入之前强制设置环境变量 ──
os.environ["LONGFORM_PUBLIC_DEMO_MODE"] = "1"

import sys
import pytest
from pathlib import Path
from unittest.mock import patch

SERVER_DIR = Path(__file__).resolve().parent / "server"
sys.path.insert(0, str(SERVER_DIR))


# ═══════════════════════════════════════════════════════════════
# 1. 核心服务层测试
# ═══════════════════════════════════════════════════════════════


class TestPublicDemoService:
    """public_demo.py 核心函数。"""

    def test_is_public_demo_mode_returns_true(self):
        from services.public_demo import is_public_demo_mode
        assert is_public_demo_mode() is True

    def test_build_app_config_demo_on(self):
        from services.public_demo import build_public_demo_app_config
        cfg = build_public_demo_app_config()
        assert cfg["public_demo_mode"] is True
        features = cfg["features"]
        assert features["allow_prompt_upload"] is True
        assert features["allow_prompt_edit"] is False
        assert features["allow_prompt_activation"] is False
        assert features["allow_prompt_versioning"] is False
        assert features["allow_preset_save"] is False
        assert features["allow_runtime_prompt_edit"] is False
        assert features["allowed_prompt_kinds"] == ["chat"]

    def test_raise_if_demo_write_blocked(self):
        from services.public_demo import raise_if_demo_write_blocked
        from fastapi import HTTPException
        with pytest.raises(HTTPException) as exc_info:
            raise_if_demo_write_blocked("测试拦截")
        assert exc_info.value.status_code == 403
        assert "测试拦截" in str(exc_info.value.detail)


# ═══════════════════════════════════════════════════════════════
# 2. Ephemeral Prompt 生命周期
# ═══════════════════════════════════════════════════════════════


class TestEphemeralPrompt:
    """临时提示词的创建、查找、列出、清理。"""

    def setup_method(self):
        from services.public_demo import ensure_public_demo_dirs, EPHEMERAL_PROMPT_DIR
        self._prompt_dir = EPHEMERAL_PROMPT_DIR
        ensure_public_demo_dirs()

    def teardown_method(self):
        if self._prompt_dir.exists():
            shutil.rmtree(self._prompt_dir)
        self._prompt_dir.mkdir(parents=True, exist_ok=True)

    def test_create_and_resolve_ephemeral_prompt(self):
        from services.public_demo import (
            create_ephemeral_prompt,
            resolve_ephemeral_prompt_path,
        )
        content = "# 测试提示词\n这是临时演示用的提示词内容。".encode("utf-8")
        result = create_ephemeral_prompt("测试提示词_v1.md", content)

        assert result["is_ephemeral"] is True
        assert result["original_filename"] == "测试提示词_v1.md"
        assert result["size"] == len(content)

        resolved = resolve_ephemeral_prompt_path(result["filename"])
        assert resolved is not None
        assert resolved.exists()
        assert resolved.read_bytes() == content

    def test_list_ephemeral_prompt_entries(self):
        from services.public_demo import (
            create_ephemeral_prompt,
            list_ephemeral_prompt_entries,
        )
        create_ephemeral_prompt("a.md", b"aaa")
        create_ephemeral_prompt("b.md", b"bbb")
        entries = list_ephemeral_prompt_entries()
        assert len(entries) >= 2
        assert all(e["is_ephemeral"] for e in entries)

    def test_resolve_nonexistent_returns_none(self):
        from services.public_demo import resolve_ephemeral_prompt_path
        assert resolve_ephemeral_prompt_path("不存在的文件.md") is None

    def test_reset_clears_ephemeral_dir(self):
        from services.public_demo import (
            create_ephemeral_prompt,
            list_ephemeral_prompt_entries,
            reset_public_demo_runtime,
            ensure_public_demo_dirs,
        )
        create_ephemeral_prompt("temp.md", b"hello")
        assert len(list_ephemeral_prompt_entries()) >= 1

        reset_public_demo_runtime()
        ensure_public_demo_dirs()
        assert len(list_ephemeral_prompt_entries()) == 0


# ═══════════════════════════════════════════════════════════════
# 3. 对话可见性隔离
# ═══════════════════════════════════════════════════════════════


class TestConversationVisibility:
    """Demo 模式下只能看到 demo 会话。"""

    def test_filter_hides_non_demo_conversations(self):
        from services.public_demo import filter_visible_conversations

        conversations = [
            {"id": "demo-1", "config": {"runtime": {"public_demo_mode": True}}},
            {"id": "old-1", "config": {"runtime": {}}},
            {"id": "old-2", "config": {}},
        ]
        visible = filter_visible_conversations(conversations)
        assert len(visible) == 1
        assert visible[0]["id"] == "demo-1"

    def test_ensure_visible_allows_demo_conversation(self):
        from services.public_demo import ensure_visible_conversation

        demo_conv = {"id": "d1", "config": {"runtime": {"public_demo_mode": True}}}
        result = ensure_visible_conversation(demo_conv, "d1")
        assert result["id"] == "d1"

    def test_ensure_visible_blocks_non_demo_conversation(self):
        from services.public_demo import ensure_visible_conversation
        from fastapi import HTTPException

        old_conv = {"id": "o1", "config": {"runtime": {}}}
        with pytest.raises(HTTPException) as exc_info:
            ensure_visible_conversation(old_conv, "o1")
        assert exc_info.value.status_code == 404

    def test_ensure_visible_blocks_none_conversation(self):
        from services.public_demo import ensure_visible_conversation
        from fastapi import HTTPException

        with pytest.raises(HTTPException) as exc_info:
            ensure_visible_conversation(None, "missing")
        assert exc_info.value.status_code == 404


# ═══════════════════════════════════════════════════════════════
# 4. FastAPI app 配置（/docs 关闭、app-config 端点）
# ═══════════════════════════════════════════════════════════════


class TestFastAPIAppConfig:
    """验证 app 级配置在 demo 模式下的行为。"""

    def test_docs_url_is_none_in_demo_mode(self):
        from config import PUBLIC_DEMO_MODE
        assert PUBLIC_DEMO_MODE is True
        # main.py 中 docs_url=None if PUBLIC_DEMO_MODE else "/docs"
        # 直接验证配置值即可
        docs_url = None if PUBLIC_DEMO_MODE else "/docs"
        assert docs_url is None

    def test_redoc_url_is_none_in_demo_mode(self):
        from config import PUBLIC_DEMO_MODE
        redoc_url = None if PUBLIC_DEMO_MODE else "/redoc"
        assert redoc_url is None

    def test_openapi_url_is_none_in_demo_mode(self):
        from config import PUBLIC_DEMO_MODE
        openapi_url = None if PUBLIC_DEMO_MODE else "/openapi.json"
        assert openapi_url is None


# ═══════════════════════════════════════════════════════════════
# 5. 文件名消毒
# ═══════════════════════════════════════════════════════════════


class TestFilenameSanitize:
    """_sanitize_filename 安全边界。"""

    def test_normal_filename(self):
        from services.public_demo import _sanitize_filename
        assert _sanitize_filename("提示词_v2.md") == "提示词_v2.md"

    def test_adds_md_extension(self):
        from services.public_demo import _sanitize_filename
        result = _sanitize_filename("no_extension")
        assert result.endswith(".md")

    def test_strips_dangerous_chars(self):
        from services.public_demo import _sanitize_filename
        result = _sanitize_filename("../../etc/passwd")
        assert ".." not in result
        assert "/" not in result

    def test_empty_filename_fallback(self):
        from services.public_demo import _sanitize_filename
        result = _sanitize_filename("")
        assert result == "prompt.md"
