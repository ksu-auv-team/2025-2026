#include <Wire.h>
#include <Servo.h>

// ── I2C ──────────────────────────────────────────────────────────────────────
// SDA/SCL are the board's default I2C pins (e.g. A4/A5 on Uno, 20/21 on Mega)
#define I2C_ADDRESS  0x08

// ── Motor PWM Pins ────────────────────────────────────────────────────────────
#define PIN_MOTOR1   6
#define PIN_MOTOR2   7
#define PIN_MOTOR3   8
#define PIN_MOTOR4   9
#define PIN_MOTOR5   10
#define PIN_MOTOR6   11
#define PIN_MOTOR7   12
#define PIN_MOTOR8   13

// ── BlueRobotics Basic ESC PWM Range ─────────────────────────────────────────
#define PWM_MIN         1200
#define PWM_NEUTRAL     1512
#define PWM_MAX         1800

#define NUM_MOTORS      8
#define REGISTER_THRUST 0x00

// ─────────────────────────────────────────────────────────────────────────────

Servo motors[NUM_MOTORS];

const uint8_t MOTOR_PINS[NUM_MOTORS] = {
    PIN_MOTOR1, PIN_MOTOR2, PIN_MOTOR3, PIN_MOTOR4, PIN_MOTOR5, PIN_MOTOR6, PIN_MOTOR7, PIN_MOTOR8
};

static inline int toMicroseconds(uint8_t value) {
    return map(value, 0, 255, PWM_MIN, PWM_MAX);
}

void onReceive(int bytes) {
    uint8_t buf[6];
    uint8_t len = 0;

    while (Wire.available() && len < sizeof(buf)) {
        buf[len++] = Wire.read();
    }
    while (Wire.available()) Wire.read();

    if (len < 6 || buf[0] != REGISTER_THRUST) return;

    for (int i = 0; i < 4; i++) {
        motors[i].writeMicroseconds(toMicroseconds(buf[i + 1]));
    }

    int remaining_us = toMicroseconds(buf[5]);
    for (int i = 4; i < NUM_MOTORS; i++) {
        motors[i].writeMicroseconds(remaining_us);
    }

    Serial.print("Received thrust: ");
    for (int i = 0; i < NUM_MOTORS; i++) {
        Serial.print(toMicroseconds(buf[i + 1]));
        Serial.print(" ");
    }
    Serial.println();
}

void setup() {
    Serial.begin(115200);

    Wire.begin(I2C_ADDRESS);
    Wire.onReceive(onReceive);

    for (int i = 0; i < NUM_MOTORS; i++) {
        motors[i].attach(MOTOR_PINS[i]);
        motors[i].writeMicroseconds(PWM_NEUTRAL);
    }
}

void loop() {
    delay(10);
}