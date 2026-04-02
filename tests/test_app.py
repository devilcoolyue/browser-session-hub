from pathlib import Path

from fastapi.testclient import TestClient

from browser_session_hub.app import create_app
from browser_session_hub.config import BrowserSessionHubConfig


def make_config(tmp_path: Path) -> BrowserSessionHubConfig:
    for name in ["chrome", "Xvfb", "openbox", "x11vnc", "novnc_proxy"]:
        (tmp_path / name).write_text("", encoding="utf-8")
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
        kiosk=False,
        browser_extra_args=[],
        default_start_url="about:blank",
        vnc_quality=9,
        vnc_compress=0,
        vnc_noxdamage=True,
    )


def test_app_health_and_static_index(tmp_path: Path):
    app = create_app(make_config(tmp_path))
    client = TestClient(app)

    health = client.get("/api/health")
    root = client.get("/")

    assert health.status_code == 200
    assert health.json()["service"] == "browser-session-hub"
    assert root.status_code == 200
    assert "Browser Session Hub" in root.text
