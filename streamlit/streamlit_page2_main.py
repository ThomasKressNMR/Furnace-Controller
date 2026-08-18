from __future__ import annotations

import json
import os
import queue
import re
import subprocess
import sys
import threading
from collections import deque
from datetime import datetime
from pathlib import Path

import streamlit as st
from serial.tools import list_ports

# Insert imports from shared module
from profile_utils import (
    load_app_config,
    update_config_key,
    calculate_profile_times,
    validate_profile,
    generate_profiles,
    plot_profile_plotly,
)

# =============================================================================
# Configuration & Global Persistence
# =============================================================================

MAX_LOG_LINES = 1000
DEFAULT_COOL_DOWN_STOP_TEMP = 100.0

SERVICES = {
    "profile": {
        "label": "Run Profile",
        "script": "run_furnace_profile.py",
        "requires_profile": True,
    },
    "influx": {
        "label": "InfluxDB Logger",
        "script": "influxdb_furnace_logging.py",
    },
    "esp32": {
        "label": "ESP32 Thermocouple",
        "script": "log_esp32_thermocouple.py",
        "requires_port": True,
    },
}

CONFIG_FILE_PATH = Path("config.json")


class ServiceManager:
    """Persistent background process manager across Streamlit reruns."""

    def __init__(self):
        self.processes: dict[str, subprocess.Popen] = {}
        self.start_times: dict[str, datetime] = {}
        self.logs: dict[str, deque] = {
            service_id: deque(maxlen=MAX_LOG_LINES) for service_id in SERVICES
        }
        self.log_queue: queue.Queue = queue.Queue()

    def append_log(self, service_id: str, message: str) -> None:
        ts = datetime.now().strftime("%H:%M:%S")
        self.logs[service_id].append(f"[{ts}] {message}")

    def process_queue(self) -> None:
        while True:
            try:
                service_id, line = self.log_queue.get_nowait()
                if service_id in self.logs:
                    self.logs[service_id].append(line)
            except queue.Empty:
                break

    def is_running(self, service_id: str) -> bool:
        proc = self.processes.get(service_id)
        if proc is None:
            return False
        return proc.poll() is None

    def get_process(self, service_id: str) -> subprocess.Popen | None:
        return self.processes.get(service_id)

    def extract_metrics(self) -> dict[str, str]:
        """Parse live log streams to extract telemetry values for st.metric."""
        metrics = {
            "temperature": "—",
            "setpoint": "—",
            "sample_temp": "—",
            "samples": "—",
        }

        for service_id in ["esp32", "profile", "influx"]:
            for line in reversed(self.logs[service_id]):
                if all(v != "—" for v in metrics.values()):
                    break

                if metrics["temperature"] == "—":
                    m = re.search(r"\btemperature=([\d\.]+)(?:°C)?", line)
                    if m:
                        metrics["temperature"] = f"{float(m.group(1)):.0f} °C"

                if metrics["setpoint"] == "—":
                    m = re.search(r"setpoint=([\d\.]+)(?:°C)?", line)
                    if m:
                        metrics["setpoint"] = f"{float(m.group(1)):.0f} °C"

                if metrics["sample_temp"] == "—":
                    m = re.search(r"sample_temperature=([\d\.]+)", line)
                    if m:
                        metrics["sample_temp"] = f"{float(m.group(1)):.2f} °C"

                if metrics["samples"] == "—":
                    m = re.search(r"\(n=(\d+)\)", line)
                    if m:
                        metrics["samples"] = m.group(1)

        return metrics


@st.cache_resource
def get_manager() -> ServiceManager:
    return ServiceManager()


def get_profile_durations(profile_dir: str, profile_name: str) -> tuple[float, float, float]:
    """
    Extract (recipe_time_min, cooling_time_min, total_time_min) from profile.

    Returns:
        tuple[float, float, float]: (recipe_min, cooling_min, total_min)
    """
    if not profile_dir or not profile_name:
        return 0.0, 0.0, 0.0

    profile_path = Path(profile_dir) / profile_name
    if profile_path.exists() and profile_path.is_file():
        try:
            with open(profile_path, "r", encoding="utf-8") as f:
                data = json.load(f)

            cfg = load_app_config()
            recipe_min, total_min = calculate_profile_times(data, cfg)
            cooling_min = max(0.0, total_min - recipe_min)
            return recipe_min, cooling_min, total_min
        except Exception:
            pass
    return 0.0, 0.0, 0.0


def format_time_min(minutes: float) -> str:
    """Format decimal minutes into Xh Ym Zs or Xm Zs string."""
    total_sec = max(0, int(minutes * 60))
    hrs = total_sec // 3600
    mins = (total_sec % 3600) // 60
    secs = total_sec % 60
    if hrs > 0:
        return f"{hrs}h {mins}m {secs}s"
    return f"{mins}m {secs}s"


# =============================================================================
# Streamlit Page Setup
# =============================================================================

st.set_page_config(
    page_title="Furnace Control Panel",
    layout="wide",
)

mgr = get_manager()

if "app_config" not in st.session_state:
    st.session_state.app_config = load_app_config()

if "profile_dir" not in st.session_state:
    st.session_state.profile_dir = st.session_state.app_config["default_folder_path"]

if "selected_profile" not in st.session_state:
    st.session_state.selected_profile = st.session_state.app_config["last_file"]

if "selected_port" not in st.session_state:
    st.session_state.selected_port = st.session_state.app_config.get("last_port", "")


# =============================================================================
# Helpers & Process Control
# =============================================================================

def on_port_change():
    selected_label = st.session_state.get("port_select_key")
    ports_map = get_serial_ports()
    if selected_label in ports_map:
        st.session_state.selected_port = ports_map[selected_label]
        update_config_key(last_port=st.session_state.selected_port)


def on_folder_change():
    update_config_key(default_folder_path=st.session_state.profile_dir)


def on_profile_change():
    st.session_state.selected_profile = st.session_state.get("profile_select_key", "")
    update_config_key(last_file=st.session_state.selected_profile)


def get_serial_ports() -> dict[str, str]:
    return {
        f"{port.device} ({port.description})": port.device
        for port in list_ports.comports()
    }


def get_profile_files(profile_dir: Path) -> list[str]:
    if not profile_dir.exists():
        return []

    return sorted(
        file.name for file in profile_dir.glob("*.json") if file.is_file()
    )


def get_service_args(service_id: str) -> list[str]:
    service = SERVICES[service_id]
    args = []

    if service.get("requires_port"):
        port = st.session_state.selected_port
        if not port:
            raise ValueError("No serial port selected.")
        args.extend(["--port", port])

    if service.get("requires_profile"):
        profile = st.session_state.selected_profile
        if not profile:
            raise ValueError("No profile selected.")
        profile_path = Path(st.session_state.profile_dir) / profile
        args.extend(["--profile", str(profile_path)])

    return args


def stream_output(service_id: str, pipe, log_queue: queue.Queue) -> None:
    try:
        for line in iter(pipe.readline, ""):
            if line:
                log_queue.put((service_id, line.rstrip()))
    finally:
        pipe.close()


def start_process(service_id: str) -> None:
    if mgr.is_running(service_id):
        return

    service = SERVICES[service_id]
    script = Path(service["script"])

    if not script.exists():
        mgr.append_log(service_id, f"ERROR: Script not found: {script}")
        return

    try:
        args = get_service_args(service_id)
    except Exception as exc:
        mgr.append_log(service_id, f"CONFIGURATION ERROR: {exc}")
        return

    try:
        cmd = [sys.executable, "-u", str(script), *args]
        env = os.environ.copy()
        env["PYTHONUNBUFFERED"] = "1"

        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            env=env,
        )

        mgr.processes[service_id] = proc
        mgr.start_times[service_id] = datetime.now()

        threading.Thread(
            target=stream_output,
            args=(service_id, proc.stdout, mgr.log_queue),
            daemon=True,
        ).start()

        mgr.append_log(service_id, f"Started (PID={proc.pid})")
        mgr.append_log(service_id, f"Command: {' '.join(cmd)}")

    except Exception as exc:
        mgr.append_log(service_id, f"LAUNCH ERROR: {exc}")


def stop_process(service_id: str) -> None:
    proc = mgr.get_process(service_id)
    if proc is None:
        return

    if proc.poll() is None:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()

    mgr.append_log(service_id, "Stopped")


# =============================================================================
# Dashboard Header & Configuration
# =============================================================================

st.title("Furnace Control Panel")

# Sidebar Settings
with st.sidebar:
    st.header("⚙️ Settings")

    # Profile Directory
    profile_dir = Path(
        st.text_input(
            "Profile Directory",
            value=st.session_state.profile_dir,
            on_change=on_folder_change,
        )
    )
    st.session_state.profile_dir = str(profile_dir)

    # Profile File
    if profile_dir.exists():
        profiles = get_profile_files(profile_dir)

        if profiles:
            if st.session_state.selected_profile not in profiles:
                st.session_state.selected_profile = profiles[0]

            default_index = profiles.index(
                st.session_state.selected_profile
            )

            st.selectbox(
                "Profile File",
                profiles,
                index=default_index,
                key="profile_select_key",
                on_change=on_profile_change,
            )
            st.session_state.selected_profile = (
                st.session_state.profile_select_key
            )
        else:
            st.info("No JSON profiles found.")
            st.session_state.selected_profile = ""

        # Serial Port
        ports = get_serial_ports()
        if ports:
            port_labels = list(ports.keys())
            port_devices = list(ports.values())

            if st.session_state.selected_port not in port_devices:
                st.session_state.selected_port = port_devices[0]

            default_idx = port_devices.index(st.session_state.selected_port)

            st.selectbox(
                "ESP32 Serial Port",
                options=port_labels,
                index=default_idx,
                key="port_select_key",
                on_change=on_port_change,
            )
            st.session_state.selected_port = ports[st.session_state.port_select_key]
        else:
            st.warning("No serial ports detected.")
            st.session_state.selected_port = ""

    else:
        st.error(f"Directory not found: {profile_dir}")
        st.session_state.selected_profile = ""

    st.divider()
    # Sidebar checkbox to toggle plotting natural cool-down phase
    include_cooldown = st.checkbox(
        "Plot natural cool-down to limit",
        value=True,
        help="Extends the simulation past the final segment down to the recipe's cool_down_stop_temp."
    )

# =============================================================================
# 3-Column Services Control
# =============================================================================

service_cols = st.columns(len(SERVICES))

for col, (service_id, service) in zip(service_cols, SERVICES.items()):
    running = mgr.is_running(service_id)

    with col:
        with st.container(border=False):
            st.subheader(service["label"])

            b_col1, b_col2 = st.columns(2)
            with b_col1:
                st.button(
                    "Start",
                    key=f"start_{service_id}",
                    disabled=running,
                    on_click=start_process,
                    args=(service_id,),
                    use_container_width=True,
                )
            with b_col2:
                st.button(
                    "Stop",
                    key=f"stop_{service_id}",
                    disabled=not running,
                    on_click=stop_process,
                    args=(service_id,),
                    use_container_width=True,
                )

            status_text = "🟢 Running" if running else "🔴 Stopped"
            proc = mgr.get_process(service_id)
            if proc and running:
                status_text += f" (PID {proc.pid})"
            st.caption(status_text)


# =============================================================================
# Live Dashboard (Metrics & Logs auto-refreshing)
# =============================================================================
@st.fragment(run_every=1.0)
def render_dashboard():
    mgr.process_queue()
    metrics = mgr.extract_metrics()

    recipe_time_min, cooling_time_min, est_total_time_min = get_profile_durations(
        st.session_state.profile_dir,
        st.session_state.selected_profile,
    )

    profile_running = mgr.is_running("profile")
    start_time = mgr.start_times.get("profile")

    if profile_running and start_time:
        elapsed_sec = (datetime.now() - start_time).total_seconds()
        elapsed_min = elapsed_sec / 60.0

        # Recipe progress vs cooling progress
        recipe_elapsed_min = min(elapsed_min, recipe_time_min)
        recipe_remaining_min = max(0.0, recipe_time_min - elapsed_min)

        cooling_elapsed_min = max(0.0, elapsed_min - recipe_time_min)
        cooling_remaining_min = max(0.0, cooling_time_min - cooling_elapsed_min)

        total_remaining_min = max(0.0, est_total_time_min - elapsed_min)
        pct = min(100.0, (elapsed_min / est_total_time_min * 100.0)) if est_total_time_min > 0 else 0.0

        elapsed_str = format_time_min(elapsed_min)
        recipe_remaining_str = format_time_min(recipe_remaining_min)
        cooling_remaining_str = format_time_min(cooling_remaining_min)
        pct_str = f"{pct:.1f}%"
        progress_val = min(1.0, max(0.0, pct / 100.0))
    else:
        elapsed_str = "0m 0s"
        recipe_remaining_str = format_time_min(recipe_time_min) if recipe_time_min > 0 else "—"
        cooling_remaining_str = format_time_min(cooling_time_min) if cooling_time_min > 0 else "—"
        pct_str = "0.0%"
        progress_val = 0.0

    # Temperature Row
    m1, m2, m3 = st.columns(3)
    m1.metric("Current Temp", metrics["temperature"])
    m2.metric("Setpoint Target", metrics["setpoint"])
    m3.metric("Sample Temp", metrics["sample_temp"])

    # Duration Totals Row
    m4, m5, m6 = st.columns(3)
    m4.metric("Recipe Duration", format_time_min(recipe_time_min) if recipe_time_min > 0 else "—")
    m5.metric("Est. Cool Down Time", format_time_min(cooling_time_min) if cooling_time_min > 0 else "—")
    m6.metric("Total Est. Duration", format_time_min(est_total_time_min) if est_total_time_min > 0 else "—")

    # Dynamic Countdown Counters Row
    m7, m8, m9 = st.columns(3)
    m7.metric("Elapsed Total Time", elapsed_str)
    m8.metric("Recipe Rem. Time", recipe_remaining_str)
    m9.metric("Cooling Rem. Time", cooling_remaining_str)

    if profile_running or est_total_time_min > 0:
        st.caption(f"Overall Completion: {pct_str}")
        st.progress(progress_val)

    # Render interactive profile graph for selected JSON
    st.markdown("### Profile Target Plot")
    selected_path = Path(st.session_state.profile_dir) / st.session_state.selected_profile
    if selected_path.exists() and selected_path.is_file():
        try:
            with open(selected_path, "r", encoding="utf-8") as f:
                selected_profile_data = json.load(f)

            warnings = validate_profile(selected_profile_data)
            for warn in warnings:
                st.warning(warn)

            # Retrieve cool down stop temp directly from the JSON profile
            cool_stop_temp = selected_profile_data.get("cool_down_stop_temp", DEFAULT_COOL_DOWN_STOP_TEMP)

            sp_time, sp_temp, sim_time_h, sim_temp, annotations, segment_info = generate_profiles(
                selected_profile_data,
                include_cool_down=include_cooldown
            )

            fig = plot_profile_plotly(
                sp_time,
                sp_temp,
                sim_time_h,
                sim_temp,
                annotations,
                segment_info,
                cool_down_stop_temp=cool_stop_temp if include_cooldown else None
            )
            st.plotly_chart(fig, width='stretch')
        except Exception as err:
            st.error(f"Could not load or plot selected profile: {err}")
    else:
        st.info("No profile loaded to display plot.")

    st.markdown("### Output Logs")
    tabs = st.tabs([service["label"] for service in SERVICES.values()])

    for tab, (service_id, service) in zip(tabs, SERVICES.items()):
        with tab:
            logs_list = list(mgr.logs[service_id])
            log_text = "\n".join(reversed(logs_list)) if logs_list else "No log activity."
            st.code(log_text, language="text", height=450)


st.divider()

render_dashboard()