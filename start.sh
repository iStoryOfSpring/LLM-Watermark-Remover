#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "$0")" && pwd)"
PYTHON_BIN=""
BACKEND_PID=""
FRONTEND_PID=""
BROWSER_PID=""
NO_BROWSER_VALUE="$(printenv NO_BROWSER 2>/dev/null || true)"
BROWSER_APP_VALUE="$(printenv BROWSER_APP 2>/dev/null || true)"

cleanup() {
  local exit_code=$?
  trap - INT TERM EXIT

  if [ -n "$BROWSER_PID" ] && kill -0 "$BROWSER_PID" 2>/dev/null; then
    kill -TERM "$BROWSER_PID" 2>/dev/null || true
  fi
  if [ -n "$FRONTEND_PID" ] && kill -0 "$FRONTEND_PID" 2>/dev/null; then
    kill -TERM "$FRONTEND_PID" 2>/dev/null || true
  fi
  if [ -n "$BACKEND_PID" ] && kill -0 "$BACKEND_PID" 2>/dev/null; then
    kill -TERM "$BACKEND_PID" 2>/dev/null || true
  fi

  if [ -n "$BROWSER_PID" ]; then wait "$BROWSER_PID" 2>/dev/null || true; fi
  if [ -n "$FRONTEND_PID" ]; then wait "$FRONTEND_PID" 2>/dev/null || true; fi
  if [ -n "$BACKEND_PID" ]; then wait "$BACKEND_PID" 2>/dev/null || true; fi
  exit "$exit_code"
}

trap cleanup INT TERM EXIT

if [ -x "$ROOT_DIR/.venv/bin/python" ]; then
  PYTHON_BIN="$ROOT_DIR/.venv/bin/python"
else
  PYTHON_BIN="$(command -v python3 || true)"
fi

if [ -z "$PYTHON_BIN" ]; then
  echo "未找到 Python 3。请先安装 Python 3.11+，或在项目根目录创建 .venv。" >&2
  exit 1
fi

if ! command -v npm >/dev/null 2>&1; then
  echo "未找到 npm。请先安装 Node.js 18+。" >&2
  exit 1
fi

if ! "$PYTHON_BIN" -c "import fastapi, uvicorn" >/dev/null 2>&1; then
  echo "当前 Python 缺少 FastAPI/uvicorn 依赖。请先执行：" >&2
  echo "  $PYTHON_BIN -m pip install -e \".[dev]\"" >&2
  exit 1
fi

if [ ! -x "$ROOT_DIR/frontend/node_modules/.bin/vite" ]; then
  echo "前端依赖尚未安装，正在执行 npm install…"
  (cd "$ROOT_DIR/frontend" && npm install)
fi

echo "LLM Watermark Remover"
echo "  API:      http://127.0.0.1:8000"
echo "  Web UI:   http://127.0.0.1:5173"
echo "  按 Ctrl+C 同时关闭前后端。"

(
  cd "$ROOT_DIR"
  exec "$PYTHON_BIN" -m backend.app.main
) &
BACKEND_PID=$!

(
  cd "$ROOT_DIR/frontend"
  exec npm run dev -- --host 127.0.0.1
) &
FRONTEND_PID=$!

if [ "$NO_BROWSER_VALUE" != "1" ]; then
  (
    sleep 1.5
    if [ -n "$BROWSER_APP_VALUE" ] && command -v open >/dev/null 2>&1; then
      open -a "$BROWSER_APP_VALUE" "http://127.0.0.1:5173/" >/dev/null 2>&1 || true
    elif [ -d "/Applications/Google Chrome.app" ] && command -v open >/dev/null 2>&1; then
      open -a "Google Chrome" "http://127.0.0.1:5173/" >/dev/null 2>&1 || true
    elif [ -d "/Applications/Microsoft Edge.app" ] && command -v open >/dev/null 2>&1; then
      open -a "Microsoft Edge" "http://127.0.0.1:5173/" >/dev/null 2>&1 || true
    elif [ -d "/Applications/Firefox.app" ] && command -v open >/dev/null 2>&1; then
      open -a "Firefox" "http://127.0.0.1:5173/" >/dev/null 2>&1 || true
    elif command -v google-chrome >/dev/null 2>&1; then
      google-chrome "http://127.0.0.1:5173/" >/dev/null 2>&1 &
    elif command -v microsoft-edge >/dev/null 2>&1; then
      microsoft-edge "http://127.0.0.1:5173/" >/dev/null 2>&1 &
    elif command -v firefox >/dev/null 2>&1; then
      firefox "http://127.0.0.1:5173/" >/dev/null 2>&1 &
    elif command -v open >/dev/null 2>&1; then
      echo "未检测到可绕过 Safari HTTPS-Only 的浏览器，正在使用系统默认浏览器。" >&2
      open "http://127.0.0.1:5173/" >/dev/null 2>&1 || true
    elif command -v xdg-open >/dev/null 2>&1; then
      xdg-open "http://127.0.0.1:5173/" >/dev/null 2>&1 || true
    fi
  ) &
  BROWSER_PID=$!
fi

while kill -0 "$BACKEND_PID" 2>/dev/null && kill -0 "$FRONTEND_PID" 2>/dev/null; do
  sleep 1
done

echo "有服务进程已退出，正在关闭剩余进程。" >&2
exit 1
