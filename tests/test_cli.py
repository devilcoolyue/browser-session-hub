from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from browser_session_hub.cli import (
    _build_foreground_command,
    _prepare_daemon_pid_file,
    _spawn_daemon,
)
from browser_session_hub.config import BrowserSessionHubConfig


def make_config(tmp_path: Path) -> BrowserSessionHubConfig:
    return BrowserSessionHubConfig(
        host="127.0.0.1",
        port=8091,
        public_scheme="http",
        public_host="127.0.0.1",
        sessions_root=tmp_path / "sessions",
        host_root=tmp_path / "host-root",
        log_dir=tmp_path / "host-root" / "logs",
        run_dir=tmp_path / "host-root" / "run",
        log_file=tmp_path / "host-root" / "logs" / "browser-session-hub.log",
        pid_file=tmp_path / "host-root" / "run" / "browser-session-hub.pid",
        chrome_path=str(tmp_path / "chrome"),
        xvfb_path=str(tmp_path / "Xvfb"),
        openbox_path=str(tmp_path / "openbox"),
        x11vnc_path=str(tmp_path / "x11vnc"),
        novnc_proxy_path=str(tmp_path / "novnc_proxy"),
        cdp_bind_host="127.0.0.1",
        cdp_port_range=(9500, 9510),
        vnc_port_range=(6510, 6520),
        novnc_port_range=(6610, 6620),
        display_range=(401, 410),
        viewport_width=1440,
        viewport_height=900,
        idle_timeout_seconds=0,
        no_sandbox=False,
        browser_extra_args=[],
        default_start_url="about:blank",
    )


def test_build_foreground_command_includes_cli_overrides():
    args = SimpleNamespace(log_level="DEBUG", host="0.0.0.0", port=9000)

    command = _build_foreground_command(args)

    assert command == [
        command[0],
        "-m",
        "browser_session_hub",
        "--log-level",
        "DEBUG",
        "--host",
        "0.0.0.0",
        "--port",
        "9000",
    ]


def test_prepare_daemon_pid_file_rejects_running_process(
    monkeypatch,
    tmp_path: Path,
):
    pid_file = tmp_path / "run" / "browser-session-hub.pid"
    pid_file.parent.mkdir(parents=True, exist_ok=True)
    pid_file.write_text("123\n", encoding="utf-8")
    monkeypatch.setattr("browser_session_hub.cli._is_process_running", lambda pid: pid == 123)

    with pytest.raises(RuntimeError):
        _prepare_daemon_pid_file(pid_file)


def test_spawn_daemon_writes_pid_file_and_sets_daemon_env(
    monkeypatch,
    tmp_path: Path,
):
    captured: dict[str, object] = {}

    class FakeProcess:
        pid = 4242

        def poll(self):
            return None

    def fake_popen(command, **kwargs):
        captured["command"] = command
        captured["kwargs"] = kwargs
        return FakeProcess()

    args = SimpleNamespace(log_level="INFO", host=None, port=None)
    config = make_config(tmp_path)

    monkeypatch.setattr("browser_session_hub.cli.subprocess.Popen", fake_popen)
    monkeypatch.setattr("browser_session_hub.cli.time.sleep", lambda _: None)

    pid = _spawn_daemon(args, config)

    assert pid == 4242
    assert config.pid_file.read_text(encoding="utf-8").strip() == "4242"
    assert captured["command"] == _build_foreground_command(args)
    assert captured["kwargs"]["start_new_session"] is True
    assert captured["kwargs"]["stderr"] == -2
    assert captured["kwargs"]["env"]["BROWSER_SESSION_HUB_DAEMONIZED"] == "1"
    assert config.log_file.exists()
