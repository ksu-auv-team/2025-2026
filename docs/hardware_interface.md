# Hardware Interface

The `hardware_interface` package (`libs/hardware_interface/`) is the bridge between the AUV's software stack and its physical sensors and actuators. It abstracts I2C communication and hardware-specific details so the rest of the stack (movement, sonar, camera) never talks to hardware directly.

---

## Overview

```
┌──────────────────────────────────┐
│  Movement / AI / Sonar packages  │  high-level consumers
└──────────────┬───────────────────┘
               │ Python calls
┌──────────────▼───────────────────┐
│       hardware_interface         │  this package
│                                  │
│   I2C drivers  │  GPIO helpers   │
└──────────────┬───────────────────┘
               │ I2C / UART / SPI
┌──────────────▼───────────────────┐
│    Jetson Orin NX  (host)        │
│  /dev/i2c-*  │  /dev/ttyTHS*     │
└──────────────────────────────────┘
               │
    ┌──────────┴──────────┐
    │                     │
  ESCs / Motors        Sensors
  (PWM via I2C)     (IMU, Depth, Hydrophone)
```

---

## I2C Communication

The Jetson Orin exposes several I2C buses. Typical bus assignments for this build:

| Bus | Device(s) |
|---|---|
| `/dev/i2c-1` | IMU (e.g. BNO055 / MPU-9250) |
| `/dev/i2c-2` | Depth sensor (e.g. Bar30) |
| `/dev/i2c-7` | ESC PWM controller (e.g. PCA9685) |

> Verify bus numbers with `i2cdetect -l` on the Orin. Bus numbers vary by carrier board.

### Scanning for devices

```bash
# list all I2C buses
i2cdetect -l

# scan a specific bus (replace 1 with the correct bus number)
i2cdetect -y 1
```

### Python I2C example (smbus2)

```python
import smbus2

bus = smbus2.SMBus(1)            # open /dev/i2c-1
address = 0x28                   # BNO055 default address

# read a byte
value = bus.read_byte_data(address, register=0x00)

# write a byte
bus.write_byte_data(address, register=0x3D, value=0x00)

bus.close()
```

---

## Sensors

### IMU

Provides orientation (roll, pitch, yaw), linear acceleration, gyroscope, and magnetometer data. Readings are written to the `imu` table via the DB Manager API.

**Typical device:** BNO055 or MPU-9250 on I2C  
**I2C address:** `0x28` (BNO055 default) or `0x68` / `0x69` (MPU)

Expected data format for the DB:

```
ACCEL_X/Y/Z  — m/s²
GYRO_X/Y/Z   — rad/s
MAG_X/Y/Z    — µT
```

### Depth Sensor

Measures water pressure and converts it to depth. Readings are written to the `depth` table.

**Typical device:** Blue Robotics Bar30 on I2C  
**I2C address:** `0x76`

Expected data format:

```
DEPTH  — meters (float)
```

### Hydrophone

Detects acoustic pinger signals and derives a heading. Readings are written to the `hydrophone` table.

**Interface:** typically UART or SPI; exact wiring depends on the hydrophone board used.

Expected data format:

```
HEADING  — string up to 5 chars (e.g. "N", "NE", "045.2")
```

---

## Actuators

### Motor Controllers (ESCs)

Four horizontal thrusters + one vertical thruster are driven by Electronic Speed Controllers. PWM signals are generated via a PCA9685 16-channel PWM driver over I2C.

**I2C address:** `0x40` (PCA9685 default)  
**PWM frequency:** 50 Hz (standard servo/ESC range)  
**Pulse range:** 1100 µs (full reverse) – 1500 µs (stop) – 1900 µs (full forward)

Motor channel mapping (subject to physical wiring):

| Channel | Thruster |
|---|---|
| 0 | MOTOR1 (horizontal) |
| 1 | MOTOR2 (horizontal) |
| 2 | MOTOR3 (horizontal) |
| 3 | MOTOR4 (horizontal) |
| 4 | VERTICAL_THRUST |

### Servos / Actuators (S1, S2, S3)

Additional PCA9685 channels are used for servo-driven actuators (grippers, droppers, etc.).

---

## Power Safety

Three battery packs are monitored for voltage, current, and temperature. These values are sampled and posted to the `power_safety` DB endpoint. If any pack exceeds safe thresholds, the arm flag in `inputs` should be set to `0` to cut motor power.

Safe operating ranges (reference — confirm with hardware team):

| Metric | Safe range |
|---|---|
| Voltage (per cell) | 3.5 V – 4.2 V |
| Current draw | < 50 A per pack |
| Temperature | < 60 °C |

---

## Testing

Hardware tests are marked `@pytest.mark.hardware` and are excluded from CI (which has no physical hardware).

```bash
# run hardware tests on the Orin with the vehicle connected
pytest -m hardware
```

To add a new hardware test:

```python
import pytest

@pytest.mark.hardware
def test_imu_reads_acceleration() -> None:
    # open I2C, read register, assert value is in range
    ...
```

Keep hardware tests self-contained and idempotent — they should not depend on the AUV being armed or in the water.

---

## Adding a New Driver

1. Create a module under `libs/hardware_interface/` (e.g. `imu.py`).
2. Export it from `libs/hardware_interface/__init__.py`.
3. Write a corresponding test in `tests/hardware_interface/` with the `@pytest.mark.hardware` marker.
4. Log readings to the DB Manager API so they appear in the data visualizer.

---

## Useful Commands (on the Orin)

```bash
# check which I2C buses exist
ls /dev/i2c-*

# scan bus 1 for connected devices
sudo i2cdetect -y 1

# read a single byte from address 0x28, register 0x00 on bus 1
sudo i2cget -y 1 0x28 0x00

# write a byte to address 0x28, register 0x3D on bus 1
sudo i2cset -y 1 0x28 0x3D 0x00
```
