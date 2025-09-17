import aiosqlite
from typing import Any, List, Optional, Tuple
from datetime import datetime
import os


class DatabaseManager:
    def __init__(self, db_path: str):
        self.db_path = db_path
        self.connection: Optional[aiosqlite.Connection] = None

    async def connect(self):
        self.connection = await aiosqlite.connect(self.db_path)
        await self.connection.execute("PRAGMA foreign_keys = ON;")
        await self.connection.commit()

    async def close(self):
        if self.connection:
            await self.connection.close()

    async def execute(self, query: str, params: Tuple = ()) -> None:
        if not self.connection:
            raise RuntimeError("Database connection is not established.")
        await self.connection.execute(query, params)
        await self.connection.commit()

    async def fetchone(self, query: str, params: Tuple = ()) -> Optional[aiosqlite.Row]:
        if not self.connection:
            raise RuntimeError("Database connection is not established.")
        cursor = await self.connection.execute(query, params)
        row = await cursor.fetchone()
        await cursor.close()
        return row
    
    async def fetchall(self, query: str, params: Tuple = ()) -> List[aiosqlite.Row]:
        if not self.connection:
            raise RuntimeError("Database connection is not established.")
        cursor = await self.connection.execute(query, params)
        rows = await cursor.fetchall()
        await cursor.close()
        return rows
    
    async def fetchlatest(self, table: str, timestamp_column: str) -> Optional[aiosqlite.Row]:
        query = f"SELECT * FROM {table} ORDER BY {timestamp_column} DESC LIMIT 1"
        return await self.fetchone(query)
    
    async def fetchbetween(self, table: str, timestamp_column: str, start: datetime, end: datetime) -> List[aiosqlite.Row]:
        query = f"SELECT * FROM {table} WHERE {timestamp_column} BETWEEN ? AND ?"
        params = (start.isoformat(), end.isoformat())
        return await self.fetchall(query, params)
    
    async def setup(self):
        queries = [
            # Inputs Table
            """
                CREATE TABLE IF NOT EXISTS inputs (
                    ID INTEGER PRIMARY KEY AUTOINCREMENT,
                    TIMESTAMP TEXT NOT NULL,
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
            """,
            # Outputs Table
            """
                CREATE TABLE IF NOT EXISTS outputs (
                    ID INTEGER PRIMARY KEY AUTOINCREMENT,
                    TIMESTAMP TEXT NOT NULL,
                    MOTOR1 INTEGER NOT NULL,
                    MOTOR2 INTEGER NOT NULL,
                    MOTOR3 INTEGER NOT NULL,
                    MOTOR4 INTEGER NOT NULL,
                    VERTICAL_THRUST INTEGER NOT NULL,
                    S1 INTEGER NOT NULL,
                    S2 INTEGER NOT NULL,
                    S3 INTEGER NOT NULL
                );
            """,
            # Hydrophone Table
            """
                CREATE TABLE IF NOT EXISTS hydrophone (
                    ID INTEGER PRIMARY KEY AUTOINCREMENT,
                    TIMESTAMP TEXT NOT NULL,
                    HEADING STRING(5) NOT NULL
                );
            """,
            # Depth Table
            """
                CREATE TABLE IF NOT EXISTS depth (
                    ID INTEGER PRIMARY KEY AUTOINCREMENT,
                    TIMESTAMP TEXT NOT NULL,
                    DEPTH REAL NOT NULL
                );
            """,
            # IMU Table
            """
                CREATE TABLE IF NOT EXISTS imu (
                    ID INTEGER PRIMARY KEY AUTOINCREMENT,
                    TIMESTAMP TEXT NOT NULL,
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
            """,
            # Power Safety Table
            """
                CREATE TABLE IF NOT EXISTS power_safety (
                    ID INTEGER PRIMARY KEY AUTOINCREMENT,
                    TIMESTAMP TEXT NOT NULL,
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
        ]
        
        for query in queries:
            if self.connection:
                await self.connection.execute(query)

if __name__ == "__main__":
    import asyncio

    async def main():
        db_manager = DatabaseManager("auv_database.db")
        await db_manager.connect()
        await db_manager.setup()
        await db_manager.close()

    asyncio.run(main())