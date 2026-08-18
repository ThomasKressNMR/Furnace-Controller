// Nologo ESP32C3 Super Mini
#include "Seeed_MCP9600.h"
#include <ArduinoJson.h>

#define SERIAL Serial
#define SENSOR_ID 1

#define REPORT_INTERVAL_MS 500

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

void loop() {
  static unsigned long lastReport = 0;

  if (millis() - lastReport < REPORT_INTERVAL_MS) {
    return;
  }

  lastReport = millis();

  float temp = 0;
  float coldTemp = 0;

  mcp_err_t tempStatus = sensor.read_hot_junc(&temp);
  mcp_err_t coldStatus = sensor.read_cold_junc(&coldTemp);

  StaticJsonDocument<160> doc;

  JsonObject thermocouple = doc.createNestedObject("thermocouple");

  thermocouple["ID"] = SENSOR_ID;
  thermocouple["hot_temp"] = temp;
  thermocouple["cold_temp"] = coldTemp;
  thermocouple["status"] =
      (tempStatus == NO_ERROR && coldStatus == NO_ERROR)
      ? "ok"
      : "error";

  serializeJson(doc, SERIAL);
  SERIAL.println();
}

void setup() {
  SERIAL.begin(115200);
  delay(100);

  SERIAL.println("serial start!!");

  if (sensor.init(THER_TYPE_N)) {
    SERIAL.println("sensor init failed!!");
    return;
  }

  sensor_basic_config();
}