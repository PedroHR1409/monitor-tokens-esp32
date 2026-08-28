from __future__ import annotations

import io
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / "tools"
sys.path.insert(0, str(TOOLS))

import doctor  # noqa: E402
import monitor  # noqa: E402
from monitor_config import MonitorConfig  # noqa: E402


FIXTURES = ROOT / "tests" / "fixtures" / "doctor"


class DoctorFixtureTests(unittest.TestCase):
    """The production break caught here is a doctor that hides failed probes or leaks secrets."""

    def config_with_token(self) -> MonitorConfig:
        return MonitorConfig.load(ROOT / "missing-monitor.toml", environ={
            "MONITOR_API_TOKEN": "configured-token-must-never-appear",
        })

    def test_healthy_fixture_has_only_successful_checks(self):
        results = doctor.run_checks(self.config_with_token(), FIXTURES / "healthy.json")
        self.assertTrue(results)
        self.assertEqual({"ok"}, {result.status for result in results})
        self.assertIn("protocol", {result.code for result in results})

    def test_warning_fixture_returns_warning_without_failure(self):
        results = doctor.run_checks(self.config_with_token(), FIXTURES / "warning.json")
        self.assertIn("warn", {result.status for result in results})
        self.assertNotIn("fail", {result.status for result in results})
        self.assertEqual(1, doctor.exit_code(results))

    def test_failure_fixture_returns_nonzero_failure_code(self):
        results = doctor.run_checks(self.config_with_token(), FIXTURES / "failing.json")
        self.assertIn("fail", {result.status for result in results})
        self.assertEqual(2, doctor.exit_code(results))

    def test_json_output_redacts_configured_token_and_fixture_password(self):
        stream = io.StringIO()
        with redirect_stdout(stream):
            code = monitor.main([
                "doctor", "--json", "--fixture", str(FIXTURES / "healthy.json"),
                "--config", str(ROOT / "missing-monitor.toml"),
            ], environ={"MONITOR_API_TOKEN": "configured-token-must-never-appear"})
        output = stream.getvalue()
        self.assertEqual(0, code)
        self.assertEqual("ok", json.loads(output)["status"])
        self.assertNotIn("configured-token-must-never-appear", output)
        self.assertNotIn("fixture-password-must-never-appear", output)

    def test_monitor_doctor_healthy_fixture_exits_zero(self):
        with redirect_stdout(io.StringIO()):
            code = monitor.main(["doctor", "--fixture", str(FIXTURES / "healthy.json")], environ={})
        self.assertEqual(0, code)

    def test_check_result_serializes_only_public_fields(self):
        result = doctor.CheckResult("storage", "ok", "SQLite available", {"path": "db"})
        self.assertEqual({"code", "status", "message", "detail"}, set(result.to_dict()))


if __name__ == "__main__":
    unittest.main()
