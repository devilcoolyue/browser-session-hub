"""Launch Playwright MCP against a Browser Session Hub session."""

from __future__ import annotations

import argparse
import atexit
from dataclasses import dataclass
import json
import logging
import os
import shlex
import signal
import subprocess
import sys
import threading
from typing import Any
import urllib.error
import urllib.request
from urllib.parse import urlparse, urlunparse


DEFAULT_MCP_COMMAND = "npx"
DEFAULT_MCP_PACKAGE = "@playwright/mcp@latest"
DEFAULT_TOUCH_INTERVAL_SECONDS = 15.0

logger = logging.getLogger(__name__)


class WrapperError(RuntimeError):
    """Raised when the wrapper cannot create or maintain a session."""


@dataclass
class WrapperConfig:
    """Runtime configuration for the wrapper."""

    base_url: str
    owner_id: str
    start_url: str | None
    viewport_width: int | None
    viewport_height: int | None
    persist_profile: bool
    metadata: dict[str, str]
    touch_interval_seconds: float
    cdp_host_override: str | None
    mcp_command: str
    mcp_package: str
    mcp_extra_args: list[str]


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


def _parse_bool(value: str | None, default: bool) -> bool:
    if value is None:
        return default
    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise WrapperError(f"Invalid boolean value: {value}")


def _parse_optional_int(value: str | None) -> int | None:
    if value in {None, ""}:
        return None
    return int(value)


def _parse_optional_float(value: str | None, default: float) -> float:
    if value in {None, ""}:
        return default
    return float(value)


def _parse_metadata_json(raw: str | None) -> dict[str, str]:
    if not raw:
        return {}
    payload = json.loads(raw)
    if not isinstance(payload, dict):
        raise WrapperError("BSH_METADATA_JSON must decode to an object")
    metadata: dict[str, str] = {}
    for key, value in payload.items():
        metadata[str(key)] = str(value)
    return metadata


def _parse_metadata_items(items: list[str]) -> dict[str, str]:
    metadata: dict[str, str] = {}
    for item in items:
        key, separator, value = item.partition("=")
        if not separator or not key:
            raise WrapperError(f"Invalid metadata item: {item!r}")
        metadata[key] = value
    return metadata


def _parse_shell_args(raw: str | None) -> list[str]:
    if not raw:
        return []
    return shlex.split(raw)


def create_parser() -> argparse.ArgumentParser:
    """Build the CLI parser."""
    env = os.environ
    parser = argparse.ArgumentParser(
        prog="browser-hub-playwright-wrapper",
        description="Create a Browser Session Hub session and attach Playwright MCP to it.",
    )
    parser.add_argument(
        "--log-level",
        default=env.get("BSH_LOG_LEVEL", "INFO"),
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
    )
    parser.add_argument(
        "--base-url",
        default=env.get("BSH_BASE_URL"),
        help="Browser Session Hub base URL, for example http://192.168.3.166:8091",
    )
    parser.add_argument(
        "--owner-id",
        default=env.get("BSH_OWNER_ID", "anonymous"),
        help="Isolation key passed through to Browser Session Hub.",
    )
    parser.add_argument(
        "--start-url",
        default=env.get("BSH_START_URL"),
        help="Initial page for the browser session.",
    )
    parser.add_argument(
        "--viewport-width",
        type=int,
        default=_parse_optional_int(env.get("BSH_VIEWPORT_WIDTH")),
    )
    parser.add_argument(
        "--viewport-height",
        type=int,
        default=_parse_optional_int(env.get("BSH_VIEWPORT_HEIGHT")),
    )
    persist_default = _parse_bool(env.get("BSH_PERSIST_PROFILE"), default=False)
    persist_group = parser.add_mutually_exclusive_group()
    persist_group.add_argument(
        "--persist-profile",
        dest="persist_profile",
        action="store_true",
        default=persist_default,
        help="Reuse the Browser Session Hub profile for this owner.",
    )
    persist_group.add_argument(
        "--no-persist-profile",
        dest="persist_profile",
        action="store_false",
        help="Use an ephemeral profile for this wrapper run.",
    )
    parser.add_argument(
        "--touch-interval",
        type=float,
        default=_parse_optional_float(
            env.get("BSH_TOUCH_INTERVAL"),
            default=DEFAULT_TOUCH_INTERVAL_SECONDS,
        ),
        help="Seconds between keepalive calls. Use 0 to disable.",
    )
    parser.add_argument(
        "--cdp-host-override",
        default=env.get("BSH_CDP_HOST_OVERRIDE"),
        help=(
            "Replace the host part of the returned CDP endpoint before launching "
            "Playwright MCP, for example 127.0.0.1."
        ),
    )
    parser.add_argument(
        "--metadata-json",
        default=env.get("BSH_METADATA_JSON"),
        help="JSON object merged into Browser Session Hub session metadata.",
    )
    parser.add_argument(
        "--metadata",
        action="append",
        default=[],
        metavar="KEY=VALUE",
        help="Additional metadata entry. Can be passed multiple times.",
    )
    parser.add_argument(
        "--mcp-command",
        default=env.get("BSH_MCP_COMMAND", DEFAULT_MCP_COMMAND),
        help="Executable used to launch Playwright MCP.",
    )
    parser.add_argument(
        "--mcp-package",
        default=env.get("BSH_MCP_PACKAGE", DEFAULT_MCP_PACKAGE),
        help="Package or command target passed to the MCP launcher.",
    )
    parser.add_argument(
        "--mcp-arg",
        action="append",
        default=[],
        metavar="ARG",
        help="Extra argument appended after --cdp-endpoint. Can be passed multiple times.",
    )
    return parser


def build_config(args: argparse.Namespace) -> WrapperConfig:
    """Normalize CLI arguments into a runtime config."""
    if not args.base_url:
        raise WrapperError("--base-url or BSH_BASE_URL is required")
    metadata = _parse_metadata_json(args.metadata_json)
    metadata.update(_parse_metadata_items(args.metadata))
    extra_args = _parse_shell_args(os.environ.get("BSH_MCP_ARGS"))
    extra_args.extend(args.mcp_arg)
    return WrapperConfig(
        base_url=args.base_url.rstrip("/"),
        owner_id=args.owner_id,
        start_url=args.start_url,
        viewport_width=args.viewport_width,
        viewport_height=args.viewport_height,
        persist_profile=args.persist_profile,
        metadata=metadata,
        touch_interval_seconds=args.touch_interval,
        cdp_host_override=args.cdp_host_override,
        mcp_command=args.mcp_command,
        mcp_package=args.mcp_package,
        mcp_extra_args=extra_args,
    )


def build_playwright_command(
    config: WrapperConfig,
    cdp_http_endpoint: str,
) -> list[str]:
    """Build the Playwright MCP command line."""
    return [
        config.mcp_command,
        "-y",
        config.mcp_package,
        "--cdp-endpoint",
        cdp_http_endpoint,
        *config.mcp_extra_args,
    ]


def _terminate_process(
    process: subprocess.Popen | None,
    timeout_seconds: float = 5.0,
) -> None:
    if process is None or process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=timeout_seconds)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=timeout_seconds)


def _decode_json_response(response: Any) -> Any:
    return json.loads(response.read().decode("utf-8"))


def _decode_http_error(exc: urllib.error.HTTPError) -> str:
    try:
        payload = json.loads(exc.read().decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return f"HTTP {exc.code} from {exc.url}"
    if isinstance(payload, dict) and payload.get("detail"):
        return f"HTTP {exc.code} from {exc.url}: {payload['detail']}"
    return f"HTTP {exc.code} from {exc.url}: {payload!r}"


def _replace_url_host(url: str, host: str) -> str:
    parsed = urlparse(url)
    if not parsed.scheme or parsed.hostname is None:
        raise WrapperError(f"Invalid URL: {url}")
    netloc = host
    if parsed.port is not None:
        netloc = f"{host}:{parsed.port}"
    return urlunparse(parsed._replace(netloc=netloc))


def _build_cdp_version_url(cdp_http_endpoint: str) -> str:
    return f"{cdp_http_endpoint.rstrip('/')}/json/version"


def _probe_cdp_endpoint(cdp_http_endpoint: str, timeout_seconds: float = 3.0) -> bool:
    request = urllib.request.Request(_build_cdp_version_url(cdp_http_endpoint))
    try:
        with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
            payload = _decode_json_response(response)
    except (urllib.error.URLError, urllib.error.HTTPError, json.JSONDecodeError):
        return False
    return isinstance(payload, dict) and "webSocketDebuggerUrl" in payload


def resolve_cdp_http_endpoint(
    config: WrapperConfig,
    cdp_http_endpoint: str,
) -> str:
    """Choose the CDP endpoint that Playwright MCP should use."""
    if config.cdp_host_override:
        resolved = _replace_url_host(cdp_http_endpoint, config.cdp_host_override)
        logger.info(
            "Overriding CDP endpoint host %s -> %s",
            cdp_http_endpoint,
            resolved,
        )
        return resolved

    if _probe_cdp_endpoint(cdp_http_endpoint):
        return cdp_http_endpoint

    parsed = urlparse(cdp_http_endpoint)
    host = parsed.hostname
    if host in {None, "127.0.0.1", "localhost"}:
        raise WrapperError(
            f"CDP endpoint is not reachable: {_build_cdp_version_url(cdp_http_endpoint)}"
        )

    for candidate_host in ("127.0.0.1", "localhost"):
        candidate = _replace_url_host(cdp_http_endpoint, candidate_host)
        if not _probe_cdp_endpoint(candidate):
            continue
        logger.warning(
            "CDP endpoint %s was unreachable; using local endpoint %s instead",
            cdp_http_endpoint,
            candidate,
        )
        return candidate

    raise WrapperError(
        "CDP endpoint is not reachable and no local fallback worked: "
        f"{_build_cdp_version_url(cdp_http_endpoint)}"
    )


def api_request(
    base_url: str,
    method: str,
    path: str,
    payload: dict[str, Any] | None = None,
    timeout_seconds: float = 10.0,
) -> Any:
    """Issue a JSON request to Browser Session Hub."""
    url = f"{base_url}{path}"
    headers: dict[str, str] = {}
    data: bytes | None = None
    if payload is not None:
        headers["Content-Type"] = "application/json"
        data = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=data,
        headers=headers,
        method=method,
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
            if getattr(response, "status", 200) == 204:
                return None
            return _decode_json_response(response)
    except urllib.error.HTTPError as exc:
        raise WrapperError(_decode_http_error(exc)) from exc
    except urllib.error.URLError as exc:
        raise WrapperError(f"Failed to reach Browser Session Hub at {url}: {exc}") from exc


class BrowserHubPlaywrightWrapper:
    """Manage one Browser Session Hub session and a Playwright MCP child."""

    def __init__(self, config: WrapperConfig) -> None:
        self._config = config
        self._child_process: subprocess.Popen | None = None
        self._session_id: str | None = None
        self._stop_event = threading.Event()
        self._touch_thread: threading.Thread | None = None
        self._cleanup_lock = threading.Lock()
        self._cleaned_up = False
        self._fatal_error_lock = threading.Lock()
        self._fatal_error: str | None = None
        self._previous_signal_handlers: dict[int, Any] = {}
        self._received_signal: int | None = None
        self._atexit_registered = False

    def run(self) -> int:
        """Run the wrapper until the Playwright MCP child exits."""
        session = self._create_session()
        self._session_id = str(session["session_id"])
        if not self._atexit_registered:
            atexit.register(self.cleanup)
            self._atexit_registered = True
        logger.info(
            "Created session %s owner=%s cdp=%s preview=%s",
            self._session_id,
            self._config.owner_id,
            session["cdp_http_endpoint"],
            session.get("preview_url", ""),
        )
        self._install_signal_handlers()
        self._start_touch_thread()
        resolved_cdp_http_endpoint = resolve_cdp_http_endpoint(
            self._config,
            str(session["cdp_http_endpoint"]),
        )
        command = build_playwright_command(
            self._config,
            resolved_cdp_http_endpoint,
        )
        if self._fatal_error is not None:
            raise WrapperError(self._fatal_error)
        logger.info("Launching Playwright MCP command: %s", shlex.join(command))
        try:
            self._child_process = subprocess.Popen(command)
        except FileNotFoundError as exc:
            raise WrapperError(
                f"Unable to launch {self._config.mcp_command}: {exc}"
            ) from exc

        try:
            exit_code = self._wait_for_child()
            if self._received_signal is not None:
                return 128 + self._received_signal
            if self._fatal_error is not None:
                return 1
            return exit_code
        finally:
            self.cleanup()
            self._restore_signal_handlers()

    def _create_session(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "owner_id": self._config.owner_id,
            "persist_profile": self._config.persist_profile,
            "metadata": self._config.metadata,
        }
        if self._config.start_url:
            payload["start_url"] = self._config.start_url
        if self._config.viewport_width is not None:
            payload["viewport_width"] = self._config.viewport_width
        if self._config.viewport_height is not None:
            payload["viewport_height"] = self._config.viewport_height
        response = api_request(
            self._config.base_url,
            "POST",
            "/api/sessions",
            payload=payload,
        )
        if not isinstance(response, dict) or "session" not in response:
            raise WrapperError("Browser Session Hub did not return a session payload")
        session = response["session"]
        if not isinstance(session, dict) or "session_id" not in session:
            raise WrapperError("Browser Session Hub returned an invalid session payload")
        return session

    def _touch_session(self) -> None:
        if not self._session_id:
            return
        api_request(
            self._config.base_url,
            "POST",
            f"/api/sessions/{self._session_id}/touch",
        )

    def _delete_session(self) -> None:
        if not self._session_id:
            return
        api_request(
            self._config.base_url,
            "DELETE",
            f"/api/sessions/{self._session_id}",
        )

    def _start_touch_thread(self) -> None:
        if self._config.touch_interval_seconds <= 0:
            return
        self._touch_thread = threading.Thread(
            target=self._touch_loop,
            name="browser-session-touch",
            daemon=True,
        )
        self._touch_thread.start()

    def _touch_loop(self) -> None:
        while not self._stop_event.wait(self._config.touch_interval_seconds):
            try:
                self._touch_session()
            except WrapperError as exc:
                self._request_exit(
                    f"Browser Session Hub session {self._session_id} became unavailable: "
                    f"{exc}"
                )
                return

    def _install_signal_handlers(self) -> None:
        for signum in (signal.SIGINT, signal.SIGTERM):
            self._previous_signal_handlers[signum] = signal.getsignal(signum)
            signal.signal(signum, self._handle_signal)

    def _restore_signal_handlers(self) -> None:
        for signum, previous_handler in self._previous_signal_handlers.items():
            signal.signal(signum, previous_handler)
        self._previous_signal_handlers.clear()

    def _handle_signal(self, signum: int, _frame: Any) -> None:
        logger.info("Received signal %s, shutting down Playwright MCP wrapper", signum)
        self._received_signal = signum
        self._stop_event.set()
        _terminate_process(self._child_process)

    def _wait_for_child(self) -> int:
        if self._child_process is None:
            raise WrapperError("Playwright MCP process was not started")
        while True:
            try:
                return self._child_process.wait()
            except InterruptedError:
                continue

    def _request_exit(self, reason: str) -> None:
        with self._fatal_error_lock:
            if self._fatal_error is not None:
                return
            self._fatal_error = reason
        logger.error("%s", reason)
        self._stop_event.set()
        _terminate_process(self._child_process)

    def cleanup(self) -> None:
        """Stop background activity and delete the active session."""
        with self._cleanup_lock:
            if self._cleaned_up:
                return
            self._cleaned_up = True
        self._stop_event.set()
        _terminate_process(self._child_process)
        if self._touch_thread is not None:
            self._touch_thread.join(timeout=1.0)
        try:
            self._delete_session()
        except WrapperError as exc:
            logger.warning(
                "Failed to delete Browser Session Hub session %s: %s",
                self._session_id,
                exc,
            )
        else:
            if self._session_id:
                logger.info("Deleted session %s", self._session_id)


def main(argv: list[str] | None = None) -> int:
    """CLI entrypoint."""
    parser = create_parser()
    args = parser.parse_args(argv)
    _setup_logging(args.log_level)
    try:
        config = build_config(args)
        wrapper = BrowserHubPlaywrightWrapper(config)
        return wrapper.run()
    except WrapperError as exc:
        logger.error("%s", exc)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
