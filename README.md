# KSU AUV 2025-2026

Software stack for the KSU Autonomous Underwater Vehicle team's 2026 RoboSub competition entry.

---

## Project Structure

```
.
├── libs/
│   ├── ai_package/          # AI / computer-vision tasks
│   ├── camera_package/      # Camera capture and streaming
│   ├── data_visualizer/     # Web dashboard (FastAPI + Jinja2)
│   ├── db_manager/          # Telemetry REST API (FastAPI + aiosqlite)
│   ├── hardware_interface/  # Low-level I2C / hardware drivers
│   ├── movement_package/    # PID motion controller
│   ├── sonar_package/       # Sonar / hydrophone processing
│   ├── config.py            # Environment variable helpers (.env loading)
│   ├── logging_config.py    # Shared rotating-file logger for all subprocesses
│   ├── process_manager.py   # Launch / monitor AUV services via multiprocessing
│   ├── quick_request.py     # AUVClient — HTTP helpers for reading/writing the DB API
│   └── ui.py                # Textual TUI — ground-station control interface
├── tests/                   # pytest unit & integration tests
├── docs/                    # In-depth documentation
│   ├── db_manager.md
│   ├── hardware_interface.md
│   └── GIT_CHEATSHEET.md
├── run.py                   # Legacy launcher (db_manager + data_visualizer)
└── pyproject.toml
```

---

## Quick Start

### Prerequisites

- Python ~= 3.12
- [`uv`](https://docs.astral.sh/uv/getting-started/installation/)

### Install

```bash
uv sync --all-groups
```

`uv` creates the virtual environment and installs all runtime and dev dependencies declared in `pyproject.toml`.

### Launch the TUI

```bash
uv run auv
```

This starts the Textual ground-station interface. It polls the DB API for live telemetry and lets you start/stop services, send manual commands, and tune PID gains — all from the terminal.

### Run services individually

**DB Manager API** (required for telemetry and the TUI):

```bash
cd libs/db_manager
uv run uvicorn run:app --reload --host 0.0.0.0 --port 8000
```

Interactive API docs at `http://localhost:8000/docs`.

---

## Modules

### `libs/ui.py` — Control TUI

A Textual dark-mode terminal interface for the ground station. Panels:

- **Services** — start/stop db, hardware_interface, movement, camera, ai via `ProcessManager`
- **Controllers** — per-device status (ESC, arm, IMU, etc.) via `HardwareProcessManager`
- **Telemetry** — live plotext graphs for accelerometer, gyroscope, magnetometer, depth, and power
- **Manual Command** — post `inputs` rows directly to the DB API
- **PID Gains** — edit and push roll/pitch stabilisation gains

Key bindings: `1–5` toggle services, `a`/`A` start/stop all, `s` toggle sim mode, `Ctrl+S` send inputs, `l` view logs, `q` quit.

### `libs/process_manager.py` — ProcessManager

Spawns and monitors AUV services as daemon subprocesses using `multiprocessing`. Supports `start`, `stop`, `start_all`, `stop_all`, and `status`. Currently manages `db` and `hardware_interface`; extend `_SERVICES` and `_TARGETS` to add more.

```python
from libs.process_manager import ProcessManager
pm = ProcessManager()
pm.start("db")
pm.status()   # {"db": {"running": True, "pid": 12345}, ...}
pm.stop_all()
```

### `libs/quick_request.py` — AUVClient

Thin `requests`-based HTTP client for reading and writing the DB API. All other packages should use this instead of raw HTTP calls.

```python
from libs.quick_request import AUVClient

client = AUVClient()                        # default: http://localhost:8000
client = AUVClient("http://orin:8000")     # remote Orin

client.post("depth", DEPTH=1.23)
row  = client.latest("imu")
page = client.list("inputs", limit=100, start="2026-01-01T00:00:00Z")
client.delete("inputs", id1=7)
```

Module-level convenience functions (`post`, `latest`, `get`, `list_rows`, `delete`) are also available for quick one-off calls.

### `libs/config.py` — Environment Config

Loads `.env` from the project root and exposes `get_env`:

```python
from libs.config import get_env

host = get_env("AUV_HOST", default="0.0.0.0")
port = get_env("AUV_PORT", required=True)   # raises RuntimeError if missing
```

Relevant env vars:

| Variable | Default | Description |
|---|---|---|
| `AUV_HOST` | `0.0.0.0` | DB server bind address |
| `AUV_PORT` | `8000` | DB server port |
| `AUV_LOG_PATH` | `auv.log` | Log file path (absolute or relative to project root) |

### `libs/logging_config.py` — Logging

Call `setup_logging` once at the top of each subprocess target to attach a shared rotating file handler (2 MB, 5 backups) labelled with the process name.

```python
from libs.logging_config import setup_logging
setup_logging("hardware_interface")
```

### `libs/db_manager/` — Telemetry API

FastAPI service backed by SQLite. Stores and serves inputs, outputs, IMU, depth, hydrophone, and power-safety readings. See [docs/db_manager.md](docs/db_manager.md) for full schema and endpoint reference.

### `libs/hardware_interface/` — Hardware Drivers

I2C drivers for sensors (IMU, depth, hydrophone) and actuators (ESC/PCA9685). See [docs/hardware_interface.md](docs/hardware_interface.md).

---

## Development

### Linting & formatting

```bash
uv run ruff check .
uv run black --check .
uv run black .           # auto-format
uv run mypy libs
```

### Tests

```bash
# unit + integration (no physical hardware required)
uv run pytest -m "not hardware"

# include hardware tests (AUV must be connected)
uv run pytest -m hardware
```

Coverage gate: **75%** (`--cov-fail-under=75` in `pytest.ini`).

### CI

GitHub Actions runs on every push and pull request — Ruff → Black → Mypy → pytest (no-hardware) — across Python 3.10, 3.11, and 3.12.

---

## Documentation

| Document | Description |
|---|---|
| [docs/db_manager.md](docs/db_manager.md) | DB Manager API — schema, endpoints, running, smoke testing |
| [docs/hardware_interface.md](docs/hardware_interface.md) | Hardware Interface — I2C drivers, sensor wiring, actuator mapping |
| [docs/GIT_CHEATSHEET.md](docs/GIT_CHEATSHEET.md) | Git workflow reference for new team members |

---

## Contributing

1. Branch off `main` using `<name>-<feature>` naming (e.g. `lees-hwi`).
2. Keep commits small and focused; use imperative commit messages.
3. Open a pull request and get at least one review before merging.

See [docs/GIT_CHEATSHEET.md](docs/GIT_CHEATSHEET.md) for the full Git workflow.

---

## License

See [LICENSE](LICENSE).
