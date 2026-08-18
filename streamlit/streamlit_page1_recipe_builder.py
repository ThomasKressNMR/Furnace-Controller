#!/usr/bin/env python3
"""
Streamlit tool to build a furnace temperature profile (JSON), validate it,
and plot the setpoint curve with segment annotations in hours (slopes in °C/min).

Run with:
    streamlit run temperature_profile_app.py
"""

import copy
import json
import uuid
from pathlib import Path

import plotly.graph_objects as go
import streamlit as st
from profile_utils import (
    CONFIG_FILE_PATH,
    PARAM_FILE_PATH,
    SEGMENT_TYPES,
    calculate_profile_times,
    generate_profiles,
    load_app_config,
    plot_profile_plotly,
    update_config_key,
    validate_profile,
)

PARAM_FILE_PATH = Path("param.json")
CONFIG_FILE_PATH = Path("config.json")
SEGMENT_TYPES = ["hold", "rate-limited", "time-limited"]
DEFAULT_COOL_DOWN_STOP_TEMP = 100.0

# ----------------------------------------------------------------------
# Config & Limits Loading
# ----------------------------------------------------------------------

def load_config():
    if CONFIG_FILE_PATH.exists():
        with open(CONFIG_FILE_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}

config = load_config()

limits_cfg = config.get("limits", {})
MAX_TEMP = limits_cfg.get("max_temp", 1200.0)
MIN_RATE = limits_cfg.get("min_rate", -6.5)
MAX_RATE = limits_cfg.get("max_rate", 6.7)
MEASUREMENT = limits_cfg.get("measurement", "TS1-1200")

# Continuous operation threshold (100°C below absolute max)
CONTINUOUS_TEMP_LIMIT = MAX_TEMP - 100.0


# ----------------------------------------------------------------------
# State Initialization
# ----------------------------------------------------------------------

def load_default_profile() -> dict:
    """Load default profile strictly from param.json or create fallback dict."""
    if PARAM_FILE_PATH.exists():
        try:
            with open(PARAM_FILE_PATH, "r", encoding="utf-8") as f:
                p = json.load(f)
                p.setdefault("cool_down_stop_temp", DEFAULT_COOL_DOWN_STOP_TEMP)
                return p
        except Exception as e:
            st.error(f"Failed to load `{PARAM_FILE_PATH}`: {e}")
            st.stop()

    return {
        "start_temperature": 25.0,
        "cool_down_stop_temp": DEFAULT_COOL_DOWN_STOP_TEMP,
        "segments": []
    }


st.set_page_config(page_title="Temperature Profile Builder", layout="wide")
st.title("Furnace Temperature Profile Builder")

app_config = load_app_config()

if "folder_path" not in st.session_state:
    st.session_state.folder_path = app_config.get("default_folder_path", ".")

if "filename_input" not in st.session_state:
    st.session_state.filename_input = app_config.get("last_file", "profile.json")

if "profile" not in st.session_state:
    target_dir = Path(st.session_state.folder_path)
    last_file_path = target_dir / st.session_state.filename_input

    if last_file_path.exists() and last_file_path.is_file():
        try:
            with open(last_file_path, "r", encoding="utf-8") as f:
                st.session_state.profile = json.load(f)
        except Exception:
            st.session_state.profile = load_default_profile()
    else:
        st.session_state.profile = load_default_profile()

profile = st.session_state.profile
profile.setdefault("cool_down_stop_temp", DEFAULT_COOL_DOWN_STOP_TEMP)


# ----------------------------------------------------------------------
# Helper Callbacks
# ----------------------------------------------------------------------

def list_json_files(folder_path: Path) -> list[str]:
    if not folder_path.exists() or not folder_path.is_dir():
        return []
    return sorted([f.name for f in folder_path.glob("*.json")])


def on_select_file():
    selected = st.session_state.get("file_select_key")
    target_dir_str = st.session_state.get("folder_path", ".")
    target_dir = Path(target_dir_str)

    if selected and target_dir.exists():
        file_path = target_dir / selected
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                st.session_state.profile = json.load(f)
            st.session_state.filename_input = selected
            st.session_state.upload_status = ("success", f"Loaded `{selected}` successfully!")
            update_config_key(last_file=selected)
        except Exception as e:
            st.session_state.upload_status = ("error", f"Failed to load `{selected}`: {e}")


def on_folder_path_change():
    current_path = st.session_state.get("folder_path", ".")
    update_config_key(default_folder_path=current_path)


# ----------------------------------------------------------------------
# Sidebar Controls
# ----------------------------------------------------------------------

with st.sidebar:
    st.header("File Operations")

    target_dir_str = st.text_input(
        "Folder Path",
        key="folder_path",
        on_change=on_folder_path_change
    )
    target_dir = Path(target_dir_str)

    if not target_dir.exists():
        st.error(f"Directory `{target_dir_str}` does not exist.")
    elif not target_dir.is_dir():
        st.error(f"`{target_dir_str}` is not a valid directory.")
    else:
        json_files = list_json_files(target_dir)

        if json_files:
            current_index = 0
            if st.session_state.filename_input in json_files:
                current_index = json_files.index(st.session_state.filename_input)

            st.selectbox(
                "Select JSON Profile",
                options=json_files,
                index=current_index,
                key="file_select_key",
                on_change=on_select_file,
            )
        else:
            st.info("No `.json` files found in this folder.")

    if "upload_status" in st.session_state:
        status_type, msg = st.session_state.upload_status
        if status_type == "success":
            st.success(msg)
        elif status_type == "error":
            st.error(msg)
        del st.session_state.upload_status

    st.divider()
    st.header("Recipe Parameters")

    profile["start_temperature"] = st.number_input(
        "Start temp (°C)",
        value=float(profile.get("start_temperature", 25.0))
    )


    st.subheader("Segments")

    segments = profile.setdefault("segments", [])

    for seg in segments:
        if "_id" not in seg:
            seg["_id"] = str(uuid.uuid4())

    for i, seg in enumerate(segments):
        seg_id = seg["_id"]

        with st.expander(f"{i + 1}. {seg.get('title', seg['type'])} ({seg['type']})", expanded=False):
            seg["title"] = st.text_input("Title", value=seg.get("title", ""), key=f"title_{seg_id}")

            type_idx = SEGMENT_TYPES.index(seg["type"]) if seg["type"] in SEGMENT_TYPES else 0
            seg["type"] = st.selectbox(
                "Type",
                SEGMENT_TYPES,
                index=type_idx,
                key=f"type_{seg_id}",
            )

            typ = seg["type"]

            if typ == "rate-limited":
                seg["target"] = st.number_input(
                    "Target temp (°C)",
                    value=float(seg.get("target", profile["start_temperature"])),
                    key=f"target_{seg_id}",
                )
                seg["rate"] = st.number_input(
                    "Rate (°C/min)",
                    value=float(seg.get("rate", 1.0)),
                    key=f"rate_{seg_id}",
                )
                seg.pop("time", None)

            elif typ == "time-limited":
                seg["target"] = st.number_input(
                    "Target temp (°C)",
                    value=float(seg.get("target", profile["start_temperature"])),
                    key=f"target_{seg_id}",
                )
                seg["time"] = st.number_input(
                    "Ramp time (min)",
                    value=float(seg.get("time", 10.0)),
                    min_value=0.01,
                    key=f"time_{seg_id}",
                )
                seg.pop("rate", None)

            elif typ == "hold":
                seg["time"] = st.number_input(
                    "Hold time (min)",
                    value=float(seg.get("time", 0.0)),
                    min_value=0.0,
                    key=f"time_{seg_id}",
                )
                seg.pop("target", None)
                seg.pop("rate", None)

            b_col1, b_col2 = st.columns(2)
            if b_col1.button("Move Up", key=f"up_{seg_id}", disabled=(i == 0), use_container_width=True):
                segments[i - 1], segments[i] = segments[i], segments[i - 1]
                st.rerun()
            if b_col2.button("Move Down", key=f"down_{seg_id}", disabled=(i == len(segments) - 1),
                             use_container_width=True):
                segments[i + 1], segments[i] = segments[i], segments[i + 1]
                st.rerun()

            b_col3, b_col4 = st.columns(2)
            if b_col3.button("Duplicate", key=f"dup_{seg_id}", use_container_width=True):
                dup_seg = copy.deepcopy(seg)
                dup_seg["_id"] = str(uuid.uuid4())
                segments.insert(i + 1, dup_seg)
                st.rerun()
            if b_col4.button("Delete", key=f"del_{seg_id}", use_container_width=True):
                segments.pop(i)
                st.rerun()

    if st.button("Add Segment", use_container_width=True):
        segments.append({
            "_id": str(uuid.uuid4()),
            "title": "New segment",
            "type": "hold",
            "time": 0.0,
        })
        st.rerun()

    profile["cool_down_stop_temp"] = st.number_input(
        "Cool Stop temp (°C)",
        value=float(profile.get("cool_down_stop_temp", DEFAULT_COOL_DOWN_STOP_TEMP)),
        min_value=0.0,
        max_value=MAX_TEMP
    )

    st.divider()
    filename = st.text_input("Save File Name", key="filename_input")
    if not filename.endswith(".json"):
        filename += ".json"

    # Calculate profile times using the recipe's cool_down_stop_temp
    recipe_time, actual_time = calculate_profile_times(profile, config)
    profile["recipe_time_min"] = recipe_time
    profile["estimated_total_time_min"] = actual_time

    profile.pop("total_experiment_time_min", None)

    clean_profile = copy.deepcopy(profile)
    for seg in clean_profile.get("segments", []):
        seg.pop("_id", None)

    st.caption(f"⏱️ Recipe Time: {recipe_time:.1f} min ({recipe_time / 60:.2f} h)")
    st.caption(f"🔥 Est. Total Time: {actual_time:.1f} min ({actual_time / 60:.2f} h)")

    profile_json = json.dumps(clean_profile, indent=2)

    s_col1, s_col2 = st.columns(2)
    with s_col1:
        if st.button("Save", use_container_width=True):
            if not target_dir.exists() or not target_dir.is_dir():
                st.error("Cannot save: target directory is invalid.")
            else:
                save_path = target_dir / filename
                try:
                    with open(save_path, "w", encoding="utf-8") as f:
                        f.write(profile_json)

                    update_config_key(last_file=filename)
                    st.success(f"Saved to `{save_path}`!")
                    st.rerun()
                except Exception as e:
                    st.error(f"Save failed: {e}")

    with s_col2:
        st.download_button(
            label="Download",
            data=profile_json,
            file_name=filename,
            mime="application/json",
            use_container_width=True
        )

# ----------------------------------------------------------------------
# Main Dashboard Section
# ----------------------------------------------------------------------

include_cooldown = st.sidebar.checkbox(
    "Plot natural cool-down to limit",
    value=True,
    help="Extends the simulation past the final segment down to cool_down_stop_temp."
)

try:
    warnings = validate_profile(profile)
    for warning_msg in warnings:
        st.warning(warning_msg)
except (ValueError, KeyError) as e:
    st.error(f"Invalid profile: {e}")
else:
    sp_time, sp_temp, sim_time_h, sim_temp, annotations, segment_info = generate_profiles(
        profile,
        config=config,
        include_cool_down=include_cooldown
    )

    cool_stop_temp = profile.get("cool_down_stop_temp", DEFAULT_COOL_DOWN_STOP_TEMP)

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

st.divider()

st.subheader("Profile JSON")
st.json(profile_json, expanded=False)