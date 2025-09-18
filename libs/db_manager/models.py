from typing import Optional, List
from pydantic import BaseModel, Field, conint, confloat, constr

# ---- inputs ----
class InputsCreate(BaseModel):
    TIMESTAMP: Optional[str] = Field(None, description="ISO8601 UTC string")
    SURGE: int; SWAY: int; HEAVE: int; ROLL: int; PITCH: int; YAW: int
    S1: conint(ge=0, le=1); S2: conint(ge=0, le=1)
    S3: int
    ARM: conint(ge=0, le=1)

class InputsRead(InputsCreate):
    ID: int
    TIMESTAMP: str

# ---- outputs ----
class OutputsCreate(BaseModel):
    TIMESTAMP: Optional[str] = None
    MOTOR1: int; MOTOR2: int; MOTOR3: int; MOTOR4: int
    VERTICAL_THRUST: int
    S1: int; S2: int; S3: int

class OutputsRead(OutputsCreate):
    ID: int
    TIMESTAMP: str

# ---- hydrophone ----
class HydrophoneCreate(BaseModel):
    TIMESTAMP: Optional[str] = None
    HEADING: constr(strip_whitespace=True, min_length=1, max_length=5)

class HydrophoneRead(HydrophoneCreate):
    ID: int
    TIMESTAMP: str

# ---- depth ----
class DepthCreate(BaseModel):
    TIMESTAMP: Optional[str] = None
    DEPTH: confloat(strict=True)

class DepthRead(DepthCreate):
    ID: int
    TIMESTAMP: str

# ---- imu ----
class ImuCreate(BaseModel):
    TIMESTAMP: Optional[str] = None
    ACCEL_X: float; ACCEL_Y: float; ACCEL_Z: float
    GYRO_X: float;  GYRO_Y: float;  GYRO_Z: float
    MAG_X: float;   MAG_Y: float;   MAG_Z: float

class ImuRead(ImuCreate):
    ID: int
    TIMESTAMP: str

# ---- power_safety ----
class PowerSafetyCreate(BaseModel):
    TIMESTAMP: Optional[str] = None
    B1_VOLTAGE: int; B2_VOLTAGE: int; B3_VOLTAGE: int
    B1_CURRENT: int; B2_CURRENT: int; B3_CURRENT: int
    B1_TEMP: int;    B2_TEMP: int;    B3_TEMP: int

class PowerSafetyRead(PowerSafetyCreate):
    ID: int
    TIMESTAMP: str

# ---- list wrapper (shared) ----
class ListEnvelope(BaseModel):
    items: list
    total: int
    limit: int
    offset: int
