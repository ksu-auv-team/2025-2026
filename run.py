#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
@file run.py
@brief Orchestrator to discover and run sub-packages' run.sh scripts as subprocesses.

@details
  - Scans the ./libs directory for subfolders and recursively finds any run.sh.
  - Lets you select which discovered services to run via CLI (--all, --only, --exclude).
  - Optionally forwards arguments to each run.sh (--forward).
  - Streams output to console and writes per-service logs under ./logs/.
  - Graceful shutdown on SIGINT/SIGTERM: sends TERM, then KILL if needed.

@usage
  # List everything discovered
  ./run.py --list

  # Run all discovered services
  ./run.py --all

  # Run only db_manager and camera_package (service names are path-like keys)
  ./run.py --only db_manager camera_package

  # Exclude a service while running all others
  ./run.py --all --exclude ai_package

  # Forward arguments to each run.sh (quoted as one string)
  ./run.py --only db_manager --forward "--port 8000 --debug"

  # Dry run (print what would be executed)
  ./run.py --all --dry-run

  # Set environment variables for child processes
  ./run.py --all --env BASE_URL=http://127.0.0.1:8000 --env MODE=prod
"""

from __future__ import annotations

import argparse
import os
import shlex
import signal
import subprocess
import sys
import time
import io
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Dict, Iterable, List, Mapping, Optional, Sequence, Tuple


# ------------------------------- Constants ------------------------------------

LIBS_DIR = Path(__file__).parent / "libs"
LOGS_DIR = Path(__file__).parent / "logs"
RUN_SCRIPT_NAME = "run.sh"
GRACE_SECONDS = 5.0


# ------------------------------ Data Classes ----------------------------------

@dataclass(frozen=True)
class Service:
    """
    @brief A discovered runnable service.

    @param key A short, unique key identifying the service (e.g., "db_manager" or "db_manager/api").
    @param run_sh Path to the run.sh script.
    @param cwd Working directory to execute the script in (its parent directory).
    """
    key: str
    run_sh: Path
    cwd: Path


@dataclass
class RunningProc:
    """
    @brief Metadata for a running subprocess.

    @param service The associated service.
    @param popen The running Popen instance.
    @param log_path File path to the combined stdout/stderr log.
    """
    service: Service
    popen: subprocess.Popen
    log_path: Path


# ------------------------------- Discovery ------------------------------------

def _relative_service_key(run_sh: Path, libs_root: Path) -> str:
    """
    @brief Build a readable key for the service based on its path under libs.

    @param run_sh Path to run.sh found in libs subtree.
    @param libs_root Path to libs/ directory.
    @return Relative key like "db_manager" or "db_manager/tools" if run.sh is nested.
    """
    rel = run_sh.parent.relative_to(libs_root)
    return str(rel).replace(os.sep, "/")  # normalize


def discover_services(libs_root: Path = LIBS_DIR) -> Dict[str, Service]:
    """
    @brief Recursively discover run.sh scripts under libs_root.

    @param libs_root The root 'libs' directory to scan.
    @return Dict mapping service key -> Service.
    """
    services: Dict[str, Service] = {}
    if not libs_root.exists():
        return services

    # Only consider *subdirectories* of libs first (as requested)
    for top in sorted([p for p in libs_root.iterdir() if p.is_dir()]):
        # Recursively look for any run.sh under this top-level subdirectory
        for run_sh in top.rglob(RUN_SCRIPT_NAME):
            if not run_sh.is_file():
                continue
            # Ensure it's executable; if not, we still can invoke via 'bash run.sh'
            key = _relative_service_key(run_sh, libs_root)
            services[key] = Service(key=key, run_sh=run_sh, cwd=run_sh.parent)

    return services


# ----------------------------- Argument Parsing -------------------------------

def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    """
    @brief Parse CLI arguments for the orchestrator.
    """
    parser = argparse.ArgumentParser(
        description="Discover and run sub-packages' run.sh scripts."
    )
    sel = parser.add_mutually_exclusive_group(required=False)
    sel.add_argument("--all", action="store_true", help="Run all discovered services.")
    sel.add_argument(
        "--only",
        nargs="+",
        metavar="SERVICE",
        help="Run only the named services (see --list).",
    )

    parser.add_argument(
        "--exclude",
        nargs="+",
        default=[],
        metavar="SERVICE",
        help="Exclude these services when using --all.",
    )
    parser.add_argument(
        "--list",
        action="store_true",
        help="List discovered services and exit.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be executed without starting processes.",
    )
    parser.add_argument(
        "--forward",
        default=None,
        metavar="ARGS",
        help="Quoted argument string to forward to each run.sh. Example: \"--port 8000 --debug\"",
    )
    parser.add_argument(
        "--env",
        action="append",
        default=[],
        metavar="K=V",
        help="Set environment variables for child processes (can be repeated).",
    )
    parser.add_argument(
        "--no-console-tee",
        action="store_true",
        help="Do not stream child output to console (still logs to files).",
    )
    parser.add_argument(
        "--grace",
        type=float,
        default=GRACE_SECONDS,
        help=f"Seconds to wait after TERM before KILL (default {GRACE_SECONDS}).",
    )
    return parser.parse_args(argv)


# ----------------------------- Utility Functions ------------------------------

def _parse_env_overrides(items: Iterable[str]) -> Dict[str, str]:
    """
    @brief Parse --env K=V entries into a dictionary.

    @param items Iterable of strings "K=V".
    @return Dict of environment overrides.
    """
    env: Dict[str, str] = {}
    for raw in items:
        if "=" not in raw:
            raise SystemExit(f"--env must be in K=V form, got: {raw!r}")
        k, v = raw.split("=", 1)
        k = k.strip()
        v = v.strip()
        if not k:
            raise SystemExit(f"Invalid env key in: {raw!r}")
        env[k] = v
    return env


def _build_command(service: Service, forward: Optional[str]) -> List[str]:
    """
    @brief Build the command to run for a service.

    @param service The service.
    @param forward Optional argument string to append.
    @return Command list for subprocess.Popen.
    """
    base = ["bash", str(service.run_sh)]
    if forward:
        base += shlex.split(forward)
    return base


def _timestamp() -> str:
    """@brief yyyy-mm-dd_HHMMSS timestamp for log naming."""
    return datetime.now().strftime("%Y-%m-%d_%H%M%S")


def _open_log_file(service_key: str) -> tuple[Path, io.TextIOWrapper]:
    """
    @brief Create/open a log file for a service.

    @param service_key The service identifier.
    @return (log_path, handle)
    """
    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    log_path = LOGS_DIR / f"{service_key.replace('/', '_')}_{_timestamp()}.log"
    handle = open(log_path, "a", buffering=1, encoding="utf-8", errors="replace")
    return log_path, handle


# ------------------------------- Main Runner ----------------------------------

def _select_services(
    discovered: Mapping[str, Service],
    run_all: bool,
    only: Optional[Sequence[str]],
    exclude: Sequence[str],
) -> Dict[str, Service]:
    """
    @brief Filter discovered services based on CLI selection.

    @return Dict of selected services preserving key->Service.
    """
    if only:
        chosen = {k: v for k, v in discovered.items() if k in set(only)}
        missing = set(only) - set(chosen.keys())
        if missing:
            missing_list = ", ".join(sorted(missing))
            raise SystemExit(f"Requested service(s) not found: {missing_list}")
        return dict(sorted(chosen.items()))
    if run_all:
        chosen = {k: v for k, v in discovered.items() if k not in set(exclude)}
        return dict(sorted(chosen.items()))
    # Default: if neither --all nor --only, do nothing but advise
    return {}


def _print_service_table(services: Mapping[str, Service]) -> None:
    """
    @brief Pretty-print discovered services.
    """
    if not services:
        print("(no services discovered)")
        return
    width = max(len(k) for k in services.keys())
    print("Discovered services:")
    for k, s in sorted(services.items()):
        rel_run = s.run_sh.relative_to(Path(__file__).parent)
        print(f"  {k.ljust(width)}  ->  {rel_run}")


def run_services(
    services: Mapping[str, Service],
    forward: Optional[str],
    env_overrides: Mapping[str, str],
    tee_console: bool,
    grace_seconds: float,
    dry_run: bool,
) -> int:
    """
    @brief Launch and supervise selected services.

    @param services Selected services to run.
    @param forward Optional string of args to forward to each run.sh.
    @param env_overrides Environment variables to add/override for children.
    @param tee_console If True, also echo child output to our stdout/stderr.
    @param grace_seconds How long to wait after TERM before KILL on shutdown.
    @param dry_run If True, do not actually start processes.
    @return Exit code (0 = success).
    """
    if not services:
        print("No services selected. Use --list, --all, or --only.")
        return 2

    # Build commands
    commands: Dict[str, List[str]] = {
        key: _build_command(svc, forward) for key, svc in services.items()
    }

    print("Planned commands:")
    for key, cmd in commands.items():
        print(f"  {key}: {shlex.join(cmd)}")
    if dry_run:
        return 0

    # Prepare environment
    child_env = os.environ.copy()
    child_env.update(env_overrides)

    # Launch
    running: Dict[str, RunningProc] = {}
    log_handles: Dict[str, "io.TextIOWrapper"] = {}

    import io
    try:
        for key, svc in services.items():
            log_path, log_handle = _open_log_file(key)
            log_handles[key] = log_handle
            popen = subprocess.Popen(
                commands[key],
                cwd=str(svc.cwd),
                env=child_env,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,  # line-buffered
            )
            running[key] = RunningProc(service=svc, popen=popen, log_path=log_path)
            print(f"[started] {key} (pid={popen.pid}) → {log_path}")

        # Install signal handlers for graceful shutdown
        stopping = {"flag": False}

        def _handle_signal(signum, _frame):
            if not stopping["flag"]:
                print(f"\n[signal] Received {signal.Signals(signum).name}, stopping…")
                stopping["flag"] = True

        signal.signal(signal.SIGINT, _handle_signal)
        signal.signal(signal.SIGTERM, _handle_signal)

        # Pump output until all exit or we're stopping
        while running and not stopping["flag"]:
            finished: List[str] = []
            for key, r in list(running.items()):
                assert r.popen.stdout is not None
                line = r.popen.stdout.readline()
                if line:  # live output
                    log_handles[key].write(line)
                    if tee_console:
                        sys.stdout.write(f"[{key}] {line}")
                        sys.stdout.flush()
                else:
                    # EOF? check if process ended
                    rc = r.popen.poll()
                    if rc is not None:
                        finished.append(key)
                        print(f"[exit] {key} rc={rc}")
                        # Drain remaining output if any
                        rem = r.popen.stdout.read()
                        if rem:
                            log_handles[key].write(rem)
            for key in finished:
                # Close its handle and remove from tracking
                log_handles[key].flush()
                log_handles[key].close()
                del log_handles[key]
                del running[key]
            # Avoid busy loop
            time.sleep(0.05)

        # If stopping requested, terminate remaining
        if running:
            print("[shutdown] Terminating services…")
            for key, r in running.items():
                with contextlib.suppress(ProcessLookupError):
                    r.popen.terminate()
            # Wait up to grace_seconds, then kill leftovers
            deadline = time.time() + grace_seconds
            while running and time.time() < deadline:
                still: List[str] = []
                for key, r in list(running.items()):
                    rc = r.popen.poll()
                    if rc is None:
                        still.append(key)
                    else:
                        print(f"[exit] {key} rc={rc}")
                        # Drain output
                        if r.popen.stdout:
                            rem = r.popen.stdout.read() or ""
                            if rem:
                                log_handles[key].write(rem)
                        log_handles[key].flush()
                        log_handles[key].close()
                        del log_handles[key]
                        del running[key]
                if still:
                    time.sleep(0.1)

            # Force kill any stubborn ones
            if running:
                print("[shutdown] Killing remaining services…")
                for key, r in running.items():
                    with contextlib.suppress(ProcessLookupError):
                        r.popen.kill()
                # Final cleanup
                for key, r in list(running.items()):
                    r.popen.wait(timeout=1)
                    if r.popen.stdout:
                        rem = r.popen.stdout.read() or ""
                        if rem:
                            log_handles[key].write(rem)
                    log_handles[key].flush()
                    log_handles[key].close()
                    del log_handles[key]
                    del running[key]

        return 0
    finally:
        # Safety: ensure all logs closed
        for h in list(log_handles.values()):
            with contextlib.suppress(Exception):
                h.flush()
                h.close()


# ------------------------------- Entry Point ----------------------------------

import contextlib  # placed here to avoid top clutter

def main(argv: Optional[Sequence[str]] = None) -> int:
    """
    @brief Entrypoint for the CLI orchestrator.
    """
    args = parse_args(argv)
    discovered = discover_services(LIBS_DIR)

    if args.list:
        _print_service_table(discovered)
        return 0

    selected = _select_services(
        discovered=discovered,
        run_all=args.all,
        only=args.only,
        exclude=args.exclude,
    )

    env_overrides = _parse_env_overrides(args.env)

    # If user didn't choose --all or --only, guide them:
    if not selected and not args.dry_run:
        _print_service_table(discovered)
        print("\nSelect what to run with --all or --only <services…> (see keys above).")
        return 2

    rc = run_services(
        services=selected,
        forward=args.forward,
        env_overrides=env_overrides,
        tee_console=not args.no_console_tee,
        grace_seconds=float(args.grace),
        dry_run=bool(args.dry_run),
    )
    return int(rc)


if __name__ == "__main__":
    sys.exit(main())
