import unittest
from unittest.mock import Mock, call, patch

import requests

import app


class RecommendationTests(unittest.TestCase):
    @patch.object(app.requests, "post")
    def test_posts_exact_payload_to_configured_url(self, post):
        with patch.object(app, "HEMS_FLEX_SET_PATH", "http://hems/flexibility-set"):
            app.send_hems_recommendation(-12.5)
        post.assert_called_once_with(
            "http://hems/flexibility-set",
            json={"activePowerReco": -12.5},
            timeout=10,
        )
        post.return_value.raise_for_status.assert_called_once_with()

    @patch.object(app.requests, "post")
    def test_rejects_invalid_recommendations(self, post):
        for value in (True, None, "12", float("nan"), float("inf"), -float("inf")):
            with self.subTest(value=value), self.assertRaises(ValueError):
                app.send_hems_recommendation(value)
        post.assert_not_called()

    @patch.object(app.requests, "post")
    def test_propagates_http_and_connection_errors(self, post):
        for error in (requests.HTTPError("rejected"), requests.Timeout("timed out")):
            with self.subTest(error=error), self.assertRaises(type(error)):
                post.reset_mock()
                post.side_effect = None
                post.return_value.raise_for_status.side_effect = None
                if isinstance(error, requests.HTTPError):
                    post.return_value.raise_for_status.side_effect = error
                else:
                    post.side_effect = error
                app.send_hems_recommendation(0)

    def test_cycle_posts_calculated_value_and_retries_after_failure(self):
        with (
            patch.object(app, "HEMS_FLEX_READ_PATH", "http://hems/read"),
            patch.object(app, "HEMS_FLEX_SET_PATH", "http://hems/set"),
            patch.object(app, "CONTROL_REFRESH_INTERVAL_SECONDS", 60),
            patch.object(app, "read_hems_parameters", return_value=(1, 10, -10)),
            patch.object(app, "read_load_sensor", return_value=5),
            patch.object(app, "run_control_algorithm", side_effect=[-3.0, 0.0]),
            patch.object(app.requests, "post") as post,
            patch.object(app.time, "monotonic", side_effect=[0, 1, 61]),
            patch.object(app.time, "sleep", side_effect=[None, KeyboardInterrupt]) as sleep,
            patch("builtins.print") as log,
        ):
            failed_response = Mock()
            failed_response.raise_for_status.side_effect = requests.HTTPError("rejected")
            post.side_effect = [failed_response, Mock()]
            with self.assertRaises(KeyboardInterrupt):
                app.main()
            self.assertEqual(post.call_args_list, [
                call("http://hems/set", json={"activePowerReco": -3.0}, timeout=10),
                call("http://hems/set", json={"activePowerReco": 0.0}, timeout=10),
            ])
            self.assertEqual(sleep.call_args_list, [call(59), call(59)])
            log.assert_any_call(
                "Miniflex cycle failed; retrying at the next interval: rejected"
            )

    @patch.object(app.requests, "post")
    def test_failed_read_does_not_post(self, post):
        with (
            patch.object(app, "HEMS_FLEX_READ_PATH", "http://hems/read"),
            patch.object(app, "HEMS_FLEX_SET_PATH", "http://hems/set"),
            patch.object(app, "read_hems_parameters", side_effect=ValueError("bad reading")),
            patch.object(app.time, "monotonic", side_effect=[0, 1]),
            patch.object(app.time, "sleep", side_effect=KeyboardInterrupt),
            patch("builtins.print"),
        ):
            with self.assertRaises(KeyboardInterrupt):
                app.main()
        post.assert_not_called()

    def test_invalid_set_url_fails_before_reading(self):
        for url in ("", "/relative", "ftp://hems/set"):
            with (
                self.subTest(url=url),
                patch.object(app, "HEMS_FLEX_READ_PATH", "http://hems/read"),
                patch.object(app, "HEMS_FLEX_SET_PATH", url),
                patch.object(app, "read_hems_parameters") as read,
                self.assertRaisesRegex(ValueError, "HEMS_FLEX_SET_PATH"),
            ):
                app.main()
            read.assert_not_called()


if __name__ == "__main__":
    unittest.main()
