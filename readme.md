```
git clone git@github.com:ThomasKressNMR/Furnace-Controller.git
```

# Arduino/ESP32
- Install the arduino IDE app
- Install ESP32 drivers (https://www.silabs.com/software-and-tools/usb-to-uart-bridge-vcp-drivers?tab=downloads)
- flash the ESP32 from Arduino IDE

# Docker
## Data source configuration (to be moved to deparment VM?)
- Install docker
- Install portainer (https://docs.portainer.io/start/install-ce/server/docker/linux). This will be helpful to manage docker scripts
- Install grafana+influx db:
```
cd ./Furnace-Controller/docker
docker compose up -d
```

## InfluxDB configuration:
In influxDB: http://localhost:8086/signin
The 'admin' default influxdb password will be shown in the influxdb log (access logs from portainer)
You need to create an access token to the 'Furnace' bucket: Go to `http://localhost:8086/orgs/982a311e8e2d5d51/load-data/tokens` and generte a new write/read access API token for Furnace
Save the token, and paste in ./streamlit/.env in the INFLUX_TOKEN field. The token will also be used in grafana.


## Grafana configuration
In grafana (http://0.0.0.0:3000)
The default grafana user/passord is admin/admin.

- Connection > Add new connection > InfluxDB
- Add new data source:
    Query language: Flux
    HTTP URL: http://influxdb:8086
    Disable Basic auth
    Organization: Forse
    Default Bucket: Furnace
    Token: The token you generated earlier

- Finally, create/import dashboard
The flux query is:
```
from(bucket: "Furnace")
  |> range(start: v.timeRangeStart, stop: v.timeRangeStop)
  |> filter(fn: (r) => r["_measurement"] == "TS1-1200")
  |> filter(fn: (r) => r["_field"] == "furnace_temperature" or r["_field"] == "furnace_setpoint" or r["_field"] == "sample_temperature")
  |> aggregateWindow(every: v.windowPeriod, fn: mean, createEmpty: false)
  |> yield(name: "mean")
```

# Python / app
## Conda
- Install miniconda and open anaconda prompt
- Create a conda environment: `conda create -n furnace python=3.14` (first time only)
- Activate environment: `conda activate furnace`
- Install python packages, whereever `requirements.txt` is located: `pip install -r requirements.txt`
- Open streamlit app: `cd streamlit`, then ``streamlit run main.py`
- For subsequent openings on Windows, this .bat file should work:
