"""Session manager for isolated browser runtimes."""

from __future__ import annotations

from dataclasses import dataclass, field
import logging
from pathlib import Path
import shutil
import subprocess
import threading
import time
from typing import Any
from urllib.parse import urlparse
from uuid import uuid4

from .config import BrowserSessionHubConfig
from .models import CreateSessionRequest, DependencyStatus, SessionStatus, SessionSummary
from .process_utils import (
    command_exists,
    is_display_available,
    is_port_available,
    is_port_open,
    open_log_file,
    sanitized_env,
    terminate_process,
    wait_for_condition,
    wait_for_json,
)

logger = logging.getLogger(__name__)


class SessionManagerError(RuntimeError):
    """Raised when session operations fail."""


@dataclass(slots=True)
class SessionPorts:
    """Port bundle assigned to a session."""

    display_number: int
    cdp_port: int
    vnc_port: int
    novnc_port: int


@dataclass(slots=True)
class ManagedSession:
    """Runtime state for a browser session."""

    session_id: str
    owner_id: str
    status: SessionStatus
    created_at: float
    last_activity: float
    start_url: str
    persist_profile: bool
    working_dir: Path
    profile_dir: Path
    ports: SessionPorts
    viewport_width: int
    viewport_height: int
    cdp_http_endpoint: str
    preview_url: str
    metadata: dict[str, str]
    processes: dict[str, subprocess.Popen] = field(default_factory=dict)
    cdp_ws_endpoint: str | None = None
    error: str | None = None

    def process_ids(self) -> dict[str, int | None]:
        """Return process ids in a JSON-friendly shape."""
        return {
            name: process.pid if process else None
            for name, process in self.processes.items()
        }

    def to_summary(self) -> SessionSummary:
        """Return an API summary."""
        return SessionSummary(
            session_id=self.session_id,
            owner_id=self.owner_id,
            status=self.status,
            created_at=self.created_at,
            last_activity=self.last_activity,
            start_url=self.start_url,
            persist_profile=self.persist_profile,
            working_dir=str(self.working_dir),
            profile_dir=str(self.profile_dir),
            cdp_http_endpoint=self.cdp_http_endpoint,
            cdp_ws_endpoint=self.cdp_ws_endpoint,
            preview_url=self.preview_url,
            display_number=self.ports.display_number,
            cdp_port=self.ports.cdp_port,
            vnc_port=self.ports.vnc_port,
            novnc_port=self.ports.novnc_port,
            viewport_width=self.viewport_width,
            viewport_height=self.viewport_height,
            processes=self.process_ids(),
            metadata=self.metadata,
            error=self.error,
        )


class BrowserSessionManager:
    """Manage isolated browser sessions."""

    def __init__(self, config: BrowserSessionHubConfig) -> None:
        self._config = config
        self._lock = threading.RLock()
        self._sessions: dict[str, ManagedSession] = {}
        self._allocated_ports: set[int] = set()
        self._allocated_displays: set[int] = set()
        self._active_profiles: set[Path] = set()
        self._config.sessions_root.mkdir(parents=True, exist_ok=True)
        (self._config.host_root / "profiles").mkdir(parents=True, exist_ok=True)

    def dependency_status(self) -> list[DependencyStatus]:
        """Return a dependency report."""
        return [
            DependencyStatus(
                name="chrome",
                path=self._config.chrome_path,
                available=command_exists(self._config.chrome_path),
            ),
            DependencyStatus(
                name="xvfb",
                path=self._config.xvfb_path,
                available=command_exists(self._config.xvfb_path),
            ),
            DependencyStatus(
                name="openbox",
                path=self._config.openbox_path,
                available=command_exists(self._config.openbox_path),
                required=False,
                note="Optional but recommended for a cleaner headed-browser desktop.",
            ),
            DependencyStatus(
                name="x11vnc",
                path=self._config.x11vnc_path,
                available=command_exists(self._config.x11vnc_path),
            ),
            DependencyStatus(
                name="novnc_proxy",
                path=self._config.novnc_proxy_path,
                available=command_exists(self._config.novnc_proxy_path),
            ),
        ]

    def list_sessions(self) -> list[SessionSummary]:
        """Return all sessions."""
        with self._lock:
            return [
                session.to_summary()
                for session in sorted(
                    self._sessions.values(),
                    key=lambda item: item.created_at,
                    reverse=True,
                )
            ]

    def get_session(self, session_id: str) -> SessionSummary:
        """Return a single session."""
        with self._lock:
            session = self._sessions.get(session_id)
            if session is None:
                raise SessionManagerError(f"Unknown session: {session_id}")
            return session.to_summary()

    def touch_session(self, session_id: str) -> SessionSummary:
        """Refresh last-activity timestamp."""
        with self._lock:
            session = self._require_session(session_id)
            session.last_activity = time.time()
            return session.to_summary()

    def cleanup_idle_sessions(self) -> list[str]:
        """Stop sessions that exceeded the idle timeout."""
        timeout = self._config.idle_timeout_seconds
        if timeout <= 0:
            return []
        stopped: list[str] = []
        now = time.time()
        for session in self.list_sessions():
            if now - session.last_activity < timeout:
                continue
            self.stop_session(session.session_id)
            stopped.append(session.session_id)
        return stopped

    def shutdown(self) -> None:
        """Stop all running sessions."""
        for session_id in [session.session_id for session in self.list_sessions()]:
            try:
                self.stop_session(session_id)
            except SessionManagerError:
                logger.exception("Failed to stop session %s during shutdown", session_id)

    def create_session(self, request: CreateSessionRequest) -> SessionSummary:
        """Create and start a new isolated session."""
        with self._lock:
            self._assert_dependencies_ready()
            session_id = uuid4().hex[:12]
            now = time.time()
            viewport_width = request.viewport_width or self._config.viewport_width
            viewport_height = request.viewport_height or self._config.viewport_height
            ports = self._allocate_ports_locked()
            working_dir = self._config.sessions_root / session_id
            logs_dir = working_dir / "logs"
            if request.persist_profile:
                profile_dir = self._config.host_root / "profiles" / request.owner_id
                if profile_dir in self._active_profiles:
                    raise SessionManagerError(
                        f"Persistent profile for owner {request.owner_id} is already in use."
                    )
                profile_dir.mkdir(parents=True, exist_ok=True)
                self._active_profiles.add(profile_dir)
            else:
                profile_dir = working_dir / "profile"
            working_dir.mkdir(parents=True, exist_ok=True)
            profile_dir.mkdir(parents=True, exist_ok=True)
            start_url = request.start_url or self._config.default_start_url
            cdp_http_endpoint = (
                f"http://{self._config.public_host}:{ports.cdp_port}"
            )
            preview_url = (
                f"{self._config.public_scheme}://{self._config.public_host}:"
                f"{ports.novnc_port}/vnc.html?autoconnect=1&resize=remote&reconnect=1"
            )
            session = ManagedSession(
                session_id=session_id,
                owner_id=request.owner_id,
                status=SessionStatus.starting,
                created_at=now,
                last_activity=now,
                start_url=start_url,
                persist_profile=request.persist_profile,
                working_dir=working_dir,
                profile_dir=profile_dir,
                ports=ports,
                viewport_width=viewport_width,
                viewport_height=viewport_height,
                cdp_http_endpoint=cdp_http_endpoint,
                preview_url=preview_url,
                metadata=request.metadata,
            )
            self._sessions[session_id] = session
            try:
                self._start_session_locked(session)
                session.status = SessionStatus.running
                session.last_activity = time.time()
                logger.info(
                    "Session %s started: cdp=%s preview=%s",
                    session_id,
                    session.cdp_http_endpoint,
                    session.preview_url,
                )
                return session.to_summary()
            except Exception as exc:
                session.status = SessionStatus.error
                session.error = str(exc)
                logger.exception("Failed to start session %s", session_id)
                self._stop_session_locked(session, keep_record=False)
                raise SessionManagerError(str(exc)) from exc

    def stop_session(self, session_id: str) -> SessionSummary:
        """Stop and remove a session."""
        with self._lock:
            session = self._require_session(session_id)
            summary = session.to_summary()
            self._stop_session_locked(session, keep_record=False)
            logger.info("Session %s stopped", session_id)
            return summary

    def _assert_dependencies_ready(self) -> None:
        missing = [
            dep.name
            for dep in self.dependency_status()
            if dep.required and not dep.available
        ]
        if missing:
            joined = ", ".join(missing)
            raise SessionManagerError(f"Missing required dependencies: {joined}")

    def _require_session(self, session_id: str) -> ManagedSession:
        session = self._sessions.get(session_id)
        if session is None:
            raise SessionManagerError(f"Unknown session: {session_id}")
        return session

    def _allocate_ports_locked(self) -> SessionPorts:
        display_number = self._allocate_display_locked()
        cdp_port = self._allocate_port_locked(
            self._config.cdp_bind_host,
            self._config.cdp_port_range,
        )
        vnc_port = self._allocate_port_locked(
            "127.0.0.1",
            self._config.vnc_port_range,
        )
        novnc_port = self._allocate_port_locked(
            "0.0.0.0",
            self._config.novnc_port_range,
        )
        return SessionPorts(
            display_number=display_number,
            cdp_port=cdp_port,
            vnc_port=vnc_port,
            novnc_port=novnc_port,
        )

    def _allocate_display_locked(self) -> int:
        start, end = self._config.display_range
        for display_number in range(start, end + 1):
            if display_number in self._allocated_displays:
                continue
            if not is_display_available(display_number):
                continue
            self._allocated_displays.add(display_number)
            return display_number
        raise SessionManagerError("No free Xvfb display numbers available")

    def _allocate_port_locked(
        self,
        host: str,
        port_range: tuple[int, int],
    ) -> int:
        start, end = port_range
        bind_host = "127.0.0.1" if host == "0.0.0.0" else host
        for port in range(start, end + 1):
            if port in self._allocated_ports:
                continue
            if not is_port_available(bind_host, port):
                continue
            self._allocated_ports.add(port)
            return port
        raise SessionManagerError(f"No free port available in range {start}-{end}")

    def _start_session_locked(self, session: ManagedSession) -> None:
        session_logs = session.working_dir / "logs"
        display = f":{session.ports.display_number}"
        display_env = sanitized_env({"DISPLAY": display})
        self._start_xvfb(session, session_logs, display)
        if self._config.openbox_path:
            self._start_openbox(session, session_logs, display_env)
        self._start_browser(session, session_logs, display_env)
        self._start_vnc(session, session_logs, display)
        self._start_novnc(session, session_logs)

    def _start_xvfb(
        self,
        session: ManagedSession,
        logs_dir: Path,
        display: str,
    ) -> None:
        log_file = open_log_file(logs_dir / "xvfb.log")
        command = [
            self._config.xvfb_path,
            display,
            "-screen",
            "0",
            f"{session.viewport_width}x{session.viewport_height}x24",
            "-nolisten",
            "tcp",
        ]
        process = subprocess.Popen(
            command,
            stdout=log_file,
            stderr=subprocess.STDOUT,
            env=sanitized_env(),
        )
        session.processes["xvfb"] = process
        ready = wait_for_condition(
            lambda: not is_display_available(session.ports.display_number),
            timeout_seconds=5.0,
            interval_seconds=0.1,
        )
        if not ready:
            raise SessionManagerError("Xvfb did not become ready in time")

    def _start_openbox(
        self,
        session: ManagedSession,
        logs_dir: Path,
        env: dict[str, str],
    ) -> None:
        log_file = open_log_file(logs_dir / "openbox.log")
        process = subprocess.Popen(
            [self._config.openbox_path],
            stdout=log_file,
            stderr=subprocess.STDOUT,
            env=env,
        )
        session.processes["openbox"] = process

    def _start_browser(
        self,
        session: ManagedSession,
        logs_dir: Path,
        env: dict[str, str],
    ) -> None:
        log_file = open_log_file(logs_dir / "browser.log")
        command = [
            self._config.chrome_path,
            f"--remote-debugging-address={self._config.cdp_bind_host}",
            f"--remote-debugging-port={session.ports.cdp_port}",
            f"--user-data-dir={session.profile_dir}",
            f"--window-size={session.viewport_width},{session.viewport_height}",
            "--no-first-run",
            "--no-default-browser-check",
            "--disable-dev-shm-usage",
            "--disable-background-networking",
            "--disable-features=Translate,MediaRouter,OptimizationHints",
            "--disable-sync",
            "--new-window",
        ]
        if self._config.no_sandbox:
            command.append("--no-sandbox")
        command.extend(self._config.browser_extra_args)
        command.append(session.start_url)
        process = subprocess.Popen(
            command,
            stdout=log_file,
            stderr=subprocess.STDOUT,
            env=env,
        )
        session.processes["browser"] = process
        loopback_host = (
            "127.0.0.1"
            if self._config.cdp_bind_host in {"0.0.0.0", "::"}
            else self._config.cdp_bind_host
        )
        version_info = wait_for_json(
            f"http://{loopback_host}:{session.ports.cdp_port}/json/version",
            timeout_seconds=20.0,
        )
        raw_ws_url = version_info.get("webSocketDebuggerUrl")
        session.cdp_ws_endpoint = self._externalize_ws_url(
            raw_ws_url,
            session.ports.cdp_port,
        )

    def _start_vnc(
        self,
        session: ManagedSession,
        logs_dir: Path,
        display: str,
    ) -> None:
        log_file = open_log_file(logs_dir / "x11vnc.log")
        command = [
            self._config.x11vnc_path,
            "-display",
            display,
            "-rfbport",
            str(session.ports.vnc_port),
            "-localhost",
            "-forever",
            "-shared",
            "-nopw",
        ]
        process = subprocess.Popen(
            command,
            stdout=log_file,
            stderr=subprocess.STDOUT,
            env=sanitized_env(),
        )
        session.processes["x11vnc"] = process
        ready = wait_for_condition(
            lambda: is_port_open("127.0.0.1", session.ports.vnc_port),
            timeout_seconds=10.0,
            interval_seconds=0.2,
        )
        if not ready:
            raise SessionManagerError("x11vnc did not start in time")

    def _start_novnc(
        self,
        session: ManagedSession,
        logs_dir: Path,
    ) -> None:
        log_file = open_log_file(logs_dir / "novnc.log")
        command = [
            self._config.novnc_proxy_path,
            "--listen",
            str(session.ports.novnc_port),
            "--vnc",
            f"127.0.0.1:{session.ports.vnc_port}",
        ]
        process = subprocess.Popen(
            command,
            stdout=log_file,
            stderr=subprocess.STDOUT,
            env=sanitized_env(),
        )
        session.processes["novnc_proxy"] = process
        ready = wait_for_condition(
            lambda: is_port_open("127.0.0.1", session.ports.novnc_port),
            timeout_seconds=10.0,
            interval_seconds=0.2,
        )
        if not ready:
            raise SessionManagerError("novnc_proxy did not start in time")

    def _externalize_ws_url(self, ws_url: str | None, port: int) -> str | None:
        if not ws_url:
            return None
        parsed = urlparse(ws_url)
        if not parsed.path:
            return ws_url
        return (
            f"{self._config.websocket_scheme}://"
            f"{self._config.public_host}:{port}{parsed.path}"
        )

    def _stop_session_locked(
        self,
        session: ManagedSession,
        keep_record: bool,
    ) -> None:
        for name in [
            "novnc_proxy",
            "x11vnc",
            "browser",
            "openbox",
            "xvfb",
        ]:
            terminate_process(session.processes.get(name))
        self._release_session_resources_locked(session)
        session.status = SessionStatus.stopped
        session.last_activity = time.time()
        session.processes.clear()
        if not keep_record:
            self._sessions.pop(session.session_id, None)
            if not session.persist_profile and session.working_dir.exists():
                shutil.rmtree(session.working_dir, ignore_errors=True)

    def _release_session_resources_locked(self, session: ManagedSession) -> None:
        self._allocated_displays.discard(session.ports.display_number)
        self._allocated_ports.discard(session.ports.cdp_port)
        self._allocated_ports.discard(session.ports.vnc_port)
        self._allocated_ports.discard(session.ports.novnc_port)
        if session.persist_profile:
            self._active_profiles.discard(session.profile_dir)
