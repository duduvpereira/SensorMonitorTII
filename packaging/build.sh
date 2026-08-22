#!/usr/bin/env bash
# Builds the standalone Sensor Monitor binary with PyInstaller: one file,
# no Python or Docker installation required to run it. Meant for Linux
# (the challenge's actual target); macOS should also work unmodified since
# nothing here is Linux-specific, but only Linux is what CI verifies.
#
# Usage: ./packaging/build.sh
# Output: dist/sensor-monitor
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

PYTHON="${PYTHON:-python3}"
BUILD_VENV=".pyinstaller-venv"

echo "==> Setting up a build environment ($BUILD_VENV)"
if [ ! -d "$BUILD_VENV" ]; then
  "$PYTHON" -m venv "$BUILD_VENV"
fi
"$BUILD_VENV/bin/pip" install --upgrade pip > /dev/null
"$BUILD_VENV/bin/pip" install -r requirements.txt pyinstaller

echo "==> Building with PyInstaller"
# --paths .: backend/ and mock_uc/ are plain top-level packages (no
# setup.py/pyproject packaging config makes them pip-installable), findable
# at runtime only because launcher.py inserts the repo root into sys.path.
# PyInstaller's static import analysis never executes that line, so without
# this flag it silently fails to bundle them at all -- the build succeeds,
# and the binary dies with ModuleNotFoundError on first run. Confirmed by
# building without it and watching exactly that happen.
#
# --collect-all for the packages whose real import graph PyInstaller's static
# analysis can't fully see on its own: uvicorn/starlette/fastapi resolve a
# lot of their protocol and event-loop backends dynamically (the same class
# of problem as above), and websockets/numpy ship platform-specific
# extension modules. Costs some binary size; buys reliability on a build
# nobody can interactively debug from a CI log the way a normal
# `pip install` failure gets debugged.
"$BUILD_VENV/bin/pyinstaller" \
  --name sensor-monitor \
  --onefile \
  --noconfirm \
  --clean \
  --paths . \
  --add-data "frontend:frontend" \
  --collect-all uvicorn \
  --collect-all starlette \
  --collect-all fastapi \
  --collect-all websockets \
  --collect-all numpy \
  packaging/launcher.py

echo
echo "Built: dist/sensor-monitor"
echo "Run it with: ./dist/sensor-monitor"
