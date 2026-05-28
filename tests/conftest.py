from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

import pytest

PROJECT_DIR = Path(__file__).resolve().parents[1]
SERVER_DIR = PROJECT_DIR / "server"

# P1-3 hotfix (cd7f186+2, 2026-05-29): session 级 LONGFORM_DB_PATH 兑底
# 防止未来新增测试忘记 setenv，误连到 server/ops_v6.db / longform.db（生产 hardlink）
_TEST_DB_FALLBACK = PROJECT_DIR / "output" / "test_runtime" / "default_fallback.db"
_TEST_DB_FALLBACK.parent.mkdir(parents=True, exist_ok=True)
os.environ.setdefault("LONGFORM_DB_PATH", str(_TEST_DB_FALLBACK))

for path in (PROJECT_DIR, SERVER_DIR):
    text = str(path)
    if text not in sys.path:
        sys.path.insert(0, text)


@pytest.fixture(autouse=True)
def ensure_main_thread_event_loop():
    policy = asyncio.get_event_loop_policy()
    try:
        loop = policy.get_event_loop()
        if loop.is_closed():
            raise RuntimeError
    except RuntimeError:
        loop = policy.new_event_loop()
        policy.set_event_loop(loop)
    yield
