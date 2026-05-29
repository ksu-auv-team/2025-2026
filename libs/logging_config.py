import logging
import threading
from datetime import datetime
from pathlib import Path

from libs.config import get_env

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_FORMAT = "%(asctime)s  [%(process_label)s]  %(levelname)-8s  %(message)s"
_DATE = "%Y-%m-%d %H:%M:%S"
_setup_lock = threading.Lock()
_RUN_TS = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")


def current_log_path() -> Path:
    """Return the resolved log file path including the run timestamp."""
    return _log_path()


def _log_path() -> Path:
    raw = get_env("AUV_LOG_PATH", default="auv.log")
    p = Path(raw)
    if not p.is_absolute():
        p = _PROJECT_ROOT / p
    return p.with_stem(f"{p.stem}_{_RUN_TS}")


def setup_logging(process_label: str) -> None:
    """
    Configure the root logger for the current process/thread to write to the
    shared rotating log file. Call once at the top of each subprocess target.
    All loggers in the process inherit this handler automatically.
    """
    root = logging.getLogger()
    with _setup_lock:
        if root.handlers:
            return

    root.setLevel(logging.INFO)

    class _LabelFilter(logging.Filter):
        def filter(self, record: logging.LogRecord) -> bool:
            record.process_label = process_label  # type: ignore[attr-defined]
            return True

    log_path = _log_path()
    log_path.parent.mkdir(parents=True, exist_ok=True)
    handler = logging.FileHandler(log_path, encoding="utf-8")
    handler.setFormatter(logging.Formatter(_FORMAT, datefmt=_DATE))
    handler.addFilter(_LabelFilter())
    root.addHandler(handler)
    logging.getLogger(__name__).info("process started")
