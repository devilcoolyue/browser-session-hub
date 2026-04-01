from pathlib import Path

from browser_session_hub.config import BrowserSessionHubConfig


def test_config_from_env_parses_ranges_and_paths(monkeypatch, tmp_path: Path):
    chrome = tmp_path / "chrome"
    xvfb = tmp_path / "Xvfb"
    x11vnc = tmp_path / "x11vnc"
    novnc = tmp_path / "novnc_proxy"
    openbox = tmp_path / "openbox"
    for path in [chrome, xvfb, x11vnc, novnc, openbox]:
        path.write_text("", encoding="utf-8")

    monkeypatch.setenv("BROWSER_SESSION_HUB_CHROME_PATH", str(chrome))
    monkeypatch.setenv("BROWSER_SESSION_HUB_XVFB_PATH", str(xvfb))
    monkeypatch.setenv("BROWSER_SESSION_HUB_X11VNC_PATH", str(x11vnc))
    monkeypatch.setenv("BROWSER_SESSION_HUB_NOVNC_PROXY_PATH", str(novnc))
    monkeypatch.setenv("BROWSER_SESSION_HUB_OPENBOX_PATH", str(openbox))
    monkeypatch.setenv("BROWSER_SESSION_HUB_CDP_PORT_RANGE", "9700-9710")
    monkeypatch.setenv("BROWSER_SESSION_HUB_NOVNC_PORT_RANGE", "6200-6210")
    monkeypatch.setenv("BROWSER_SESSION_HUB_DISPLAY_RANGE", "301-305")
    monkeypatch.setenv("BROWSER_SESSION_HUB_NO_SANDBOX", "true")
    monkeypatch.setenv("BROWSER_SESSION_HUB_BROWSER_EXTRA_ARGS", "--disable-gpu --lang=en-US")
    monkeypatch.setenv("BROWSER_SESSION_HUB_HOST", "0.0.0.0")
    monkeypatch.setenv("BROWSER_SESSION_HUB_SESSIONS_ROOT", str(tmp_path / "sessions"))
    monkeypatch.setenv("BROWSER_SESSION_HUB_HOST_ROOT", str(tmp_path / "host-root"))
    monkeypatch.setenv("BROWSER_SESSION_HUB_LOG_FILE", str(tmp_path / "custom" / "hub.log"))
    monkeypatch.setenv("BROWSER_SESSION_HUB_PID_FILE", str(tmp_path / "custom" / "hub.pid"))

    config = BrowserSessionHubConfig.from_env()

    assert config.cdp_port_range == (9700, 9710)
    assert config.novnc_port_range == (6200, 6210)
    assert config.display_range == (301, 305)
    assert config.no_sandbox is True
    assert config.browser_extra_args == ["--disable-gpu", "--lang=en-US"]
    assert config.public_host == "127.0.0.1"
    assert config.sessions_root == tmp_path / "sessions"
    assert config.host_root == tmp_path / "host-root"
    assert config.log_dir == tmp_path / "host-root" / "logs"
    assert config.run_dir == tmp_path / "host-root" / "run"
    assert config.log_file == tmp_path / "custom" / "hub.log"
    assert config.pid_file == tmp_path / "custom" / "hub.pid"
