"""Configuration helpers for Browser Session Hub."""

from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import shutil


def _parse_bool(value: str | None, default: bool = False) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _parse_range(value: str | None, default: tuple[int, int]) -> tuple[int, int]:
    if value is None or not value.strip():
        return default
    raw = value.strip()
    if "-" not in raw:
        parsed = int(raw)
        return (parsed, parsed)
    start_str, end_str = raw.split("-", 1)
    start = int(start_str.strip())
    end = int(end_str.strip())
    if end < start:
        raise ValueError(f"Invalid range: {raw}")
    return (start, end)


def _parse_args(value: str | None) -> list[str]:
    if value is None or not value.strip():
        return []
    return [item for item in value.strip().split(" ") if item]


def _default_public_host(bind_host: str) -> str:
    if bind_host in {"0.0.0.0", "::"}:
        return "127.0.0.1"
    return bind_host


def _default_data_root() -> Path:
    return Path(os.path.expanduser("~")) / ".browser-session-hub"


def _resolve_optional_binary(env_name: str, *candidates: str) -> str | None:
    override = os.environ.get(env_name)
    if override:
        return override
    for candidate in candidates:
        resolved = shutil.which(candidate)
        if resolved:
            return resolved
    return None


def _resolve_required_binary(env_name: str, *candidates: str) -> str:
    resolved = _resolve_optional_binary(env_name, *candidates)
    if resolved:
        return resolved
    names = ", ".join(candidates)
    raise RuntimeError(
        f"Unable to resolve required binary for {env_name}. "
        f"Set {env_name} or install one of: {names}."
    )


@dataclass(slots=True)
class BrowserSessionHubConfig:
    """Runtime configuration."""

    host: str
    port: int
    public_scheme: str
    public_host: str
    sessions_root: Path
    host_root: Path
    chrome_path: str
    xvfb_path: str
    openbox_path: str | None
    x11vnc_path: str
    novnc_proxy_path: str
    cdp_bind_host: str
    cdp_port_range: tuple[int, int]
    vnc_port_range: tuple[int, int]
    novnc_port_range: tuple[int, int]
    display_range: tuple[int, int]
    viewport_width: int
    viewport_height: int
    idle_timeout_seconds: int
    no_sandbox: bool
    browser_extra_args: list[str]
    default_start_url: str

    @classmethod
    def from_env(cls) -> "BrowserSessionHubConfig":
        host = os.environ.get("BROWSER_SESSION_HUB_HOST", "127.0.0.1")
        sessions_root = Path(
            os.environ.get(
                "BROWSER_SESSION_HUB_SESSIONS_ROOT",
                str(_default_data_root() / "sessions"),
            )
        )
        host_root = Path(
            os.environ.get(
                "BROWSER_SESSION_HUB_HOST_ROOT",
                str(_default_data_root()),
            )
        )
        public_host = os.environ.get(
            "BROWSER_SESSION_HUB_PUBLIC_HOST",
            _default_public_host(host),
        )
        return cls(
            host=host,
            port=int(os.environ.get("BROWSER_SESSION_HUB_PORT", "8091")),
            public_scheme=os.environ.get(
                "BROWSER_SESSION_HUB_PUBLIC_SCHEME",
                "http",
            ),
            public_host=public_host,
            sessions_root=sessions_root,
            host_root=host_root,
            chrome_path=_resolve_required_binary(
                "BROWSER_SESSION_HUB_CHROME_PATH",
                "google-chrome",
                "google-chrome-stable",
                "chromium-browser",
                "chromium",
                "chrome",
            ),
            xvfb_path=_resolve_required_binary(
                "BROWSER_SESSION_HUB_XVFB_PATH",
                "Xvfb",
            ),
            openbox_path=_resolve_optional_binary(
                "BROWSER_SESSION_HUB_OPENBOX_PATH",
                "openbox",
            ),
            x11vnc_path=_resolve_required_binary(
                "BROWSER_SESSION_HUB_X11VNC_PATH",
                "x11vnc",
            ),
            novnc_proxy_path=_resolve_required_binary(
                "BROWSER_SESSION_HUB_NOVNC_PROXY_PATH",
                "novnc_proxy",
            ),
            cdp_bind_host=os.environ.get(
                "BROWSER_SESSION_HUB_CDP_BIND_HOST",
                "127.0.0.1",
            ),
            cdp_port_range=_parse_range(
                os.environ.get("BROWSER_SESSION_HUB_CDP_PORT_RANGE"),
                (9333, 9432),
            ),
            vnc_port_range=_parse_range(
                os.environ.get("BROWSER_SESSION_HUB_VNC_PORT_RANGE"),
                (5901, 6000),
            ),
            novnc_port_range=_parse_range(
                os.environ.get("BROWSER_SESSION_HUB_NOVNC_PORT_RANGE"),
                (6081, 6180),
            ),
            display_range=_parse_range(
                os.environ.get("BROWSER_SESSION_HUB_DISPLAY_RANGE"),
                (101, 200),
            ),
            viewport_width=int(
                os.environ.get("BROWSER_SESSION_HUB_VIEWPORT_WIDTH", "1440")
            ),
            viewport_height=int(
                os.environ.get("BROWSER_SESSION_HUB_VIEWPORT_HEIGHT", "900")
            ),
            idle_timeout_seconds=int(
                os.environ.get("BROWSER_SESSION_HUB_IDLE_TIMEOUT", "0")
            ),
            no_sandbox=_parse_bool(
                os.environ.get("BROWSER_SESSION_HUB_NO_SANDBOX"),
                default=False,
            ),
            browser_extra_args=_parse_args(
                os.environ.get("BROWSER_SESSION_HUB_BROWSER_EXTRA_ARGS")
            ),
            default_start_url=os.environ.get(
                "BROWSER_SESSION_HUB_DEFAULT_START_URL",
                "about:blank",
            ),
        )

    @property
    def dashboard_url(self) -> str:
        return f"{self.public_scheme}://{self.public_host}:{self.port}"

    @property
    def websocket_scheme(self) -> str:
        return "wss" if self.public_scheme == "https" else "ws"
