from contextlib import asynccontextmanager
from typing import AsyncIterator

import aiosqlite
from fastapi import FastAPI, Request

from database import DatabaseManager  # your existing file with DatabaseManager


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """
    App startup/shutdown: create the DB connection, ensure tables exist,
    enable foreign keys, and make rows accessible by column name.
    """
    dbm = DatabaseManager("auv_database.db")
    await dbm.connect()

    # Name-based access for rows (row["COL"])
    dbm.connection.row_factory = aiosqlite.Row

    # Ensure tables exist and set DB-side default timestamps in UTC
    await dbm.connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS inputs (
            ID INTEGER PRIMARY KEY AUTOINCREMENT,
            TIMESTAMP TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
            SURGE INTEGER NOT NULL,
            SWAY INTEGER NOT NULL,
            HEAVE INTEGER NOT NULL,
            ROLL INTEGER NOT NULL,
            PITCH INTEGER NOT NULL,
            YAW INTEGER NOT NULL,
            S1 BOOLEAN NOT NULL,
            S2 BOOLEAN NOT NULL,
            S3 INTEGER NOT NULL,
            ARM BOOLEAN NOT NULL
        );

        CREATE TABLE IF NOT EXISTS outputs (
            ID INTEGER PRIMARY KEY AUTOINCREMENT,
            TIMESTAMP TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
            MOTOR1 INTEGER NOT NULL,
            MOTOR2 INTEGER NOT NULL,
            MOTOR3 INTEGER NOT NULL,
            MOTOR4 INTEGER NOT NULL,
            VERTICAL_THRUST INTEGER NOT NULL,
            S1 INTEGER NOT NULL,
            S2 INTEGER NOT NULL,
            S3 INTEGER NOT NULL
        );

        CREATE TABLE IF NOT EXISTS hydrophone (
            ID INTEGER PRIMARY KEY AUTOINCREMENT,
            TIMESTAMP TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
            HEADING STRING(5) NOT NULL
        );

        CREATE TABLE IF NOT EXISTS depth (
            ID INTEGER PRIMARY KEY AUTOINCREMENT,
            TIMESTAMP TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
            DEPTH REAL NOT NULL
        );

        CREATE TABLE IF NOT EXISTS imu (
            ID INTEGER PRIMARY KEY AUTOINCREMENT,
            TIMESTAMP TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
            ACCEL_X REAL NOT NULL,
            ACCEL_Y REAL NOT NULL,
            ACCEL_Z REAL NOT NULL,
            GYRO_X REAL NOT NULL,
            GYRO_Y REAL NOT NULL,
            GYRO_Z REAL NOT NULL,
            MAG_X REAL NOT NULL,
            MAG_Y REAL NOT NULL,
            MAG_Z REAL NOT NULL
        );

        CREATE TABLE IF NOT EXISTS power_safety (
            ID INTEGER PRIMARY KEY AUTOINCREMENT,
            TIMESTAMP TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
            B1_VOLTAGE INTEGER NOT NULL,
            B2_VOLTAGE INTEGER NOT NULL,
            B3_VOLTAGE INTEGER NOT NULL,
            B1_CURRENT INTEGER NOT NULL,
            B2_CURRENT INTEGER NOT NULL,
            B3_CURRENT INTEGER NOT NULL,
            B1_TEMP INTEGER NOT NULL,
            B2_TEMP INTEGER NOT NULL,
            B3_TEMP INTEGER NOT NULL
        );
        """
    )
    await dbm.connection.commit()

    # stash the manager on app.state so handlers can access the connection
    app.state.dbm = dbm
    try:
        yield
    finally:
        await app.state.dbm.close()


# Dependency: fetch the active aiosqlite connection for each request
async def get_db(request: Request) -> aiosqlite.Connection:
    return request.app.state.dbm.connection
