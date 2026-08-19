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

pages = [
    st.Page("streamlit_page1_recipe_builder.py", title="🧪  Furnace Recipe Builder"),
    st.Page("streamlit_page2_main.py", title="🎛️  Furnace Control Panel"),
    st.Page("streamlit_page3_gasflow.py", title="💨 Gas flow calculator"),

]


pg = st.navigation(pages)
pg.run()