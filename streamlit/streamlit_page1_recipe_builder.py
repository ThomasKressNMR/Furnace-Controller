#!/usr/bin/env python3
"""
Streamlit tool to build a furnace temperature profile (JSON), validate it,
and plot the setpoint curve with segment annotations in hours (slopes in °C/min).

Run with:
    streamlit run temperature_profile_app.py
"""

import copy
import json
from pathlib import Path

import plotly.graph_objects as go
import streamlit as st

import copy
import json
from pathlib import Path

import streamlit as st
from profile_utils import (
    CONFIG_FILE_PATH,
    PARAM_FILE_PATH,
    SEGMENT_TYPES,
    calculate_total_time_min,
    generate_profiles,
    load_app_config,
    plot_profile_plotly,
    update_config_key,
    validate_profile,
)

PARAM_FILE_PATH = Path("param.json")
CONFIG_FILE_PATH = Path("config.json")
SEGMENT_TYPES = ["hold", "rate-limited", "time-limited"]

# ----------------------------------------------------------------------
# Hardcoded Hard & Operating Limits
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
# Config & State Initialization
# ----------------------------------------------------------------------


def load_default_profile() -> dict:
    """Load default profile strictly from param.json or create fallback dict."""
    if PARAM_FILE_PATH.exists():
        try:
            with open(PARAM_FILE_PATH, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            st.error(f"Failed to load `{PARAM_FILE_PATH}`: {e}")
            st.stop()

    # Fallback default structure if param.json doesn't exist yet
    return {
        "start_temperature": 25.0,
        "segments": []
    }


st.set_page_config(page_title="Temperature Profile Builder", layout="wide")
st.title("Furnace Temperature Profile Builder")

# Load configuration on startup
app_config = load_app_config()

if "folder_path" not in st.session_state:
    st.session_state.folder_path = app_config.get("default_folder_path", ".")

if "filename_input" not in st.session_state:
    st.session_state.filename_input = app_config.get("last_file", "profile.json")

# On initial load, attempt to load the last selected file from target directory
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


# ----------------------------------------------------------------------
# Helper Functions & Callbacks
# ----------------------------------------------------------------------

def list_json_files(folder_path: Path) -> list[str]:
    """Return a sorted list of .json file names in the target directory."""
    if not folder_path.exists() or not folder_path.is_dir():
        return []
    return sorted([f.name for f in folder_path.glob("*.json")])


def on_select_file():
    """Triggered automatically when a file selection changes in the selectbox."""
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

            # Update ONLY the last_file key in config.json
            update_config_key(last_file=selected)
        except Exception as e:
            st.session_state.upload_status = ("error", f"Failed to load `{selected}`: {e}")


def on_folder_path_change():
    """Save updated folder path to config.json when modified by the user."""
    current_path = st.session_state.get("folder_path", ".")

    # Update ONLY the default_folder_path key in config.json
    update_config_key(default_folder_path=current_path)

# ----------------------------------------------------------------------
# Core logic (validation + generation)
# ----------------------------------------------------------------------



# ----------------------------------------------------------------------
# Sidebar Controls
# ----------------------------------------------------------------------

with st.sidebar:
    st.header("File Operations")

    # Folder Path input triggers automatic save to config.json when edited
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
    st.header("Segments")

    profile["start_temperature"] = st.number_input(
        "Start temperature (°C)", value=float(profile.get("start_temperature", 25.0))
    )

    segments = profile.setdefault("segments", [])

    for i, seg in enumerate(segments):
        with st.expander(f"{i + 1}. {seg.get('title', seg['type'])} ({seg['type']})", expanded=False):
            seg["title"] = st.text_input("Title", value=seg.get("title", ""), key=f"title_{i}")
            seg["type"] = st.selectbox(
                "Type", SEGMENT_TYPES,
                index=SEGMENT_TYPES.index(seg["type"]) if seg["type"] in SEGMENT_TYPES else 0,
                key=f"type_{i}",
            )

            typ = seg["type"]

            if typ == "rate-limited":
                seg["target"] = st.number_input(
                    "Target temp (°C)",
                    value=float(seg.get("target", profile["start_temperature"])),
                    key=f"target_{i}",
                )
                seg["rate"] = st.number_input(
                    "Rate (°C/min)",
                    value=float(seg.get("rate", 1.0)),
                    key=f"rate_{i}",
                )
                seg.pop("time", None)

            elif typ == "time-limited":
                seg["target"] = st.number_input(
                    "Target temp (°C)",
                    value=float(seg.get("target", profile["start_temperature"])),
                    key=f"target_{i}",
                )
                seg["time"] = st.number_input(
                    "Ramp time (min)",
                    value=float(seg.get("time", 10.0)),
                    min_value=0.01,
                    key=f"time_{i}",
                )
                seg.pop("rate", None)

            elif typ == "hold":
                seg["time"] = st.number_input(
                    "Hold time (min)",
                    value=float(seg.get("time", 0.0)),
                    min_value=0.0,
                    key=f"time_{i}",
                )
                seg.pop("target", None)
                seg.pop("rate", None)

            # Reorganization buttons
            b_col1, b_col2 = st.columns(2)
            if b_col1.button("Move Up", key=f"up_{i}", disabled=(i == 0), width='stretch'):
                segments[i - 1], segments[i] = segments[i], segments[i - 1]
                st.rerun()
            if b_col2.button("Move Down", key=f"down_{i}", disabled=(i == len(segments) - 1), width='stretch'):
                segments[i + 1], segments[i] = segments[i], segments[i + 1]
                st.rerun()

            b_col3, b_col4 = st.columns(2)
            if b_col3.button("Duplicate", key=f"dup_{i}", width='stretch'):
                segments.insert(i + 1, copy.deepcopy(seg))
                st.rerun()
            if b_col4.button("Delete", key=f"del_{i}", width='stretch'):
                segments.pop(i)
                st.rerun()

    if st.button("Add Segment", width='stretch'):
        segments.append({
            "title": "New segment",
            "type": "hold",
            "time": 0.0,
        })
        st.rerun()

    st.divider()
    filename = st.text_input("Save File Name", key="filename_input")
    if not filename.endswith(".json"):
        filename += ".json"

    # Compute total experiment duration before dumping to JSON
    profile["total_experiment_time_min"] = calculate_total_time_min(profile)

    profile_json = json.dumps(profile, indent=2)

    s_col1, s_col2 = st.columns(2)
    with s_col1:
        if st.button("Save", width='stretch'):
            if not target_dir.exists() or not target_dir.is_dir():
                st.error("Cannot save: target directory is invalid.")
            else:
                save_path = target_dir / filename
                try:
                    with open(save_path, "w", encoding="utf-8") as f:
                        f.write(profile_json)

                    # Update config with current folder and saved file name
                    print(filename, target_dir)
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
            width='stretch'
        )

# ----------------------------------------------------------------------
# Main Dashboard Section
# ----------------------------------------------------------------------

try:
    warnings = validate_profile(profile)
    for warning_msg in warnings:
        st.warning(warning_msg)
except (ValueError, KeyError) as e:
    st.error(f"Invalid profile: {e}")
else:
    results = generate_profiles(profile)
    fig = plot_profile_plotly(*results)
    st.plotly_chart(fig, width='stretch')

st.divider()

st.subheader("Profile JSON")
st.json(profile_json, expanded=False)