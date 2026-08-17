from __future__ import annotations

import json
from pathlib import Path
import plotly.graph_objects as go
import streamlit as st
import math

PARAM_FILE_PATH = Path("param.json")
CONFIG_FILE_PATH = Path("config.json")
SEGMENT_TYPES = ["hold", "rate-limited", "time-limited"]


def load_app_config() -> dict:
    """Load settings from config.json or return default fallbacks."""
    default_config = {
        "default_folder_path": ".",
        "last_file": "profile.json",
        "last_port": "",
        "esp32": {"measurement": "TS1-1200", "log_interval": 1.0},
        "eurotherm": {"ip": "192.168.111.222", "port": 502, "poll_interval": 1.0},
        "limits": {
            "max_temp": 1200.0,
            "min_rate": -6.5,
            "max_rate": 6.7,
            "measurement": "TS1-1200",
        },
    }
    if CONFIG_FILE_PATH.exists():
        try:
            with open(CONFIG_FILE_PATH, "r", encoding="utf-8") as f:
                default_config.update(json.load(f))
        except Exception:
            pass
    return default_config


def update_config_key(**kwargs):
    """Update specific key(s) in config.json."""
    config = load_app_config()
    config.update(kwargs)
    try:
        with open(CONFIG_FILE_PATH, "w", encoding="utf-8") as f:
            json.dump(config, f, indent=2)
    except Exception as e:
        st.error(f"Failed to update config.json: {e}")





def calculate_profile_times(profile: dict, config: dict) -> tuple[float, float]:
    """
    Calculate recipe duration and actual estimated experiment duration in minutes.

    Returns:
        tuple[float, float]: (recipe_time_min, estimated_total_time_min)
    """
    sp = profile.get("start_temperature", 25.0)
    t_recipe = 0.0
    t_actual = 0.0

    limits = config.get("limits", {})
    t_ambient = limits.get("t_ambient", 30.0)

    # Target temperature to end cooling estimate (e.g. 100.0 °C)
    cool_down_stop_temp = limits.get("cool_down_stop_temp", 100.0)

    # Resolve half-life in minutes from decay_rate_h1 (h^-1), half_life_h (hours), or half_life_min
    if "decay_rate_h1" in limits and limits["decay_rate_h1"] > 0:
        half_life_min = (math.log(2) / limits["decay_rate_h1"]) * 60.0
    elif "half_life_h" in limits:
        half_life_min = limits["half_life_h"] * 60.0
    else:
        half_life_min = limits.get("half_life_min", 127.66)

    MIN_DELTA = 0.5  # Safety margin above ambient to prevent log(0)

    for seg in profile.get("segments", []):
        typ = seg.get("type")

        if typ == "rate-limited":
            target = seg.get("target", sp)
            rate = seg.get("rate", 0.0)

            t_linear = abs(target - sp) / abs(rate) if rate != 0 else 0.0
            t_recipe += t_linear

            if target < sp:  # Cooling segment
                # Target for natural cooling calculation capped at cool_down_stop_temp
                effective_target = max(target, cool_down_stop_temp)

                if sp <= t_ambient or sp <= effective_target:
                    t_actual += t_linear
                else:
                    sp_clamped = max(sp, t_ambient + MIN_DELTA)
                    target_clamped = max(effective_target, t_ambient + MIN_DELTA)

                    if sp_clamped > target_clamped:
                        temp_ratio = (target_clamped - t_ambient) / (sp_clamped - t_ambient)
                        t_natural = -half_life_min * math.log2(temp_ratio)
                    else:
                        t_natural = 0.0

                    t_actual += max(t_linear, t_natural)
            else:  # Heating segment
                t_actual += t_linear

            sp = target

        elif typ == "time-limited":
            t_seg = seg.get("time", 0.0)
            t_recipe += t_seg
            t_actual += t_seg
            sp = seg.get("target", sp)

        elif typ == "hold":
            t_seg = seg.get("time", 0.0)
            t_recipe += t_seg
            t_actual += t_seg

    return round(t_recipe, 2), round(t_actual, 2)

def validate_profile(profile: dict):
    """Validate temperature thresholds and rates against hardware limits."""
    config = load_app_config()
    limits_cfg = config.get("limits", {})
    max_temp = limits_cfg.get("max_temp", 1200.0)
    min_rate = limits_cfg.get("min_rate", -6.5)
    max_rate = limits_cfg.get("max_rate", 6.7)
    continuous_limit = max_temp - 100.0
    warnings = []

    if profile.get("start_temperature", 25.0) > max_temp:
        raise ValueError(f"Start temperature ({profile['start_temperature']} °C) exceeds absolute limit ({max_temp} °C)")

    if profile.get("start_temperature", 25.0) > continuous_limit:
        warnings.append(
            f"Warning: Start temperature ({profile['start_temperature']:.1f} °C) is within 100 °C of the maximum limit."
        )

    current_sp = profile.get("start_temperature", 25.0)

    for i, segment in enumerate(profile.get("segments", []), start=1):
        typ = segment["type"]

        if typ not in SEGMENT_TYPES:
            raise ValueError(f"Segment {i}: unknown type '{typ}'")

        if typ in ("rate-limited", "time-limited"):
            target = segment["target"]
            if target > max_temp:
                raise ValueError(f"Segment {i}: target {target} °C exceeds max limit ({max_temp} °C)")
            if target > continuous_limit:
                warnings.append(f"Warning: Segment {i} target ({target:.1f} °C) is above continuous limit ({continuous_limit:.1f} °C).")

        if typ == "rate-limited":
            rate = segment["rate"]
            if rate == 0:
                raise ValueError(f"Segment {i}: rate cannot be 0")
            if rate > 0 and rate > max_rate:
                raise ValueError(f"Segment {i}: heating rate {rate} °C/min exceeds maximum limit of {max_rate} °C/min")
            elif rate < 0 and rate < min_rate:
                raise ValueError(f"Segment {i}: cooling rate {rate} °C/min exceeds limit of {min_rate} °C/min")
            current_sp = segment["target"]

        elif typ == "time-limited":
            time_duration = segment.get("time", 0.0)
            if time_duration <= 0:
                raise ValueError(f"Segment {i}: time duration must be greater than 0")
            target = segment["target"]
            calculated_rate = (target - current_sp) / time_duration
            if calculated_rate > 0 and calculated_rate > max_rate:
                raise ValueError(f"Segment {i}: rate ({calculated_rate:.2f} °C/min) exceeds limit of {max_rate} °C/min")
            elif calculated_rate < 0 and calculated_rate < min_rate:
                raise ValueError(f"Segment {i}: cooling rate ({calculated_rate:.2f} °C/min) exceeds limit of {min_rate} °C/min")
            current_sp = target

        elif typ == "hold":
            if "time" in segment and segment["time"] < 0:
                raise ValueError(f"Segment {i}: hold time cannot be negative")

    if current_sp >= 50.0:
        warnings.append(f"Warning: Final temperature is {current_sp:.1f} °C. Recommended to end below 50 °C.")

    return warnings

def generate_profiles(profile: dict, config: dict = None):
    """Generate setpoint profile coordinates, simulated physical temperature curve, annotations, and segment timelines."""
    if config is None:
        config = load_app_config()

    limits = config.get("limits", {})
    t_ambient = limits.get("t_ambient", 30.0)

    # Determine decay rate k (in min^-1)
    if "decay_rate_h1" in limits and limits["decay_rate_h1"] > 0:
        k_min = limits["decay_rate_h1"] / 60.0
    elif "half_life_h" in limits:
        k_min = math.log(2) / (limits["half_life_h"] * 60.0)
    else:
        half_life_min = limits.get("half_life_min", 127.66)
        k_min = math.log(2) / half_life_min

    max_heating_rate = limits.get("max_rate", 6.7)  # °C/min

    start_temp = profile.get("start_temperature", 25.0)
    sp_time, sp_temp = [0.0], [start_temp]
    annotations, segment_info = [], []

    # Simulation lists (time in minutes)
    sim_time_min = [0.0]
    sim_temp = [start_temp]

    t_min = 0.0
    sp = start_temp
    curr_sim_temp = start_temp
    dt = 0.5  # simulation step in minutes (~30s)

    def simulate_step(target_sp: float, max_rate: float, duration_min: float):
        nonlocal t_min, curr_sim_temp
        elapsed = 0.0
        while elapsed < duration_min:
            step = min(dt, duration_min - elapsed)
            elapsed += step
            t_min += step

            if target_sp > curr_sim_temp:
                # Heating phase: follows commanded profile rate capped by hardware max_rate
                rate = min(max_rate, (target_sp - curr_sim_temp) / step) if step > 0 else max_rate
                curr_sim_temp += rate * step
            else:
                # Cooling phase: natural Newton cooling vs commanded rate
                natural_cooling_rate = k_min * (curr_sim_temp - t_ambient)
                curr_sim_temp -= natural_cooling_rate * step
                if curr_sim_temp < target_sp:
                    curr_sim_temp = target_sp

            sim_time_min.append(t_min)
            sim_temp.append(curr_sim_temp)

    for segment in profile.get("segments", []):
        segment_start_h = t_min / 60.0
        typ = segment["type"]
        title = segment.get("title", typ)

        if typ == "rate-limited":
            target = segment["target"]
            rate = segment["rate"]
            duration_min = abs(target - sp) / abs(rate) if rate != 0 else 0.0
            start_sp = sp

            simulate_step(target, abs(rate), duration_min)

            sp = target
            t_h = t_min / 60.0
            duration_h = duration_min / 60.0

            sp_time.append(t_h)
            sp_temp.append(sp)
            annotations.append({
                "x": (segment_start_h + t_h) / 2.0,
                "y": (start_sp + sp) / 2.0,
                "text": f"{title}<br>{duration_h:.2f} h | {rate:+.2f} °C/min",
            })

        elif typ == "time-limited":
            target = segment["target"]
            duration_min = segment.get("time", 0.0)
            calculated_rate_min = (target - sp) / duration_min if duration_min > 0 else 0.0
            start_sp = sp

            simulate_step(target, abs(calculated_rate_min), duration_min)

            sp = target
            t_h = t_min / 60.0
            duration_h = duration_min / 60.0

            sp_time.append(t_h)
            sp_temp.append(sp)
            annotations.append({
                "x": (segment_start_h + t_h) / 2.0,
                "y": (start_sp + sp) / 2.0,
                "text": f"{title}<br>{duration_h:.2f} h | {calculated_rate_min:+.2f} °C/min",
            })

        elif typ == "hold":
            hold_time_min = segment.get("time", 0.0)
            start_sp = sp

            simulate_step(sp, max_heating_rate, hold_time_min)

            t_h = t_min / 60.0
            hold_time_h = hold_time_min / 60.0

            sp_time.append(t_h)
            sp_temp.append(sp)
            if hold_time_min > 0:
                annotations.append({
                    "x": (segment_start_h + t_h) / 2.0,
                    "y": start_sp,
                    "text": f"{title}<br>{hold_time_h:.2f} h",
                })

        segment_info.append({"start": segment_start_h, "end": t_min / 60.0, "title": title})

    sim_time_h = [t / 60.0 for t in sim_time_min]

    return sp_time, sp_temp, sim_time_h, sim_temp, annotations, segment_info


def plot_profile_plotly(sp_time, sp_temp, sim_time_h, sim_temp, annotations, segment_info):
    """Build and return an interactive Plotly figure comparing Setpoint and Simulated Temp."""
    fig = go.Figure()
    colors = [
        "rgba(31, 119, 180, 0.12)", "rgba(255, 127, 14, 0.12)",
        "rgba(44, 160, 44, 0.12)", "rgba(214, 39, 40, 0.12)",
        "rgba(148, 103, 189, 0.12)", "rgba(140, 86, 75, 0.12)",
    ]

    for i, segment in enumerate(segment_info):
        fig.add_vrect(
            x0=segment["start"], x1=segment["end"],
            fillcolor=colors[i % len(colors)],
            layer="below", line_width=0,
            annotation_text=segment["title"],
            annotation_position="top",
            annotation_font_size=10
        )

    # Simulated Physical Temperature: Dashed line
    fig.add_trace(go.Scatter(
        x=sim_time_h, y=sim_temp,
        mode='lines',
        name='Simulated Temp',
        line=dict(color='#d62728', width=2.5, dash='dash')
    ))

    # Commanded Setpoint Target: Plain (Solid line)
    fig.add_trace(go.Scatter(
        x=sp_time, y=sp_temp,
        mode='lines+markers',
        name='Setpoint Target',
        line=dict(color='#1f77b4', width=2)
    ))



    for ann in annotations:
        fig.add_annotation(
            x=ann["x"], y=ann["y"], text=ann["text"],
            showarrow=True, arrowhead=2, arrowsize=1, arrowwidth=1,
            ax=0, ay=-35, font=dict(size=10)
        )

    fig.update_layout(
        xaxis_title="Time (h)",
        yaxis_title="Temperature (°C)",
        hovermode="x unified",
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
        margin=dict(l=40, r=40, t=50, b=40),
        height=550
    )
    return fig