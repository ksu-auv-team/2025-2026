#include <Arduino.h>
#include <Adafruit_BNO08x.h>
#include <math.h>

// ====== BNO08x config ======
#define BNO08X_RESET -1
Adafruit_BNO08x bno08x(BNO08X_RESET);
sh2_SensorValue_t sensorValue;

// Choose a rotation vector stream:
#define USE_ARVR_STABILIZED_RV 1
#if USE_ARVR_STABILIZED_RV
  static const sh2_SensorId_t RV_TYPE = SH2_ARVR_STABILIZED_RV;
  static const long RV_INTERVAL_US = 5000;   // ~200 Hz
#else
  static const sh2_SensorId_t RV_TYPE = SH2_GYRO_INTEGRATED_RV;
  static const long RV_INTERVAL_US = 2000;   // faster, noisier
#endif
static const long LA_INTERVAL_US = 5000;     // Linear Accel ~200 Hz

// ====== Serial protocol framing ======
static const uint8_t START1 = 'B';
static const uint8_t START2 = 'R';

// Msg IDs
static const uint16_t MSG_GET_IMU   = 0x0101;
static const uint16_t MSG_SET_HOME  = 0x0102;
static const uint16_t MSG_RESET_VEL = 0x0103;  // NEW: zero the velocity integrator
static const uint16_t MSG_RESP_IMU  = 0x8101;
static const uint16_t MSG_ACK       = 0x8000;
static const uint16_t MSG_NACK      = 0x8001;

// Error codes for NACK
enum : uint8_t { ERR_BAD_LENGTH=1, ERR_UNKNOWN_MSG=2, ERR_MALFORMED=3 };

// IDs
static const uint8_t DEVICE_ID = 0x01;  // Pico
static const uint8_t HOST_ID   = 0x00;  // PC

// ====== IMU data (latest latched values) ======
struct Euler {
  float roll, pitch, yaw; // degrees (note order: R, P, Y)
};
volatile Euler rpy = {0,0,0};

// Gravity-removed linear acceleration (body frame) and velocity (body frame)
volatile float lax=0, lay=0, laz=0;     // m/s^2 (SH2_LINEAR_ACCELERATION)
volatile float vx=0,  vy=0,  vz=0;      // m/s   (integrated)

volatile uint8_t rv_status=0, la_status=0;

static float homeRoll=0, homePitch=0, homeYaw=0;
static bool homeSet=false;

static uint32_t last_la_us = 0;         // timestamp for velocity integration

// Integration tuning (simple but practical)
static const float LA_DEADBAND = 0.05f; // m/s^2; ignore tiny noise
static const float VEL_DAMP    = 0.30f; // s^-1; exponential velocity decay when near zero accel

inline float wrap180(float aDeg){
  while (aDeg > 180.f) aDeg -= 360.f;
  while (aDeg < -180.f) aDeg += 360.f;
  return aDeg;
}

void quaternionToEuler(float qr, float qi, float qj, float qk, Euler* outDeg) {
  float sqr = sq(qr), sqi = sq(qi), sqj = sq(qj), sqk = sq(qk);
  float yaw   = atan2f(2.0f*(qi*qj + qk*qr), (sqi - sqj - sqk + sqr));
  float pitch = asinf (-2.0f*(qi*qk - qj*qr) / (sqi + sqj + sqk + sqr));
  float roll  = atan2f(2.0f*(qj*qk + qi*qr), (-sqi - sqj + sqk + sqr));
  outDeg->roll  = roll  * RAD_TO_DEG;
  outDeg->pitch = pitch * RAD_TO_DEG;
  outDeg->yaw   = yaw   * RAD_TO_DEG;
}

void enableReport(sh2_SensorId_t id, long us){
  bno08x.enableReport(id, us); // silent on failure to keep serial clean
}

// ====== Packing helpers ======
inline void putLE16(uint8_t* p, uint16_t v){ p[0]=uint8_t(v); p[1]=uint8_t(v>>8); }
inline void putLE32(uint8_t* p, uint32_t v){ p[0]=uint8_t(v); p[1]=uint8_t(v>>8); p[2]=uint8_t(v>>16); p[3]=uint8_t(v>>24); }
inline void putF32(uint8_t* p, float f){ uint32_t v; memcpy(&v,&f,4); putLE32(p,v); }

uint16_t checksum16(const uint8_t* data, size_t n){
  uint32_t sum=0;
  for(size_t i=0;i<n;i++) sum += data[i];
  return (uint16_t)sum;
}

void sendMsg(uint16_t msgId, uint8_t src, uint8_t dst, const uint8_t* payload, uint16_t plen){
  uint8_t hdr[2+2+2+1+1]; // BR + len + id + src + dst
  hdr[0]=START1; hdr[1]=START2;
  putLE16(&hdr[2], plen);
  putLE16(&hdr[4], msgId);
  hdr[6]=src; hdr[7]=dst;

  uint16_t cksum = checksum16(hdr, sizeof(hdr));
  if(plen && payload) cksum += checksum16(payload, plen);

  uint8_t tail[2];
  putLE16(tail, cksum);

  Serial.write(hdr, sizeof(hdr));
  if(plen && payload) Serial.write(payload, plen);
  Serial.write(tail, 2);
}

// ====== Responses ======
// RESP_IMU payload (little-endian):
// u32 micros
// u8  rv_status
// u8  la_status
// float roll_deg, pitch_deg, yaw_deg
// float vx, vy, vz        (m/s, body frame)
// float ax_lin, ay_lin, az_lin (m/s^2, body frame)
void respondIMU(uint8_t reqSrc){
  uint8_t buf[4 + 1 + 1 + 4*9];
  uint32_t t = micros();

  // Orientation relative to home, if set (R,P,Y requested order)
  float r   = homeSet ? wrap180(rpy.roll  - homeRoll)  : rpy.roll;
  float p   = homeSet ? wrap180(rpy.pitch - homePitch) : rpy.pitch;
  float y   = homeSet ? wrap180(rpy.yaw   - homeYaw)   : rpy.yaw;

  putLE32(&buf[0], t);
  buf[4] = rv_status;
  buf[5] = la_status;
  putF32(&buf[6],  r);
  putF32(&buf[10], p);
  putF32(&buf[14], y);
  putF32(&buf[18], vx);
  putF32(&buf[22], vy);
  putF32(&buf[26], vz);
  putF32(&buf[30], lax);
  putF32(&buf[34], lay);
  putF32(&buf[38], laz);

  sendMsg(MSG_RESP_IMU, DEVICE_ID, reqSrc, buf, sizeof(buf));
}

void setHomeCurrent(){
  homeRoll = rpy.roll; homePitch = rpy.pitch; homeYaw = rpy.yaw;
  homeSet = true;
}

void setHomeExplicit(const uint8_t* payload, uint16_t len){
  if(len != 12){ uint8_t e=ERR_BAD_LENGTH; sendMsg(MSG_NACK, DEVICE_ID, HOST_ID, &e, 1); return; }
  float r,p,y;
  memcpy(&r, payload+0, 4);
  memcpy(&p, payload+4, 4);
  memcpy(&y, payload+8, 4);
  homeRoll = r; homePitch = p; homeYaw = y;
  homeSet = true;
  sendMsg(MSG_ACK, DEVICE_ID, HOST_ID, nullptr, 0);
}

void resetVelocity(){
  vx = vy = vz = 0.0f;
  last_la_us = micros(); // avoid large dt on next integrate
  sendMsg(MSG_ACK, DEVICE_ID, HOST_ID, nullptr, 0);
}

// ====== Parser (state machine) ======
enum ParseState { PS_FIND_S1, PS_FIND_S2, PS_LEN0, PS_LEN1, PS_ID0, PS_ID1, PS_SRC, PS_DST, PS_PAYLOAD, PS_CK0, PS_CK1 };
static ParseState ps = PS_FIND_S1;
static uint16_t pl_len=0, msg_id=0;
static uint8_t src_id=0, dst_id=0;
static uint16_t recv_ck=0, calc_ck=0;
static const uint16_t MAX_PAYLOAD = 128;
static uint8_t payload_buf[MAX_PAYLOAD];
static uint16_t payload_idx=0;

void resetParser(){ ps=PS_FIND_S1; pl_len=0; msg_id=0; src_id=0; dst_id=0; recv_ck=0; calc_ck=0; payload_idx=0; }

void processOneByte(uint8_t b){
  switch(ps){
    case PS_FIND_S1:
      if(b==START1){ calc_ck=b; ps=PS_FIND_S2; }
      break;
    case PS_FIND_S2:
      if(b==START2){ calc_ck += b; ps=PS_LEN0; }
      else { ps=PS_FIND_S1; }
      break;
    case PS_LEN0:
      pl_len = b; calc_ck += b; ps=PS_LEN1; break;
    case PS_LEN1:
      pl_len |= (uint16_t)b<<8; calc_ck += b; ps=PS_ID0; break;
    case PS_ID0:
      msg_id = b; calc_ck += b; ps=PS_ID1; break;
    case PS_ID1:
      msg_id |= (uint16_t)b<<8; calc_ck += b; ps=PS_SRC; break;
    case PS_SRC:
      src_id = b; calc_ck += b; ps=PS_DST; break;
    case PS_DST:
      dst_id = b; calc_ck += b;
      if(pl_len > MAX_PAYLOAD){ ps=PS_FIND_S1; }
      else { payload_idx=0; ps = (pl_len==0) ? PS_CK0 : PS_PAYLOAD; }
      break;
    case PS_PAYLOAD:
      payload_buf[payload_idx++] = b; calc_ck += b;
      if(payload_idx >= pl_len) ps=PS_CK0;
      break;
    case PS_CK0:
      recv_ck = b; ps=PS_CK1; break;
    case PS_CK1:
      recv_ck |= (uint16_t)b<<8;
      if(recv_ck == calc_ck){
        if(dst_id == DEVICE_ID || dst_id == 0xFF){
          switch(msg_id){
            case MSG_GET_IMU:
              if(pl_len!=0){ uint8_t e=ERR_BAD_LENGTH; sendMsg(MSG_NACK, DEVICE_ID, src_id, &e, 1); }
              else { respondIMU(src_id); }
              break;
            case MSG_SET_HOME:
              if(pl_len==0){ setHomeCurrent(); sendMsg(MSG_ACK, DEVICE_ID, src_id, nullptr, 0); }
              else { setHomeExplicit(payload_buf, pl_len); }
              break;
            case MSG_RESET_VEL:
              if(pl_len!=0){ uint8_t e=ERR_BAD_LENGTH; sendMsg(MSG_NACK, DEVICE_ID, src_id, &e, 1); }
              else { resetVelocity(); }
              break;
            default:{
              uint8_t e=ERR_UNKNOWN_MSG; sendMsg(MSG_NACK, DEVICE_ID, src_id, &e, 1);
            } break;
          }
        }
      } else {
        uint8_t e=ERR_MALFORMED; sendMsg(MSG_NACK, DEVICE_ID, src_id, &e, 1);
      }
      resetParser();
      break;
  }
}

void pollSerial(){
  while(Serial.available()){
    uint8_t b = (uint8_t)Serial.read();
    processOneByte(b);
  }
}

// ====== Setup & Loop ======
void setup() {
  Serial.begin(115200);
  if(!bno08x.begin_I2C(0x4B)){
    while(true) { delay(100); }
  }
  enableReport(RV_TYPE,              RV_INTERVAL_US);
  enableReport(SH2_LINEAR_ACCELERATION, LA_INTERVAL_US);
  last_la_us = micros();
}

void loop() {
  // Re-enable after reset
  if (bno08x.wasReset()){
    enableReport(RV_TYPE,                RV_INTERVAL_US);
    enableReport(SH2_LINEAR_ACCELERATION, LA_INTERVAL_US);
    last_la_us = micros();
  }

  // Update latest sensor values
  if (bno08x.getSensorEvent(&sensorValue)){
    switch(sensorValue.sensorId){
      case SH2_ARVR_STABILIZED_RV:
        quaternionToEuler(sensorValue.un.arvrStabilizedRV.real,
                          sensorValue.un.arvrStabilizedRV.i,
                          sensorValue.un.arvrStabilizedRV.j,
                          sensorValue.un.arvrStabilizedRV.k,
                          (Euler*)&rpy);
        rv_status = sensorValue.status;
        break;

      case SH2_GYRO_INTEGRATED_RV:
        quaternionToEuler(sensorValue.un.gyroIntegratedRV.real,
                          sensorValue.un.gyroIntegratedRV.i,
                          sensorValue.un.gyroIntegratedRV.j,
                          sensorValue.un.gyroIntegratedRV.k,
                          (Euler*)&rpy);
        rv_status = sensorValue.status;
        break;

      case SH2_LINEAR_ACCELERATION: {
        // Linear acceleration (gravity removed), body frame, m/s^2
        lax = sensorValue.un.linearAcceleration.x;
        lay = sensorValue.un.linearAcceleration.y;
        laz = sensorValue.un.linearAcceleration.z;
        la_status = sensorValue.status;

        // --- Integrate to velocity (simple estimator) ---
        uint32_t now = micros();
        float dt = (now - last_la_us) * 1e-6f;
        if (dt < 0.5f) { // guard against long pauses
          // X
          if (fabsf(lax) > LA_DEADBAND) {
            vx += lax * dt;
          } else {
            float decay = expf(-VEL_DAMP * dt);
            vx *= decay;
          }
          // Y
          if (fabsf(lay) > LA_DEADBAND) {
            vy += lay * dt;
          } else {
            float decay = expf(-VEL_DAMP * dt);
            vy *= decay;
          }
          // Z
          if (fabsf(laz) > LA_DEADBAND) {
            vz += laz * dt;
          } else {
            float decay = expf(-VEL_DAMP * dt);
            vz *= decay;
          }
        }
        last_la_us = now;
      } break;

      default: break;
    }
  }

  // Handle incoming serial protocol
  pollSerial();
}
