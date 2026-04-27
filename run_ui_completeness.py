import asyncio
import socket
import sys
import threading
import time
from pathlib import Path

import uvicorn


PROJECT_DIR = Path(__file__).resolve().parent
SERVER_DIR = PROJECT_DIR / "server"
for path in (PROJECT_DIR, SERVER_DIR):
    text = str(path)
    if text not in sys.path:
        sys.path.insert(0, text)

import main as server_main  # noqa: E402
from tests.integration import test_ui_completeness  # noqa: E402


def wait_port(host: str, port: int, timeout: float = 30.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with socket.create_connection((host, port), timeout=1):
                return True
        except OSError:
            time.sleep(0.2)
    return False


def main() -> int:
    config = uvicorn.Config(
        server_main.app,
        host="127.0.0.1",
        port=8000,
        log_level="warning",
    )
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()

    if not wait_port("127.0.0.1", 8000):
        print("❌ 本地服务未在 30 秒内启动成功")
        server.should_exit = True
        thread.join(timeout=5)
        return 1

    exit_code = 0
    try:
        asyncio.run(test_ui_completeness.main())
    except SystemExit as exc:
        exit_code = exc.code if isinstance(exc.code, int) else 1
    finally:
        server.should_exit = True
        thread.join(timeout=10)
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
