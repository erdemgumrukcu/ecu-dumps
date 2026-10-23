import importlib.util
import os
from pathlib import Path
import unittest
from unittest.mock import Mock, call, patch

import requests


def load_app(environment=None):
    with patch.dict(os.environ, environment or {}, clear=True):
        spec = importlib.util.spec_from_file_location(
            "application_api", Path(__file__).with_name("app.py")
        )
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
    return module


def parameters(capacity=10.0, charging=5.0, discharging=4.0):
    return {
        "BatteryCapacity": capacity,
        "BatteryMaxChargingPower": charging,
        "BatteryMaxDischargingPower": discharging,
    }


class FlexibilityTests(unittest.TestCase):
    def setUp(self):
        self.module = load_app()
        self.module.app.config["TESTING"] = True
        self.parameters = {"Battery": parameters(), "EVC": parameters(50.0, 7.0, 6.0)}
        self.module.app.config["FLEX_PARAMETERS"] = self.parameters
        self.client = self.module.app.test_client()

    def test_power_limited_range_and_exact_response_shape(self):
        with patch.object(
            self.module, "read_core_command_value", side_effect=[0.5, 0.5, 4.0, 3.0]
        ) as read:
            response = self.client.get("/api/v1/flexibility-range?delta_t_seconds=900")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json, {"hems_ub": 13.0, "hems_lb": -9.0})
        self.assertEqual(read.call_args_list, [
            call("/api/v3/device/name/Battery/BatterySOC", "BatterySOC"),
            call("/api/v3/device/name/EVC/BatterySOC", "BatterySOC"),
            call("/api/v3/device/name/Load/ActivePower", "ActivePower"),
            call("/api/v3/device/name/PV/ActivePower", "ActivePower"),
        ])
        self.assertEqual(self.module.app.config["FLEX_PARAMETERS"], self.parameters)

    def test_energy_limited_and_asymmetric_bounds(self):
        with patch.object(
            self.module, "read_core_command_value", side_effect=[0.1, 0.99, 2.0, 5.0]
        ):
            response = self.client.get("/api/v1/flexibility-range?delta_t_seconds=3600")
        self.assertEqual(response.status_code, 200)
        self.assertAlmostEqual(response.json["hems_ub"], 2.5)
        self.assertAlmostEqual(response.json["hems_lb"], -10.0)

    def test_empty_full_and_zero_capacity_assets(self):
        calculate = self.module.calculate_asset_bounds
        self.assertEqual(calculate(parameters(), 0.0, 1.0), (0.0, 5.0))
        self.assertEqual(calculate(parameters(), 1.0, 1.0), (-4.0, 0.0))
        self.assertEqual(calculate(parameters(0.0), 0.5, 1.0), (0.0, 0.0))
        self.assertEqual(calculate(parameters(charging=0.0, discharging=0.0), 0.5, 1), (0, 0))

    def test_horizon_changes_energy_limited_range(self):
        for seconds, expected in ((3600, 1.0), (1800, 2.0)):
            with self.subTest(seconds=seconds):
                self.module.app.config["FLEX_PARAMETERS"] = {
                    "Battery": parameters(2.0, 10.0, 10.0),
                    "EVC": parameters(0.0),
                }
                with patch.object(
                    self.module, "read_core_command_value", side_effect=[0.5, 0.5, 0.0, 0.0]
                ):
                    response = self.client.get(
                        f"/api/v1/flexibility-range?delta_t_seconds={seconds}"
                    )
                self.assertEqual(response.json, {"hems_ub": expected, "hems_lb": -expected})

    def test_invalid_or_missing_duration(self):
        for query in ("", "?delta_t_seconds=", "?delta_t_seconds=abc",
                      "?delta_t_seconds=0", "?delta_t_seconds=-1",
                      "?delta_t_seconds=NaN", "?delta_t_seconds=Infinity",
                      "?delta_t_seconds=1e-323"):
            with self.subTest(query=query):
                with patch.object(self.module, "read_core_command_value") as read:
                    response = self.client.get("/api/v1/flexibility-range" + query)
                self.assertEqual(response.status_code, 400)
                read.assert_not_called()

    def test_missing_cache_is_explicit_and_does_not_fetch(self):
        del self.module.app.config["FLEX_PARAMETERS"]
        with patch.object(self.module, "read_core_command_value") as read:
            response = self.client.get("/api/v1/flexibility-range?delta_t_seconds=900")
        self.assertEqual(response.status_code, 503)
        self.assertIn("capacityparameters", response.json["error"])
        read.assert_not_called()

    def test_bad_soc_and_power_readings(self):
        for readings in (
            [-0.1], [1.1], [float("nan")], [float("inf")],
            [0.5, 0.5, float("nan"), 0.0],
            [0.5, 0.5, 0.0, float("inf")],
        ):
            with self.subTest(readings=readings):
                with patch.object(self.module, "read_core_command_value", side_effect=readings):
                    response = self.client.get("/api/v1/flexibility-range?delta_t_seconds=900")
                self.assertEqual(response.status_code, 502)
                self.assertIn("error", response.json)

    def test_bad_cached_parameters(self):
        for field in parameters():
            for value in (-1, float("nan"), float("inf"), "5", None, True):
                with self.subTest(field=field, value=value):
                    self.module.app.config["FLEX_PARAMETERS"] = {
                        "Battery": {**parameters(), field: value},
                        "EVC": parameters(),
                    }
                    with patch.object(self.module, "read_core_command_value", return_value=0.5):
                        response = self.client.get("/api/v1/flexibility-range?delta_t_seconds=900")
                    self.assertEqual(response.status_code, 502)

    def test_upstream_errors(self):
        for error, status in (
            (requests.exceptions.ConnectionError("offline"), 503),
            (requests.exceptions.Timeout("timeout"), 503),
            (requests.exceptions.HTTPError(response=Mock(status_code=404)), 502),
            (requests.exceptions.JSONDecodeError("invalid", "", 0), 502),
            (KeyError("event"), 502),
            (StopIteration(), 502),
        ):
            with self.subTest(error=error):
                with patch.object(self.module, "read_core_command_value", side_effect=error):
                    response = self.client.get("/api/v1/flexibility-range?delta_t_seconds=900")
                self.assertEqual(response.status_code, status)
                self.assertEqual(set(response.json), {"error"})

    def test_cache_population_and_live_refresh(self):
        del self.module.app.config["FLEX_PARAMETERS"]
        with patch.object(self.module, "read_core_command_value", side_effect=[
            5.0, 4.0, 10.0, 7.0, 6.0, 50.0,
        ]) as read:
            response = self.client.get("/api/v1/flexdevices/capacityparameters")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(read.call_count, 6)
        for soc, expected in ((0.0, {"hems_ub": 13.0, "hems_lb": 1.0}),
                              (1.0, {"hems_ub": 1.0, "hems_lb": -9.0})):
            with patch.object(
                self.module, "read_core_command_value", side_effect=[soc, soc, 4.0, 3.0]
            ):
                response = self.client.get("/api/v1/flexibility-range?delta_t_seconds=900")
            self.assertEqual(response.json, expected)

    def test_configured_paths_and_no_startup_reads(self):
        with patch("requests.get") as get:
            module = load_app({
                "BATTERY_SOC_PATH": "/custom/battery",
                "EVC_SOC_PATH": "/custom/ev",
                "LOAD_ACTIVE_POWER_PATH": "/custom/load",
                "PV_ACTIVE_POWER_PATH": "/custom/pv",
            })
        get.assert_not_called()
        module.app.config["FLEX_PARAMETERS"] = self.parameters
        with patch.object(
            module, "read_core_command_value", side_effect=[0.5, 0.5, 4.0, 3.0]
        ) as read:
            response = module.app.test_client().get("/api/v1/flexibility-range?delta_t_seconds=900")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(read.call_args_list, [
            call("/custom/battery", "BatterySOC"), call("/custom/ev", "BatterySOC"),
            call("/custom/load", "ActivePower"), call("/custom/pv", "ActivePower"),
        ])

    def test_existing_active_power_and_setpoint_endpoints(self):
        with patch.object(self.module, "read_core_command_value", return_value=3.0):
            response = self.client.get("/api/v1/flexdevices/activepower")
        self.assertEqual(response.json, {
            device: {"ActivePower": 3.0} for device in ("Battery", "EVC", "PV", "Load")
        })
        with patch.object(self.module.requests, "put") as put:
            response = self.client.post("/api/v1/flexibility-requests", json={"activePowerReco": 2.0})
        self.assertEqual(response.status_code, 200)
        put.assert_called_once()


if __name__ == "__main__":
    unittest.main()
