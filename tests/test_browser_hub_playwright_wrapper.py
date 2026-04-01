from __future__ import annotations

import json
import urllib.error

from browser_session_hub.browser_hub_playwright_wrapper import (
    BrowserHubPlaywrightWrapper,
    WrapperConfig,
    build_config,
    build_playwright_command,
    create_parser,
    resolve_cdp_http_endpoint,
)


class FakeJsonResponse:
    def __init__(self, payload: object, status: int = 200):
        self._payload = payload
        self.status = status

    def read(self) -> bytes:
        return json.dumps(self._payload).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


def make_config() -> WrapperConfig:
    return WrapperConfig(
        base_url="http://127.0.0.1:8091",
        owner_id="agent:test",
        start_url="https://example.com",
        viewport_width=1280,
        viewport_height=900,
        persist_profile=True,
        metadata={"agent_id": "test"},
        touch_interval_seconds=0,
        cdp_host_override=None,
        mcp_command="npx",
        mcp_package="@playwright/mcp@latest",
        mcp_extra_args=["--browser", "chromium"],
    )


def test_build_config_merges_env_and_cli_metadata(monkeypatch):
    monkeypatch.setenv("BSH_BASE_URL", "http://127.0.0.1:8091")
    monkeypatch.setenv("BSH_PERSIST_PROFILE", "true")
    monkeypatch.setenv("BSH_MCP_ARGS", "--headless=false")
    monkeypatch.setenv("BSH_METADATA_JSON", '{"user_id": "u-1"}')
    monkeypatch.setenv("BSH_CDP_HOST_OVERRIDE", "127.0.0.1")

    parser = create_parser()
    args = parser.parse_args(
        [
            "--owner-id",
            "agent:planner",
            "--metadata",
            "agent_id=a-1",
            "--mcp-arg=--trace=retain-on-failure",
        ]
    )

    config = build_config(args)

    assert config.base_url == "http://127.0.0.1:8091"
    assert config.owner_id == "agent:planner"
    assert config.persist_profile is True
    assert config.cdp_host_override == "127.0.0.1"
    assert config.metadata == {"user_id": "u-1", "agent_id": "a-1"}
    assert config.mcp_extra_args == [
        "--headless=false",
        "--trace=retain-on-failure",
    ]


def test_build_playwright_command_appends_cdp_endpoint():
    command = build_playwright_command(make_config(), "http://127.0.0.1:9333")

    assert command == [
        "npx",
        "-y",
        "@playwright/mcp@latest",
        "--cdp-endpoint",
        "http://127.0.0.1:9333",
        "--browser",
        "chromium",
    ]


def test_wrapper_run_creates_session_and_deletes_it(monkeypatch):
    requests: list[tuple[str, str, object | None]] = []
    popen_calls: list[list[str]] = []

    class FakeProcess:
        def __init__(self):
            self.returncode: int | None = None

        def wait(self, timeout: float | None = None) -> int:
            self.returncode = 0
            return 0

        def poll(self) -> int | None:
            return self.returncode

        def terminate(self) -> None:
            self.returncode = -15

        def kill(self) -> None:
            self.returncode = -9

    def fake_urlopen(request, timeout=10.0):
        payload = (
            json.loads(request.data.decode("utf-8"))
            if request.data is not None
            else None
        )
        requests.append((request.get_method(), request.full_url, payload))
        if request.get_method() == "POST" and request.full_url.endswith("/api/sessions"):
            return FakeJsonResponse(
                {
                    "session": {
                        "session_id": "session-123",
                        "cdp_http_endpoint": "http://127.0.0.1:9334",
                        "preview_url": "http://127.0.0.1:6081/vnc.html",
                    }
                }
            )
        if request.full_url == "http://127.0.0.1:9334/json/version":
            return FakeJsonResponse(
                {
                    "webSocketDebuggerUrl": (
                        "ws://127.0.0.1:9334/devtools/browser/session-123"
                    )
                }
            )
        return FakeJsonResponse({"ok": True})

    def fake_popen(command, **kwargs):
        popen_calls.append(command)
        assert kwargs == {}
        return FakeProcess()

    monkeypatch.setattr(
        "browser_session_hub.browser_hub_playwright_wrapper.urllib.request.urlopen",
        fake_urlopen,
    )
    monkeypatch.setattr(
        "browser_session_hub.browser_hub_playwright_wrapper.subprocess.Popen",
        fake_popen,
    )

    wrapper = BrowserHubPlaywrightWrapper(make_config())

    exit_code = wrapper.run()

    assert exit_code == 0
    assert requests == [
        (
            "POST",
            "http://127.0.0.1:8091/api/sessions",
            {
                "owner_id": "agent:test",
                "start_url": "https://example.com",
                "viewport_width": 1280,
                "viewport_height": 900,
                "persist_profile": True,
                "metadata": {"agent_id": "test"},
            },
        ),
        (
            "GET",
            "http://127.0.0.1:9334/json/version",
            None,
        ),
        (
            "DELETE",
            "http://127.0.0.1:8091/api/sessions/session-123",
            None,
        ),
    ]
    assert popen_calls == [
        [
            "npx",
            "-y",
            "@playwright/mcp@latest",
            "--cdp-endpoint",
            "http://127.0.0.1:9334",
            "--browser",
            "chromium",
        ]
    ]


def test_resolve_cdp_http_endpoint_uses_override():
    config = make_config()
    config.cdp_host_override = "127.0.0.1"

    resolved = resolve_cdp_http_endpoint(config, "http://192.168.3.166:9333")

    assert resolved == "http://127.0.0.1:9333"


def test_wrapper_run_falls_back_to_loopback_for_cdp(monkeypatch):
    requests: list[tuple[str, str, object | None]] = []
    popen_calls: list[list[str]] = []

    class FakeProcess:
        def __init__(self):
            self.returncode: int | None = None

        def wait(self, timeout: float | None = None) -> int:
            self.returncode = 0
            return 0

        def poll(self) -> int | None:
            return self.returncode

        def terminate(self) -> None:
            self.returncode = -15

        def kill(self) -> None:
            self.returncode = -9

    def fake_urlopen(request, timeout=10.0):
        payload = (
            json.loads(request.data.decode("utf-8"))
            if getattr(request, "data", None) is not None
            else None
        )
        requests.append((request.get_method(), request.full_url, payload))
        if request.get_method() == "POST" and request.full_url.endswith("/api/sessions"):
            return FakeJsonResponse(
                {
                    "session": {
                        "session_id": "session-123",
                        "cdp_http_endpoint": "http://192.168.3.166:9334",
                        "preview_url": "http://192.168.3.166:6081/vnc.html",
                    }
                }
            )
        if request.full_url == "http://192.168.3.166:9334/json/version":
            raise urllib.error.URLError("connection refused")
        if request.full_url == "http://127.0.0.1:9334/json/version":
            return FakeJsonResponse(
                {
                    "webSocketDebuggerUrl": (
                        "ws://127.0.0.1:9334/devtools/browser/session-123"
                    )
                }
            )
        return FakeJsonResponse({"ok": True})

    def fake_popen(command, **kwargs):
        popen_calls.append(command)
        assert kwargs == {}
        return FakeProcess()

    monkeypatch.setattr(
        "browser_session_hub.browser_hub_playwright_wrapper.urllib.request.urlopen",
        fake_urlopen,
    )
    monkeypatch.setattr(
        "browser_session_hub.browser_hub_playwright_wrapper.subprocess.Popen",
        fake_popen,
    )

    wrapper = BrowserHubPlaywrightWrapper(make_config())

    exit_code = wrapper.run()

    assert exit_code == 0
    assert popen_calls == [
        [
            "npx",
            "-y",
            "@playwright/mcp@latest",
            "--cdp-endpoint",
            "http://127.0.0.1:9334",
            "--browser",
            "chromium",
        ]
    ]
