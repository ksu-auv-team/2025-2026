#include <Servo.h>
#include <Wire.h>

#define SERIALDEBUG

#define I2CADDRESS 8

const unsigned long timeout = 2000;
unsigned long lastReceiveTime = 0;
const uint8_t defaultPWM = 127;
const uint16_t thrusterLow = 1200;
const uint16_t thrusterHigh = 1800;
bool I2CTimeoutSet = false;
uint8_t loopTime = 50; //Hz
uint8_t loopDelay = (1000 / loopTime);

uint8_t motorValues[8] = { defaultPWM, defaultPWM, defaultPWM, defaultPWM, defaultPWM, defaultPWM, defaultPWM, defaultPWM };
bool newData = 0;
Servo ESC[8];
const uint8_t ESCPins[] = { 3, 11, 10, 9, 6, 5, 2, 0 };
// Motors in order by I2C call 1, 2, 3, 4, 5, 6, 7, 8
// By Motors: M1 = P3, M2 = P11, M3 = P10, M4 = P9, M5 = P6, M6 = P5, M7 = P2, M8 = P0
// By Pins: P0 = M8, P2 = M7, P3 = M1, P5 = M6, P6 = M5, P9 = M4, P10 = M3, P11 = M2

void setup() {
#ifdef SERIALDEBUG  // prints to USB when SERIALDEBUG is defined
  Serial.begin(9600);
  Serial.println("Serial Enabled");
#endif
  Wire.begin(I2CADDRESS);        // start listening for I2C commands
  Wire.onReceive(receiveEvent);  // register the I2C interrupt
  for (int i = 0; i < 8; i++) {  // register each pin as a servo object
    ESC[i].attach(ESCPins[i]);
  }
  lastReceiveTime = millis();
}

void loop() {
  unsigned long currentTime = millis();
  if (currentTime - lastReceiveTime > timeout) {  // code to run after not recieving I2C commands for <timeout> time
    for (int i = 0; i < 8; i++) {
      ESC[i].writeMicroseconds(map(defaultPWM, 0, 255, thrusterLow, thrusterHigh));
      I2CTimeoutSet = true;
#ifdef SERIALDEBUG  // prints to USB when SERIALDEBUG is defined
      Serial.println("I2C Timeout");
      for (int i = 0; i < 8; i++) {
        Serial.print(i + 1);
        Serial.print(": ");
        Serial.print(motorValues[i]);
        Serial.print(" ");
      }
      Serial.println(" ");
#endif
    }
  } else if (newData) {  // code to run in order to assign commanded thrust level
    for (int i = 0; i < 8; i++) {
      ESC[i].writeMicroseconds(map(motorValues[i], 0, 255, thrusterLow, thrusterHigh));
      I2CTimeoutSet = false;
    }
    newData = 0;
  }

  int ledToggle = !ledToggle;  // toggles the onboard LED every second main loop
  if (ledToggle) {
    digitalWrite(1, !digitalRead(1));
  }

  delay(loopDelay);  // limits how fast the main loop will run
}

void receiveEvent(int howMany) {  // code that runs every time we are given an I2C command
  while (Wire.available() && (howMany == 6+1)) {
    Wire.read();
    for (int i = 0; i < 6; i++) {
      motorValues[i] = Wire.read();  // reads the buffer 8 times and assigns those values to the servo value array
    }
#ifdef SERIALDEBUG  // prints to USB when SERIALDEBUG is defined
    for (int i = 0; i < 6; i++) {
      Serial.print(i + 1);
      Serial.print(": ");
      Serial.print(motorValues[i]);
      Serial.print(" ");
    }
    Serial.println(" ");
#endif
    newData = 1;
    lastReceiveTime = millis();  // for the timeout function
  }
}