"""Process and readiness helpers."""

from __future__ import annotations

import json
import os
from pathlib import Path
import socket
import subprocess
import time
from typing import Any, Callable
import urllib.error
import urllib.request


def command_exists(path: str | None) -> bool:
    """Return whether a binary path is usable."""
    return bool(path and Path(path).exists())


def open_log_file(path: Path):
    """Open a line-buffered log file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    return path.open("a", encoding="utf-8", buffering=1)


def is_port_available(host: str, port: int) -> bool:
    """Check whether a TCP port is free."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.bind((host, port))
        except OSError:
            return False
    return True


def is_port_open(host: str, port: int, timeout: float = 0.25) -> bool:
    """Check whether a TCP port is accepting connections."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(timeout)
        try:
            return sock.connect_ex((host, port)) == 0
        except OSError:
            return False


def is_display_available(display_number: int) -> bool:
    """Check whether an X display number is free."""
    x_socket = Path(f"/tmp/.X11-unix/X{display_number}")
    return not x_socket.exists()


def wait_for_condition(
    predicate: Callable[[], bool],
    timeout_seconds: float,
    interval_seconds: float = 0.2,
) -> bool:
    """Poll a predicate until it succeeds or times out."""
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(interval_seconds)
    return predicate()


def fetch_json(url: str) -> Any:
    """Fetch and decode a JSON HTTP response."""
    with urllib.request.urlopen(url, timeout=1.5) as response:
        return json.loads(response.read().decode("utf-8"))


def wait_for_json(url: str, timeout_seconds: float) -> Any:
    """Poll a JSON endpoint until it responds."""
    deadline = time.monotonic() + timeout_seconds
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        try:
            return fetch_json(url)
        except (urllib.error.URLError, json.JSONDecodeError, TimeoutError) as exc:
            last_error = exc
            time.sleep(0.25)
    if last_error:
        raise RuntimeError(f"Timed out waiting for {url}: {last_error!s}")
    raise RuntimeError(f"Timed out waiting for {url}")


def terminate_process(
    process: subprocess.Popen | None,
    timeout_seconds: float = 5.0,
) -> None:
    """Terminate a subprocess if it is still alive."""
    if process is None:
        return
    if process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=timeout_seconds)
        return
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=timeout_seconds)


def sanitized_env(extra: dict[str, str] | None = None) -> dict[str, str]:
    """Build an environment for spawned processes."""
    env = os.environ.copy()
    if extra:
        env.update(extra)
    return env
