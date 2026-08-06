#!/usr/bin/env python3
"""
Stream a temperature profile JSON directly to a Eurotherm furnace via Modbus TCP
in REAL TIME with per-step progress bars, clean rounding, and 1-second resolution.
"""

import json
import sys
from pathlib import Path
from pymodbus.client import ModbusTcpClient
from tqdm import tqdm
import time

# --- Configuration ----------------------------------------------------
# JSON_FILE = Path("/Users/zorlaki/PycharmProjects/General-Postdoc/Temperature_logging/test/param.json")
# DT_SECONDS = 1.0  # Defined Timestep: tick interval in seconds
# EUROTHERM_IP = "192.168.111.222"
# EUROTHERM_PORT = 502

CONFIG_FILE = Path("config.json")

def load_config():
    if CONFIG_FILE.exists():
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}

config = load_config()
from pathlib import Path

JSON_FILE = Path(config.get("default_folder_path")) / config.get("last_file")
eurotherm_cfg = config.get("eurotherm", {})
EUROTHERM_IP = eurotherm_cfg.get("ip", "192.168.111.222")
EUROTHERM_PORT = eurotherm_cfg.get("port", 502)
DT_SECONDS = eurotherm_cfg.get("poll_interval", 1.0)


from pymodbus.client import ModbusTcpClient

SP_REGISTER = 2  # Setpoint Register
PV_REGISTER = 1  # Process Value (Current Temperature) Register
DEVICE_ID = 1

def send_setpoint(client: ModbusTcpClient, setpoint: float) -> bool:
    """Write target setpoint to Eurotherm Modbus register."""
    val_to_write = int(round(setpoint))
    result = client.write_register(
        address=SP_REGISTER,
        value=val_to_write,
        device_id=DEVICE_ID,
    )
    return not result.isError()


def read_current_temperature(client: ModbusTcpClient) -> float:
    """Read actual furnace current temperature (PV) via Modbus."""
    try:
        result = client.read_holding_registers(
            address=PV_REGISTER,
            count=1,
            device_id=DEVICE_ID,
        )
        if not result.isError():
            return float(result.registers[0])
    except Exception:
        pass
    return 0.0


def read_current_setpoint(client: ModbusTcpClient) -> float:
    """Read actual furnace current temperature (PV) via Modbus."""
    try:
        result = client.read_holding_registers(
            address=SP_REGISTER,
            count=1,
            device_id=DEVICE_ID,
        )
        if not result.isError():
            return float(result.registers[0])
    except Exception:
        pass
    return 0.0



def run_realtime_profile(profile: dict, client: ModbusTcpClient, DT_SECONDS: float):
    sp = float(profile["start_temperature"])
    send_setpoint(client, sp)

    t0 = time.monotonic()
    n = 0

    for segment_idx, seg in enumerate(profile["segments"], start=1):
        typ = seg["type"]
        title = seg.get("title", f"Segment {segment_idx}")

        # --------------------------------------------------------------
        # 1. RATE-LIMITED (Ramp using specified °C/min rate)
        # --------------------------------------------------------------
        if typ == "rate-limited":
            target = float(seg["target"])
            rate = float(seg["rate"])

            # Ensure sign of rate matches movement direction
            if target < sp and rate > 0:
                rate = -rate
            elif target > sp and rate < 0:
                rate = -rate

            duration_min = abs(target - sp) / abs(rate) if rate != 0 else 0
            steps = int(round(duration_min / (DT_SECONDS / 60.0)))
            temp_step = rate * (DT_SECONDS / 60.0)

            print(f"\n## Step {segment_idx}: '{title}' (RAMP {rate:+.2f}°C/min to {target}°C)")

            step_pbar = tqdm(
                total=round(duration_min, 2),
                desc=f"Step {segment_idx}",
                unit="min",
                ncols=100,
                bar_format="{l_bar}{bar}| {n_fmt}/{total_fmt} min [{elapsed}<{remaining}] {postfix}"
            )

            current_step_min = 0.0
            for _ in range(steps):
                sp += temp_step
                send_setpoint(client, sp)

                n += 1
                remaining = t0 + n * DT_SECONDS - time.monotonic()
                drift = 0.0
                if remaining > 0:
                    time.sleep(remaining)
                else:
                    drift = -remaining

                pv = read_current_temperature(client)

                current_step_min = round(current_step_min + (DT_SECONDS / 60.0), 4)
                step_pbar.n = round(current_step_min, 2)
                postfix = f"SP: {round(sp, 1)}°C | PV: {round(pv, 1)}°C"
                if drift > 0.05:
                    postfix += f" | behind: {drift:.2f}s"
                step_pbar.set_postfix_str(postfix)
                step_pbar.refresh()

            sp = target
            send_setpoint(client, sp)
            step_pbar.close()

        # --------------------------------------------------------------
        # 2. TIME-LIMITED (Ramp to target over fixed duration)
        # --------------------------------------------------------------
        elif typ == "time-limited":
            target = float(seg["target"])
            duration_min = float(seg.get("time", 0.0))

            steps = int(round(duration_min / (DT_SECONDS / 60.0)))
            temp_step = (target - sp) / steps if steps > 0 else 0
            calc_rate = (target - sp) / duration_min if duration_min > 0 else 0

            print(
                f"\n## Step {segment_idx}: '{title}' (TIME RAMP {calc_rate:+.2f}°C/min to {target}°C over {duration_min:.2f} min)")

            step_pbar = tqdm(
                total=round(duration_min, 2),
                desc=f"Step {segment_idx}",
                unit="min",
                ncols=100,
                bar_format="{l_bar}{bar}| {n_fmt}/{total_fmt} min [{elapsed}<{remaining}] {postfix}"
            )

            current_step_min = 0.0
            for _ in range(steps):
                sp += temp_step
                send_setpoint(client, sp)

                n += 1
                remaining = t0 + n * DT_SECONDS - time.monotonic()
                drift = 0.0
                if remaining > 0:
                    time.sleep(remaining)
                else:
                    drift = -remaining

                pv = read_current_temperature(client)

                current_step_min = round(current_step_min + (DT_SECONDS / 60.0), 4)
                step_pbar.n = round(current_step_min, 2)
                postfix = f"SP: {round(sp, 1)}°C | PV: {round(pv, 1)}°C"
                if drift > 0.05:
                    postfix += f" | behind: {drift:.2f}s"
                step_pbar.set_postfix_str(postfix)
                step_pbar.refresh()

            sp = target
            send_setpoint(client, sp)
            step_pbar.close()

        # --------------------------------------------------------------
        # 3. HOLD (Maintain current temperature for fixed time)
        # --------------------------------------------------------------
        elif typ == "hold":
            hold_time_min = float(seg.get("time", 0.0))
            send_setpoint(client, sp)
            steps = int(round(hold_time_min / (DT_SECONDS / 60.0)))

            print(f"\n## Step {segment_idx}: '{title}' (HOLD {sp}°C for {hold_time_min:.2f} min)")

            step_pbar = tqdm(
                total=round(hold_time_min, 2),
                desc=f"Step {segment_idx}",
                unit="min",
                ncols=100,
                bar_format="{l_bar}{bar}| {n_fmt}/{total_fmt} min [{elapsed}<{remaining}] {postfix}"
            )

            current_step_min = 0.0
            for _ in range(steps):
                n += 1
                remaining = t0 + n * DT_SECONDS - time.monotonic()
                drift = 0.0
                if remaining > 0:
                    time.sleep(remaining)
                else:
                    drift = -remaining

                send_setpoint(client, sp)
                pv = read_current_temperature(client)

                current_step_min = round(current_step_min + (DT_SECONDS / 60.0), 4)
                step_pbar.n = round(current_step_min, 2)
                postfix = f"SP: {round(sp, 1)}°C | PV: {round(pv, 1)}°C"
                if drift > 0.05:
                    postfix += f" | behind: {drift:.2f}s"
                step_pbar.set_postfix_str(postfix)
                step_pbar.refresh()

            step_pbar.close()


def main():
    if not JSON_FILE.exists():
        sys.exit(f"File not found: {JSON_FILE}")

    try:
        with open(JSON_FILE, "r", encoding="utf-8") as f:
            profile = json.load(f)
    except Exception as e:
        sys.exit(f"Failed to read JSON: {e}")

    client = ModbusTcpClient(host=EUROTHERM_IP, port=EUROTHERM_PORT)
    if not client.connect():
        sys.exit(f"Failed to connect to {EUROTHERM_IP}:{EUROTHERM_PORT}")

    print("Starting real-time furnace execution...")
    try:
        run_realtime_profile(profile, client, DT_SECONDS)
        print("\n\nAll profile segments completed successfully!")
    except KeyboardInterrupt:
        print("\nExecution stopped by user.")
    finally:
        client.close()


if __name__ == "__main__":
    main()