from __future__ import annotations

import os
from pathlib import Path

# 兼容保留：默认 pytest 入口已收敛到 tests/ 目录。
# 手工脚本迁入 scripts/manual_checks/ 后，不再通过 collect_ignore 排除。
collect_ignore = []

PROJECT_DIR = Path(__file__).resolve().parent
TEST_DB_DIR = PROJECT_DIR / "output" / "test_runtime"
TEST_DB_DIR.mkdir(parents=True, exist_ok=True)

# 任何测试模块在 import 时如果先触发 database/config 加载，
# 默认也只能落到测试库，避免误连到 server/longform.db。
os.environ.setdefault("LONGFORM_DB_PATH", str(TEST_DB_DIR / "pytest_session.db"))
