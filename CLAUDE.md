# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What This Project Is

Browser Session Hub is a Python microservice that manages isolated headed-browser sessions on Linux. Each session runs its own Xvfb → Openbox → Chrome → x11vnc → noVNC stack, exposed via a FastAPI REST API with CDP endpoints and web-based VNC preview.

## Development Setup

```bash
python3 -m venv .venv && . .venv/bin/activate && pip install -e .
```

Requires Python >= 3.10. Runtime depends on Linux host binaries: Chrome/Chromium, Xvfb, x11vnc, novnc_proxy, and optionally openbox.

## Commands

```bash
# Run the service
browser-session-hub                          # default http://127.0.0.1:8091
browser-session-hub --daemon --log-level DEBUG
python -m browser_session_hub                # alternative

# Run all tests
pytest

# Run a single test file
pytest tests/test_app.py -q

# Run a specific test
pytest tests/test_session_manager.py::test_name -v
```

No linter or formatter is configured. Match existing style.

## Architecture

**Source layout:** `src/browser_session_hub/` with tests mirroring under `tests/`.

**Key modules and their roles:**

- **cli.py** — Entry point. Parses `--host`, `--port`, `--daemon`, `--log-level`. Daemon mode forks a background process with PID file.
- **config.py** — Reads all settings from `BROWSER_SESSION_HUB_*` environment variables. Resolves binary paths (env override → PATH lookup). No hardcoded paths.
- **app.py** — FastAPI application factory (`create_app`). Lifespan manages the `BrowserSessionManager`. Optional idle-session cleanup loop. Serves the static dashboard at `/`.
- **session_manager.py** — Core orchestrator. `BrowserSessionManager` is thread-safe (RLock). Creates sessions by allocating ports/displays, then starting 5 subprocesses in sequence. Manages graceful teardown in reverse order.
- **models.py** — Pydantic v2 schemas for API request/response. `SessionStatus` enum: `starting|running|stopped|error`.
- **process_utils.py** — Subprocess helpers: port/display availability checks, process termination, HTTP polling (`wait_for_json`), sanitized env construction.
- **browser_hub_playwright_wrapper.py** — Standalone adapter that creates a Hub session, launches Playwright MCP against its CDP endpoint, and keeps the session alive with periodic touch calls. Separate CLI entry point (`browser-hub-playwright-wrapper`).
- **static/** — Dashboard HTML/JS/CSS served by FastAPI.

**Session creation flow:**
`POST /api/sessions` → allocate ports + display → start Xvfb → Openbox → Chrome (with CDP) → x11vnc → noVNC proxy → poll readiness → return `SessionSummary` with CDP HTTP endpoint and preview URL.

**Session teardown:** Processes terminated in reverse order, ports released, working directory cleaned (unless `persist_profile=true`).

## Coding Conventions

- 4-space indentation, `from __future__ import annotations` in all modules
- Type hints on public functions
- `snake_case` for functions/variables/tests, `PascalCase` for classes/models
- Tests use pytest + `TestClient`, `tmp_path`, `monkeypatch`. Mock subprocess calls rather than depending on real system binaries in unit tests.

## Configuration

All config via `BROWSER_SESSION_HUB_*` env vars. Key ones: `HOST`, `PORT`, `CHROME_PATH`, `XVFB_PATH`, `X11VNC_PATH`, `NOVNC_PROXY_PATH`, `CDP_PORT_RANGE`, `VNC_PORT_RANGE`, `NOVNC_PORT_RANGE`, `DISPLAY_RANGE`, `IDLE_TIMEOUT`, `NO_SANDBOX`.

The Playwright wrapper uses `PLAYWRIGHT_WRAPPER_*` env vars.

## API Routes

- `GET /api/health` — health check
- `GET /api/dependencies` — runtime dependency status
- `GET|POST /api/sessions` — list or create sessions
- `GET /api/sessions/{id}` — session details
- `POST /api/sessions/{id}/touch` — refresh activity timestamp
- `DELETE /api/sessions/{id}` — stop session
