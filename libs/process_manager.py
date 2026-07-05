import multiprocessing
import time
from pathlib import Path

from libs.config import get_env

_DB_DIR = Path(__file__).parent / "db_manager"
_LIBS_DIR = Path(__file__).parent
_RECONCILE_INTERVAL: float = 5.0

# Extend this list as high-level packages are implemented.
_SERVICES: list[str] = ["db", "hardware_interface", "camera", "movement"]


def _run_db() -> None:
    """
    Start the FastAPI DB server.

    Inserts the db_manager directory into sys.path so its bare local
    imports (routers, deps, config) resolve without changing those files.
    """
    import logging
    import sys

    import uvicorn

    from libs.logging_config import setup_logging
    setup_logging("db")
    log = logging.getLogger(__name__)

    sys.path.insert(0, str(_DB_DIR))

    try:
        from libs.db_manager.run import app
    except Exception:
        log.exception("DB app failed to import")
        return

    host = get_env("AUV_HOST", default="0.0.0.0")
    port = int(get_env("AUV_PORT", default="8000"))
    try:
        uvicorn.run(app, host=host, port=port, reload=False, log_config=None)
    except BaseException:
        log.exception("DB server crashed")
        raise


def _run_hardware_interface(simulation: bool = False) -> None:
    """Start the hardware interface reconcile loop."""
    import logging
    import sys

    sys.path.insert(0, str(_LIBS_DIR))

    from libs.hardware_interface.process_manager import (
        HardwareProcessManager,
    )
    from libs.logging_config import setup_logging

    setup_logging("hardware_interface")
    log = logging.getLogger(__name__)

    pm = HardwareProcessManager(dry_run=simulation)
    while True:
        try:
            pm.reconcile()
        except Exception as exc:
            log.error("reconcile failed: %r", exc)
        time.sleep(_RECONCILE_INTERVAL)


def _run_camera() -> None:
    """Start the camera acquisition and streaming service."""
    from libs.camera_package.camera_manager import run
    run()


def _run_movement_package() -> None:
    """Start the movement package process."""
    from libs.movement_package.movement_package import run
    run()

_TARGETS: dict[str, object] = {
    "db": _run_db,
    "hardware_interface": _run_hardware_interface,
    "camera": _run_camera,
    "movement": _run_movement_package,
}


class ProcessManager:
    def __init__(self, dry_run: bool = False) -> None:
        """
        Args:
            dry_run: When True, log actions without starting real processes.
                     Useful for testing without live hardware or a DB.
        """
        self.dry_run = dry_run
        self._processes: dict[str, multiprocessing.Process] = {}

    def start_all(self) -> None:
        """Start all registered services."""
        for name in _SERVICES:
            self.start(name)

    def stop_all(self) -> None:
        """Terminate all running services."""
        for name in list(self._processes):
            self.stop(name)

    def start(self, name: str, simulation: bool = False) -> None:
        """Start a service by name. No-op if already running."""
        if name not in _TARGETS:
            raise ValueError(
                f"Unknown service: '{name}'. Valid: {_SERVICES}",
            )
        if self._is_alive(name):
            return
        if self.dry_run:
            print(f"[dry_run] start: {name}")
            return
        kwargs = {"simulation": simulation} if name == "hardware_interface" else {}
        p = multiprocessing.Process(
            target=_TARGETS[name], name=name, daemon=True, kwargs=kwargs,
        )
        p.start()
        self._processes[name] = p

    def stop(self, name: str) -> None:
        """Terminate a service. No-op if not running."""
        if self.dry_run:
            print(f"[dry_run] stop: {name}")
            return
        proc = self._processes.pop(name, None)
        if proc is None:
            return
        proc.terminate()
        proc.join(timeout=5)
        if proc.is_alive():
            proc.kill()

    def status(self) -> dict[str, dict]:
        """Return running status for every registered service."""
        result: dict[str, dict] = {}
        for name in _SERVICES:
            alive = self._is_alive(name)
            proc = self._processes.get(name)
            result[name] = {
                "running": alive,
                "pid": proc.pid if alive else None,
            }
        return result

    def _is_alive(self, name: str) -> bool:
        proc = self._processes.get(name)
        return proc is not None and proc.is_alive()
