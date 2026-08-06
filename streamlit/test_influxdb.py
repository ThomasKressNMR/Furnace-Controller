import os
import sys
from dotenv import load_dotenv
from influxdb_client import InfluxDBClient, Point
from influxdb_client.client.write_api import SYNCHRONOUS

# Load environment variables
load_dotenv()

url = os.getenv("INFLUX_URL")
token = os.getenv("INFLUX_TOKEN")
org = os.getenv("INFLUX_ORG")
# Strip quotes in case INFLUX_BUCKET="Furnace" retains them from the file
bucket = os.getenv("INFLUX_BUCKET", "").strip('"')


def test_influx_connection():
    print(f"Connecting to {url}...")
    client = InfluxDBClient(url=url, token=token, org=org)

    # 1. Health Check
    if not client.ping():
        print("❌ Server ping failed. Check your INFLUX_URL and service status.")
        sys.exit(1)
    print("✅ Server reachable.")

    # 2. Write Test
    write_api = client.write_api(write_options=SYNCHRONOUS)
    test_point = (
        Point("connection_test")
        .tag("location", "local")
        .field("status", 1.0)
    )

    try:
        write_api.write(bucket=bucket, record=test_point)
        print(f"✅ Write successful! Data written to bucket: '{bucket}'.")
    except Exception as e:
        print(f"❌ Write failed: {e}")
        client.close()
        sys.exit(1)

    # 3. Query Test
    query_api = client.query_api()
    flux_query = f'''
    from(bucket: "{bucket}")
        |> range(start: -1m)
        |> filter(fn: (r) => r._measurement == "connection_test")
    '''

    try:
        result = query_api.query(query=flux_query)
        records_found = 0
        for table in result:
            for record in table.records:
                records_found += 1
                print(f"✅ Read successful! Found record: {record.get_measurement()} = {record.get_value()}")

        if records_found == 0:
            print("⚠️ Connected and wrote, but query returned 0 records.")
    except Exception as e:
        print(f"❌ Query failed: {e}")
    finally:
        client.close()


if __name__ == "__main__":
    test_influx_connection()