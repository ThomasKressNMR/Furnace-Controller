import json
import logging
import os
import sys
import time
from collections import defaultdict
from pathlib import Path

import serial
from dotenv import load_dotenv
from influxdb_client import InfluxDBClient, Point
from influxdb_client.client.write_api import SYNCHRONOUS
from serial.tools import list_ports

import argparse

def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--port",
        required=True,
        help="Serial port for ESP32",
    )
    return parser.parse_args()

CONFIG_FILE = Path("config.json")

def load_config():
    if CONFIG_FILE.exists():
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}

config = load_config()

esp32_cfg = config.get("esp32", {})

BAUD_RATE = 115200
SERIAL_TIMEOUT = 2
MEASUREMENT = esp32_cfg.get("measurement","TS1-1200")
LOG_INTERVAL = esp32_cfg.get("log_interval", 1)
RECONNECT_DELAY = 5

load_dotenv()


def require_env(name: str) -> str:
    value = os.getenv(name)
    if not value:
        sys.exit(f"Missing required environment variable: {name}")
    return value


INFLUX_URL = require_env("INFLUX_URL")
INFLUX_TOKEN = require_env("INFLUX_TOKEN")
INFLUX_ORG = require_env("INFLUX_ORG")
INFLUX_BUCKET = require_env("INFLUX_BUCKET")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger(__name__)


def parse_line(raw_line: str) -> dict | None:
    raw_line = raw_line.strip()
    if not raw_line:
        return None

    try:
        data = json.loads(raw_line)
    except json.JSONDecodeError:
        log.warning("Malformed JSON: %r", raw_line)
        return None

    reading = data.get("thermocouple")
    if not reading:
        return None

    if "ID" not in reading or "temp" not in reading:
        log.warning("Unexpected payload: %r", raw_line)
        return None

    return reading


def write_window(write_api, buffers: dict[str, list[float]]) -> None:
    for sensor_id, temps in buffers.items():
        if not temps:
            continue

        avg_temp = sum(temps) / len(temps)

        point = (
            Point(MEASUREMENT)
            .field("sample_temperature", avg_temp)
        )

        write_api.write(bucket=INFLUX_BUCKET, record=point)

        log.info(
            "Wrote sample_temperature=%.2f (n=%d)",
            avg_temp,
            len(temps),
        )
        print(f"Wrote sample_temperature={avg_temp:.2f} (n={len(temps)})")

def run() -> None:
    args = parse_args()
    serial_port = args.port
    ports = list(list_ports.comports())
    if not ports:
        raise RuntimeError("No serial ports found")
    log.info(
        "Available ports: %s",
        ", ".join(p.device for p in ports),
    )

    client = InfluxDBClient(
        url=INFLUX_URL,
        token=INFLUX_TOKEN,
        org=INFLUX_ORG,
    )
    write_api = client.write_api(write_options=SYNCHRONOUS)

    buffers: dict[str, list[float]] = defaultdict(list)
    window_start = time.monotonic()

    try:
        while True:
            try:
                with serial.Serial(
                    serial_port,
                    BAUD_RATE,
                    timeout=SERIAL_TIMEOUT,
                ) as ser:
                    log.info(
                        "Connected to %s at %d baud",
                        serial_port,
                        BAUD_RATE,
                    )

                    while True:
                        line = ser.readline().decode(
                            "utf-8",
                            errors="replace",
                        )

                        reading = parse_line(line)
                        if reading:
                            sensor_id = str(reading["ID"])
                            status = reading.get("status", "unknown")

                            if status == "ok":
                                buffers[sensor_id].append(
                                    float(reading["temp"])
                                )
                            else:
                                log.warning(
                                    "Sensor %s status=%s",
                                    sensor_id,
                                    status,
                                )

                        now = time.monotonic()
                        if now - window_start >= LOG_INTERVAL:
                            write_window(write_api, buffers)
                            buffers.clear()
                            window_start = now

            except serial.SerialException as exc:
                log.error(
                    "Serial connection lost (%s), retrying in %ds",
                    exc,
                    RECONNECT_DELAY,
                )
                time.sleep(RECONNECT_DELAY)

    except KeyboardInterrupt:
        log.info("Interrupted, shutting down")

    finally:
        write_api.close()
        client.close()


if __name__ == "__main__":
    run()