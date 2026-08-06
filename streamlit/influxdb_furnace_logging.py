#!/usr/bin/env python3

import argparse
import logging
import os
import sys
import time

from dotenv import load_dotenv
from influxdb_client import InfluxDBClient, Point, WritePrecision
from influxdb_client.client.write_api import SYNCHRONOUS
from pymodbus.client import ModbusTcpClient
import json
from pathlib import Path

# ------------------------------------------------------------------
# Eurotherm configuration
# ------------------------------------------------------------------


PV_REGISTER = 1 # Current temperature
SP_REGISTER = 2  # Setpoint Temperature




CONFIG_FILE = Path("config.json")

def load_config():
    if CONFIG_FILE.exists():
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}

config = load_config()

# Load specific sections with fallback default values
eurotherm_cfg = config.get("eurotherm", {})
EUROTHERM_IP = eurotherm_cfg.get("ip", "192.168.111.222")
EUROTHERM_PORT = eurotherm_cfg.get("port", 502)
POLL_INTERVAL = eurotherm_cfg.get("poll_interval", 1.0)
MEASUREMENT = eurotherm_cfg.get("MEASUREMENT", "TS1-1200")


# ------------------------------------------------------------------
# InfluxDB configuration
# ------------------------------------------------------------------

load_dotenv()

def require_env(name):
    value = os.environ.get(name)
    if not value:
        sys.exit(f"Missing required environment variable: {name}")
    return value


INFLUX_URL = require_env("INFLUX_URL")
INFLUX_TOKEN = require_env("INFLUX_TOKEN")
INFLUX_ORG = require_env("INFLUX_ORG")
INFLUX_BUCKET = require_env("INFLUX_BUCKET")


def read_register(client, address):
    result = client.read_holding_registers(
        address=address,
        count=1,
        device_id=1,
    )

    if result.isError():
        raise RuntimeError(f"Failed reading register {address}")

    return result.registers[0]



logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)

log = logging.getLogger(__name__)




def run():

    influx_client = InfluxDBClient(
        url=INFLUX_URL,
        token=INFLUX_TOKEN,
        org=INFLUX_ORG,
    )

    write_api = influx_client.write_api(
        write_options=SYNCHRONOUS
    )

    while True:
        modbus = ModbusTcpClient(
            host=EUROTHERM_IP,
            port=EUROTHERM_PORT,
        )

        try:
            if not modbus.connect():
                raise RuntimeError(
                    f"Cannot connect to {EUROTHERM_IP}:{EUROTHERM_PORT}"
                )

            log.info(
                "Connected to Eurotherm at %s:%d",
                EUROTHERM_IP,
                EUROTHERM_PORT,
            )

            while True:
                pv = read_register(modbus, PV_REGISTER)
                sp = read_register(modbus, SP_REGISTER)

                point = Point(MEASUREMENT).field("furnace_temperature", pv).field("furnace_setpoint", sp).time(time.time_ns(), WritePrecision.NS)

                write_api.write(
                    bucket=INFLUX_BUCKET,
                    record=point,
                )

                log.info(
                    "temperature=%.2f°C  setpoint=%.2f°C",
                    pv,
                    sp,
                )

                time.sleep(POLL_INTERVAL)

        except KeyboardInterrupt:
            break

        except Exception as exc:
            log.error("Error: %s", exc)
            time.sleep(5)

        finally:
            modbus.close()

    write_api.close()
    influx_client.close()


if __name__ == "__main__":
    run()