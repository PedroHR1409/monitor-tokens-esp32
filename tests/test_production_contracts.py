from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class ProductionContractsTests(unittest.TestCase):
    def test_secret_scanner_detects_a_leak_without_printing_secret(self):
        scanner = ROOT / "tools" / "check_secrets.py"
        self.assertTrue(scanner.is_file(), "falta tools/check_secrets.py")
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            (repo / "include").mkdir()
            secret = "private-test-value-8391"
            (repo / "include" / "secrets.h").write_text(
                '#define WIFI_PASSWORD "{}"\n'.format(secret), encoding="utf-8")
            (repo / "leak.txt").write_text(secret, encoding="utf-8")
            result = subprocess.run(
                [sys.executable, str(scanner), "--root", str(repo)],
                text=True, capture_output=True, check=False)
        self.assertNotEqual(0, result.returncode)
        self.assertNotIn(secret, result.stdout + result.stderr)
        self.assertIn("leak.txt", result.stdout + result.stderr)

    def test_versionable_secrets_example_exists(self):
        example = ROOT / "include" / "secrets.example.h"
        self.assertTrue(example.is_file())
        text = example.read_text(encoding="utf-8") if example.is_file() else ""
        self.assertIn("WIFI_SSID", text)
        self.assertIn("WIFI_PASSWORD", text)
        self.assertIn("MONITOR_API_TOKEN", text)

    def test_default_build_does_not_enable_demo_data(self):
        config = (ROOT / "include" / "config.h").read_text(encoding="utf-8")
        self.assertNotIn("#define USE_MOCK_DATA     1", config)
        self.assertIn("MONITOR_DEMO_DATA", config)

        platformio = (ROOT / "platformio.ini").read_text(encoding="utf-8")
        self.assertIn("default_envs = esp32-s3-3v5-lcd", platformio)
        default_section = platformio.split("[env:esp32-s3-3v5-lcd]", 1)[1].split(
            "[env:esp32-s3-3v5-lcd-demo]", 1
        )[0]
        self.assertNotIn("-DMONITOR_DEMO_DATA=1", default_section)

    def test_runtime_logs_do_not_print_wifi_identifier(self):
        transport = (ROOT / "src" / "sessions" / "session_transport.cpp").read_text(encoding="utf-8")
        self.assertNotIn('WiFi \'%s\'', transport)

    def test_touch_callbacks_cache_rendered_ids_instead_of_trusting_slots(self):
        ui = (ROOT / "src" / "ui" / "ui_dashboard.cpp").read_text(encoding="utf-8")
        self.assertIn("g_cardRenderedId", ui)
        self.assertIn("g_pickerRenderedId", ui)
        self.assertIn("find_session_by_id(selectedId)", ui)

    def test_mutating_http_routes_require_token_size_limit_and_payload_epoch(self):
        transport = (ROOT / "src" / "sessions" / "session_transport.cpp").read_text(encoding="utf-8")
        daemon = (ROOT / "tools" / "session_daemon.py").read_text(encoding="utf-8")
        self.assertIn("constant_time_token_match", transport)
        self.assertIn("HTTP_MAX_BODY_BYTES", transport)
        self.assertIn("generated_at_epoch", transport)
        self.assertIn("X-Monitor-Token", daemon)


if __name__ == "__main__":
    unittest.main()
