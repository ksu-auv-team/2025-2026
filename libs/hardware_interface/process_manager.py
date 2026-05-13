import logging
import threading
import time
from typing import Callable

from auvsoftware.config import get_env
from auvsoftware.hardware_interface.scanner import scan_i2c_bus

_RETRY_DELAY: float = 5.0
_log = logging.getLogger(__name__)


def _with_retry(name: str, fn: Callable, stop_event: threading.Event) -> None:
    """Run *fn* in a loop, restarting after any exception (e.g. DB not yet up)."""
    while not stop_event.is_set():
        try:
            fn()
        except KeyboardInterrupt:
            break
        except Exception as exc:
            _log.error("%s crashed: %r — retrying in %.1fs", name, exc, _RETRY_DELAY)
            stop_event.wait(_RETRY_DELAY)


def _run_esc(stop_event: threading.Event) -> None:
    from auvsoftware.logging_config import setup_logging
    setup_logging("esc")
    from auvsoftware.hardware_interface.modules.esc_controller import ESCController
    _with_retry("esc", lambda: ESCController().run(), stop_event)


def _run_arm(stop_event: threading.Event) -> None:
    from auvsoftware.logging_config import setup_logging
    setup_logging("arm")
    from auvsoftware.hardware_interface.modules.arm_controller import ArmController
    _with_retry("arm", lambda: ArmController().run(), stop_event)


def _run_imu(stop_event: threading.Event) -> None:
    from auvsoftware.logging_config import setup_logging
    setup_logging("imu")
    from auvsoftware.hardware_interface.modules.imu_controller import ImuController
    _with_retry("imu", lambda: ImuController().run(), stop_event)


def _run_psa(stop_event: threading.Event) -> None:
    from auvsoftware.logging_config import setup_logging
    setup_logging("psa")
    from auvsoftware.hardware_interface.modules.psa_controller import PsaController
    _with_retry("psa", lambda: PsaController().run(), stop_event)


def _run_torpedo(stop_event: threading.Event) -> None:
    from auvsoftware.logging_config import setup_logging
    setup_logging("torpedo")
    from auvsoftware.hardware_interface.modules.tor_controller import TorpedoController
    _with_retry("torpedo", lambda: TorpedoController().run(), stop_event)


def _run_pressure(stop_event: threading.Event) -> None:
    from auvsoftware.logging_config import setup_logging
    setup_logging("pressure")
    from auvsoftware.hardware_interface.modules.pre_controller import PressureController
    _with_retry("pressure", lambda: PressureController().run(), stop_event)


def _run_display(stop_event: threading.Event) -> None:
    from auvsoftware.logging_config import setup_logging
    setup_logging("display")
    from auvsoftware.hardware_interface.modules.dis_controller import DisplayController
    _with_retry("display", lambda: DisplayController().run(), stop_event)


# (flag_env_key, address_env_key, short_name, target_fn)
_REGISTRY: list[tuple[str, str, str, Callable]] = [
    ("ESC_CONTROLLER",      "ESC_ADDRESS",      "esc",      _run_esc),
    ("ARM_CONTROLLER",      "ARM_ADDRESS",      "arm",      _run_arm),
    ("IMU_CONTROLLER",      "IMU_ADDRESS",      "imu",      _run_imu),
    ("PSA_CONTROLLER",      "PSA_ADDRESS",      "psa",      _run_psa),
    ("TORPEDO_CONTROLLER",  "TORPEDO_ADDRESS",  "torpedo",  _run_torpedo),
    ("PRESSURE_CONTROLLER", "PRESSURE_ADDRESS", "pressure", _run_pressure),
    ("DISPLAY_CONTROLLER",  "DISPLAY_ADDRESS",  "display",  _run_display),
]

_NAME_TO_TARGET: dict[str, Callable[[threading.Event], None]] = {
    name: fn for _, _, name, fn in _REGISTRY
}


class HardwareProcessManager:
    def __init__(self, dry_run: bool = False) -> None:
        """
        Args:
            dry_run: When True, log what would happen instead of spawning real
                     threads. Useful for testing detection + flag logic without
                     live hardware or a DB.
        """
        self.dry_run = dry_run
        self._threads: dict[str, tuple[threading.Thread, threading.Event]] = {}

    def _is_alive(self, name: str) -> bool:
        entry = self._threads.get(name)
        return entry is not None and entry[0].is_alive()

    def reconcile(self) -> None:
        """
        Scan the I2C bus and sync running threads against .env config.
        Starts a controller only when its flag is True AND its device is detected.
        Stops a controller when either condition becomes false.
        """
        bus = int(get_env("I2C_BUS_NUMBER", required=True))
        detected = set(scan_i2c_bus(bus))

        for flag_key, addr_key, name, _ in _REGISTRY:
            raw = get_env(flag_key, default="False").strip().lower()
            enabled = raw in ("true", "1", "yes")
            addr_str = get_env(addr_key, default="")
            address = int(addr_str.strip(), 16) if addr_str.strip() else None

            should_run = enabled and address is not None and address in detected

            if should_run and not self._is_alive(name):
                self._spawn(name)
            elif not should_run and self._is_alive(name):
                self.stop(name)

    def start_all(self) -> None:
        """Start all .env-enabled controllers regardless of I2C detection."""
        for flag_key, _, name, _ in _REGISTRY:
            raw = get_env(flag_key, default="False").strip().lower()
            if raw in ("true", "1", "yes"):
                self._spawn(name)

    def stop_all(self) -> None:
        """Stop all running controller threads."""
        for name in list(self._threads):
            self.stop(name)

    def start(self, name: str) -> None:
        """Manually start a controller by short name (e.g. 'esc')."""
        if name not in _NAME_TO_TARGET:
            valid = sorted(_NAME_TO_TARGET)
            raise ValueError(f"Unknown controller: '{name}'. Valid: {valid}")
        self._spawn(name)

    def stop(self, name: str) -> None:
        """Signal a controller thread to stop and wait for it. No-op if not running."""
        if self.dry_run:
            print(f"[dry_run] stop: {name}")
            return
        entry = self._threads.pop(name, None)
        if entry is None:
            return
        thread, stop_event = entry
        stop_event.set()
        thread.join(timeout=5)
        if thread.is_alive():
            _log.warning("%s thread did not exit within timeout", name)

    def status(self) -> dict[str, dict]:
        """
        Return status for every registered controller.

        Each entry: {"enabled": bool, "detected": bool, "running": bool,
        "tid": int|None}
        """
        try:
            bus = int(get_env("I2C_BUS_NUMBER", default="1"))
            detected = set(scan_i2c_bus(bus))
        except OSError:
            detected = set()

        result: dict[str, dict] = {}
        for flag_key, addr_key, name, _ in _REGISTRY:
            entry = self._threads.get(name)
            alive = entry is not None and entry[0].is_alive()
            addr_str = get_env(addr_key, default="")
            address = int(addr_str.strip(), 16) if addr_str.strip() else None
            result[name] = {
                "enabled": get_env(flag_key, default="False").strip().lower()
                in ("true", "1", "yes"),
                "detected": address is not None and address in detected,
                "running": alive,
                "tid": entry[0].ident if alive else None,
            }
        return result

    def _spawn(self, name: str) -> None:
        if self.dry_run:
            print(f"[dry_run] spawn: {name}")
            return
        if self._is_alive(name):
            return
        stop_event = threading.Event()
        t = threading.Thread(
            target=_NAME_TO_TARGET[name], args=(stop_event,), name=name, daemon=True
        )
        t.start()
        self._threads[name] = (t, stop_event)
