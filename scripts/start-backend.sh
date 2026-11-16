#!/bin/bash
# Run from any directory. Both services stay attached to this supervising terminal.
set -euo pipefail
PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$PROJECT_DIR/backend"
mkdir -p "$PROJECT_DIR/.local/logs"
if [ "${1:-}" = "--background" ]; then
  .venv/bin/python - "$PROJECT_DIR" <<'PYTHON'
import subprocess, sys
from pathlib import Path
root = Path(sys.argv[1])
with (root / '.local/logs/supervisor.log').open('a') as log:
    process = subprocess.Popen(
        ['bash', str(root / 'scripts/start-backend.sh')], cwd=root,
        stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT,
        start_new_session=True,
    )
print(f'Backend supervisor arka planda başlatıldı (PID {process.pid}).')
PYTHON
  exit 0
fi
if [ ! -x .venv/bin/python ]; then
  echo "Python bağımlılıkları eksik. Önce backend klasöründe uv sync çalıştırın."
  exit 1
fi
if lsof -nP -iTCP:8000 -sTCP:LISTEN >/dev/null 2>&1; then
  echo "8000 portu kullanımda. Mevcut API terminalini kapatıp yeniden deneyin."
  exit 1
fi
API_PID=""
AGENT_PID=""
cleanup() {
  trap - EXIT INT TERM
  [ -z "$AGENT_PID" ] || kill "$AGENT_PID" 2>/dev/null || true
  [ -z "$API_PID" ] || kill "$API_PID" 2>/dev/null || true
}
trap cleanup EXIT INT TERM
.venv/bin/python -u -m uvicorn app.main:app --host 127.0.0.1 --port 8000 >> "$PROJECT_DIR/.local/logs/api.log" 2>&1 &
API_PID=$!
.venv/bin/python -u -m app.agent dev >> "$PROJECT_DIR/.local/logs/agent.log" 2>&1 &
AGENT_PID=$!
echo "API ve LiveKit agent başlatılıyor. Bu terminali açık bırakın."
echo "Kayıtlar: .local/logs/api.log ve .local/logs/agent.log"
echo "Agent kaydında 'registered worker' görünce http://localhost:3000 adresinden deneyin."
while kill -0 "$API_PID" 2>/dev/null && kill -0 "$AGENT_PID" 2>/dev/null; do
  sleep 2
done
echo "Bir servis durdu. Son kayıtlar:"
tail -n 25 "$PROJECT_DIR/.local/logs/api.log" "$PROJECT_DIR/.local/logs/agent.log"
exit 1
