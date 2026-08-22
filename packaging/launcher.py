"""Entry point for the standalone Sensor Monitor binary.

Not part of the application proper -- this is what PyInstaller freezes into
`sensor-monitor`, for anyone who wants to run the app without installing
Python or Docker at all. It starts the mock uC and the backend on the same
asyncio event loop (one process, one binary, no subprocesses to manage) and
opens a browser.

Build it with packaging/build.sh; see packaging/README.md for details.

    python packaging/launcher.py                 (also runs fine unfrozen,
                                                    from a normal checkout
                                                    with the deps installed --
                                                    useful for testing this
                                                    file without a PyInstaller
                                                    build at all)
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import os
import socket
import sys
import threading
import webbrowser
from pathlib import Path

# Unfrozen only: this file lives in packaging/, one level below the repo
# root, so `backend` and `mock_uc` aren't importable via the normal
# `python packaging/launcher.py` invocation without this. A frozen build
# needs no such fixup -- PyInstaller's own import machinery resolves bundled
# modules directly, independent of sys.path/filesystem layout.
if not getattr(sys, "frozen", False):
    _repo_root = str(Path(__file__).resolve().parent.parent)
    if _repo_root not in sys.path:
        sys.path.insert(0, _repo_root)

# ---------------------------------------------------------------------------
# Locate the bundled frontend, if this is a frozen build.
#
# Must happen before importing backend.app.main: that module reads
# SENSOR_MONITOR_FRONTEND_DIR at import time to decide where index.html and
# app.js live. Unfrozen (running this file straight from the repo), it is
# left unset and backend.app.main falls back to its normal repo-relative
# path -- this branch only exists for the frozen case.
# ---------------------------------------------------------------------------


def _bundled_frontend_dir() -> Path | None:
    """Where PyInstaller put frontend/, or None if this isn't a frozen build.

    Onefile builds unpack everything (including --add-data) under a fresh
    temp directory named in sys._MEIPASS every time the binary runs; that
    attribute simply doesn't exist in a normal `python launcher.py` run,
    which is exactly the signal used here to tell the two cases apart.
    """
    if not getattr(sys, "frozen", False):
        return None
    meipass = getattr(sys, "_MEIPASS", None)
    base = Path(meipass) if meipass else Path(sys.executable).resolve().parent
    return base / "frontend"


_frontend_dir = _bundled_frontend_dir()
if _frontend_dir is not None:
    os.environ["SENSOR_MONITOR_FRONTEND_DIR"] = str(_frontend_dir)


def _port_free(host: str, port: int) -> bool:
    """A real bind attempt, not just "is something answering" -- catches a
    port that's reserved but not yet listening too."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        sock.bind((host, port))
        return True
    except OSError:
        return False
    finally:
        sock.close()


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="sensor-monitor",
        description=(
            "Sensor Monitor, self-contained: starts the mock uC and the "
            "backend together, no Python or Docker installation required."
        ),
    )
    parser.add_argument("--host", default="0.0.0.0", help="address the web UI binds to")
    parser.add_argument("--port", type=int, default=48000, help="web UI port")
    parser.add_argument("--uc-port", type=int, default=48765, help="mock uC port")
    parser.add_argument(
        "--fps", type=float, default=60.0, help="mock frame rate (real board is ~100)"
    )
    parser.add_argument(
        "--samples", type=int, default=20000, help="samples per mock frame (20000 = valid)"
    )
    parser.add_argument(
        "--no-mock", action="store_true", help="do not start the mock uC (for real hardware)"
    )
    parser.add_argument(
        "--uc-url",
        default=None,
        help="pre-fill the GUI with this uC URL instead of ws://127.0.0.1:<uc-port> "
        "(combine with --no-mock to point at real hardware)",
    )
    parser.add_argument("--no-browser", action="store_true", help="do not open a browser window")
    return parser.parse_args(argv)


async def _serve(args: argparse.Namespace) -> None:
    # Deferred: backend.app.main reads SENSOR_MONITOR_FRONTEND_DIR (and
    # SENSOR_MONITOR_UC_URL, set below) as soon as it is imported.
    default_uc_url = args.uc_url or f"ws://127.0.0.1:{args.uc_port}"
    os.environ.setdefault("SENSOR_MONITOR_UC_URL", default_uc_url)

    import uvicorn

    from backend.app.main import app as fastapi_app

    config = uvicorn.Config(fastapi_app, host=args.host, port=args.port, log_level="info")
    server = uvicorn.Server(config)

    def open_browser() -> None:
        display_host = "127.0.0.1" if args.host in ("", "0.0.0.0") else args.host
        with contextlib.suppress(Exception):
            webbrowser.open(f"http://{display_host}:{args.port}")

    if not args.no_mock:
        import websockets

        from mock_uc.server import _handler as uc_handler

        async def bound_uc_handler(ws):
            await uc_handler(ws, args.fps, args.samples)

        async with websockets.serve(
            bound_uc_handler, "0.0.0.0", args.uc_port, max_size=None, compression=None
        ):
            print(
                f"[sensor-monitor] mock uC listening on ws://127.0.0.1:{args.uc_port} "
                f"({args.samples} samples/frame, {args.fps} fps target)"
            )
            _print_banner(args)
            if not args.no_browser:
                threading.Timer(1.0, open_browser).start()
            await server.serve()
    else:
        _print_banner(args)
        if not args.no_browser:
            threading.Timer(1.0, open_browser).start()
        await server.serve()


def _print_banner(args: argparse.Namespace) -> None:
    display_host = "127.0.0.1" if args.host in ("", "0.0.0.0") else args.host
    print()
    print(f"  Open http://{display_host}:{args.port}")
    if not args.no_mock:
        print(f"  URL field pre-fills with ws://127.0.0.1:{args.uc_port} -- press Connect.")
    print("  Ctrl-C to stop.")
    print()


def main(argv: list[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)

    checks = [("web UI", args.host or "0.0.0.0", args.port)]
    if not args.no_mock:
        checks.append(("mock uC", "0.0.0.0", args.uc_port))
    for label, host, port in checks:
        if not _port_free(host, port):
            print(
                f"ERROR: port {port} ({label}) is already in use.\n"
                f"Stop whatever is using it, or pick a different one "
                f"(--port / --uc-port).",
                file=sys.stderr,
            )
            return 1

    with contextlib.suppress(KeyboardInterrupt):
        asyncio.run(_serve(args))
    return 0


if __name__ == "__main__":
    sys.exit(main())
