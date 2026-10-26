import os
import time
import math
import requests
from datetime import datetime
from urllib.parse import urlsplit


TRAFO_SENSOR_P_READ_PATH = os.getenv("TRAFO_SENSOR_P_READ_PATH", "")
HEMS_FLEX_READ_PATH = os.getenv("HEMS_FLEX_READ_PATH", "")
CONTROL_REFRESH_INTERVAL_SECONDS = int(os.getenv("CONTROL_REFRESH_INTERVAL_SECONDS", "60"))
TRANSFORMER_LIMIT = float(os.getenv("TRANSFORMER_LIMIT", "0.0"))


def read_load_sensor():
    """Read load factor sensor."""
    try:
        print(f"Reading transformer factor from {TRAFO_SENSOR_P_READ_PATH}...")
        load_response = requests.get(TRAFO_SENSOR_P_READ_PATH, timeout=10)
        load_response.raise_for_status()
        
        if "application/json" in load_response.headers.get("Content-Type", "").lower():
            payload = load_response.json()
            rt_load = _extract_edgex_reading_value(payload)
            return rt_load
        else:
            raise ValueError("Response is not JSON")
    except Exception as e:
        print(f"Error reading load: {e}")
        raise

def read_hems_flex():
    print(f"Reading HEMS flexibility from {HEMS_FLEX_READ_PATH}...")
    response = requests.get(HEMS_FLEX_READ_PATH, timeout=10)
    response.raise_for_status()
    if "application/json" not in response.headers.get("Content-Type", "").lower():
        raise ValueError("HEMS response is not JSON")

    payload = response.json()
    readings = payload["event"]["readings"]
    reading = next(
        (item for item in readings if item["resourceName"] == "flexibility-range"),
        None,
    )
    if reading is None or not isinstance(reading.get("objectValue"), dict):
        raise ValueError("HEMS response has no flexibility-range Object reading")
    return reading["objectValue"]


def read_hems_parameters():
    payload = read_hems_flex()
    values = []
    for name in ("current_net", "hems_ub", "hems_lb"):
        value = payload[name]
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
            raise ValueError(f"HEMS {name} must be a finite number")
        values.append(float(value))
    return tuple(values)

def _extract_edgex_reading_value(payload):
    """Extract the first reading value from an EdgeX event payload."""
    reading = payload["event"]["readings"][0]

    if "value" in reading:
        return float(reading["value"])

    if "objectValue" in reading and "Value" in reading["objectValue"]:
        return float(reading["objectValue"]["Value"])

    raise ValueError("Unsupported EdgeX reading payload structure")

def _read_edgex_parameter(path, parameter_name):
    """Read a single numeric parameter from an EdgeX REST endpoint."""
    try:
        print(f"Reading {parameter_name} from {path}...")
        response = requests.get(path, timeout=10)
        response.raise_for_status()

        if "application/json" not in response.headers.get("Content-Type", "").lower():
            raise ValueError("Response is not JSON")

        payload = response.json()
        return _extract_edgex_reading_value(payload)
    except Exception as e:
        print(f"Error reading {parameter_name}: {e}")
        raise


def run_control_algorithm(rt_load, load_target, hems_p_now,hems_p_ub, hems_p_lb):
    
    load_without_hems=rt_load - hems_p_now

    if load_without_hems==load_target:
        p_ref=0
    elif load_without_hems>load_target:
        surplus=load_target-load_without_hems
        p_ref=max(surplus,hems_p_lb)
    else:
        deficit=load_target-load_without_hems
        p_ref=min(deficit,hems_p_ub)

    return p_ref

def main():
    url = urlsplit(HEMS_FLEX_READ_PATH)
    if url.scheme not in ("http", "https") or not url.netloc:
        raise ValueError("HEMS_FLEX_READ_PATH must be an absolute HTTP(S) URL")
    if CONTROL_REFRESH_INTERVAL_SECONDS <= 0:
        raise ValueError("CONTROL_REFRESH_INTERVAL_SECONDS must be positive")

    print("Starting miniflex...")
    next_read_time = time.monotonic()
    while True:
        print(f"HEMS reading at {datetime.now().isoformat()}")
        try:
            hems_p_now, hems_p_ub, hems_p_lb = read_hems_parameters()
            print("HEMS p_now:", hems_p_now)
            print("HEMS p_ub:", hems_p_ub)
            print("HEMS p_lb:", hems_p_lb)
            # if TRAFO_SENSOR_P_READ_PATH:
            #     rt_load_trafo = read_load_sensor()
            #     p_ref = run_control_algorithm(
            #         rt_load_trafo, TRANSFORMER_LIMIT, hems_p_now, hems_p_ub, hems_p_lb
            #     )
            #     print("HEMS p_ref:", p_ref)
        except (requests.RequestException, ValueError, KeyError, TypeError, OverflowError) as error:
            print(f"Miniflex cycle failed; retrying at the next interval: {error}")

        next_read_time += CONTROL_REFRESH_INTERVAL_SECONDS
        current_time = time.monotonic()
        if next_read_time <= current_time:
            next_read_time = current_time + CONTROL_REFRESH_INTERVAL_SECONDS
        time.sleep(next_read_time - current_time)
        

if __name__ == "__main__":
    main()