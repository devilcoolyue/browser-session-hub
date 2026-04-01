# Browser Session Hub

英文版文档： [README.md](README.md)

Browser Session Hub 是一个自托管的浏览器会话编排服务，适合需要同时满足以下条件的 agent 工作流：

- 每个会话独立的 Chromium 实例
- 可供 Playwright MCP 或其他自动化客户端连接的 CDP endpoint
- 人可直接查看的实时预览页面
- 人可以直接接管浏览器进行操作
- 用户和会话之间相互隔离

这个服务不再使用 JPEG 帧推流，而是让每个会话运行在真实的有头浏览器桌面中：`Xvfb + Chrome/Chromium + x11vnc + noVNC`。

## 为什么要做这个

原先基于 CDP screencast 帧流的方案更适合轻量观察，但不适合作为“agent 和人共同操作同一浏览器”的控制面。Browser Session Hub 的思路是：

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
│  Openbox（可选）                                   │
│  Headed Chrome/Chromium                            │
│  CDP port 933x                                     │
│  x11vnc port 590x（仅 localhost）                  │
│  novnc_proxy port 608x                             │
│  隔离的 user-data-dir                              │
└────────────────────────────────────────────────────┘
              │                         │
              │                         │
              ▼                         ▼
   Playwright MCP 通过 CDP        人通过 noVNC 看实时画面
```

## 功能特性

- 每会话独立 Chromium 进程
- 每会话独立 `--user-data-dir`
- 返回可直接用于 `connectOverCDP()` 的 CDP endpoint
- 通过 noVNC 提供实时预览和人工接管
- 支持按 owner 复用持久 profile
- 自带最小 dashboard，可创建、选择、停止会话
- API 优先设计，方便外部编排器接入

## Linux 部署依赖

部署到 Linux 时，需要同时满足 Python 运行依赖和宿主机图形链路依赖。

### 宿主机必备组件

| 组件 | 是否必需 | 作用 |
| --- | --- | --- |
| Python 3.10+ | 必需 | 运行 FastAPI 服务 |
| `pip` 和 `venv` | 必需 | 安装 Python 包并隔离运行环境 |
| Google Chrome 或 Chromium | 必需 | 每个会话的真实浏览器进程 |
| `Xvfb` | 必需 | 为每个会话提供独立虚拟显示 |
| `x11vnc` | 必需 | 将 Xvfb 桌面导出为本地 VNC |
| `noVNC` 和 `novnc_proxy` | 必需 | 将 VNC 转成浏览器可访问的预览页面 |
| `openbox` | 可选 | 轻量窗口管理器，桌面行为更稳定 |

当前代码启动时会尝试从 `PATH` 或环境变量中解析以下二进制：

- 浏览器：`google-chrome`、`google-chrome-stable`、`chromium-browser`、`chromium`、`chrome`
- `Xvfb`
- `x11vnc`
- `novnc_proxy`
- `openbox` 可选

### Linux 侧运行前提

- 运行服务的账号需要对会话目录有创建和删除权限。
- 宿主机需要允许绑定 API 端口，以及配置中的 CDP / VNC / noVNC 端口范围。
- 浏览器必须支持 Chromium DevTools Remote Debugging 参数。

### Ubuntu 安装示例

```bash
sudo apt-get update
sudo apt-get install -y python3 python3-venv python3-pip xvfb x11vnc novnc openbox
```

Chrome 或 Chromium 需要另外安装。Chrome for Linux 官方安装说明：

- https://support.google.com/chrome/answer/16737616

### CentOS Stream 9 安装示例

这个项目要求 Python `>=3.10`。而 CentOS Stream 9 的默认 `python3` 通常是 Python 3.9，所以这里建议直接使用 Python 3.11。

先安装系统依赖：

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

然后用 Python 3.11 创建虚拟环境：

```bash
python3.11 -m venv .venv
. .venv/bin/activate
pip install --upgrade pip
pip install -e .
```

安装完成后，可以直接运行下面的检查命令：

```bash
bash scripts/check_linux_dependencies.sh
```

补充说明：

- `chromium`、`x11vnc`、`novnc`、`openbox` 一般来自 EPEL 9。
- `novnc` 包会提供这个服务需要的 `novnc_proxy` 可执行文件。
- 如果你更想用 Google Chrome 而不是 Chromium，建议按 Google 官方 Linux 安装说明单独安装。

Playwright 关于 Linux 有头模式和 MCP 的参考文档：

- https://playwright.dev/docs/docker
- https://playwright.dev/docs/next/getting-started-mcp

## 安装

```bash
cd browser-session-hub
python3 -m venv .venv
. .venv/bin/activate
pip install -e .
```

## 运行

```bash
browser-session-hub
```

默认服务地址：

```text
http://127.0.0.1:8091
```

在 Linux 上启动前，请确认 `google-chrome` 或 `chromium`、`Xvfb`、`x11vnc`、`novnc_proxy` 都能在 `PATH` 中找到，或者通过对应的 `BROWSER_SESSION_HUB_*_PATH` 环境变量显式指定。

## 环境变量

关键配置项：

| 变量 | 默认值 | 说明 |
| --- | --- | --- |
| `BROWSER_SESSION_HUB_HOST` | `127.0.0.1` | API 绑定地址 |
| `BROWSER_SESSION_HUB_PORT` | `8091` | API 监听端口 |
| `BROWSER_SESSION_HUB_PUBLIC_SCHEME` | `http` | 返回 URL 时使用的 scheme |
| `BROWSER_SESSION_HUB_PUBLIC_HOST` | 从 host 推导 | 返回 URL 时使用的主机名 |
| `BROWSER_SESSION_HUB_SESSIONS_ROOT` | `~/.browser-session-hub/sessions` | 会话工作目录根路径 |
| `BROWSER_SESSION_HUB_HOST_ROOT` | `~/.browser-session-hub` | 宿主机共享根路径，持久 profile 也放这里 |
| `BROWSER_SESSION_HUB_CDP_BIND_HOST` | `127.0.0.1` | Chrome 的 CDP 监听地址 |
| `BROWSER_SESSION_HUB_CDP_PORT_RANGE` | `9333-9432` | 会话可分配的 CDP 端口范围 |
| `BROWSER_SESSION_HUB_VNC_PORT_RANGE` | `5901-6000` | 内部 VNC 端口范围 |
| `BROWSER_SESSION_HUB_NOVNC_PORT_RANGE` | `6081-6180` | 对外 noVNC 端口范围 |
| `BROWSER_SESSION_HUB_DISPLAY_RANGE` | `101-200` | Xvfb display 号范围 |
| `BROWSER_SESSION_HUB_VIEWPORT_WIDTH` | `1440` | 浏览器宽度 |
| `BROWSER_SESSION_HUB_VIEWPORT_HEIGHT` | `900` | 浏览器高度 |
| `BROWSER_SESSION_HUB_IDLE_TIMEOUT` | `0` | 空闲超时秒数，`0` 表示关闭 |
| `BROWSER_SESSION_HUB_NO_SANDBOX` | `false` | 必要时为 Chrome 增加 `--no-sandbox` |

二进制路径覆盖变量：

- `BROWSER_SESSION_HUB_CHROME_PATH`
- `BROWSER_SESSION_HUB_XVFB_PATH`
- `BROWSER_SESSION_HUB_OPENBOX_PATH`
- `BROWSER_SESSION_HUB_X11VNC_PATH`
- `BROWSER_SESSION_HUB_NOVNC_PROXY_PATH`

## 部署检查清单

首次部署到 Linux 前，建议按这个顺序检查：

1. 安装 Python 3.10+、`venv`、`pip`。
2. 安装 Chrome 或 Chromium。
3. 安装 `Xvfb`、`x11vnc`、`noVNC`，确保 `novnc_proxy` 在 `PATH` 中可执行。
4. 按需安装 `openbox`。
5. 创建虚拟环境并执行 `pip install -e .`。
6. 启动服务后访问 `/api/dependencies`，确认所有必需组件都显示为可用。
7. 确认目标主机上的 API 端口，以及 CDP / VNC / noVNC 端口范围符合你的网络策略。

## 依赖自检

宿主机依赖安装完成后，可以直接执行：

```bash
bash scripts/check_linux_dependencies.sh
```

这个脚本会检查：

- Python 版本、`venv`、`pip`
- Chromium 兼容浏览器二进制
- `Xvfb`
- `x11vnc`
- `novnc_proxy`
- `openbox` 是否存在（可选项）

退出码说明：

- `0`：所有必需依赖都已找到
- `1`：至少有一个必需依赖缺失或不可用

服务启动后，也可以再通过 API 看服务自己识别到的依赖状态：

```bash
curl -s http://127.0.0.1:8091/api/dependencies
```

## API

### 创建会话

```bash
curl -s http://127.0.0.1:8091/api/sessions \
  -H 'content-type: application/json' \
  -d '{
    "owner_id": "alice",
    "start_url": "https://example.com"
  }'
```

示例返回：

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

### 配合 Playwright MCP 使用

把返回的 `cdp_http_endpoint` 配置给 MCP：

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

### 预览页面

dashboard 会直接把返回的 `preview_url` 嵌入 iframe。你也可以手动在浏览器中打开它。

## 当前集成状态

当前实现已经足以支撑一个最小 CoPaw 集成流程：

- CoPaw 调用 `POST /api/sessions` 创建会话
- CoPaw 读取返回的 `cdp_http_endpoint`
- Playwright MCP 使用该 `cdp_http_endpoint` 建立 CDP 连接
- 前端把返回的 `preview_url` 嵌入页面，用 noVNC 展示实时浏览器画面

也就是说，当前版本已经支持“agent 通过 CDP 操作浏览器，同时前端实时看到操作画面”这条主链路。

当前限制如下：

- 当前工作区只验证过单元测试，还没有在真实 Linux 机器上完成端到端验证
- `preview_url` 目前仍然是直接暴露每会话 noVNC 端口，而不是通过主服务反向代理
- 预览访问还没有 token 或统一鉴权控制
- 当前空闲续租主要依赖显式 `/touch`，还不是更稳健的 lease 模型

## 推荐的后续迭代顺序

为了让后续 CoPaw 接入更稳定，建议按以下顺序推进：

1. 先补服务内 preview 反向代理和短期 token，不再直接暴露原始 noVNC 端口。
2. 把当前 `/touch` 续命模型升级成 lease 或 heartbeat 模型，并让 preview 访问自动刷新活跃时间。
3. 增加鉴权和 owner 约束，让 `owner_id` 来自可信的服务端上下文，而不是客户端随意传入。
4. 补生产化能力，包括配额、失败诊断、Linux smoke test、部署示例。
5. 最后再接真正的 CoPaw MCP create / renew / stop 流程。

## 说明

- VNC 只监听 localhost，用户通过 noVNC 访问。
- 当前实现返回的是直连 noVNC 的 URL，还没有经过 API 服务代理。
- 持久 profile 是按 owner 独占的，同一个 owner 不能同时跑两个持久 profile 会话。

## 测试

```bash
pytest
```
