import math
import os

import requests
from flask import Flask, jsonify, request


app = Flask(__name__)
CORE_COMMAND_URL = os.environ.get("CORE_COMMAND_URL", "http://edgex-core-command:59882").rstrip("/")


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
        response = requests.get(
            f"{CORE_COMMAND_URL}/api/v3/device/name/{device}/{resource}", timeout=10
        )
        response.raise_for_status()
        readings = response.json()["event"]["readings"]
        reading = next(item for item in readings if item["resourceName"] == resource)
        value = float(reading["value"])
    except requests.exceptions.HTTPError as error:
        status = 404 if error.response.status_code == 404 else 502
        return jsonify(error="Core Command rejected the request"), status
    except requests.exceptions.RequestException:
        return jsonify(error="Core Command is unavailable"), 503
    except (KeyError, ValueError, TypeError, StopIteration):
        return jsonify(error="Core Command returned an invalid reading"), 502

    return jsonify(device=device, resource=resource, value=value)