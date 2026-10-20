import math
import os

import requests
from flask import Flask, jsonify, request


app = Flask(__name__)
CORE_COMMAND_URL = os.environ.get("CORE_COMMAND_URL", "http://edgex-core-command:59882").rstrip("/")
DEVICE_READ_PATHS = {
    device: {
        resource: os.environ.get(
            f"{device.upper()}_{suffix}_PATH",
            f"/api/v3/device/name/{device}/{resource}",
        )
        for suffix, resource in (
            ("MAX_CHARGING_POWER", "BatteryMaxChargingPower"),
            ("MAX_DISCHARGING_POWER", "BatteryMaxDischargingPower"),
            ("CAPACITY", "BatteryCapacity"),
        )
    }
    for device in ("Battery", "EVC")
}


def read_core_command_value(path, resource):
    response = requests.get(f"{CORE_COMMAND_URL}{path}", timeout=10)
    response.raise_for_status()
    readings = response.json()["event"]["readings"]
    reading = next(item for item in readings if item["resourceName"] == resource)
    return float(reading["value"])


def create_app():
    """Validate configured paths without contacting Core Command."""
    for device, resources in DEVICE_READ_PATHS.items():
        for resource, path in resources.items():
            if not path.startswith("/") or path.startswith("//"):
                raise ValueError(f"{device}/{resource} path must start with a single '/'")
    return app


@app.get("/api/v1/devices/readings")
def read_device_values():
    snapshot = {}
    try:
        for device, resources in DEVICE_READ_PATHS.items():
            snapshot[device] = {}
            for resource, path in resources.items():
                value = read_core_command_value(path, resource)
                if not math.isfinite(value):
                    raise ValueError("reading must be finite")
                snapshot[device][resource] = value
    except requests.exceptions.HTTPError:
        return jsonify(error="Core Command rejected the request"), 502
    except requests.exceptions.JSONDecodeError:
        return jsonify(error="Core Command returned an invalid reading"), 502
    except requests.exceptions.RequestException:
        return jsonify(error="Core Command is unavailable"), 503
    except (KeyError, ValueError, TypeError, StopIteration, OverflowError):
        return jsonify(error="Core Command returned an invalid reading"), 502

    app.config["DEVICE_READINGS"] = snapshot
    return jsonify(snapshot)


@app.post("/api/v1/flexibility-requests")
def receive_flexibility_request():
    payload = request.get_json(silent=True)
    value = payload.get("activePowerReco") if isinstance(payload, dict) else None
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        return jsonify(error="activePowerReco must be a finite number"), 400

    try:
        response = requests.put(
            f"{CORE_COMMAND_URL}/api/v3/device/name/Battery/ActivePowerSetpoint",
            json={"ActivePowerSetpoint": value},
            timeout=10,
        )
        response.raise_for_status()
    except requests.exceptions.HTTPError:
        return jsonify(error="Core Command rejected the request"), 502
    except requests.exceptions.RequestException:
        return jsonify(error="Core Command is unavailable"), 503

    return jsonify(device="Battery", resource="ActivePowerSetpoint", value=value)


@app.get("/api/v1/devices/<device>/<resource>")
def read_resource(device, resource):
    try:
        value = read_core_command_value(
            f"/api/v3/device/name/{device}/{resource}", resource
        )
    except requests.exceptions.HTTPError as error:
        status = 404 if error.response.status_code == 404 else 502
        return jsonify(error="Core Command rejected the request"), status
    except requests.exceptions.RequestException:
        return jsonify(error="Core Command is unavailable"), 503
    except (KeyError, ValueError, TypeError, StopIteration):
        return jsonify(error="Core Command returned an invalid reading"), 502

    return jsonify(device=device, resource=resource, value=value)