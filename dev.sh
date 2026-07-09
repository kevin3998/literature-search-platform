#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKEND_DIR="$ROOT_DIR/backend"
FRONTEND_DIR="$ROOT_DIR/frontend"

export LITERATURE_RESEARCH_CODE_DIR="${LITERATURE_RESEARCH_CODE_DIR:-/Users/chenlintao/paper-crawler-ops/literature_research}"
export LITERATURE_DATA_DIR="${LITERATURE_DATA_DIR:-/Users/chenlintao/paper-crawler-ops/literature_data}"
export LIBRARY_DIR="${LIBRARY_DIR:-/Users/chenlintao/paper-crawler-ops/literature_data}"

RUNTIME_DIR="$ROOT_DIR/.runtime"
mkdir -p "$RUNTIME_DIR"
export LITERATURE_MEMORY_DB_PATH="${LITERATURE_MEMORY_DB_PATH:-$RUNTIME_DIR/platform_memory.sqlite}"

BACKEND_PYTHON="${BACKEND_PYTHON:-/opt/anaconda3/envs/pc_plus/bin/python}"
if [[ ! -x "$BACKEND_PYTHON" ]]; then
  if command -v python3 >/dev/null 2>&1; then
    BACKEND_PYTHON="$(command -v python3)"
  elif command -v python >/dev/null 2>&1; then
    BACKEND_PYTHON="$(command -v python)"
  else
    echo "找不到可用的 Python，请先安装 Python 或设置 BACKEND_PYTHON。" >&2
    exit 1
  fi
fi

HOST="${HOST:-127.0.0.1}"
BACKEND_PORT="${BACKEND_PORT:-8000}"
FRONTEND_PORT="${FRONTEND_PORT:-5173}"
FRONTEND_HOST="${FRONTEND_HOST:-0.0.0.0}"
BACKEND_RELOAD="${BACKEND_RELOAD:-0}"
BACKEND_CONTRACT_PROBE="/api/structured-extraction/tasks/__route_probe__/collection/candidates"

backend_pid=""
frontend_pid=""
frontend_reused="false"

cleanup() {
  if [[ -n "${frontend_pid}" ]]; then
    kill "${frontend_pid}" 2>/dev/null || true
  fi
  if [[ -n "${backend_pid}" ]]; then
    kill "${backend_pid}" 2>/dev/null || true
  fi
}

trap cleanup EXIT INT TERM

backend_contract_ok() {
  local base_url="http://${HOST}:${BACKEND_PORT}"
  local probe_body
  curl -fsS "${base_url}/api/readiness" >/dev/null 2>&1 || return 1
  probe_body="$(curl -sS "${base_url}${BACKEND_CONTRACT_PROBE}" 2>/dev/null || true)"
  [[ "$probe_body" == *"structured extraction task not found"* ]]
}

start_backend() {
  local backend_args=(main:app --host "$HOST" --port "$BACKEND_PORT")
  if [[ "$BACKEND_RELOAD" == "1" || "$BACKEND_RELOAD" == "true" ]]; then
    backend_args=(main:app --reload --host "$HOST" --port "$BACKEND_PORT")
  fi
  (
    cd "$BACKEND_DIR"
    exec "$BACKEND_PYTHON" -m uvicorn "${backend_args[@]}"
  ) &
  backend_pid="$!"
}

stop_existing_backend() {
  local existing_pids
  existing_pids="$(lsof -tiTCP:"$BACKEND_PORT" -sTCP:LISTEN || true)"
  if [[ -z "$existing_pids" ]]; then
    return 0
  fi
  echo "检测到已有后端进程，正在停止端口 ${BACKEND_PORT} 上的监听进程..."
  kill $existing_pids 2>/dev/null || true
  for _ in {1..20}; do
    if ! lsof -nP -iTCP:"$BACKEND_PORT" -sTCP:LISTEN >/dev/null 2>&1; then
      return 0
    fi
    sleep 0.2
  done
  existing_pids="$(lsof -tiTCP:"$BACKEND_PORT" -sTCP:LISTEN || true)"
  if [[ -n "$existing_pids" ]]; then
    echo "已有后端未正常退出，强制停止端口 ${BACKEND_PORT} 上的监听进程..."
    kill -9 $existing_pids 2>/dev/null || true
    sleep 0.3
  fi
}

echo "启动后端: http://${HOST}:${BACKEND_PORT}"
if lsof -nP -iTCP:"$BACKEND_PORT" -sTCP:LISTEN >/dev/null 2>&1; then
  stop_existing_backend
  if lsof -nP -iTCP:"$BACKEND_PORT" -sTCP:LISTEN >/dev/null 2>&1; then
    echo "端口 ${BACKEND_PORT} 仍被占用。请手动释放端口或设置 BACKEND_PORT。" >&2
    exit 1
  fi
fi
start_backend

echo "等待后端就绪..."
for _ in {1..60}; do
  if backend_contract_ok; then
    echo "后端已就绪: http://${HOST}:${BACKEND_PORT}"
    break
  fi
  if ! kill -0 "$backend_pid" 2>/dev/null; then
    wait "$backend_pid" || true
    echo "后端启动失败。"
    exit 1
  fi
  sleep 0.5
done
if ! backend_contract_ok; then
  echo "后端未能在 30 秒内通过 /api/readiness，请检查端口或后端日志。" >&2
  exit 1
fi

echo "启动前端: http://${HOST}:${FRONTEND_PORT}"
if lsof -nP -iTCP:"$FRONTEND_PORT" -sTCP:LISTEN >/dev/null 2>&1; then
  if curl -fsS "http://${HOST}:${FRONTEND_PORT}" >/dev/null 2>&1; then
    echo "检测到已有可用前端，复用: http://${HOST}:${FRONTEND_PORT}"
    frontend_reused="true"
  else
    echo "端口 ${FRONTEND_PORT} 已被占用，但不是可用的前端服务。请先释放端口或设置 FRONTEND_PORT。" >&2
    exit 1
  fi
else
  (
    cd "$FRONTEND_DIR"
    exec npm run dev -- --host "$FRONTEND_HOST" --port "$FRONTEND_PORT"
  ) &
  frontend_pid="$!"
fi

echo "完成后按 Ctrl+C 退出。"

while true; do
  if ! kill -0 "$backend_pid" 2>/dev/null; then
    wait "$backend_pid" || true
    echo "后端已退出。"
    exit 1
  fi
  if [[ "$frontend_reused" == "false" ]] && ! kill -0 "$frontend_pid" 2>/dev/null; then
    wait "$frontend_pid" || true
    echo "前端已退出。"
    exit 1
  fi
  sleep 1
done
