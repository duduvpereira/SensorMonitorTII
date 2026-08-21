#!/usr/bin/env bash
# One-shot setup for running Sensor Monitor without Docker: finds a Python
# 3.12+ interpreter (there may be several on the machine, and the one `python3`
# happens to resolve to is not guaranteed to be new enough), creates .venv with
# it, and installs the dev dependencies.
#
# Usage: ./setup.sh
set -euo pipefail

REQUIRED_MAJOR=3
REQUIRED_MINOR=12

is_new_enough() {
  # $1: a python interpreter to check.
  "$1" -c "import sys; sys.exit(0 if sys.version_info >= (${REQUIRED_MAJOR}, ${REQUIRED_MINOR}) else 1)" \
    > /dev/null 2>&1
}

PYTHON=""
for candidate in python3.12 python3.13 python3.14 python3 python; do
  if command -v "$candidate" > /dev/null 2>&1 && is_new_enough "$candidate"; then
    PYTHON="$candidate"
    break
  fi
done

if [ -z "$PYTHON" ]; then
  echo "ERROR: no Python ${REQUIRED_MAJOR}.${REQUIRED_MINOR}+ interpreter found on PATH." >&2
  echo "Checked: python3.12, python3.13, python3.14, python3, python." >&2
  echo >&2
  echo "On Ubuntu, the deadsnakes PPA installs a newer interpreter side by" >&2
  echo "side with the system one:" >&2
  echo "  sudo add-apt-repository -y ppa:deadsnakes/ppa && sudo apt update" >&2
  echo "  sudo apt install -y python3.12 python3.12-venv" >&2
  echo >&2
  echo "Or skip Python entirely and run with Docker instead:" >&2
  echo "  docker compose up --build" >&2
  exit 1
fi

FOUND_VERSION="$("$PYTHON" -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')"
echo "Using $PYTHON (Python $FOUND_VERSION)"

if [ -d .venv ]; then
  echo ".venv already exists, reusing it. Delete it first (rm -rf .venv) for a clean rebuild."
else
  "$PYTHON" -m venv .venv
  echo "Created .venv"
fi

.venv/bin/pip install --upgrade pip > /dev/null
.venv/bin/pip install -r requirements-dev.txt

echo
echo "Setup complete. Next steps:"
echo "  source .venv/bin/activate"
echo "  python -m mock_uc.server --fps 60 --port 48765   # terminal 1"
echo "  python -m uvicorn backend.app.main:app --reload --port 48000   # terminal 2"
echo "  open http://localhost:48000"
