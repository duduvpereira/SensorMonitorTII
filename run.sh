#!/usr/bin/env bash
# One-command launcher: starts the mock uC and the backend together, tails
# their logs, and cleans up on Ctrl-C. Requires ./setup.sh to have already
# created .venv -- this script's only job is running an environment that
# already exists, not building one.
#
# Usage:
#   ./run.sh            start both services
#   ./run.sh --doctor   print environment diagnostics and exit (nothing started)
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"

VENV_PY=".venv/bin/python"
RUNDIR=".sensor-monitor-run"
STATE_FILE="$RUNDIR/pids"
LOG_DIR="$RUNDIR/logs"
APP_PORT="${APP_PORT:-48000}"
UC_PORT="${MOCK_PORT:-48765}"
FPS="${FPS:-60}"

# ---------------------------------------------------------------------------
# Shared checks
# ---------------------------------------------------------------------------

require_venv() {
  if [ ! -x "$VENV_PY" ]; then
    echo "ERROR: .venv not found (or has no python). Run ./setup.sh first." >&2
    exit 1
  fi
}

python_floor() {
  # Same source of truth setup.sh reads: requires-python in pyproject.toml.
  local ver
  ver="$(grep -E '^requires-python' pyproject.toml 2>/dev/null | grep -oE '[0-9]+\.[0-9]+' | head -1 || true)"
  echo "${ver:-3.12}"
}

probe_python() {
  # Any interpreter can run the socket-bind checks below; .venv is not
  # required for them, so this must not hard-fail when it's missing (that
  # is itself one of the things --doctor is meant to report, not choke on).
  if [ -x "$VENV_PY" ]; then
    echo "$VENV_PY"
  else
    command -v python3 || command -v python || true
  fi
}

port_status() {
  # $1: port. Prints "free" or "busy" -- a real bind attempt, not just
  # "is something answering", so it also catches a port reserved but not
  # yet listening.
  local py
  py="$(probe_python)"
  if [ -z "$py" ]; then
    echo "unknown (no Python interpreter available to check)"
    return
  fi
  "$py" - "$1" <<'EOF'
import socket, sys
port = int(sys.argv[1])
s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
try:
    s.bind(("0.0.0.0", port))
    print("free")
except OSError:
    print("busy")
finally:
    s.close()
EOF
}

# ---------------------------------------------------------------------------
# Item 1: leftover-process reaping. A launcher killed without running its
# trap (closed terminal, `kill -9`, a crashed parent shell) leaves the mock
# uC and/or backend bound to their ports with nothing left to stop them --
# exactly the "address already in use" report from a previous session. Each
# run records what it started; the next run kills anything still alive from
# that record before binding the same ports again.
# ---------------------------------------------------------------------------

reap_previous_run() {
  [ -f "$STATE_FILE" ] || return 0
  local pid tag line
  while IFS=' ' read -r tag pid; do
    [ -n "${pid:-}" ] || continue
    kill -0 "$pid" 2>/dev/null || continue
    # Never kill a PID just because it's in our file: recycled PIDs are real.
    # Only touch it if its own command line still names this project's
    # module, i.e. it is unmistakably a leftover of *this* app.
    local cmdline
    cmdline="$(ps -p "$pid" -o args= 2>/dev/null || true)"
    case "$cmdline" in
      *mock_uc.server*|*backend.app.main*)
        echo "Stopping leftover $tag process from a previous run (pid $pid)"
        kill "$pid" 2>/dev/null || true
        for _ in $(seq 1 20); do
          kill -0 "$pid" 2>/dev/null || break
          sleep 0.2
        done
        kill -9 "$pid" 2>/dev/null || true
        ;;
    esac
  done < "$STATE_FILE"
  rm -f "$STATE_FILE"
}

write_state() {
  mkdir -p "$RUNDIR"
  {
    echo "uc $MOCK_PID"
    echo "app $APP_PID"
  } > "$STATE_FILE"
}

# ---------------------------------------------------------------------------
# Item 2: verify the app actually imports before spawning anything. A bad
# environment (wrong Python, half-installed dependency) otherwise shows up
# as a background process that exits in the first second for a reason
# buried in a log file instead of a message on screen right now.
# ---------------------------------------------------------------------------

verify_imports() {
  echo "Checking the environment can import the application..."
  if ! "$VENV_PY" -c "import backend.app.main, mock_uc.server" 2> "$RUNDIR/import_check.log"; then
    echo "ERROR: the application failed to import in $VENV_PY:" >&2
    sed 's/^/    /' "$RUNDIR/import_check.log" >&2
    echo >&2
    echo "This usually means .venv was built with the wrong Python, or" >&2
    echo "requirements-dev.txt failed partway through. Try:" >&2
    echo "  rm -rf .venv && ./setup.sh" >&2
    exit 1
  fi
}

# ---------------------------------------------------------------------------
# Item 3: --doctor. Everything a "why won't this run on your machine"
# conversation ends up asking for, in one command instead of several
# screenshots back and forth.
# ---------------------------------------------------------------------------

doctor() {
  echo "Sensor Monitor -- environment diagnostics"
  echo
  echo "project root     : $ROOT"
  echo "python floor     : >=$(python_floor)  (from pyproject.toml)"
  echo

  echo "interpreters on PATH:"
  local seen=""
  for candidate in python3.9 python3.10 python3.11 python3.12 python3.13 python3.14 python3 python; do
    command -v "$candidate" > /dev/null 2>&1 || continue
    local resolved
    resolved="$(command -v "$candidate")"
    case " $seen " in *" $resolved "*) continue ;; esac
    seen="$seen $resolved"
    local version
    version="$("$resolved" -c 'import sys; print("%d.%d" % sys.version_info[:2])' 2>/dev/null || echo "?")"
    printf "  %-28s %s\n" "$resolved" "$version"
  done
  echo

  if [ -x "$VENV_PY" ]; then
    echo ".venv          : present ($("$VENV_PY" -c 'import sys; print("%d.%d.%d" % sys.version_info[:3])'))"
    echo "packages in .venv:"
    "$VENV_PY" - <<'EOF'
for name in ("fastapi", "uvicorn", "websockets", "numpy", "xxhash"):
    try:
        mod = __import__(name)
        print("  %-12s %s" % (name, getattr(mod, "__version__", "?")))
    except Exception:
        print("  %-12s MISSING" % name)
EOF
  else
    echo ".venv          : not found -- run ./setup.sh"
  fi
  echo

  echo "ports:"
  echo "  app ($APP_PORT)      : $(port_status "$APP_PORT")"
  echo "  mock uC ($UC_PORT)   : $(port_status "$UC_PORT")"
  echo

  echo "tools:"
  for tool in git docker curl; do
    printf "  %-8s %s\n" "$tool" "$(command -v "$tool" || echo "-")"
  done
  echo

  if [ -f "$STATE_FILE" ]; then
    echo "previous run state ($STATE_FILE):"
    sed 's/^/  /' "$STATE_FILE"
  else
    echo "previous run state: none"
  fi
}

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

if [ "${1:-}" = "--doctor" ]; then
  # No require_venv here on purpose: a missing .venv is itself one of the
  # things --doctor exists to reveal, and doctor() already reports it as a
  # normal finding rather than needing the environment to be complete first.
  doctor
  exit 0
fi

require_venv
mkdir -p "$LOG_DIR"
reap_previous_run
verify_imports

echo "Starting mock uC on port $UC_PORT (--fps $FPS)..."
"$VENV_PY" -m mock_uc.server --host 0.0.0.0 --port "$UC_PORT" --fps "$FPS" \
  > "$LOG_DIR/mock_uc.log" 2>&1 &
MOCK_PID=$!

echo "Starting backend on port $APP_PORT..."
SENSOR_MONITOR_UC_URL="ws://127.0.0.1:$UC_PORT" \
  "$VENV_PY" -m uvicorn backend.app.main:app --host 0.0.0.0 --port "$APP_PORT" \
  > "$LOG_DIR/backend.log" 2>&1 &
APP_PID=$!

write_state

cleanup() {
  echo
  echo "Shutting down..."
  kill "$MOCK_PID" "$APP_PID" 2>/dev/null || true
  wait "$MOCK_PID" "$APP_PID" 2>/dev/null || true
  rm -f "$STATE_FILE"
}
trap cleanup EXIT INT TERM

sleep 1
if ! kill -0 "$MOCK_PID" 2>/dev/null; then
  echo "ERROR: the mock uC exited immediately. Last log lines:" >&2
  tail -n 20 "$LOG_DIR/mock_uc.log" >&2
  exit 1
fi
if ! kill -0 "$APP_PID" 2>/dev/null; then
  echo "ERROR: the backend exited immediately. Last log lines:" >&2
  tail -n 20 "$LOG_DIR/backend.log" >&2
  exit 1
fi

echo
echo "  Open http://localhost:$APP_PORT"
echo "  URL field pre-fills with ws://127.0.0.1:$UC_PORT -- press Connect."
echo "  Logs: $LOG_DIR"
echo "  Ctrl-C to stop everything."
echo

# Supervise: tail both logs, but exit loudly if either process dies.
tail -n 0 -f "$LOG_DIR/mock_uc.log" "$LOG_DIR/backend.log" &
TAIL_PID=$!
trap 'kill "$TAIL_PID" 2>/dev/null || true; cleanup' EXIT INT TERM

while kill -0 "$MOCK_PID" 2>/dev/null && kill -0 "$APP_PID" 2>/dev/null; do
  sleep 1
done

if ! kill -0 "$MOCK_PID" 2>/dev/null; then
  echo "ERROR: the mock uC exited unexpectedly. Last log lines:" >&2
  tail -n 20 "$LOG_DIR/mock_uc.log" >&2
fi
if ! kill -0 "$APP_PID" 2>/dev/null; then
  echo "ERROR: the backend exited unexpectedly. Last log lines:" >&2
  tail -n 20 "$LOG_DIR/backend.log" >&2
fi
exit 1
