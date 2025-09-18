from typing import Optional, Sequence

import aiosqlite
from fastapi import APIRouter, Depends, HTTPException, Query, Form

from deps import get_db

router = APIRouter()


# ----------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------
async def _insert_and_fetch(
    db: aiosqlite.Connection, table: str, cols: Sequence[str], values: Sequence
) -> dict:
    placeholders = ",".join(["?"] * len(cols))
    await db.execute(
        f"INSERT INTO {table} ({','.join(cols)}) VALUES ({placeholders});",
        values,
    )
    await db.commit()
    cur = await db.execute(f"SELECT * FROM {table} ORDER BY ID DESC LIMIT 1;")
    row = await cur.fetchone()
    await cur.close()
    return dict(row)

async def _get_by_id(db: aiosqlite.Connection, table: str, id_: int) -> dict | None:
    cur = await db.execute(f"SELECT * FROM {table} WHERE ID = ?;", (id_,))
    row = await cur.fetchone()
    await cur.close()
    return dict(row) if row else None

async def _delete_by_id(db: aiosqlite.Connection, table: str, id_: int) -> int:
    cur = await db.execute(f"DELETE FROM {table} WHERE ID = ?;", (id_,))
    await db.commit()
    return cur.rowcount

async def _list_by_time(
    db: aiosqlite.Connection, table: str, ts_col: str,
    limit: int, offset: int, start: Optional[str], end: Optional[str]
) -> tuple[list[dict], int]:
    args: list = []
    if start and end:
        where = f" WHERE {ts_col} BETWEEN ? AND ?"
        args = [start, end]
    elif start:
        where = f" WHERE {ts_col} >= ?"
        args = [start]
    elif end:
        where = f" WHERE {ts_col} <= ?"
        args = [end]
    else:
        where = ""

    cur = await db.execute(f"SELECT COUNT(*) FROM {table}{where};", args)
    (total,) = await cur.fetchone()
    await cur.close()

    cur = await db.execute(
        f"SELECT * FROM {table}{where} ORDER BY {ts_col} DESC LIMIT ? OFFSET ?;",
        [*args, limit, offset],
    )
    rows = [dict(r) for r in await cur.fetchall()]
    await cur.close()
    return rows, total


# ----------------------------------------------------------------------
# inputs
#   NOTE: order matters: define /latest BEFORE /{id}
# ----------------------------------------------------------------------
@router.post("/inputs", tags=["inputs"])
async def create_inputs(
    SURGE: int = Form(...), SWAY: int = Form(...), HEAVE: int = Form(...),
    ROLL: int = Form(...), PITCH: int = Form(...), YAW: int = Form(...),
    S1: int = Form(...), S2: int = Form(...), S3: int = Form(...), ARM: int = Form(...),
    db: aiosqlite.Connection = Depends(get_db),
):
    cols = ["SURGE", "SWAY", "HEAVE", "ROLL", "PITCH", "YAW", "S1", "S2", "S3", "ARM"]
    vals = [SURGE, SWAY, HEAVE, ROLL, PITCH, YAW, S1, S2, S3, ARM]
    return await _insert_and_fetch(db, "inputs", cols, vals)

@router.get("/inputs", tags=["inputs"])
async def list_inputs(
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    start: Optional[str] = None,
    end: Optional[str] = None,
    db: aiosqlite.Connection = Depends(get_db),
):
    rows, total = await _list_by_time(db, "inputs", "TIMESTAMP", limit, offset, start, end)
    return {"items": rows, "total": total, "limit": limit, "offset": offset}

@router.get("/inputs/latest", tags=["inputs"])
async def latest_inputs(db: aiosqlite.Connection = Depends(get_db)):
    cur = await db.execute("SELECT * FROM inputs ORDER BY TIMESTAMP DESC LIMIT 1;")
    row = await cur.fetchone()
    await cur.close()
    return dict(row) if row else None

@router.get("/inputs/{id}", tags=["inputs"])
async def get_inputs(id: int, db: aiosqlite.Connection = Depends(get_db)):
    row = await _get_by_id(db, "inputs", id)
    if not row:
        raise HTTPException(404, "inputs not found")
    return row

@router.delete("/inputs/{id}", status_code=204, tags=["inputs"])
async def delete_inputs(id: int, db: aiosqlite.Connection = Depends(get_db)):
    if await _delete_by_id(db, "inputs", id) == 0:
        raise HTTPException(404, "inputs not found")


# ----------------------------------------------------------------------
# outputs
# ----------------------------------------------------------------------
@router.post("/outputs", tags=["outputs"])
async def create_outputs(
    MOTOR1: int = Form(...), MOTOR2: int = Form(...), MOTOR3: int = Form(...), MOTOR4: int = Form(...),
    VERTICAL_THRUST: int = Form(...),
    S1: int = Form(...), S2: int = Form(...), S3: int = Form(...),
    db: aiosqlite.Connection = Depends(get_db),
):
    cols = ["MOTOR1", "MOTOR2", "MOTOR3", "MOTOR4", "VERTICAL_THRUST", "S1", "S2", "S3"]
    vals = [MOTOR1, MOTOR2, MOTOR3, MOTOR4, VERTICAL_THRUST, S1, S2, S3]
    return await _insert_and_fetch(db, "outputs", cols, vals)

@router.get("/outputs", tags=["outputs"])
async def list_outputs(
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    start: Optional[str] = None,
    end: Optional[str] = None,
    db: aiosqlite.Connection = Depends(get_db),
):
    rows, total = await _list_by_time(db, "outputs", "TIMESTAMP", limit, offset, start, end)
    return {"items": rows, "total": total, "limit": limit, "offset": offset}

@router.get("/outputs/latest", tags=["outputs"])
async def latest_outputs(db: aiosqlite.Connection = Depends(get_db)):
    cur = await db.execute("SELECT * FROM outputs ORDER BY TIMESTAMP DESC LIMIT 1;")
    row = await cur.fetchone()
    await cur.close()
    return dict(row) if row else None

@router.get("/outputs/{id}", tags=["outputs"])
async def get_outputs(id: int, db: aiosqlite.Connection = Depends(get_db)):
    row = await _get_by_id(db, "outputs", id)
    if not row:
        raise HTTPException(404, "outputs not found")
    return row

@router.delete("/outputs/{id}", status_code=204, tags=["outputs"])
async def delete_outputs(id: int, db: aiosqlite.Connection = Depends(get_db)):
    if await _delete_by_id(db, "outputs", id) == 0:
        raise HTTPException(404, "outputs not found")


# ----------------------------------------------------------------------
# hydrophone
# ----------------------------------------------------------------------
@router.post("/hydrophone", tags=["hydrophone"])
async def create_hydrophone(
    HEADING: str = Form(...),
    db: aiosqlite.Connection = Depends(get_db),
):
    cols = ["HEADING"]
    vals = [HEADING]
    return await _insert_and_fetch(db, "hydrophone", cols, vals)

@router.get("/hydrophone", tags=["hydrophone"])
async def list_hydrophone(
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    start: Optional[str] = None,
    end: Optional[str] = None,
    db: aiosqlite.Connection = Depends(get_db),
):
    rows, total = await _list_by_time(db, "hydrophone", "TIMESTAMP", limit, offset, start, end)
    return {"items": rows, "total": total, "limit": limit, "offset": offset}

@router.get("/hydrophone/latest", tags=["hydrophone"])
async def latest_hydrophone(db: aiosqlite.Connection = Depends(get_db)):
    cur = await db.execute("SELECT * FROM hydrophone ORDER BY TIMESTAMP DESC LIMIT 1;")
    row = await cur.fetchone()
    await cur.close()
    return dict(row) if row else None

@router.get("/hydrophone/{id}", tags=["hydrophone"])
async def get_hydrophone(id: int, db: aiosqlite.Connection = Depends(get_db)):
    row = await _get_by_id(db, "hydrophone", id)
    if not row:
        raise HTTPException(404, "hydrophone not found")
    return row

@router.delete("/hydrophone/{id}", status_code=204, tags=["hydrophone"])
async def delete_hydrophone(id: int, db: aiosqlite.Connection = Depends(get_db)):
    if await _delete_by_id(db, "hydrophone", id) == 0:
        raise HTTPException(404, "hydrophone not found")


# ----------------------------------------------------------------------
# depth
# ----------------------------------------------------------------------
@router.post("/depth", tags=["depth"])
async def create_depth(
    DEPTH: float = Form(...),
    db: aiosqlite.Connection = Depends(get_db),
):
    cols = ["DEPTH"]
    vals = [DEPTH]
    return await _insert_and_fetch(db, "depth", cols, vals)

@router.get("/depth", tags=["depth"])
async def list_depth(
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    start: Optional[str] = None,
    end: Optional[str] = None,
    db: aiosqlite.Connection = Depends(get_db),
):
    rows, total = await _list_by_time(db, "depth", "TIMESTAMP", limit, offset, start, end)
    return {"items": rows, "total": total, "limit": limit, "offset": offset}

@router.get("/depth/latest", tags=["depth"])
async def latest_depth(db: aiosqlite.Connection = Depends(get_db)):
    cur = await db.execute("SELECT * FROM depth ORDER BY TIMESTAMP DESC LIMIT 1;")
    row = await cur.fetchone()
    await cur.close()
    return dict(row) if row else None

@router.get("/depth/{id}", tags=["depth"])
async def get_depth(id: int, db: aiosqlite.Connection = Depends(get_db)):
    row = await _get_by_id(db, "depth", id)
    if not row:
        raise HTTPException(404, "depth not found")
    return row

@router.delete("/depth/{id}", status_code=204, tags=["depth"])
async def delete_depth(id: int, db: aiosqlite.Connection = Depends(get_db)):
    if await _delete_by_id(db, "depth", id) == 0:
        raise HTTPException(404, "depth not found")


# ----------------------------------------------------------------------
# imu
# ----------------------------------------------------------------------
@router.post("/imu", tags=["imu"])
async def create_imu(
    ACCEL_X: float = Form(...), ACCEL_Y: float = Form(...), ACCEL_Z: float = Form(...),
    GYRO_X: float = Form(...),  GYRO_Y: float = Form(...),  GYRO_Z: float = Form(...),
    MAG_X: float = Form(...),   MAG_Y: float = Form(...),   MAG_Z: float = Form(...),
    db: aiosqlite.Connection = Depends(get_db),
):
    cols = ["ACCEL_X", "ACCEL_Y", "ACCEL_Z", "GYRO_X", "GYRO_Y", "GYRO_Z", "MAG_X", "MAG_Y", "MAG_Z"]
    vals = [ACCEL_X, ACCEL_Y, ACCEL_Z, GYRO_X, GYRO_Y, GYRO_Z, MAG_X, MAG_Y, MAG_Z]
    return await _insert_and_fetch(db, "imu", cols, vals)

@router.get("/imu", tags=["imu"])
async def list_imu(
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    start: Optional[str] = None,
    end: Optional[str] = None,
    db: aiosqlite.Connection = Depends(get_db),
):
    rows, total = await _list_by_time(db, "imu", "TIMESTAMP", limit, offset, start, end)
    return {"items": rows, "total": total, "limit": limit, "offset": offset}

@router.get("/imu/latest", tags=["imu"])
async def latest_imu(db: aiosqlite.Connection = Depends(get_db)):
    cur = await db.execute("SELECT * FROM imu ORDER BY TIMESTAMP DESC LIMIT 1;")
    row = await cur.fetchone()
    await cur.close()
    return dict(row) if row else None

@router.get("/imu/{id}", tags=["imu"])
async def get_imu(id: int, db: aiosqlite.Connection = Depends(get_db)):
    row = await _get_by_id(db, "imu", id)
    if not row:
        raise HTTPException(404, "imu not found")
    return row

@router.delete("/imu/{id}", status_code=204, tags=["imu"])
async def delete_imu(id: int, db: aiosqlite.Connection = Depends(get_db)):
    if await _delete_by_id(db, "imu", id) == 0:
        raise HTTPException(404, "imu not found")


# ----------------------------------------------------------------------
# power_safety
# ----------------------------------------------------------------------
@router.post("/power_safety", tags=["power_safety"])
async def create_power_safety(
    B1_VOLTAGE: int = Form(...), B2_VOLTAGE: int = Form(...), B3_VOLTAGE: int = Form(...),
    B1_CURRENT: int = Form(...), B2_CURRENT: int = Form(...), B3_CURRENT: int = Form(...),
    B1_TEMP: int = Form(...),    B2_TEMP: int = Form(...),    B3_TEMP: int = Form(...),
    db: aiosqlite.Connection = Depends(get_db),
):
    cols = [
        "B1_VOLTAGE", "B2_VOLTAGE", "B3_VOLTAGE",
        "B1_CURRENT", "B2_CURRENT", "B3_CURRENT",
        "B1_TEMP", "B2_TEMP", "B3_TEMP"
    ]
    vals = [
        B1_VOLTAGE, B2_VOLTAGE, B3_VOLTAGE,
        B1_CURRENT, B2_CURRENT, B3_CURRENT,
        B1_TEMP, B2_TEMP, B3_TEMP
    ]
    return await _insert_and_fetch(db, "power_safety", cols, vals)

@router.get("/power_safety", tags=["power_safety"])
async def list_power_safety(
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    start: Optional[str] = None,
    end: Optional[str] = None,
    db: aiosqlite.Connection = Depends(get_db),
):
    rows, total = await _list_by_time(db, "power_safety", "TIMESTAMP", limit, offset, start, end)
    return {"items": rows, "total": total, "limit": limit, "offset": offset}

@router.get("/power_safety/latest", tags=["power_safety"])
async def latest_power_safety(db: aiosqlite.Connection = Depends(get_db)):
    cur = await db.execute("SELECT * FROM power_safety ORDER BY TIMESTAMP DESC LIMIT 1;")
    row = await cur.fetchone()
    await cur.close()
    return dict(row) if row else None

@router.get("/power_safety/{id}", tags=["power_safety"])
async def get_power_safety(id: int, db: aiosqlite.Connection = Depends(get_db)):
    row = await _get_by_id(db, "power_safety", id)
    if not row:
        raise HTTPException(404, "power_safety not found")
    return row

@router.delete("/power_safety/{id}", status_code=204, tags=["power_safety"])
async def delete_power_safety(id: int, db: aiosqlite.Connection = Depends(get_db)):
    if await _delete_by_id(db, "power_safety", id) == 0:
        raise HTTPException(404, "power_safety not found")
