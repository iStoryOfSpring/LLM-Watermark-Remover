from __future__ import annotations

import argparse
import json
import os
import socket
import signal
import threading
import time
import urllib.error
import urllib.request
import webbrowser
from pathlib import Path

import uvicorn

from backend.app.config import settings


def _free_port(host: str) -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind((host, 0))
        return int(probe.getsockname()[1])


def _ready_payload(host: str, port: int) -> dict[str, str | int]:
    return {
        "pid": os.getpid(),
        "host": host,
        "port": port,
        "url": f"http://{host}:{port}/",
        "health_url": f"http://{host}:{port}/api/health",
    }


def _wait_for_health(host: str, port: int, timeout: float = 20.0) -> bool:
    deadline = time.monotonic() + timeout
    url = f"http://{host}:{port}/api/health"
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=0.8) as response:
                if response.status == 200:
                    return True
        except (OSError, urllib.error.URLError):
            time.sleep(0.15)
    return False


def _write_ready_file(path: Path, payload: dict[str, str | int]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    temporary.replace(path)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the local rewrite desktop backend.")
    parser.add_argument("--host", default=settings.host)
    parser.add_argument("--port", type=int, default=None, help="Use 0 to select an available loopback port.")
    parser.add_argument("--ready-file", type=Path, default=None)
    parser.add_argument("--no-browser", action="store_true", help="Do not open a browser after startup.")
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    host = args.host
    port = settings.port if args.port is None else args.port
    if port == 0:
        port = _free_port(host)
    ready_file = args.ready_file
    if ready_file is None:
        configured_ready_file = os.getenv("LOCAL_REWRITE_READY_FILE")
        ready_file = Path(configured_ready_file) if configured_ready_file else None

    from backend.app.main import app

    config = uvicorn.Config(app, host=host, port=port, reload=False, log_level="info")
    server = uvicorn.Server(config)
    server_thread = threading.Thread(target=server.run, name="local-rewrite-api", daemon=True)

    def request_shutdown(_signum, _frame) -> None:
        server.should_exit = True

    previous_handlers = {
        signal_number: signal.getsignal(signal_number)
        for signal_number in (signal.SIGINT, signal.SIGTERM)
    }
    try:
        for signal_number in previous_handlers:
            signal.signal(signal_number, request_shutdown)
        server_thread.start()
        if not _wait_for_health(host, port):
            raise RuntimeError(f"本地 API 启动失败: http://{host}:{port}/api/health")

        payload = _ready_payload(host, port)
        if ready_file is not None:
            _write_ready_file(ready_file, payload)

        if not args.no_browser:
            webbrowser.open(str(payload["url"]))

        server_thread.join()
    finally:
        server.should_exit = True
        if server_thread.is_alive():
            server_thread.join(timeout=5)
        if ready_file is not None:
            ready_file.unlink(missing_ok=True)
        for signal_number, handler in previous_handlers.items():
            signal.signal(signal_number, handler)


if __name__ == "__main__":
    main()
