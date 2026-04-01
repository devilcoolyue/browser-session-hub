# Browser Session Hub

Chinese documentation: [README.zh-CN.md](README.zh-CN.md)

Browser Session Hub is a self-hosted browser orchestration service for agent workflows that need all of the following at the same time:

- a dedicated Chromium instance per session
- a CDP endpoint for Playwright MCP or other automation clients
- a human-viewable live preview
- direct human takeover through the preview page
- isolation between users and sessions

The service does not use JPEG frame streaming. Instead, each session runs a real headed browser inside `Xvfb`, exports the desktop through `x11vnc`, and exposes a browser-friendly viewer through `noVNC`.

## Why This Exists

The original `browser-live-view` project is optimized around CDP screencast frames over WebSocket. That works for lightweight observation, but it is not ideal for a shared human-and-agent control plane. Browser Session Hub changes the architecture:

```text
┌────────────────────────────┐
│ Browser Session Hub        │
│ FastAPI + dashboard        │
└─────────────┬──────────────┘
              │ create session
              ▼
┌────────────────────────────────────────────────────┐
│ Session N                                          │
│  Xvfb display                                      │
│  Openbox (optional)                                │
│  Headed Chrome/Chromium                            │
│  CDP port 933x                                     │
│  x11vnc port 590x (localhost only)                 │
│  novnc_proxy port 608x                             │
│  isolated user-data-dir                            │
└────────────────────────────────────────────────────┘
              │                         │
              │                         │
              ▼                         ▼
   Playwright MCP via CDP        Human preview via noVNC
```

## Features

- Per-session Chromium process isolation
- Per-session `--user-data-dir` isolation
- CDP endpoint ready for `connectOverCDP()`
- Human preview and takeover through noVNC
- Optional persistent profile mode per owner
- Minimal dashboard for creating, selecting, and stopping sessions
- API-first design so another orchestrator can create sessions programmatically

## Linux Deployment Requirements

Deploying this service on Linux requires both Python dependencies and host-level GUI / remote-desktop components.

### Required host components

| Component | Required | Purpose |
| --- | --- | --- |
| Python 3.10+ | yes | Runs the FastAPI service |
| `pip` and `venv` support | yes | Installs the Python package in an isolated environment |
| Google Chrome or Chromium | yes | Real headed browser process for each session |
| `Xvfb` | yes | Per-session virtual X display |
| `x11vnc` | yes | Exposes the Xvfb desktop as VNC on localhost |
| `noVNC` with `novnc_proxy` | yes | Converts the VNC session into a browser preview page |
| `openbox` | no | Optional lightweight window manager for cleaner desktop behavior |

The current code resolves the following binaries at startup, either from `PATH` or from environment overrides:

- browser: `google-chrome`, `google-chrome-stable`, `chromium-browser`, `chromium`, or `chrome`
- `Xvfb`
- `x11vnc`
- `novnc_proxy`
- `openbox` is optional

### Required Linux capabilities

- The service account must be able to create and remove directories under the configured session root.
- The host must allow binding to the configured API port and the configured CDP / VNC / noVNC port ranges.
- The browser binary must support the DevTools remote debugging flags used by Chromium-based browsers.

### Ubuntu example

Install system packages:

```bash
sudo apt-get update
sudo apt-get install -y python3 python3-venv python3-pip xvfb x11vnc novnc openbox
```

Install Chrome or Chromium separately. Chrome for Linux is officially supported by Google:

- https://support.google.com/chrome/answer/16737616

### CentOS Stream 9 example

This repository requires Python `>=3.10`. On CentOS Stream 9, the default `python3` is typically Python 3.9, so use Python 3.11 for the project environment.

Install system packages:

```bash
sudo dnf install -y epel-release dnf-plugins-core
sudo dnf config-manager --set-enabled crb
sudo dnf install -y \
  python3.11 \
  python3.11-pip \
  chromium \
  xorg-x11-server-Xvfb \
  x11vnc \
  novnc \
  openbox
```

Then create the virtual environment with Python 3.11:

```bash
python3.11 -m venv .venv
. .venv/bin/activate
pip install --upgrade pip
pip install -e .
```

Verify the installed components:

```bash
bash scripts/check_linux_dependencies.sh
```

Notes:

- `chromium`, `x11vnc`, `novnc`, and `openbox` are typically provided through EPEL 9.
- the `novnc` package provides the `novnc_proxy` binary expected by this service.
- if you prefer Google Chrome over Chromium, install Chrome separately using Google's official Linux instructions.
- if `pip install -e .` still fails on an older host toolchain, run `python3.11 -m pip install --upgrade pip setuptools wheel` first.

Playwright references for headed Linux and MCP configuration:

- https://playwright.dev/docs/docker
- https://playwright.dev/docs/next/getting-started-mcp

## Installation

```bash
cd browser-session-hub
python3 -m venv .venv
. .venv/bin/activate
pip install -e .
```

If the target host has an older `pip` or `setuptools`, the repository also includes a minimal `setup.py` so legacy editable installs still work.

## Run

```bash
browser-session-hub
```

Run in the background:

```bash
browser-session-hub --daemon
```

Default service URL:

```text
http://127.0.0.1:8091
```

Before starting the service on Linux, make sure `google-chrome` or `chromium`, `Xvfb`, `x11vnc`, and `novnc_proxy` are installed and resolvable on `PATH`, or set the corresponding `BROWSER_SESSION_HUB_*_PATH` environment variables.

Default daemon paths:

```text
log file: ~/.browser-session-hub/logs/browser-session-hub.log
pid file: ~/.browser-session-hub/run/browser-session-hub.pid
```

The `--daemon` command prints the resolved log file and pid file paths after the background process is created.

## Environment Variables

Key settings:

| Variable | Default | Description |
| --- | --- | --- |
| `BROWSER_SESSION_HUB_HOST` | `127.0.0.1` | API bind host |
| `BROWSER_SESSION_HUB_PORT` | `8091` | API bind port |
| `BROWSER_SESSION_HUB_PUBLIC_SCHEME` | `http` | Scheme used in returned URLs |
| `BROWSER_SESSION_HUB_PUBLIC_HOST` | derived from host | Hostname used in returned URLs |
| `BROWSER_SESSION_HUB_SESSIONS_ROOT` | `~/.browser-session-hub/sessions` | Session working directories |
| `BROWSER_SESSION_HUB_HOST_ROOT` | `~/.browser-session-hub` | Shared root for persistent profiles |
| `BROWSER_SESSION_HUB_LOG_DIR` | `~/.browser-session-hub/logs` | Default directory for service logs |
| `BROWSER_SESSION_HUB_RUN_DIR` | `~/.browser-session-hub/run` | Default directory for pid and runtime files |
| `BROWSER_SESSION_HUB_LOG_FILE` | `~/.browser-session-hub/logs/browser-session-hub.log` | Log file used by `--daemon` |
| `BROWSER_SESSION_HUB_PID_FILE` | `~/.browser-session-hub/run/browser-session-hub.pid` | Pid file used by `--daemon` |
| `BROWSER_SESSION_HUB_CDP_BIND_HOST` | `127.0.0.1` | CDP listen host for Chrome |
| `BROWSER_SESSION_HUB_CDP_PORT_RANGE` | `9333-9432` | CDP ports assigned to sessions |
| `BROWSER_SESSION_HUB_VNC_PORT_RANGE` | `5901-6000` | Internal VNC ports |
| `BROWSER_SESSION_HUB_NOVNC_PORT_RANGE` | `6081-6180` | noVNC ports exposed to users |
| `BROWSER_SESSION_HUB_DISPLAY_RANGE` | `101-200` | Xvfb display numbers |
| `BROWSER_SESSION_HUB_VIEWPORT_WIDTH` | `1440` | Browser width |
| `BROWSER_SESSION_HUB_VIEWPORT_HEIGHT` | `900` | Browser height |
| `BROWSER_SESSION_HUB_IDLE_TIMEOUT` | `0` | Idle timeout in seconds, disabled when `0` |
| `BROWSER_SESSION_HUB_NO_SANDBOX` | `false` | Add `--no-sandbox` when needed |

Binary overrides:

- `BROWSER_SESSION_HUB_CHROME_PATH`
- `BROWSER_SESSION_HUB_XVFB_PATH`
- `BROWSER_SESSION_HUB_OPENBOX_PATH`
- `BROWSER_SESSION_HUB_X11VNC_PATH`
- `BROWSER_SESSION_HUB_NOVNC_PROXY_PATH`

## Daemon Example

Example with explicit public host, root-safe Chrome launch, and daemon mode:

```bash
export BROWSER_SESSION_HUB_PUBLIC_HOST=180.184.84.200
export BROWSER_SESSION_HUB_NO_SANDBOX=true
browser-session-hub --daemon
```

Example with custom daemon log and pid locations:

```bash
export BROWSER_SESSION_HUB_LOG_FILE=/var/log/browser-session-hub/service.log
export BROWSER_SESSION_HUB_PID_FILE=/var/run/browser-session-hub.pid
browser-session-hub --daemon
```

## Deployment Checklist

Use this checklist before the first Linux deployment:

1. Install Python 3.10+, `venv`, and `pip`.
2. Install Chrome or Chromium.
3. Install `Xvfb`, `x11vnc`, and `noVNC` so that `novnc_proxy` is available on `PATH`.
4. Optionally install `openbox`.
5. Create a virtual environment and run `pip install -e .`.
6. Confirm `/api/dependencies` reports all required components as available.
7. Verify the configured API port and the CDP / VNC / noVNC port ranges are reachable as intended on the target host.

## Dependency Verification

After installing the host packages, run:

```bash
bash scripts/check_linux_dependencies.sh
```

The script checks:

- Python version, `venv`, and `pip`
- a Chromium-compatible browser binary
- `Xvfb`
- `x11vnc`
- `novnc_proxy`
- `openbox` as an optional component

Exit code rules:

- `0`: all required components were found
- `1`: one or more required components are missing or unusable

After the service starts, you can also verify what the app sees:

```bash
curl -s http://127.0.0.1:8091/api/dependencies
```

## API

### Create a session

```bash
curl -s http://127.0.0.1:8091/api/sessions \
  -H 'content-type: application/json' \
  -d '{
    "owner_id": "alice",
    "start_url": "https://example.com"
  }'
```

Example response:

```json
{
  "session": {
    "session_id": "2c1f6f8eb8ce",
    "owner_id": "alice",
    "status": "running",
    "cdp_http_endpoint": "http://127.0.0.1:9333",
    "cdp_ws_endpoint": "ws://127.0.0.1:9333/devtools/browser/...",
    "preview_url": "http://127.0.0.1:6081/vnc.html?autoconnect=1&resize=remote&reconnect=1"
  }
}
```

### Use with Playwright MCP

Point the MCP server to the returned `cdp_http_endpoint`:

```json
{
  "mcpServers": {
    "playwright": {
      "command": "npx",
      "args": [
        "-y",
        "@playwright/mcp@latest",
        "--cdp-endpoint",
        "http://127.0.0.1:9333"
      ]
    }
  }
}
```

If your orchestrator runs on the same machine as Browser Session Hub and Chromium only
exposes DevTools on loopback, use the wrapper and force the MCP-side CDP host to
`127.0.0.1`:

```json
{
  "mcpServers": {
    "playwright": {
      "command": "/data/app/browser-session-hub/.venv/bin/browser-hub-playwright-wrapper",
      "args": [
        "--base-url",
        "http://127.0.0.1:8091",
        "--owner-id",
        "agent:default",
        "--touch-interval",
        "20",
        "--start-url",
        "about:blank",
        "--cdp-host-override",
        "127.0.0.1",
        "--mcp-arg=--browser",
        "--mcp-arg=chromium"
      ]
    }
  }
}
```

### Preview

The dashboard embeds the returned `preview_url` in an iframe. You can also open it directly in a new tab.

## Notes

- VNC itself is kept on localhost. Users connect through noVNC.
- The current implementation returns direct noVNC URLs instead of reverse-proxying them through the API service.
- Persistent profiles are exclusive per owner. A second concurrent session cannot reuse the same persistent profile directory.

## Current Integration Status

The current implementation is already sufficient for a basic CoPaw integration where:

- CoPaw creates a session through `POST /api/sessions`
- CoPaw reads the returned `cdp_http_endpoint`
- Playwright MCP is started with that `cdp_http_endpoint`
- a frontend page embeds the returned `preview_url` to show the live browser desktop through noVNC

In other words, the core flow "agent drives Chrome through CDP while a human watches the live page" is already supported by this service.

Current limitations to keep in mind:

- this has only been unit-tested in the current workspace, not end-to-end on a Linux host with real `Chrome/Chromium + Xvfb + x11vnc + novnc_proxy`
- `preview_url` currently points directly to the per-session noVNC port instead of going through the main service
- there is no access-token or reverse-proxy layer on preview traffic yet
- idle-session renewal currently depends on explicit `/touch` calls rather than a stronger lease model

## Recommended Next Iteration Order

To keep later CoPaw integration work stable, follow this order for the next rounds of implementation:

1. Add an in-service preview reverse proxy and short-lived preview tokens so users no longer access raw noVNC ports directly.
2. Replace the current `/touch`-only keepalive model with a proper lease or heartbeat design, and make preview access refresh activity automatically.
3. Add authentication and ownership enforcement so `owner_id` comes from trusted server-side context instead of raw client input.
4. Add production hardening: session quotas, clearer failure reporting, Linux smoke tests, and deployment examples.
5. Integrate the real CoPaw MCP create/renew/stop flow on top of the hardened contract.

The reason for this order is simple: the orchestration core already works, but the external exposure surface is still too open. Closing preview access and lease semantics first reduces the risk of baking weak assumptions into the later CoPaw integration.

## Tests

```bash
pytest
```
