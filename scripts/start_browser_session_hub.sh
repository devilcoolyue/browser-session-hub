#!/usr/bin/env bash
# 一键启动 Browser Session Hub
# 用法: bash scripts/start_browser_session_hub.sh [--daemon] [--port 8091] [--public-host IP]
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
VENV_DIR="$PROJECT_DIR/.venv"
PYTHON="${PYTHON:-python3.11}"
PID_FILE="${PID_FILE:-/tmp/browser-session-hub.pid}"

# ---------- 解析参数 ----------
DAEMON=""
EXTRA_ARGS=()
PUBLIC_HOST="${BROWSER_SESSION_HUB_PUBLIC_HOST:-}"

while [[ $# -gt 0 ]]; do
    case "$1" in
        --daemon)   DAEMON=1; shift ;;
        --public-host) PUBLIC_HOST="$2"; shift 2 ;;
        *)          EXTRA_ARGS+=("$1"); shift ;;
    esac
done

# ---------- 如果已在运行则提示 ----------
if [[ -f "$PID_FILE" ]]; then
    OLD_PID=$(cat "$PID_FILE")
    if kill -0 "$OLD_PID" 2>/dev/null; then
        echo "[INFO] Browser Session Hub 已在运行 (PID $OLD_PID)"
        echo "       如需重启请先执行: kill $OLD_PID"
        exit 0
    else
        echo "[INFO] 清理过期 PID 文件"
        rm -f "$PID_FILE"
    fi
fi

# ---------- 创建 / 激活虚拟环境 ----------
if [[ ! -d "$VENV_DIR" ]]; then
    echo "[1/3] 创建虚拟环境 ..."
    "$PYTHON" -m venv "$VENV_DIR"
else
    echo "[1/3] 虚拟环境已存在，跳过创建"
fi

# shellcheck disable=SC1091
source "$VENV_DIR/bin/activate"

# ---------- 安装依赖 ----------
echo "[2/3] 安装 / 更新依赖 ..."
# --no-build-isolation: 绕过构建隔离子进程不继承 trusted-host 导致的 SSL 问题
# 先确保 setuptools 存在（构建需要）
pip install --quiet setuptools >/dev/null 2>&1 || true
pip install --quiet --no-build-isolation -e "$PROJECT_DIR" 2>&1 | tail -3

# ---------- 环境变量 ----------
export BROWSER_SESSION_HUB_NO_SANDBOX="${BROWSER_SESSION_HUB_NO_SANDBOX:-true}"
export BROWSER_SESSION_HUB_HOST="${BROWSER_SESSION_HUB_HOST:-0.0.0.0}"
[[ -n "$PUBLIC_HOST" ]] && export BROWSER_SESSION_HUB_PUBLIC_HOST="$PUBLIC_HOST"

# ---------- 启动服务 ----------
echo "[3/3] 启动 Browser Session Hub ..."
CMD_ARGS=("${EXTRA_ARGS[@]+"${EXTRA_ARGS[@]}"}")
if [[ -n "$DAEMON" ]]; then
    CMD_ARGS+=(--daemon)
    echo "       以守护进程模式运行"
fi

exec browser-session-hub "${CMD_ARGS[@]}"
