# DB Manager

The DB Manager is a lightweight FastAPI service that stores and exposes all AUV telemetry over a REST API. It uses an async SQLite backend (`aiosqlite`) so it stays non-blocking and runs comfortably on the Jetson Orin.

---

## Architecture

```
┌─────────────────────────────────┐
│         FastAPI app (run.py)    │
│                                 │
│  lifespan (deps.py)             │  startup / shutdown
│    └─ DatabaseManager           │  connect, create tables, row_factory
│                                 │
│  APIRouter (routers.py)         │  all CRUD endpoints
│    └─ get_db (deps.py)          │  per-request connection dependency
└─────────────────────────────────┘
            │
            ▼
     auv_database.db  (SQLite)
```

| File | Role |
|---|---|
| `database.py` | `DatabaseManager` — raw async query helpers |
| `deps.py` | FastAPI lifespan (startup/shutdown) and `get_db` dependency |
| `run.py` | `FastAPI` app instance; registers the router |
| `routers.py` | All REST endpoints |
| `models.py` | Pydantic request/response models |

---

## Database Schema

All timestamps are stored as ISO-8601 UTC strings and are set automatically by the database (`strftime('%Y-%m-%dT%H:%M:%fZ','now')`) if not provided by the caller.

### `inputs`

Controller inputs received from the operator.

| Column | Type | Description |
|---|---|---|
| ID | INTEGER PK | Auto-increment |
| TIMESTAMP | TEXT | ISO-8601 UTC |
| SURGE | INTEGER | Forward / backward thrust command |
| SWAY | INTEGER | Left / right thrust command |
| HEAVE | INTEGER | Up / down thrust command |
| ROLL | INTEGER | Roll rotation command |
| PITCH | INTEGER | Pitch rotation command |
| YAW | INTEGER | Yaw rotation command |
| S1 | BOOLEAN (0/1) | Switch 1 |
| S2 | BOOLEAN (0/1) | Switch 2 |
| S3 | INTEGER | Switch 3 (multi-state) |
| ARM | BOOLEAN (0/1) | Arm/disarm flag |

### `outputs`

Motor and actuator commands sent to hardware.

| Column | Type | Description |
|---|---|---|
| ID | INTEGER PK | Auto-increment |
| TIMESTAMP | TEXT | ISO-8601 UTC |
| MOTOR1 | INTEGER | Motor 1 PWM value |
| MOTOR2 | INTEGER | Motor 2 PWM value |
| MOTOR3 | INTEGER | Motor 3 PWM value |
| MOTOR4 | INTEGER | Motor 4 PWM value |
| VERTICAL_THRUST | INTEGER | Vertical thruster PWM value |
| S1 | INTEGER | Servo / actuator 1 |
| S2 | INTEGER | Servo / actuator 2 |
| S3 | INTEGER | Servo / actuator 3 |

### `hydrophone`

Acoustic heading readings.

| Column | Type | Description |
|---|---|---|
| ID | INTEGER PK | Auto-increment |
| TIMESTAMP | TEXT | ISO-8601 UTC |
| HEADING | STRING(5) | Cardinal or bearing string (e.g. `"N"`, `"NE"`) |

### `depth`

Depth sensor readings.

| Column | Type | Description |
|---|---|---|
| ID | INTEGER PK | Auto-increment |
| TIMESTAMP | TEXT | ISO-8601 UTC |
| DEPTH | REAL | Depth in meters |

### `imu`

Inertial Measurement Unit data (accelerometer, gyroscope, magnetometer).

| Column | Type | Description |
|---|---|---|
| ID | INTEGER PK | Auto-increment |
| TIMESTAMP | TEXT | ISO-8601 UTC |
| ACCEL_X/Y/Z | REAL | Linear acceleration (m/s²) |
| GYRO_X/Y/Z | REAL | Angular velocity (rad/s) |
| MAG_X/Y/Z | REAL | Magnetic field (µT) |

### `power_safety`

Battery monitoring for three battery packs.

| Column | Type | Description |
|---|---|---|
| ID | INTEGER PK | Auto-increment |
| TIMESTAMP | TEXT | ISO-8601 UTC |
| B1/B2/B3_VOLTAGE | INTEGER | Pack voltage (raw ADC or mV) |
| B1/B2/B3_CURRENT | INTEGER | Pack current (raw ADC or mA) |
| B1/B2/B3_TEMP | INTEGER | Pack temperature (°C or raw) |

---

## REST API Endpoints

Every resource follows the same pattern. Replace `{resource}` with one of: `inputs`, `outputs`, `hydrophone`, `depth`, `imu`, `power_safety`.

### Create a record

```
POST /{resource}
Content-Type: application/x-www-form-urlencoded
```

Supply all required fields as form parameters (see schema above). `TIMESTAMP` is optional — the DB fills it in automatically.

**Response:** the newly inserted row as JSON.

### List records

```
GET /{resource}?limit=50&offset=0&start=<ISO>&end=<ISO>
```

| Query param | Default | Description |
|---|---|---|
| `limit` | 50 | Max rows returned (1 – 500) |
| `offset` | 0 | Pagination offset |
| `start` | — | ISO-8601 lower bound (inclusive) |
| `end` | — | ISO-8601 upper bound (inclusive) |

**Response:**

```json
{
  "items": [...],
  "total": 123,
  "limit": 50,
  "offset": 0
}
```

### Get latest record

```
GET /{resource}/latest
```

Returns the most recent row ordered by `TIMESTAMP DESC`, or `null` if the table is empty.

### Get record by ID

```
GET /{resource}/{id}
```

Returns the row with the given `ID`, or `404` if not found.

### Delete record by ID

```
DELETE /{resource}/{id}
```

Returns `204 No Content` on success, `404` if not found.

---

## Running

### Development (with auto-reload)

```bash
cd libs/db_manager
uvicorn run:app --reload --host 0.0.0.0 --port 8000
```

### On the Orin (production)

```bash
bash libs/db_manager/run.sh
```

The run script launches uvicorn bound to all interfaces on port 8000 without `--reload`.

### Interactive docs

Once running, open `http://<host>:8000/docs` for the Swagger UI or `http://<host>:8000/redoc` for ReDoc.

---

## Smoke Testing

`smoke_test.sh` exercises every endpoint end-to-end. It requires `curl` and `jq`.

```bash
# against local dev server
bash libs/db_manager/smoke_test.sh

# against the Orin on the network
BASE=http://orin:8000 bash libs/db_manager/smoke_test.sh
```

The script inserts one row per table, reads it back via list / latest / by-id, then deletes it and prints the HTTP status code for each call.

---

## DatabaseManager API

`DatabaseManager` in [libs/db_manager/database.py](../libs/db_manager/database.py) provides the low-level async helpers. The FastAPI app accesses the connection directly through `deps.get_db`, but other packages can use `DatabaseManager` standalone.

```python
from libs.db_manager.database import DatabaseManager

db = DatabaseManager("path/to/auv_database.db")
await db.connect()
await db.setup()           # creates tables if they don't exist

row  = await db.fetchone("SELECT * FROM depth WHERE ID = ?", (1,))
rows = await db.fetchall("SELECT * FROM imu")
latest = await db.fetchlatest("imu", "TIMESTAMP")
between = await db.fetchbetween("depth", "TIMESTAMP", start_dt, end_dt)

await db.execute("INSERT INTO depth (DEPTH) VALUES (?)", (3.5,))
await db.close()
```

| Method | Description |
|---|---|
| `connect()` | Opens the aiosqlite connection and enables foreign keys |
| `close()` | Closes the connection |
| `execute(query, params)` | Run a write query and commit |
| `fetchone(query, params)` | Return the first matching row |
| `fetchall(query, params)` | Return all matching rows |
| `fetchlatest(table, ts_col)` | Return the most recent row by timestamp column |
| `fetchbetween(table, ts_col, start, end)` | Return rows in a datetime range |
| `setup()` | Create all tables if they don't already exist |
