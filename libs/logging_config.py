import logging
import logging.handlers
import threading
from pathlib import Path

from libs.config import get_env

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
_FORMAT = "%(asctime)s  [%(process_label)s]  %(levelname)-8s  %(message)s"
_DATE = "%Y-%m-%d %H:%M:%S"
_setup_lock = threading.Lock()


def _log_path() -> Path:
    raw = get_env("AUV_LOG_PATH", default="auv.log")
    p = Path(raw)
    return p if p.is_absolute() else _PROJECT_ROOT / p


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

    handler = logging.handlers.RotatingFileHandler(
        _log_path(),
        maxBytes=2_000_000,
        backupCount=5,
        encoding="utf-8",
    )
    handler.setFormatter(logging.Formatter(_FORMAT, datefmt=_DATE))
    handler.addFilter(_LabelFilter())
    root.addHandler(handler)
    logging.getLogger(__name__).info("process started")
