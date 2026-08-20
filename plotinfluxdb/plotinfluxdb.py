import os
import matplotlib.pyplot as plt
import pandas as pd
from dotenv import load_dotenv
from influxdb_client import InfluxDBClient

load_dotenv()

URL = os.getenv("INFLUX_URL")
TOKEN = os.getenv("INFLUX_TOKEN")
ORG = os.getenv("INFLUX_ORG")
BUCKET = os.getenv("INFLUX_BUCKET", "").strip(' "')

START_TIME = "2026-08-19T08:00:00Z"
STOP_TIME = "2026-08-20T08:00:00Z"
AGGREGATION_WINDOW = "1m"

# START_TIME = "2026-08-19T11:30:00Z"
# STOP_TIME =  "2026-08-19T13:00:00Z"
# AGGREGATION_WINDOW = "2s"

# Plot display mode: Choose "hours" (relative elapsed time) or "calendar" (UTC timestamps)
PLOT_MODE = "hours"

# Map raw InfluxDB field names to display labels
FIELD_MAP = {
    "furnace_setpoint": "Setpoint (°C)",
    "furnace_temperature": "Furnace Temp (°C)",
    "sample_temperature": "Sample Temp (°C)",
}

print(f"Executing Flux range: {START_TIME} to {STOP_TIME}")

query = f'''
from(bucket: "{BUCKET}")
  |> range(start: {START_TIME}, stop: {STOP_TIME})
  |> filter(fn: (r) => r["_measurement"] == "TS1-1200")
  |> filter(fn: (r) => r["_field"] == "furnace_setpoint" or r["_field"] == "furnace_temperature" or r["_field"] == "sample_temperature")
  |> aggregateWindow(every: {AGGREGATION_WINDOW}, fn: mean, createEmpty: false)
  |> pivot(rowKey:["_time"], columnKey: ["_field"], valueColumn: "_value")
'''

with InfluxDBClient(url=URL, token=TOKEN, org=ORG) as client:
    df = client.query_api().query_data_frame(query)

if isinstance(df, list):
    df = pd.concat(df, ignore_index=True)

if df.empty:
    print("No data returned for the specified time range.")
else:
    df["_time"] = pd.to_datetime(df["_time"])

    plt.figure(figsize=(6, 5))

    if PLOT_MODE == "hours":
        # Calculate relative elapsed time from t0
        start_point = df["_time"].min()
        df["x_axis"] = (df["_time"] - start_point).dt.total_seconds() / 3600.0
        x_col = "x_axis"
        x_label = "Time / hours"
    else:
        x_col = "_time"
        x_label = "Time (UTC)"
        plt.xticks(rotation=45)

    # Plot each mapped field if present in DataFrame
    for raw_field, display_label in FIELD_MAP.items():
        if raw_field in df.columns:
            plt.plot(df[x_col], df[raw_field], label=display_label)

    plt.title("Furnace Temperature Profile")
    plt.xlabel(x_label)
    plt.ylabel("Temperature / ºC")
    plt.legend()
    plt.grid(True)
    plt.tight_layout()
    plt.show()