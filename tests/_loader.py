from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


PROJECT_DIR = Path(__file__).resolve().parents[1]


def load_legacy_tests(namespace: dict, filename: str):
    path = PROJECT_DIR / filename
    module_name = f"legacy_{path.stem}"
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"无法加载旧测试文件: {path}")
    module = importlib.util.module_from_spec(spec)
    path_before = list(sys.path)
    try:
        spec.loader.exec_module(module)
    finally:
        sys.path[:] = path_before
    for name, value in vars(module).items():
        if not name.startswith("__"):
            namespace[name] = value
    return module
