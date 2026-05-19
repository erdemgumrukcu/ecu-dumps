import os
import time
import math
import requests
import base64
import json
from datetime import datetime


LOAD_SENSOR_READ_PATH = os.getenv("LOAD_SENSOR_READ_PATH", "{}")
HEMS_READ_PATH_P_NOW = os.getenv("HEMS_READ_PATH_P_NOW", "{}")
HEMS_READ_PATH_P_UB = os.getenv("HEMS_READ_PATH_P_UB", "{}")
HEMS_READ_PATH_P_LB = os.getenv("HEMS_READ_PATH_P_LB", "{}")
HEMS_WRITE_PATH_P_REF_OUTPUT = os.getenv("HEMS_WRITE_PATH_P_REF_OUTPUT", "{}")
CONTROL_REFRESH_INTERVAL_SECONDS = int(os.getenv("CONTROL_REFRESH_INTERVAL_SECONDS", "60"))
TRANSFORMER_LIMIT = float(os.getenv("TRANSFORMER_LIMIT", "100.0"))


def read_load_sensor():
    """Read load factor sensor."""
    try:
        print(f"Reading load factor from {LOAD_SENSOR_READ_PATH}...")
        load_response = requests.get(LOAD_SENSOR_READ_PATH, timeout=10)
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

def read_hems_parameters():
    """Read HEMS parameters p_now, p_ub, and p_lb."""
    hems_p_now = _read_edgex_parameter(HEMS_READ_PATH_P_NOW, "hems_p_now")
    hems_p_ub = _read_edgex_parameter(HEMS_READ_PATH_P_UB, "hems_p_ub")
    hems_p_lb = _read_edgex_parameter(HEMS_READ_PATH_P_LB, "hems_p_lb")
    return hems_p_now, hems_p_ub, hems_p_lb

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
    
    print("Starting thermal state estimation application...")
    print()

    # Wait until the next minute starts with 00 seconds
    now = datetime.now()
    seconds_to_wait = 60 - now.second
    if seconds_to_wait < 60:
        print(f"Waiting {seconds_to_wait} seconds to synchronize to HH/MM/00...")
        time.sleep(seconds_to_wait)
    print()
    
    # Set the next reading time
    next_read_time = time.time() + CONTROL_REFRESH_INTERVAL_SECONDS
    
    while True:
   
        timestamp = datetime.now().isoformat()

        # Verify sensor data can be read before running model. If sensor read fails, skip this cycle but keep trying in the next one.
        print(f"Sensor readings at {timestamp}")
        try:
            rt_load_trafo = read_load_sensor()
            realtime_sensor_data=True
            print("Load (kW):", rt_load_trafo)
        except Exception as e:
            realtime_sensor_data=False
            print(f"Error while reading sensor data: {e}")

        try:
            hems_p_now, hems_p_ub, hems_p_lb = read_hems_parameters()
            realtime_hems_data = True
            print("HEMS p_now:", hems_p_now)
            print("HEMS p_ub:", hems_p_ub)
            print("HEMS p_lb:", hems_p_lb)
        except Exception as e:
            realtime_hems_data = False
            print(f"Error while reading HEMS parameters: {e}")


        #Run model and write to database if we have both realtime sensor data and initialized state. If sensor read fails, skip this cycle but keep trying in the next one.
        if realtime_sensor_data and realtime_hems_data:
            print("Control algorithm...")            
            p_ref=run_control_algorithm(rt_load_trafo, TRANSFORMER_LIMIT, hems_p_now,hems_p_ub, hems_p_lb)
            print("HEMS p_ref:", p_ref)
        else:
            print("Using old data.")
        print()

        # Calculate how long to sleep to maintain exact state estimation intervals
        current_time = time.time()
        sleep_time = next_read_time - current_time

        # Set the next reading time
        next_read_time += CONTROL_REFRESH_INTERVAL_SECONDS
        
        if sleep_time > 0:
            time.sleep(sleep_time)
        

if __name__ == "__main__":
    main()