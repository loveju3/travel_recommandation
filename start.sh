#!/usr/bin/env bash
# 一鍵建立環境並啟動服務（可重複執行，已完成的步驟會自動跳過）
#
#   ./start.sh            建環境 + 啟動 uvicorn
#   ./start.sh --setup    只建環境，不啟動
#   ./start.sh --ingest   建環境 + 匯入資料（第一次用新資料庫時）+ 啟動
#   PORT=9000 ./start.sh  改用其他 port
set -euo pipefail

PY_VERSION="3.12.12"
PORT="${PORT:-8000}"
VENV=".venv"

cd "$(dirname "$0")"

RUN=1; INGEST=0
for arg in "$@"; do
  case "${arg}" in
    --setup)  RUN=0 ;;
    --ingest) INGEST=1 ;;
    -h|--help) sed -n '2,8p' "$0"; exit 0 ;;
    *) echo "未知參數：${arg}（用 --help 看用法）"; exit 1 ;;
  esac
done

step() { printf '\n\033[1;34m▶ %s\033[0m\n' "$1"; }
ok()   { printf '  \033[32m✓\033[0m %s\n' "$1"; }
warn() { printf '  \033[33m!\033[0m %s\n' "$1"; }

# 1. 選定 Python ------------------------------------------------------
step "Python"
if command -v pyenv >/dev/null 2>&1; then
  if ! pyenv versions --bare | grep -qx "${PY_VERSION}"; then
    warn "pyenv 沒有 ${PY_VERSION}，開始安裝（需要幾分鐘）"
    pyenv install "${PY_VERSION}"
  fi
  pyenv local "${PY_VERSION}"
  PYTHON="$(pyenv root)/versions/${PY_VERSION}/bin/python"
else
  PYTHON="$(command -v python3.12 || command -v python3 || true)"
  [ -n "${PYTHON}" ] || { echo "找不到 Python，請先安裝 pyenv 或 Python 3.12"; exit 1; }
  warn "沒有 pyenv，改用 ${PYTHON}"
fi
ok "$("${PYTHON}" --version)"

# 2. 虛擬環境 ---------------------------------------------------------
step "虛擬環境 ${VENV}"
if [ -x "${VENV}/bin/python" ]; then
  ok "已存在，略過建立"
else
  "${PYTHON}" -m venv "${VENV}"
  ok "已建立"
fi

# 3. 套件（requirements.txt 有變動才重裝）-----------------------------
step "套件"
REQ_HASH="$("${VENV}/bin/python" -c 'import hashlib;print(hashlib.sha256(open("requirements.txt","rb").read()).hexdigest())')"
STAMP="${VENV}/.requirements.sha256"
if [ -f "${STAMP}" ] && [ "$(cat "${STAMP}")" = "${REQ_HASH}" ]; then
  ok "requirements.txt 沒變動，略過安裝"
else
  "${VENV}/bin/python" -m pip install -q --upgrade pip
  "${VENV}/bin/python" -m pip install -q -r requirements.txt
  echo "${REQ_HASH}" > "${STAMP}"
  ok "安裝完成"
fi

# 4. .env -------------------------------------------------------------
step ".env"
if [ ! -f .env ]; then
  cp .env.example .env
  warn "已從 .env.example 複製出 .env，請填入 DATABASE_URL 與 OPENAI_API_KEY 後再執行一次"
  exit 1
fi
ok "已存在"

# 5. 匯入資料（選用）--------------------------------------------------
if [ "${INGEST}" = 1 ]; then
  step "匯入資料"
  "${VENV}/bin/python" scripts/ingest.py
fi

# 6. 啟動 -------------------------------------------------------------
if [ "${RUN}" = 1 ]; then
  step "啟動服務 → http://localhost:${PORT}"
  exec "${VENV}/bin/python" -m uvicorn app.main:app --reload --port "${PORT}"
else
  printf '\n環境就緒。啟動：./start.sh　或　source %s/bin/activate\n' "${VENV}"
fi
