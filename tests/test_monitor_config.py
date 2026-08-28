from __future__ import annotations

import os
import sys
import tempfile
import unittest
from dataclasses import FrozenInstanceError
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))


class MonitorConfigLoadingTests(unittest.TestCase):
    def test_load_defaults_to_a_standalone_role(self):
        """Removing the local default role would make a fresh install ambiguous."""
        from monitor_config import MonitorConfig

        config = MonitorConfig.load(path=Path("does-not-exist.toml"), environ={})

        self.assertEqual("standalone", config.daemon.role)
        self.assertEqual("monitor-ai.local", config.device.host)
        self.assertTrue(config.transport.prefer_websocket)

    def test_config_path_uses_platform_user_configuration_directories(self):
        """Putting config beside the checkout would lose settings after an update."""
        from monitor_config import config_path

        with patch("monitor_config.sys.platform", "win32"), \
             patch.dict(os.environ, {"APPDATA": r"C:\\Users\\Ada\\AppData\\Roaming"}, clear=True):
            self.assertEqual(Path(r"C:\\Users\\Ada\\AppData\\Roaming") / "monitor-ai" / "monitor.toml",
                             config_path())
        with patch("monitor_config.sys.platform", "linux"), \
             patch.dict(os.environ, {"XDG_CONFIG_HOME": "/tmp/config"}, clear=True):
            self.assertEqual(Path("/tmp/config/monitor-ai/monitor.toml"), config_path())
        with patch("monitor_config.sys.platform", "darwin"):
            self.assertEqual(Path.home() / "Library" / "Application Support" /
                             "monitor-ai" / "monitor.toml", config_path())

    def test_load_parses_all_nested_toml_settings_into_frozen_types(self):
        """Ignoring a TOML section would make a configured daemon run with unsafe defaults."""
        from monitor_config import MonitorConfig

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "monitor.toml"
            path.write_text("""
[daemon]
role = "aggregator"
interval_s = 3.5
timezone = "UTC"
[device]
host = "display.lan"
port = 8080
id = "desk-a"
[storage]
database_path = "state/monitor.db"
retention_days = 14
hourly_retention_days = 90
[node]
id = "office"
[transport]
api_token = "toml-token"
prefer_websocket = false
timeout_s = 9.5
[usage]
claude_context_window = 200000
claude_5h_budget = 500000
[alerts]
warning_after_s = 60
critical_after_s = 180
snooze_minutes = 30
[service]
enabled = true
""", encoding="utf-8")

            config = MonitorConfig.load(path, environ={})

        self.assertEqual("aggregator", config.daemon.role)
        self.assertEqual(3.5, config.daemon.interval_s)
        self.assertEqual("display.lan", config.device.host)
        self.assertEqual(8080, config.device.port)
        self.assertEqual(Path(tmp) / "state" / "monitor.db", config.storage.database_path)
        self.assertEqual(90, config.storage.hourly_retention_days)
        self.assertEqual("office", config.node.id)
        self.assertEqual("toml-token", config.transport.api_token)
        self.assertFalse(config.transport.prefer_websocket)
        self.assertEqual(200000, config.usage.claude_context_window)
        self.assertEqual(30, config.alerts.snooze_minutes)
        self.assertTrue(config.service.enabled)
        with self.assertRaises(FrozenInstanceError):
            config.device.host = "other.lan"

    def test_environment_secret_overrides_toml_without_overriding_operations(self):
        """A shell-injected token must win without making deployment settings non-reproducible."""
        from monitor_config import MonitorConfig

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "monitor.toml"
            path.write_text("""
[device]
host = "configured.lan"
[transport]
api_token = "toml-secret"
""", encoding="utf-8")
            config = MonitorConfig.load(path, environ={
                "MONITOR_API_TOKEN": "environment-secret",
                "MONITOR_DEVICE_HOST": "ignored.lan",
            })

        self.assertEqual("environment-secret", config.transport.api_token)
        self.assertEqual("configured.lan", config.device.host)

    def test_load_rejects_invalid_runtime_values(self):
        """Accepting invalid roles, ports, or alert order would fail later inside the daemon."""
        from monitor_config import MonitorConfig

        cases = (
            ("[daemon]\nrole = 'peer'", "daemon.role"),
            ("[device]\nport = 0", "device.port"),
            ("[alerts]\nwarning_after_s = 120\ncritical_after_s = 60", "critical_after_s"),
            ("[transport]\ntimeout_s = 0", "transport.timeout_s"),
        )
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "monitor.toml"
            for contents, message in cases:
                with self.subTest(contents=contents):
                    path.write_text(contents, encoding="utf-8")
                    with self.assertRaisesRegex(ValueError, message):
                        MonitorConfig.load(path, environ={})

    def test_load_reports_invalid_string_types_as_configuration_errors(self):
        """An invalid TOML type must not escape as an AttributeError during startup."""
        from monitor_config import MonitorConfig

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "monitor.toml"
            path.write_text("[daemon]\ntimezone = 42", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "daemon.timezone"):
                MonitorConfig.load(path, environ={})

    def test_redacted_dict_never_exposes_a_configured_token(self):
        """Returning the token from config show or doctor would leak credentials to logs."""
        from monitor_config import MonitorConfig

        config = MonitorConfig.load(path=Path("does-not-exist.toml"), environ={
            "MONITOR_API_TOKEN": "test-fixture-token",
        })
        redacted = config.redacted_dict()

        self.assertEqual("***redacted***", redacted["transport"]["api_token"])
        self.assertNotIn("test-fixture-token", repr(redacted))
        self.assertEqual("monitor-ai.local", redacted["device"]["host"])

    def test_write_example_contains_no_secret_and_is_private(self):
        """An example config containing credentials or broad permissions would leak on shared hosts."""
        from monitor_config import write_example

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "nested" / "monitor.toml"
            write_example(path)
            contents = path.read_text(encoding="utf-8")
            mode = path.stat().st_mode

        self.assertIn("[daemon]", contents)
        self.assertIn('api_token = ""', contents)
        self.assertNotIn("test-fixture-token", contents)
        if os.name != "nt":
            self.assertEqual(0, mode & 0o077)


if __name__ == "__main__":
    unittest.main()
