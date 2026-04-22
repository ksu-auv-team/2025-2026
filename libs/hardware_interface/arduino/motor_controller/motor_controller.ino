#include <Servo.h>
#include <Wire.h>

#define SERIALDEBUG

#define I2CADDRESS 8

const unsigned long timeout = 2000;
unsigned long lastReceiveTime = 0;
const uint8_t defaultPWM = 127;
const uint16_t thrusterLow = 1350;
const uint16_t thrusterHigh = 1650;

// Values received over I2C: MOTOR1, MOTOR2, MOTOR3, MOTOR4, VERTICAL_THRUST
const uint8_t MOTOR_COUNT = 5;
// Physical ESCs: M1-M4 independent, M5-M8 all share VERTICAL_THRUST (motorValues[4])
const uint8_t ESC_COUNT = 8;

uint8_t motorValues[MOTOR_COUNT] = { defaultPWM, defaultPWM, defaultPWM, defaultPWM, defaultPWM };
bool newData = false;
bool i2cTimeout = false;

Servo ESC[ESC_COUNT];
// M1=P3, M2=P11, M3=P10, M4=P9, M5=P6, M6=P5, M7=P2, M8=P0
const byte ESCPins[ESC_COUNT] = { 3, 11, 10, 9, 6, 5, 2, 0 };
// Maps each ESC index to its motorValues index (M5-M8 all use VERTICAL_THRUST at index 4)
const uint8_t escToMotor[ESC_COUNT] = { 0, 1, 2, 3, 4, 4, 4, 4 };

void setup() {
#ifdef SERIALDEBUG
  Serial.begin(9600);
  Serial.println("Serial Enabled");
#endif
  Wire.begin(I2CADDRESS);
  Wire.onReceive(receiveEvent);
  for (int i = 0; i < ESC_COUNT; i++) {
    ESC[i].attach(ESCPins[i]);
    ESC[i].writeMicroseconds(map(defaultPWM, 0, 255, thrusterLow, thrusterHigh));
  }
  lastReceiveTime = millis();
}

void loop() {
  unsigned long currentTime = millis();

  if (currentTime - lastReceiveTime > timeout) {
    if (!i2cTimeout) {
      for (int i = 0; i < ESC_COUNT; i++) {
        ESC[i].writeMicroseconds(map(defaultPWM, 0, 255, thrusterLow, thrusterHigh));
      }
      i2cTimeout = true;
#ifdef SERIALDEBUG
      Serial.println("I2C Timeout — motors set to neutral");
#endif
    }
  } else if (newData) {
    for (int i = 0; i < ESC_COUNT; i++) {
      ESC[i].writeMicroseconds(map(motorValues[escToMotor[i]], 0, 255, thrusterLow, thrusterHigh));
    }
    i2cTimeout = false;
    newData = false;
#ifdef SERIALDEBUG
    for (int i = 0; i < MOTOR_COUNT; i++) {
      Serial.print("M");
      Serial.print(i + 1);
      Serial.print(": ");
      Serial.print(motorValues[i]);
      Serial.print("  ");
    }
    Serial.println();
#endif
  }

  delay(20);
}

void receiveEvent(int howMany) {
  // Expect 6 bytes: 1 header (discarded) + 5 motor values
  if (howMany != 6) {
    while (Wire.available()) Wire.read();
    return;
  }
  Wire.read();  // discard header byte
  for (int i = 0; i < MOTOR_COUNT; i++) {
    motorValues[i] = Wire.read();
  }
  newData = true;
  lastReceiveTime = millis();
}
