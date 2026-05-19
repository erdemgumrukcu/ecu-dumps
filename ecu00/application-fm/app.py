import os
import time
import math
import requests
import base64
import json
from datetime import datetime

try:
    import psycopg2
    import psycopg2.extras
except ImportError:
    psycopg2 = None

LOAD_SENSOR_READ_PATH = os.getenv("LOAD_SENSOR_READ_PATH", "{}")
HEMS_READ_PATH_P_NOW = os.getenv("HEMS_READ_PATH_P_NOW", "{}")
HEMS_READ_PATH_P_UB = os.getenv("HEMS_READ_PATH_P_UB", "{}")
HEMS_READ_PATH_P_LB = os.getenv("HEMS_READ_PATH_P_LB", "{}")
HEMS_WRITE_PATH_P_REF_OUTPUT = os.getenv("HEMS_WRITE_PATH_P_REF_OUTPUT", "{}")
CONTROL_REFRESH_INTERVAL_SECONDS = int(os.getenv("CONTROL_REFRESH_INTERVAL_SECONDS", "60"))
CLOCK_SYNC_MAX_SKEW_SECONDS = float(os.getenv("CLOCK_SYNC_MAX_SKEW_SECONDS", "2.0"))

DB_HOST = os.getenv("DB_HOST", None)
DB_PORT = os.getenv("DB_PORT", "5432")
DB_NAME = os.getenv("DB_NAME", None)
DB_USER = os.getenv("DB_USER", None)
DB_PASSWORD = os.getenv("DB_PASSWORD", None)

TRANSFORMER_LIMIT_STATE = {
    "pow_limit": None,
}

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


def _read_trafo_limit_from_db():
    """Read TRAFO_LIMIT_STATE from the database."""
    if psycopg2 is None:
        print("psycopg2 not available. Skipping database read.")
        return None
    
    if not all([DB_HOST, DB_NAME, DB_USER, DB_PASSWORD]):
        return None
    
    try:
        conn = psycopg2.connect(
            host=DB_HOST,
            port=DB_PORT,
            database=DB_NAME,
            user=DB_USER,
            password=DB_PASSWORD
        )
    except Exception as e:
        print(f"Warning: Could not connect to database: {e}")
        return None
    
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
            cur.execute("SELECT pow_limit FROM trafo_limit_state ORDER BY id DESC LIMIT 1")
            row = cur.fetchone()
            if row:
                return {
                    "pow_limit": row["pow_limit"],
                }
        return None
    except Exception as e:
        print(f"Warning: Could not read trafo limit from database: {e}")
        return None
    finally:
        conn.close()


def _check_db_clock_sync():
    """Validate application clock against PostgreSQL clock at startup."""
    if psycopg2 is None:
        raise RuntimeError("psycopg2 not available. Cannot validate clock sync against database.")

    if not all([DB_HOST, DB_NAME, DB_USER, DB_PASSWORD]):
        raise RuntimeError("Database configuration missing. Cannot validate clock sync.")

    try:
        conn = psycopg2.connect(
            host=DB_HOST,
            port=DB_PORT,
            database=DB_NAME,
            user=DB_USER,
            password=DB_PASSWORD
        )
    except Exception as e:
        raise RuntimeError(f"Could not connect to database for clock check: {e}") from e

    try:
        with conn.cursor() as cur:
            cur.execute("SELECT EXTRACT(EPOCH FROM CURRENT_TIMESTAMP)")
            row = cur.fetchone()
            if row is None or row[0] is None:
                raise RuntimeError("Database clock check returned no timestamp.")

            db_epoch = float(row[0])
            app_epoch = time.time()
            skew_seconds = abs(app_epoch - db_epoch)

            print(
                "Clock sync check:",
                f"app_epoch={app_epoch:.3f}",
                f"db_epoch={db_epoch:.3f}",
                f"skew_seconds={skew_seconds:.3f}",
            )

            if skew_seconds > CLOCK_SYNC_MAX_SKEW_SECONDS:
                raise RuntimeError(
                    f"Clock skew too high between application and database: {skew_seconds:.3f}s "
                    f"(max allowed {CLOCK_SYNC_MAX_SKEW_SECONDS:.3f}s)."
                )

            print("Clock sync check passed.")
    finally:
        conn.close()

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

    _check_db_clock_sync()

    # Try to restore trafo limit from database; fall back to fresh state.
    db_state = _read_trafo_limit_from_db()
    if db_state is not None:
        print("Restored trafo limit from database.")
        print(db_state)
        TRANSFORMER_LIMIT_STATE.update(db_state)
    else:
        print("Starting with fresh trafo limit (no prior state in database).")
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

        # Verify trafo limit is initialized before running model
        if (TRANSFORMER_LIMIT_STATE["pow_limit"] is None):
            realtime_limit_data=False
            raise RuntimeError("Transformer limit not initialized. Cannot run estimation.")
        else:
            realtime_limit_data=True
            print("Transformer limit:",TRANSFORMER_LIMIT_STATE)

        #Run model and write to database if we have both realtime sensor data and initialized state. If sensor read fails, skip this cycle but keep trying in the next one.
        if realtime_sensor_data and realtime_limit_data and realtime_hems_data:
            print("Control algorithm...")            
            p_ref=run_control_algorithm(rt_load_trafo, TRANSFORMER_LIMIT_STATE["pow_limit"], hems_p_now,hems_p_ub, hems_p_lb)
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