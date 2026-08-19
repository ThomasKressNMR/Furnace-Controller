import json
import numpy as np
import plotly.graph_objects as go
import streamlit as st

# Set page layout
st.set_page_config(page_title="Gas Flow & Velocity", layout="wide")


# ============================================================
# CONFIGURATION & CONSTANTS
# ============================================================
# Default fallback values in case config loading fails
CONFIG_DEFAULTS = {
    "max_temp": 1200.0,
    "max_flow": 2.0,
}


def load_config():
    """Load limits from config.json or fall back to default values."""
    try:
        with open("config.json", "r") as f:
            data = json.load(f)
            max_temp = float(
                data.get("limits", {}).get(
                    "max_temp", CONFIG_DEFAULTS["max_temp"]
                )
            )
            max_flow = float(
                data.get("gas", {}).get(
                    "max_flow_rate_lmp_RT", CONFIG_DEFAULTS["max_flow"]
                )
            )
            return max_temp, max_flow
    except (FileNotFoundError, json.JSONDecodeError, KeyError, ValueError):
        return CONFIG_DEFAULTS["max_temp"], CONFIG_DEFAULTS["max_flow"]


MAX_TEMP, MAX_FLOW = load_config()

T0_C = 25.0
molecular_mass = {
    "Nitrogen": 28.0134,
    "Air": 28.97,
    "Oxygen": 31.998,
    "Argon": 39.948,
}
M_air = molecular_mass["Air"]

# ============================================================
# SIDEBAR: INPUT PARAMETERS
# ============================================================
with st.sidebar:
    st.header("Parameters")

    gas = st.selectbox("Select Gas", list(molecular_mass.keys()), index=0)
    diameter_mm = st.number_input(
        "Tube Internal Diameter [mm]", min_value=1.0, value=60.0, step=1.0
    )

    st.divider()
    st.subheader("Point Calculation Target")
    target_flow = st.number_input(
        "Flow Reading [L/min]",
        min_value=0.0,
        max_value=MAX_FLOW,
        value=min(1.0, MAX_FLOW),
        step=0.05,
    )
    target_temp = st.number_input(
        "Temperature [°C]",
        min_value=0.0,
        max_value=MAX_TEMP,
        value=min(1000.0, MAX_TEMP),
        step=10.0,
    )

# ============================================================
# CORE CALCULATIONS
# ============================================================
M_gas = molecular_mass[gas]
correction_factor = np.sqrt(M_air / M_gas)

# Specific Point Calculation
D = diameter_mm / 1000.0
T0 = T0_C + 273.15

Q_gas_target_L_min = target_flow * correction_factor
Q0_target = Q_gas_target_L_min * 1e-3 / 60.0
T_target = target_temp + 273.15
Q_actual_target = Q0_target * (T_target / T0)
A_target = np.pi * D**2 / 4.0
velocity_target_cm_s = (Q_actual_target / A_target) * 100.0

# Dynamic Grid Calculation driven by config limits
flow_meter = np.linspace(0.0, MAX_FLOW, 101)
temp_C = np.linspace(0.0, MAX_TEMP, 121)
T = temp_C + 273.15

Q_gas_L_min = flow_meter * correction_factor
Q0 = Q_gas_L_min * 1e-3 / 60.0
Q = Q0[None, :] * T[:, None] / T0
velocity_cm_s = (Q / A_target) * 100.0

# ============================================================
# MAIN INTERFACE
# ============================================================
st.title("Gas Flow & Velocity Calculator")
# Top Summary Cards (KPI Metrics Bar)
kpi1, kpi2, kpi3 = st.columns(3)

kpi1.metric("Selected Gas", gas, help=f"Molar Mass: {M_gas:.2f} g/mol")
kpi2.metric("Correction Factor", f"{correction_factor:.3f}")
kpi3.metric("Calculated Velocity", f"{velocity_target_cm_s:.2f} cm/s")

st.divider()

# Contour Plot Layout
fig = go.Figure(
    data=go.Contour(
        x=flow_meter,
        y=temp_C,
        z=velocity_cm_s,
        colorscale="Viridis",
        contours=dict(
            start=0,
            end=velocity_cm_s.max(),
            size=max(0.1, velocity_cm_s.max() / 20.0),  # Adaptive step size
            coloring="heatmap",
            showlabels=True,
            labelfont=dict(size=10, color="white"),
        ),
        colorbar=dict(title="Velocity [cm/s]"),
        hovertemplate=(
            "Flow Reading: %{x:.2f} L/min<br>"
            "Temperature: %{y:.0f} °C<br>"
            "Velocity: %{z:.2f} cm/s<extra></extra>"
        ),
    )
)

# Highlight selected target point on plot
fig.add_trace(
    go.Scatter(
        x=[target_flow],
        y=[target_temp],
        mode="markers",
        marker=dict(
            size=10, color="white", symbol="x", line=dict(width=2, color="black")
        ),
        name="Target Point",
        showlegend=False,
    )
)

fig.update_layout(
    xaxis=dict(
        title="Flow-meter reading [L/min air calibration]", range=[0, MAX_FLOW]
    ),
    yaxis=dict(title="Temperature [°C]", range=[0, MAX_TEMP]),
    margin=dict(l=20, r=20, t=20, b=20),
    height=500,
    template="plotly_white",
)

st.plotly_chart(fig, width='stretch')

# Collapsible Reference Section
with st.expander("Model Assumptions & Gas Data"):
    tab1, tab2 = st.tabs(["Equations & Assumptions", "Gas Correction Table"])

    with tab1:
        st.markdown(
            f"""
        - **Configured Plot Range:** 0 to {MAX_FLOW} L/min | 0 to {MAX_TEMP} °C
        - **Flow meter:** Variable-area rotameter calibrated for Air at 25 °C.
        - **Pressure:** Ideal gas assumption at constant atmospheric pressure.
        """
        )
        c1, c2, c3 = st.columns(3)
        with c1:
            st.latex(
                r"Q_{\mathrm{gas}} \approx Q_{\mathrm{air}}"
                r" \sqrt{\frac{M_{\mathrm{air}}}{M_{\mathrm{gas}}}}"
            )
        with c2:
            st.latex(r"Q(T) = Q(T_0) \frac{T}{T_0}")
        with c3:
            st.latex(r"v = \frac{4Q(T)}{\pi D^2}")

    with tab2:
        st.table(
            {
                "Gas": list(molecular_mass.keys()),
                "Molar Mass [g/mol]": list(molecular_mass.values()),
                "Correction Factor": [
                    np.sqrt(M_air / m) for m in molecular_mass.values()
                ],
            }
        )