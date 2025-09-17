#!/usr/bin/env bash
set -euo pipefail
BASE="http://127.0.0.1:8000"

call() {
  # $1: METHOD, $2: PATH, $3: DATA (optional)
  METHOD="$1"; PATH_="$2"; DATA="${3:-}"
  echo -e "\n$METHOD $PATH_"
  if [[ -n "$DATA" ]]; then
    curl -sS -X "$METHOD" "$BASE$PATH_" \
      -H "Content-Type: application/x-www-form-urlencoded" \
      --data "$DATA" \
      -w "\nHTTP %{http_code}\n"
  else
    curl -sS -X "$METHOD" "$BASE$PATH_" -w "\nHTTP %{http_code}\n"
  fi
}

echo "== Root =="
call GET "/"

echo "== inputs =="
call POST "/inputs" "SURGE=10&SWAY=0&HEAVE=-5&ROLL=0&PITCH=2&YAW=-1&S1=1&S2=0&S3=42&ARM=1"
call GET  "/inputs"
call GET  "/inputs/latest"
call GET  "/inputs/1"
call DELETE "/inputs/1"

echo "== outputs =="
call POST "/outputs" "MOTOR1=10&MOTOR2=11&MOTOR3=12&MOTOR4=13&VERTICAL_THRUST=7&S1=1&S2=0&S3=2"
call GET  "/outputs"
call GET  "/outputs/latest"
call GET  "/outputs/1"
call DELETE "/outputs/1"

echo "== hydrophone =="
call POST "/hydrophone" "HEADING=N"
call GET  "/hydrophone"
call GET  "/hydrophone/latest"
call GET  "/hydrophone/1"
call DELETE "/hydrophone/1"

echo "== depth =="
call POST "/depth" "DEPTH=3.14"
call GET  "/depth"
call GET  "/depth/latest"
call GET  "/depth/1"
call DELETE "/depth/1"

echo "== imu =="
call POST "/imu" "ACCEL_X=0.1&ACCEL_Y=0.0&ACCEL_Z=-0.1&GYRO_X=0.01&GYRO_Y=-0.02&GYRO_Z=0.03&MAG_X=12.3&MAG_Y=0.4&MAG_Z=-7.8"
call GET  "/imu"
call GET  "/imu/latest"
call GET  "/imu/1"
call DELETE "/imu/1"

echo "== power_safety =="
call POST "/power_safety" "B1_VOLTAGE=1200&B2_VOLTAGE=1195&B3_VOLTAGE=1188&B1_CURRENT=15&B2_CURRENT=14&B3_CURRENT=16&B1_TEMP=32&B2_TEMP=31&B3_TEMP=33"
call GET  "/power_safety"
call GET  "/power_safety/latest"
call GET  "/power_safety/1"
call DELETE "/power_safety/1"

echo -e "\n== DONE =="
