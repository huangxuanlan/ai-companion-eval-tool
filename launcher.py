from __future__ import annotations

import hashlib
import os
import subprocess
import sys
import time
import webbrowser
from pathlib import Path
from threading import Thread


PROJECT_DIR = Path(__file__).resolve().parent
RUNTIME_DIR = PROJECT_DIR / ".runtime"
VENV_DIR = RUNTIME_DIR / "venv"
REQUIREMENTS_FILE = PROJECT_DIR / "server" / "requirements.txt"
STAMP_FILE = RUNTIME_DIR / "requirements.sha256"


def _venv_python() -> Path:
    if os.name == "nt":
        return VENV_DIR / "Scripts" / "python.exe"
    return VENV_DIR / "bin" / "python"


def _hash_file(path: Path) -> str:
    digest = hashlib.sha256()
    digest.update(path.read_bytes())
    return digest.hexdigest()


def _in_virtualenv() -> bool:
    return sys.prefix != getattr(sys, "base_prefix", sys.prefix)


def _ensure_bundle_env() -> None:
    bundle_dir = PROJECT_DIR / "bundle_assets"
    if not bundle_dir.exists():
        return
    os.environ.setdefault("LONGFORM_BUNDLE_DIR", str(bundle_dir))
    os.environ.setdefault("LONGFORM_TOOLCHAIN_ROOT", str(bundle_dir))
    os.environ.setdefault("LONGFORM_CONTENT_ROOT", str(bundle_dir / "长文模式"))
    os.environ.setdefault(
        "LONGFORM_PROVIDER_LLM_DIR",
        str(bundle_dir / "prompt-validator-llm"),
    )
    os.environ.setdefault(
        "LONGFORM_SCORING_PIPELINE_DIR",
        str(bundle_dir / "promptfoo-pipeline" / "scoring_prompts" / "长文模式"),
    )
    os.environ.setdefault(
        "LONGFORM_PIPELINE_SCRIPTS_DIR",
        str(bundle_dir / "promptfoo-pipeline" / "scripts"),
    )


def _ensure_venv() -> None:
    if _venv_python().exists():
        return
    RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
    subprocess.check_call(
        [sys.executable, "-m", "venv", str(VENV_DIR)],
        cwd=PROJECT_DIR,
    )


def _ensure_requirements() -> None:
    RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
    wanted = _hash_file(REQUIREMENTS_FILE)
    current = STAMP_FILE.read_text(encoding="utf-8").strip() if STAMP_FILE.exists() else ""
    if current == wanted and _venv_python().exists():
        return

    python_exe = str(_venv_python())
    subprocess.check_call(
        [python_exe, "-m", "pip", "install", "--upgrade", "pip"],
        cwd=PROJECT_DIR,
    )
    subprocess.check_call(
        [python_exe, "-m", "pip", "install", "-r", str(REQUIREMENTS_FILE)],
        cwd=PROJECT_DIR,
    )
    STAMP_FILE.write_text(wanted, encoding="utf-8")


def _relaunch_inside_venv() -> int:
    env = os.environ.copy()
    env["PYTHONUTF8"] = "1"
    return subprocess.call(
        [str(_venv_python()), str(PROJECT_DIR / "launcher.py")],
        cwd=PROJECT_DIR,
        env=env,
    )


def _open_browser_later(url: str) -> None:
    def _worker():
        time.sleep(1.2)
        try:
            webbrowser.open(url)
        except Exception:
            return

    Thread(target=_worker, daemon=True).start()


def main() -> int:
    _ensure_bundle_env()

    host = str(os.environ.get("LONGFORM_HOST") or os.environ.get("HOST") or "127.0.0.1")
    port = str(os.environ.get("LONGFORM_PORT") or os.environ.get("PORT") or "8000")
    url = f"http://{host}:{port}"

    if not _in_virtualenv():
        _ensure_venv()
        _ensure_requirements()
        return _relaunch_inside_venv()

    _ensure_requirements()

    print("=" * 60)
    print("长文模式多轮对话验证工具")
    print(f"前端界面: {url}")
    print(f"API 文档: {url}/docs")
    print("=" * 60)

    _open_browser_later(url)
    env = os.environ.copy()
    env["PYTHONUTF8"] = "1"
    return subprocess.call(
        [
            sys.executable,
            "-m",
            "uvicorn",
            "server.main:app",
            "--host",
            host,
            "--port",
            port,
        ],
        cwd=PROJECT_DIR,
        env=env,
    )


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except subprocess.CalledProcessError as exc:
        print(f"[错误] 启动失败: {exc}", file=sys.stderr)
        raise SystemExit(exc.returncode)
