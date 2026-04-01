"""CLI entry points for Browser Session Hub."""

from __future__ import annotations

import argparse
import atexit
import logging
import os
from pathlib import Path
import subprocess
import sys
import time

import uvicorn

from .app import create_app
from .config import BrowserSessionHubConfig


def _setup_logging(level: str = "INFO") -> None:
    root = logging.getLogger()
    for handler in root.handlers[:]:
        root.removeHandler(handler)
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(
        logging.Formatter("%(asctime)s %(name)s %(levelname)s %(message)s")
    )
    root.addHandler(handler)
    root.setLevel(getattr(logging, level.upper(), logging.INFO))


def _build_foreground_command(args: argparse.Namespace) -> list[str]:
    """Build the foreground command used by daemon mode."""
    command = [
        sys.executable,
        "-m",
        "browser_session_hub",
        "--log-level",
        args.log_level,
    ]
    if args.host:
        command.extend(["--host", args.host])
    if args.port is not None:
        command.extend(["--port", str(args.port)])
    return command


def _read_pid_file(pid_file: Path) -> int | None:
    """Read a pid file when present and valid."""
    try:
        raw = pid_file.read_text(encoding="utf-8").strip()
    except FileNotFoundError:
        return None
    if not raw:
        return None
    try:
        return int(raw)
    except ValueError:
        return None


def _is_process_running(pid: int) -> bool:
    """Return whether the given pid appears to be alive."""
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _remove_pid_file(pid_file: Path, expected_pid: int | None = None) -> None:
    """Delete a pid file when empty, stale, or owned by this process."""
    current_pid = _read_pid_file(pid_file)
    if expected_pid is not None and current_pid not in {None, expected_pid}:
        return
    pid_file.unlink(missing_ok=True)


def _prepare_daemon_pid_file(pid_file: Path) -> None:
    """Ensure daemon mode will not collide with an active process."""
    pid_file.parent.mkdir(parents=True, exist_ok=True)
    existing_pid = _read_pid_file(pid_file)
    if existing_pid is not None and _is_process_running(existing_pid):
        raise RuntimeError(
            f"Browser Session Hub daemon is already running with pid {existing_pid}. "
            f"Remove {pid_file} if it is stale."
        )
    _remove_pid_file(pid_file)


def _write_pid_file(pid_file: Path, pid: int) -> None:
    """Persist the running daemon pid."""
    pid_file.parent.mkdir(parents=True, exist_ok=True)
    pid_file.write_text(f"{pid}\n", encoding="utf-8")


def _install_daemon_pid_cleanup(pid_file: Path) -> None:
    """Record the current pid and remove it when the process exits."""
    current_pid = os.getpid()
    _write_pid_file(pid_file, current_pid)
    atexit.register(_remove_pid_file, pid_file, current_pid)


def _spawn_daemon(
    args: argparse.Namespace,
    config: BrowserSessionHubConfig,
) -> int:
    """Start the service in a detached background process."""
    _prepare_daemon_pid_file(config.pid_file)
    config.log_dir.mkdir(parents=True, exist_ok=True)
    with config.log_file.open("a", encoding="utf-8", buffering=1) as log_file:
        env = os.environ.copy()
        env["BROWSER_SESSION_HUB_DAEMONIZED"] = "1"
        process = subprocess.Popen(
            _build_foreground_command(args),
            stdin=subprocess.DEVNULL,
            stdout=log_file,
            stderr=subprocess.STDOUT,
            start_new_session=True,
            close_fds=True,
            cwd=Path.cwd(),
            env=env,
        )
    _write_pid_file(config.pid_file, process.pid)
    time.sleep(0.2)
    return_code = process.poll()
    if return_code is not None:
        _remove_pid_file(config.pid_file, process.pid)
        raise RuntimeError(
            f"Browser Session Hub daemon exited immediately with code {return_code}. "
            f"Check {config.log_file}."
        )
    return process.pid


def main() -> None:
    """Run the service."""
    parser = argparse.ArgumentParser(
        prog="browser-session-hub",
        description="Self-hosted isolated browser sessions with CDP and noVNC previews",
    )
    parser.add_argument(
        "--log-level",
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
    )
    parser.add_argument("--host", default=None)
    parser.add_argument("--port", type=int, default=None)
    parser.add_argument(
        "--daemon",
        action="store_true",
        help="Run the service in the background and write logs to the configured log file.",
    )
    args = parser.parse_args()

    config = BrowserSessionHubConfig.from_env()
    if args.host:
        config.host = args.host
    if args.port is not None:
        config.port = args.port

    if args.daemon:
        try:
            pid = _spawn_daemon(args, config)
        except RuntimeError as exc:
            parser.exit(status=1, message=f"{exc}\n")
        print(
            f"Browser Session Hub daemon started with pid {pid}. "
            f"Log file: {config.log_file}. PID file: {config.pid_file}."
        )
        return

    _setup_logging(args.log_level)
    if os.environ.get("BROWSER_SESSION_HUB_DAEMONIZED") == "1":
        _install_daemon_pid_cleanup(config.pid_file)
        logging.getLogger(__name__).info(
            "Starting daemon pid=%s log_file=%s pid_file=%s",
            os.getpid(),
            config.log_file,
            config.pid_file,
        )

    uvicorn.run(
        create_app(config),
        host=config.host,
        port=config.port,
        log_level="warning",
    )
