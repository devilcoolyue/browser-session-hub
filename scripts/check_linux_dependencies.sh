#!/usr/bin/env bash

set -u

failures=0
warnings=0

pass() {
  printf '[OK] %s\n' "$1"
}

fail() {
  printf '[FAIL] %s\n' "$1"
  failures=$((failures + 1))
}

warn() {
  printf '[WARN] %s\n' "$1"
  warnings=$((warnings + 1))
}

find_first_command() {
  local candidate
  for candidate in "$@"; do
    if command -v "$candidate" >/dev/null 2>&1; then
      command -v "$candidate"
      return 0
    fi
  done
  return 1
}

check_required_command() {
  local label="$1"
  shift
  local resolved
  resolved="$(find_first_command "$@" 2>/dev/null || true)"
  if [ -n "$resolved" ]; then
    pass "$label found at $resolved"
    return 0
  fi
  fail "$label not found on PATH"
  return 1
}

check_optional_command() {
  local label="$1"
  shift
  local resolved
  resolved="$(find_first_command "$@" 2>/dev/null || true)"
  if [ -n "$resolved" ]; then
    pass "$label found at $resolved"
    return 0
  fi
  warn "$label not found on PATH"
  return 0
}

check_python() {
  local python_bin
  local version

  python_bin="$(find_first_command python3.11 python3 python 2>/dev/null || true)"
  if [ -z "$python_bin" ]; then
    fail "Python 3.10+ not found on PATH"
    return 1
  fi

  version="$("$python_bin" -c 'import sys; print(".".join(map(str, sys.version_info[:3]))); raise SystemExit(0 if sys.version_info >= (3, 10) else 1)' 2>/dev/null)"
  if [ $? -eq 0 ]; then
    pass "Python >= 3.10 available via $python_bin (version $version)"
  else
    fail "Python at $python_bin is too old (version $version, need >= 3.10)"
  fi

  if "$python_bin" -m venv --help >/dev/null 2>&1; then
    pass "Python venv module is available"
  else
    fail "Python venv module is unavailable"
  fi

  if "$python_bin" -m pip --version >/dev/null 2>&1; then
    pass "Python pip is available via $python_bin -m pip"
  else
    fail "Python pip is unavailable via $python_bin -m pip"
  fi
}

main() {
  printf 'Checking Browser Session Hub Linux dependencies\n'
  printf '\n'

  check_python
  check_required_command "Browser" google-chrome google-chrome-stable chromium-browser chromium chrome
  check_required_command "Xvfb" Xvfb
  check_required_command "x11vnc" x11vnc
  check_required_command "novnc_proxy" novnc_proxy
  check_optional_command "openbox" openbox

  printf '\n'
  if [ "$failures" -eq 0 ]; then
    printf 'Dependency check passed'
    if [ "$warnings" -gt 0 ]; then
      printf ' with %s warning(s)' "$warnings"
    fi
    printf '.\n'
    exit 0
  fi

  printf 'Dependency check failed with %s error(s)' "$failures"
  if [ "$warnings" -gt 0 ]; then
    printf ' and %s warning(s)' "$warnings"
  fi
  printf '.\n'
  exit 1
}

main "$@"
