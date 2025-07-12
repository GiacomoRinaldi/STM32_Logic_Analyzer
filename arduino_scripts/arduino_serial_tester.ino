/* Simple program to test a serial logic analyzer; handles support for
 *  UART, SPI, and I2C connections. To run the program, set COMM_TYPE to 
 * your desired choice; ensure wiring is correct, and run the script and 
 * logic analyzer simultaneously. 
 *
 * Author: Giacomo Rinaldi 
 * Date Created: July 12, 2025
 * Last Updated: July 12, 2025 
 */

#include <Wire.h>
#include <SPI.h>

#define I2C 0
#define SPI 1
#define UART 2

const uint8_t COMM_TYPE = UART; // modify this according to your needs

char msg[13] = {'H', 'e', 'l', 'l', 'o', ',', ' ', 'W', 'o', 'r', 'l', 'd', '!'};

void setup() {
  Wire.begin();
  Serial.begin(9600); // if using UART, change baudrate as needed 
  SPI.begin();
  pinMode(SS, OUTPUT);
  digitalWrite(SS, HIGH);
}

void loop() {
  // switch for COMM_TYPE
  switch(COMM_TYPE) {
    case 0: // Handle I2C Communication protocol
      Wire.beginTransmission(0x01); // send to imaginary device at address 0x01
      Wire.write(msg, 13);
      Wire.endTransmission();
      delay(5000); 
      break;

    case 1: // Handle SPI Communication protocol
      digitalWrite(SS, LOW);
      for (int i=0; i<13; i++) {
        SPI.transfer(msg[i]);
      }
      digitalWrite(SS, HIGH);
      delay(5000);
      break; 

    case 2: // Handle UART Communication protocol 
      Serial.write(msg, 13); 
      delay(5000);
      break;
  }
}