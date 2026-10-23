import math
import os

import requests
from flask import Flask, jsonify, request


app = Flask(__name__)
CORE_COMMAND_URL = os.environ.get("CORE_COMMAND_URL", "http://edgex-core-command:59882").rstrip("/")
FLEX_ASSET_PARAM_PATHS = {
    device: {
        resource: os.environ.get(
            f"{device.upper()}_{suffix}_PATH",
            f"/api/v3/device/name/{device}/{resource}",
        )
        for suffix, resource in (
            ("MAX_CHARGING_POWER", "BatteryMaxChargingPower"),
            ("MAX_DISCHARGING_POWER", "BatteryMaxDischargingPower"),
            ("CAPACITY", "BatteryCapacity"),
            ("SOC_MIN", "BatterySOC_Min"),
            ("SOC_MAX", "BatterySOC_Max")
        )
    }
    for device in ("Battery", "EVC")
}

RT_ACTIVE_POWER_PATHS= {
    device: {
        "ActivePower": os.environ.get(
            f"{device.upper()}_ACTIVE_POWER_PATH",
            f"/api/v3/device/name/{device}/ActivePower",
        )
    }
    for device in ("Battery", "EVC", "PV", "Load")
}

SOC_PATHS = {
    device: os.environ.get(
        f"{device.upper()}_SOC_PATH",
        f"/api/v3/device/name/{device}/BatterySOC",
    )
    for device in ("Battery", "EVC")
}

for device in RT_ACTIVE_POWER_PATHS:
    resources = {
        **FLEX_ASSET_PARAM_PATHS.get(device, {}),
        **RT_ACTIVE_POWER_PATHS[device],
        **({"BatterySOC": SOC_PATHS[device]} if device in SOC_PATHS else {}),
    }
    for resource, path in resources.items():
        if not path.startswith("/") or path.startswith("//"):
            raise ValueError(f"{device}/{resource} path must start with a single '/'")


def read_core_command_value(path, resource):
    response = requests.get(f"{CORE_COMMAND_URL}{path}", timeout=10)
    response.raise_for_status()
    readings = response.json()["event"]["readings"]
    reading = next(item for item in readings if item["resourceName"] == resource)
    return float(reading["value"])


def calculate_asset_bounds(parameters, soc, delta_t_hours):
    capacity = parameters["BatteryCapacity"]
    charging = parameters["BatteryMaxChargingPower"]
    discharging = parameters["BatteryMaxDischargingPower"]
    soc_min = parameters["BatterySOC_Min"]
    soc_max = parameters["BatterySOC_Max"]
    if any(
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(value)
        or value < 0
        for value in (capacity, charging, discharging, soc_min, soc_max)
    ):
        raise ValueError("Capacity and power limits must be finite and nonnegative")
    if not math.isfinite(soc) or not 0 <= soc <= 1:
        raise ValueError("SOC must be between 0 and 1")

    lower = -min(discharging, (soc-soc_min) * capacity / delta_t_hours)
    upper = min(charging, (soc_max - soc) * capacity / delta_t_hours)
    return lower, upper


@app.get("/api/v1/flexibility-range")
def read_flexibility_range():
    try:
        delta_t_seconds = float(request.args["delta_t_seconds"])
        delta_t_hours = delta_t_seconds / 3600
        if not math.isfinite(delta_t_seconds) or delta_t_hours <= 0:
            raise ValueError("Invalid duration")
    except (KeyError, ValueError, OverflowError):
        return jsonify(error="delta_t_seconds must be a finite positive number"), 400

    parameters = app.config.get("FLEX_PARAMETERS")
    if parameters is None:
        return jsonify(
            error="Read /api/v1/flexdevices/capacityparameters before requesting flexibility"
        ), 503

    try:
        lower = upper = 0.0
        for device, path in SOC_PATHS.items():
            soc = read_core_command_value(path, "BatterySOC")
            asset_lower, asset_upper = calculate_asset_bounds(
                parameters[device], soc, delta_t_hours
            )
            lower += asset_lower
            upper += asset_upper

        load = read_core_command_value(RT_ACTIVE_POWER_PATHS["Load"]["ActivePower"], "ActivePower")
        pv = read_core_command_value(RT_ACTIVE_POWER_PATHS["PV"]["ActivePower"], "ActivePower")
        evc= read_core_command_value(RT_ACTIVE_POWER_PATHS["EVC"]["ActivePower"], "ActivePower")
        bat = read_core_command_value(RT_ACTIVE_POWER_PATHS["Battery"]["ActivePower"], "ActivePower")
        inflexible = load - pv
        current_net= load - pv + evc + bat
        lower += inflexible
        upper += inflexible
        if not all(math.isfinite(value) for value in (load, pv, lower, upper)):
            raise ValueError("Power and bounds must be finite")
    except requests.exceptions.HTTPError:
        return jsonify(error="Core Command rejected the request"), 502
    except requests.exceptions.JSONDecodeError:
        return jsonify(error="Core Command returned an invalid reading"), 502
    except requests.exceptions.RequestException:
        return jsonify(error="Core Command is unavailable"), 503
    except (KeyError, ValueError, TypeError, StopIteration, OverflowError):
        return jsonify(error="Invalid flexibility parameters or Core Command reading"), 502

    return jsonify(hems_ub=upper, hems_lb=lower, current_net=current_net)


@app.get("/api/v1/flexdevices/capacityparameters")
def read_parameters():
    snapshot = {}
    try:
        for device, resources in FLEX_ASSET_PARAM_PATHS.items():
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

    app.config["FLEX_PARAMETERS"] = snapshot
    return jsonify(snapshot)

@app.get("/api/v1/flexdevices/activepower")
def read_active_power():
    snapshot = {}
    try:
        for device, resources in RT_ACTIVE_POWER_PATHS.items():
            if "ActivePower" in resources:
                path = resources["ActivePower"]
                value = read_core_command_value(path, "ActivePower")
                if not math.isfinite(value):
                    raise ValueError("reading must be finite")
                snapshot[device] = {"ActivePower": value}
    except requests.exceptions.HTTPError:
        return jsonify(error="Core Command rejected the request"), 502
    except requests.exceptions.JSONDecodeError:
        return jsonify(error="Core Command returned an invalid reading"), 502
    except requests.exceptions.RequestException:
        return jsonify(error="Core Command is unavailable"), 503
    except (KeyError, ValueError, TypeError, StopIteration, OverflowError):
        return jsonify(error="Core Command returned an invalid reading"), 502

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