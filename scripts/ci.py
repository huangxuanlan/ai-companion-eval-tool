from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path


PROJECT_DIR = Path(__file__).resolve().parents[1]
LINT_TARGETS = [
    "server/database.py",
    "server/routers/conversations.py",
    "server/services/conversation_generation.py",
    "server/services/conversation_runtime.py",
    "server/services/conversation_service.py",
    "server/services/conversation_store.py",
    "server/services/conversation_summary.py",
    "tests",
    "scripts/ci.py",
]


def _run(cmd: list[str]) -> int:
    print(f"[ci] {' '.join(cmd)}")
    completed = subprocess.run(cmd, cwd=PROJECT_DIR)
    return completed.returncode


def run_smoke() -> int:
    commands = [
        [sys.executable, "-m", "ruff", "check", *LINT_TARGETS],
        [sys.executable, "-m", "pytest", "-q", "tests/smoke"],
    ]
    for cmd in commands:
        code = _run(cmd)
        if code != 0:
            return code
    return 0


def run_full() -> int:
    commands = [
        [sys.executable, "-m", "ruff", "check", *LINT_TARGETS],
        [sys.executable, "-m", "pytest", "-q", "tests"],
    ]
    for cmd in commands:
        code = _run(cmd)
        if code != 0:
            return code
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="长文模式项目统一 CI 入口")
    parser.add_argument("--smoke", action="store_true", help="运行冒烟检查")
    parser.add_argument("--full", action="store_true", help="运行完整检查")
    args = parser.parse_args()

    if args.full:
        return run_full()
    return run_smoke()


if __name__ == "__main__":
    raise SystemExit(main())
