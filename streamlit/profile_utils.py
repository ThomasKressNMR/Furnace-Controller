from __future__ import annotations

import json
from pathlib import Path
import plotly.graph_objects as go
import streamlit as st

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


def calculate_total_time_min(profile: dict) -> float:
    """Calculate the total duration of the profile in minutes."""
    sp = profile.get("start_temperature", 25.0)
    t_min = 0.0

    for seg in profile.get("segments", []):
        typ = seg.get("type")
        if typ == "rate-limited":
            target = seg.get("target", sp)
            rate = seg.get("rate", 0.0)
            if rate != 0:
                t_min += abs(target - sp) / abs(rate)
            sp = target
        elif typ == "time-limited":
            t_min += seg.get("time", 0.0)
            sp = seg.get("target", sp)
        elif typ == "hold":
            t_min += seg.get("time", 0.0)

    return round(t_min, 2)


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


def generate_profiles(profile: dict):
    """Generate profile coordinates, annotations, and segment timelines."""
    start_temp = profile.get("start_temperature", 25.0)
    sp_time, sp_temp = [0.0], [start_temp]
    annotations, segment_info = [], []
    t_min = 0.0
    sp = start_temp

    for segment in profile.get("segments", []):
        segment_start_h = t_min / 60.0
        typ = segment["type"]
        title = segment.get("title", typ)

        if typ == "rate-limited":
            target = segment["target"]
            rate = segment["rate"]
            duration_min = abs(target - sp) / abs(rate) if rate != 0 else 0.0
            start_sp = sp
            t_min += duration_min
            t_h = t_min / 60.0
            duration_h = duration_min / 60.0
            sp = target

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
            t_min += duration_min
            t_h = t_min / 60.0
            duration_h = duration_min / 60.0
            sp = target

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
            t_min += hold_time_min
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

    return sp_time, sp_temp, annotations, segment_info


def plot_profile_plotly(sp_time, sp_temp, annotations, segment_info):
    """Build and return an interactive Plotly figure."""
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

    fig.add_trace(go.Scatter(
        x=sp_time, y=sp_temp,
        mode='lines+markers',
        name='Setpoint',
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