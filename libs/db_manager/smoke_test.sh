#!/usr/bin/env bash
set -euo pipefail

BASE="${BASE:-http://orin:8000}"

say() { echo -e "\n== $* =="; }

# curl wrapper that shows HTTP code at the end
call() {
  # $1: METHOD, $2: PATH, $3: DATA (optional)
  local METHOD="$1" PATH_="$2" DATA="${3:-}"
  echo -e "\n$METHOD $PATH_"
  if [[ -n "$DATA" ]]; then
    curl -sS -X "$METHOD" "$BASE$PATH_" \
      -H "Content-Type: application/x-www-form-urlencoded" \
      --data "$DATA" -w "\nHTTP %{http_code}\n"
  else
    curl -sS -X "$METHOD" "$BASE$PATH_" -w "\nHTTP %{http_code}\n"
  fi
}

# POST helper that returns the new row's ID via stdout
post_and_get_id() {
  # $1: path, $2: form data
  local PATH_="$1" DATA="$2"
  curl -sS -X POST "$BASE$PATH_" \
    -H "Content-Type: application/x-www-form-urlencoded" \
    --data "$DATA" | jq -r '.ID'
}

say "Root"
call GET "/"

# -------------------------
# inputs
# -------------------------
say "inputs"
INP_ID=$(post_and_get_id "/inputs" "SURGE=10&SWAY=0&HEAVE=-5&ROLL=0&PITCH=2&YAW=-1&S1=1&S2=0&S3=42&ARM=1")
echo "Inserted inputs ID=$INP_ID"
call GET  "/inputs"
call GET  "/inputs/latest"
call GET  "/inputs/$INP_ID"
call DELETE "/inputs/$INP_ID"

# -------------------------
# outputs
# -------------------------
say "outputs"
OUT_ID=$(post_and_get_id "/outputs" "MOTOR1=10&MOTOR2=11&MOTOR3=12&MOTOR4=13&VERTICAL_THRUST=7&S1=1&S2=0&S3=2")
echo "Inserted outputs ID=$OUT_ID"
call GET  "/outputs"
call GET  "/outputs/latest"
call GET  "/outputs/$OUT_ID"
call DELETE "/outputs/$OUT_ID"

# -------------------------
# hydrophone
# -------------------------
say "hydrophone"
HYD_ID=$(post_and_get_id "/hydrophone" "HEADING=N")
echo "Inserted hydrophone ID=$HYD_ID"
call GET  "/hydrophone"
call GET  "/hydrophone/latest"
call GET  "/hydrophone/$HYD_ID"
call DELETE "/hydrophone/$HYD_ID"

# -------------------------
# depth
# -------------------------
say "depth"
DEP_ID=$(post_and_get_id "/depth" "DEPTH=3.14")
echo "Inserted depth ID=$DEP_ID"
call GET  "/depth"
call GET  "/depth/latest"
call GET  "/depth/$DEP_ID"
call DELETE "/depth/$DEP_ID"

# -------------------------
# imu
# -------------------------
say "imu"
IMU_ID=$(post_and_get_id "/imu" "ACCEL_X=0.1&ACCEL_Y=0.0&ACCEL_Z=-0.1&GYRO_X=0.01&GYRO_Y=-0.02&GYRO_Z=0.03&MAG_X=12.3&MAG_Y=0.4&MAG_Z=-7.8")
echo "Inserted imu ID=$IMU_ID"
call GET  "/imu"
call GET  "/imu/latest"
call GET  "/imu/$IMU_ID"
call DELETE "/imu/$IMU_ID"

# -------------------------
# power_safety
# -------------------------
say "power_safety"
PWR_ID=$(post_and_get_id "/power_safety" "B1_VOLTAGE=1200&B2_VOLTAGE=1195&B3_VOLTAGE=1188&B1_CURRENT=15&B2_CURRENT=14&B3_CURRENT=16&B1_TEMP=32&B2_TEMP=31&B3_TEMP=33")
echo "Inserted power_safety ID=$PWR_ID"
call GET  "/power_safety"
call GET  "/power_safety/latest"
call GET  "/power_safety/$PWR_ID"
call DELETE "/power_safety/$PWR_ID"

echo -e "\n== DONE =="
