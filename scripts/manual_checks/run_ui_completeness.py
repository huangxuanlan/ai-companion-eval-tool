from __future__ import annotations

import runpy
from pathlib import Path


PROJECT_DIR = Path(__file__).resolve().parents[2]


if __name__ == "__main__":
    runpy.run_path(str(PROJECT_DIR / "run_ui_completeness.py"), run_name="__main__")
