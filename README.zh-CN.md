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

## 和 CoPaw、Playwright MCP、其他智能体平台的关系

这几个组件解决的是不同层的问题，不要混为一谈：

- Browser Session Hub 负责创建和管理隔离浏览器会话。
- Playwright MCP 负责通过 CDP 去控制一个已经存在的浏览器。
- CoPaw 或其他智能体平台负责决定什么时候创建会话、续租、销毁，以及哪个用户或哪个 agent 拥有这次浏览器会话。

典型链路如下：

```text
智能体平台（CoPaw、自研 orchestrator 等）
    -> POST /api/sessions
    -> 拿到 session_id + cdp_http_endpoint + preview_url
    -> 用这个 cdp_http_endpoint 启动 Playwright MCP
    -> 把 preview_url 展示给人
    -> 活跃期间 POST /api/sessions/{id}/touch
    -> 结束时 DELETE /api/sessions/{id}
```

这个项目本身不是浏览器控制型 MCP server，它是 Playwright MCP 下面的“浏览器会话层”。

如果你的编排器支持运行时动态更新 MCP 配置，那么它可以直接先调用 `POST /api/sessions`，再把返回的 `cdp_http_endpoint` 填给 Playwright MCP。

如果你的平台只能配置一个静态的 `stdio` MCP 命令，而且你又不想改平台源码，那么就用仓库内置的 `browser-hub-playwright-wrapper`。它会先创建 session，再用正确的动态 endpoint 拉起 `@playwright/mcp`。

## 隔离模型

真正的隔离边界是 Browser Session Hub 的请求参数，不是 Playwright MCP 自己。

- `session_id` 是一次具体运行出来的浏览器会话 ID。
- `owner_id` 是由外部编排器决定的逻辑隔离键。
- `persist_profile=false` 表示使用会话目录下的临时 profile。
- `persist_profile=true` 表示同一个 `owner_id` 复用 profile，但这个 profile 在会话运行期间是独占的。

推荐的 `owner_id` 设计：

- 每个 agent 一套浏览器：`agent:{agent_id}`
- 同一套 agent 系统里每个最终用户一套浏览器：`user:{user_id}:agent:{agent_id}`
- 每个用户会话一套浏览器：`user:{user_id}:agent:{agent_id}:chat:{chat_id}`

一个重要限制：

- 静态 MCP 配置无法在运行时自动为不同终端用户生成不同的 `owner_id`
- 如果你要在“同一个 agent 下按最终用户隔离”，而平台又不能动态改 MCP 参数，就需要一个很薄的编排层，或者单独做一个 MCP server 来暴露 `create_session` / `touch_session` / `stop_session`

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
- 如果宿主机上的工具链偏老，`pip install -e .` 仍然失败，可以先执行 `python3.11 -m pip install --upgrade pip setuptools wheel`。

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

如果目标机器里的 `pip` 或 `setuptools` 比较老，仓库里现在也带了一个最小 `setup.py`，用来兼容旧版 editable install。

## 运行

```bash
browser-session-hub
```

后台启动：

```bash
browser-session-hub --daemon
```

默认服务地址：

```text
http://127.0.0.1:8091
```

在 Linux 上启动前，请确认 `google-chrome` 或 `chromium`、`Xvfb`、`x11vnc`、`novnc_proxy` 都能在 `PATH` 中找到，或者通过对应的 `BROWSER_SESSION_HUB_*_PATH` 环境变量显式指定。

daemon 模式默认路径：

```text
日志文件: ~/.browser-session-hub/logs/browser-session-hub.log
pid 文件: ~/.browser-session-hub/run/browser-session-hub.pid
```

执行 `browser-session-hub --daemon` 后，命令行会直接输出最终使用的日志文件和 pid 文件路径。

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
| `BROWSER_SESSION_HUB_LOG_DIR` | `~/.browser-session-hub/logs` | 服务日志默认目录 |
| `BROWSER_SESSION_HUB_RUN_DIR` | `~/.browser-session-hub/run` | pid 和运行时文件默认目录 |
| `BROWSER_SESSION_HUB_LOG_FILE` | `~/.browser-session-hub/logs/browser-session-hub.log` | `--daemon` 使用的日志文件 |
| `BROWSER_SESSION_HUB_PID_FILE` | `~/.browser-session-hub/run/browser-session-hub.pid` | `--daemon` 使用的 pid 文件 |
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

这些配置在真实接入里还要注意：

- `BROWSER_SESSION_HUB_PUBLIC_HOST` 决定 API 返回的 `cdp_http_endpoint` 和 `preview_url` 里写什么主机名。
- `BROWSER_SESSION_HUB_CDP_BIND_HOST` 决定 Browser Session Hub 会让 Chrome 监听哪个网卡地址。
- 这两个配置有关联，但不是同一件事。
- 在真实部署里，有些 Chromium 即使带了 `--remote-debugging-address=0.0.0.0`，最终 DevTools 仍然只监听在 loopback。遇到这种情况，本机编排器应该使用 wrapper 的 `--cdp-host-override 127.0.0.1`。

## Daemon 启动示例

带公网地址和 root 场景 `--no-sandbox` 的后台启动示例：

```bash
export BROWSER_SESSION_HUB_PUBLIC_HOST=180.184.84.200
export BROWSER_SESSION_HUB_NO_SANDBOX=true
browser-session-hub --daemon
```

自定义日志和 pid 路径的示例：

```bash
export BROWSER_SESSION_HUB_LOG_FILE=/var/log/browser-session-hub/service.log
export BROWSER_SESSION_HUB_PID_FILE=/var/run/browser-session-hub.pid
browser-session-hub --daemon
```

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

### 通用接入流程

正确的接入顺序应该是：

1. 先调用 `POST /api/sessions` 创建会话。
2. 从返回里读取 `session.cdp_http_endpoint`。
3. 用这个值启动 Playwright MCP 的 `--cdp-endpoint`。
4. 把 `session.preview_url` 提供给人查看或接管。
5. 如果启用了 `BROWSER_SESSION_HUB_IDLE_TIMEOUT`，持续调用 `POST /api/sessions/{session_id}/touch` 保活。
6. 用完后调用 `DELETE /api/sessions/{session_id}` 停掉会话。

不要把 `9333`、`9334` 这种端口写死。CDP 端口是按会话动态分配的。

### 只支持静态 MCP 配置时，用 wrapper

如果智能体平台只能接受一个静态 `stdio` MCP 配置，不适合直接注册 `npx @playwright/mcp`，而应该注册 wrapper。

wrapper 会做这些事情：

- 先调用 `POST /api/sessions`
- 必要时把返回的 CDP host 改写成本机可用地址
- 用正确的 `--cdp-endpoint` 启动 `@playwright/mcp`
- 按需定时 `/touch`
- 退出时自动删除 session

它不是一个常驻系统服务，而是由智能体平台在 MCP client 建立连接时按需拉起的子进程。

如果编排器和 Browser Session Hub 在同一台机器上，而 Chromium 的 DevTools 只监听 loopback，那么请这样配置：

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

对于 CoPaw，建议 MCP client key 保持为 `playwright`。在真实部署里，模型最终看到的工具名可能是 `browser_navigate`、`browser_snapshot`、`browser_click`，但底层仍然可能是 `playwright` 这个 MCP client 在提供服务。用 `playwright` 这个 key，CoPaw 才能更稳定地对齐它自己的 browser skill 和工具池。

如果服务环境里的 `npx` 不在 `PATH` 中，可以通过 `--mcp-command` 传绝对路径，例如：

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
        "--mcp-command",
        "/root/.nvm/versions/node/v22.22.2/bin/npx",
        "--mcp-arg=--browser",
        "--mcp-arg=chromium"
      ]
    }
  }
}
```

### Wrapper 参数和环境变量对照

wrapper 同时支持 CLI 参数和环境变量：

| CLI 参数 | 环境变量 | 作用 |
| --- | --- | --- |
| `--base-url` | `BSH_BASE_URL` | Browser Session Hub 服务地址 |
| `--owner-id` | `BSH_OWNER_ID` | 逻辑隔离键 |
| `--start-url` | `BSH_START_URL` | 浏览器初始页面 |
| `--viewport-width` | `BSH_VIEWPORT_WIDTH` | 初始浏览器宽度 |
| `--viewport-height` | `BSH_VIEWPORT_HEIGHT` | 初始浏览器高度 |
| `--persist-profile` / `--no-persist-profile` | `BSH_PERSIST_PROFILE` | 是否复用同一个 owner 的 profile |
| `--touch-interval` | `BSH_TOUCH_INTERVAL` | 保活间隔秒数；`0` 表示不 touch |
| `--cdp-host-override` | `BSH_CDP_HOST_OVERRIDE` | 改写返回的 CDP endpoint 的 host |
| `--metadata-json` | `BSH_METADATA_JSON` | 合并到 session metadata 的 JSON 对象 |
| `--metadata KEY=VALUE` | 无 | 额外 metadata 项 |
| `--mcp-command` | `BSH_MCP_COMMAND` | 用来启动 Playwright MCP 的命令 |
| `--mcp-package` | `BSH_MCP_PACKAGE` | 传给 launcher 的包名，默认 `@playwright/mcp@latest` |
| `--mcp-arg ARG` | `BSH_MCP_ARGS` | 透传给 Playwright MCP 的额外参数 |

### 预览页面

dashboard 会直接把返回的 `preview_url` 嵌入 iframe。你也可以手动在浏览器中打开它。

## 真实部署中遇到的常见问题

下面这些不是理论问题，而是在真实 CoPaw 部署里实际遇到过的。

### 1. 把动态 CDP 端口误当成固定端口

Browser Session Hub 每次创建会话都会动态分配一个空闲 CDP 端口。某次可能是 `9333`，下一次可能就是 `9334`、`9335`。

含义是：

- 不要把 `--cdp-endpoint http://host:9333` 写死
- 必须以 `POST /api/sessions` 返回的 `cdp_http_endpoint` 为准

### 2. API 返回的公网地址，不等于本机一定能连到的 DevTools 地址

在一个真实 Linux 部署里，API 返回的是 `http://192.168.3.166:9335`，但 Chromium 实际只在 `127.0.0.1:9335` 暴露 DevTools。预览正常，但 Playwright MCP 报错：

```text
Error: connect ECONNREFUSED 192.168.3.166:9333
```

这里的含义是：

- `BROWSER_SESSION_HUB_PUBLIC_HOST` 决定 API 返回什么地址
- 它不保证 Chromium 真的在那个网卡地址上可达
- 如果编排器和 Browser Session Hub 在同一台机器，本机接入请优先用 `--cdp-host-override 127.0.0.1`

### 3. CoPaw 的热重载和持久 profile 会打架

CoPaw 做 hot reload 时，可能会在旧 MCP client 完全退出之前，先拉起新的 MCP client。此时如果 `persist_profile=true` 且 `owner_id` 固定，Browser Session Hub 会正确拒绝第二个会话，因为同一个持久 profile 已经被占用。

这里的含义是：

- 对零停机 MCP reload 来说，`persist_profile=false` 通常更稳妥
- 如果必须保留持久 profile，就需要让编排器做更严格的停旧启新顺序控制

### 4. 工具名不一定和 MCP client key 一样

在 CoPaw 里，模型看到的工具名可能是 `browser_navigate`、`browser_snapshot` 等，即使底层真正提供能力的是 `playwright` 这个 MCP client。

这里的含义是：

- 不要只凭工具名猜底层接的是哪套服务
- 要看平台内部的工具池映射
- 在 CoPaw 里，MCP client key 建议保持为 `playwright`

## 当前集成状态

当前实现已经足以支撑一个实用的 CoPaw 集成流程：

- CoPaw 调用 `POST /api/sessions` 创建会话
- CoPaw 注册一个由 `browser-hub-playwright-wrapper` 驱动的 `playwright` MCP client
- wrapper 负责创建 session、解析本机可用的 CDP endpoint，并拉起 Playwright MCP
- 前端把返回的 `preview_url` 嵌入页面，用 noVNC 展示实时浏览器画面

也就是说，当前版本已经支持“agent 通过 CDP 操作浏览器，同时前端实时看到操作画面”这条主链路。

当前限制如下：

- wrapper 方案解决了动态 endpoint 问题，但仍然要求智能体平台支持启动一个 `stdio` 子进程型 MCP client
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
