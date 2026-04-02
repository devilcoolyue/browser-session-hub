from pathlib import Path

from browser_session_hub.config import BrowserSessionHubConfig
from browser_session_hub.models import CreateSessionRequest, SessionStatus
from browser_session_hub.session_manager import BrowserSessionManager


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
        idle_timeout_seconds=5,
        no_sandbox=False,
        kiosk=False,
        browser_extra_args=[],
        default_start_url="about:blank",
        vnc_quality=9,
        vnc_compress=0,
        vnc_noxdamage=True,
    )


def fake_start_factory(config: BrowserSessionHubConfig):
    def fake_start(session):
        session.cdp_ws_endpoint = (
            f"{config.websocket_scheme}://{config.public_host}:"
            f"{session.ports.cdp_port}/devtools/browser/mock"
        )

    return fake_start


def fake_stop(manager: BrowserSessionManager):
    def _stop(session, keep_record):
        manager._release_session_resources_locked(session)
        session.status = SessionStatus.stopped
        session.processes.clear()
        if not keep_record:
            manager._sessions.pop(session.session_id, None)

    return _stop


def test_create_session_assigns_unique_runtime(monkeypatch, tmp_path: Path):
    manager = BrowserSessionManager(make_config(tmp_path))
    monkeypatch.setattr("browser_session_hub.session_manager.is_port_available", lambda *_: True)
    monkeypatch.setattr("browser_session_hub.session_manager.is_display_available", lambda *_: True)
    monkeypatch.setattr(manager, "_assert_dependencies_ready", lambda: None)
    monkeypatch.setattr(manager, "_start_session_locked", fake_start_factory(manager._config))
    monkeypatch.setattr(manager, "_stop_session_locked", fake_stop(manager))

    summary = manager.create_session(
        CreateSessionRequest(owner_id="alice", start_url="https://example.com")
    )

    assert summary.owner_id == "alice"
    assert summary.status == SessionStatus.running
    assert summary.start_url == "https://example.com"
    assert summary.cdp_http_endpoint.startswith("http://127.0.0.1:95")
    assert summary.preview_url == f"http://127.0.0.1:8091/preview/{summary.session_id}"
    assert summary.profile_dir.endswith(f"{summary.session_id}/profile")

    manager.stop_session(summary.session_id)
    assert manager.list_sessions() == []


def test_create_session_reuses_existing_owner_session(monkeypatch, tmp_path: Path):
    manager = BrowserSessionManager(make_config(tmp_path))
    monkeypatch.setattr("browser_session_hub.session_manager.is_port_available", lambda *_: True)
    monkeypatch.setattr("browser_session_hub.session_manager.is_display_available", lambda *_: True)
    monkeypatch.setattr(manager, "_assert_dependencies_ready", lambda: None)
    monkeypatch.setattr(manager, "_stop_session_locked", fake_stop(manager))

    start_calls: list[str] = []

    def fake_start(session):
        start_calls.append(session.session_id)
        fake_start_factory(manager._config)(session)

    monkeypatch.setattr(manager, "_start_session_locked", fake_start)

    first = manager.create_session(
        CreateSessionRequest(
            owner_id="bob",
            persist_profile=True,
            start_url="https://first.example.com",
        )
    )
    manager._sessions[first.session_id].last_activity -= 10
    previous_last_activity = manager._sessions[first.session_id].last_activity

    second = manager.create_session(
        CreateSessionRequest(
            owner_id="bob",
            persist_profile=False,
            start_url="https://second.example.com",
        )
    )

    assert second.session_id == first.session_id
    assert second.start_url == "https://first.example.com"
    assert second.persist_profile is True
    assert second.last_activity > previous_last_activity
    assert start_calls == [first.session_id]
    assert len(manager.list_sessions()) == 1
    manager.stop_session(first.session_id)


def test_cleanup_idle_sessions_stops_old_sessions(monkeypatch, tmp_path: Path):
    manager = BrowserSessionManager(make_config(tmp_path))
    monkeypatch.setattr("browser_session_hub.session_manager.is_port_available", lambda *_: True)
    monkeypatch.setattr("browser_session_hub.session_manager.is_display_available", lambda *_: True)
    monkeypatch.setattr(manager, "_assert_dependencies_ready", lambda: None)
    monkeypatch.setattr(manager, "_start_session_locked", fake_start_factory(manager._config))
    monkeypatch.setattr(manager, "_stop_session_locked", fake_stop(manager))

    summary = manager.create_session(CreateSessionRequest(owner_id="carol"))
    manager._sessions[summary.session_id].last_activity -= 60

    stopped = manager.cleanup_idle_sessions()

    assert stopped == [summary.session_id]
    assert manager.list_sessions() == []
