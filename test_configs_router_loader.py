from __future__ import annotations

import sys
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent
SERVER_DIR = PROJECT_DIR / "server"

if str(SERVER_DIR) not in sys.path:
    sys.path.insert(0, str(SERVER_DIR))

from routers import configs as configs_router  # noqa: E402


def _clear_longform_multi_turn_cache():
    sys.modules.pop(configs_router._LONGFORM_MULTI_TURN_MODULE_NAME, None)


def test_load_configs_from_excel_without_sys_path_pollution(
    tmp_path: Path,
    monkeypatch,
):
    (tmp_path / "longform_multi_turn.py").write_text(
        """
def load_config_from_excel(file_path: str):
    return [{"loaded_from": file_path, "ok": True}]
""".strip(),
        encoding="utf-8",
    )

    _clear_longform_multi_turn_cache()
    monkeypatch.setattr(configs_router, "PROJECT_DIR", tmp_path)
    path_before = list(sys.path)

    try:
        result = configs_router._load_configs_from_excel("demo.xlsx")
        assert result == [{"loaded_from": "demo.xlsx", "ok": True}]
        assert sys.path == path_before
    finally:
        _clear_longform_multi_turn_cache()
