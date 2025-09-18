# Notes

## Models needed

- Inputs
  - `X`, int, 0 - 100
  - `Y`, int, 0 - 100
  - `Z`, int, 0 - 100
  - `Yaw`, int, 0 - 100
  - `S1`, bool
  - `S2`, bool
  - `S3`, int, 0 - 100
  - `Arm`, bool

- Outputs
  - `M1`, int, 0 - 255
  - `M2`, int, 0 - 255
  - `M3`, int, 0 - 255
  - `M4`, int, 0 - 255
  - `V`, int, 0 - 255
  - `S1`, int, 0 - 255
  - `S2`, int, 0 - 255
  - `S3`, int, 0 - 255

- Hydrophone
  - `Heading`, string(4)

- Depth
  - `depth`, int, 0 - 100

- IMU
  - `X`, int, 0 - 255
  - `Y`, int, 0 - 255
  - `Z`, int, 0 - 255
  - `Roll`, int, 0 - 255
  - `Pitch`, int, 0 - 255
  - `Yaw`, int, 0 - 255

- Power Safety
  - `B1_Voltage`, int, 0 - 100
  - `B2_Voltage`, int, 0 - 100
  - `B3_Voltage`, int, 0 - 100
  - `B1_Current`, int, 0 - 50
  - `B2_Current`, int, 0 - 50
  - `B3_Current`, int, 0 - 50
  - `B1_Temp`, int, 0 - 100
  - `B2_Temp`, int, 0 - 100
  - `B3_Temp`, int, 0 - 100
