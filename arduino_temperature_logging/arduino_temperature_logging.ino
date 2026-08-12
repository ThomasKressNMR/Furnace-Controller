// Nologo ESP32C3 Super Mini
#include "Seeed_MCP9600.h"
#include <ArduinoJson.h>
#define SERIAL Serial

#define SENSOR_ID 1

MCP9600 sensor;

mcp_err_t sensor_basic_config() {
  mcp_err_t ret = NO_ERROR;
  CHECK_RESULT(ret, sensor.set_filt_coefficients(FILT_MID));
  CHECK_RESULT(ret, sensor.set_cold_junc_resolution(COLD_JUNC_RESOLUTION_0_25));
  CHECK_RESULT(ret, sensor.set_ADC_meas_resolution(ADC_18BIT_RESOLUTION));
  CHECK_RESULT(ret, sensor.set_burst_mode_samp(BURST_32_SAMPLE));
  CHECK_RESULT(ret, sensor.set_sensor_mode(NORMAL_OPERATION));
  return ret;
}

mcp_err_t get_temperature(float* value) {
  mcp_err_t ret = NO_ERROR;
  CHECK_RESULT(ret, sensor.read_hot_junc(value));
  return ret;
}

void serialize_reading(float temp, mcp_err_t status) {
  StaticJsonDocument<128> doc;

  JsonObject thermocouple = doc.createNestedObject("thermocouple");
  thermocouple["ID"] = SENSOR_ID;
  thermocouple["temp"] = temp;
  thermocouple["status"] = (status == NO_ERROR) ? "ok" : "error";

  serializeJson(doc, SERIAL);
  SERIAL.println();
}

void setup() {
  SERIAL.begin(115200);
  delay(1);
  SERIAL.println("serial start!!");
  if (sensor.init(THER_TYPE_N)) {
    SERIAL.println("sensor init failed!!");

  }
  sensor_basic_config();
}

void loop() {
  float temp = 0;
  mcp_err_t status = get_temperature(&temp);
  serialize_reading(temp, status);
}