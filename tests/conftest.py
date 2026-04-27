from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest

PROJECT_DIR = Path(__file__).resolve().parents[1]
SERVER_DIR = PROJECT_DIR / "server"

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
