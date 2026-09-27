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

    def test_secret_scanner_ignores_a_broadcast_ssid(self):
        """Um SSID e publico (vai em beacon em claro); trata-lo como segredo acusava
        falso vazamento quando o nome da rede coincidia com o sobrenome do autor."""
        scanner = ROOT / "tools" / "check_secrets.py"
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            (repo / "include").mkdir()
            (repo / "include" / "secrets.h").write_text(
                '#define WIFI_SSID "broadcast-test-network"\n'
                '#define WIFI_PASSWORD "private-test-value-8391"\n', encoding="utf-8")
            (repo / "shared.md").write_text("broadcast-test-network", encoding="utf-8")
            result = subprocess.run(
                [sys.executable, str(scanner), "--root", str(repo)],
                text=True, capture_output=True, check=False)
        self.assertEqual(0, result.returncode)

    def test_secret_scanner_still_flags_a_password_even_after_dropping_ssid(self):
        scanner = ROOT / "tools" / "check_secrets.py"
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            (repo / "include").mkdir()
            secret = "private-test-value-8391"
            (repo / "include" / "secrets.h").write_text(
                '#define WIFI_PASSWORD_2 "{}"\n'.format(secret), encoding="utf-8")
            (repo / "shared.md").write_text(secret, encoding="utf-8")
            result = subprocess.run(
                [sys.executable, str(scanner), "--root", str(repo)],
                text=True, capture_output=True, check=False)
        self.assertNotEqual(0, result.returncode)
        self.assertNotIn(secret, result.stdout + result.stderr)

    def test_versionable_secrets_example_exists(self):
        example = ROOT / "include" / "secrets.example.h"
        self.assertTrue(example.is_file())
        text = example.read_text(encoding="utf-8") if example.is_file() else ""
        self.assertIn("WIFI_SSID", text)
        self.assertIn("WIFI_PASSWORD", text)
        self.assertIn("MONITOR_API_TOKEN", text)

    def test_secrets_example_declares_a_second_network(self):
        """O exemplo versionado e o contrato de formato das duas redes; sem as chaves
        _2, quem clona nao descobre que a alternancia existe."""
        example = ROOT / "include" / "secrets.example.h"
        text = example.read_text(encoding="utf-8") if example.is_file() else ""
        self.assertIn("WIFI_SSID_2", text)
        self.assertIn("WIFI_PASSWORD_2", text)

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

    def test_usage_widget_has_title_arrow_and_no_card_longpress(self):
        ui = (ROOT / "src" / "ui" / "ui_dashboard.cpp").read_text(encoding="utf-8")
        self.assertIn("CONSUMO DE TOKENS (EM MM)", ui)          # unidade no titulo
        self.assertIn("COL_X[USAGE_PROVIDERS] = {8, 82, 156, 230}", ui)  # podio 4 colunas
        self.assertIn("usage_arrow_cb", ui)                     # seta = unica via ao podio
        # long-press no card foi removido (podio agora e so pela seta)
        self.assertNotIn("usage_widget_toggle_cb, LV_EVENT_LONG_PRESSED", ui)

    def test_mutating_http_routes_require_token_size_limit_and_payload_epoch(self):
        transport = (ROOT / "src" / "sessions" / "session_transport.cpp").read_text(encoding="utf-8")
        daemon = (ROOT / "tools" / "session_daemon.py").read_text(encoding="utf-8")
        self.assertIn("constant_time_token_match", transport)
        self.assertIn("HTTP_MAX_BODY_BYTES", transport)
        self.assertIn("generated_at_epoch", transport)
        self.assertIn("X-Monitor-Token", daemon)


if __name__ == "__main__":
    unittest.main()
