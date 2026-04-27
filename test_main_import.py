from __future__ import annotations

import importlib
import sys
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent
SERVER_DIR = PROJECT_DIR / "server"


def test_main_can_import_as_package_without_server_dir_on_sys_path():
    original_path = list(sys.path)
    removed_modules = {}
    target_modules = [
        "server.main",
        "database",
        "models",
        "config",
        "routers",
        "services",
    ]

    for name in target_modules:
        if name in sys.modules:
            removed_modules[name] = sys.modules.pop(name)

    if str(SERVER_DIR) in sys.path:
        sys.path.remove(str(SERVER_DIR))
    if str(PROJECT_DIR) not in sys.path:
        sys.path.insert(0, str(PROJECT_DIR))

    try:
        main_module = importlib.import_module("server.main")
        assert main_module.app.title == "长文模式多轮对话验证工具"
        assert str(SERVER_DIR) not in sys.path
    finally:
        sys.modules.pop("server.main", None)
        for name, module in removed_modules.items():
            sys.modules[name] = module
        sys.path[:] = original_path
