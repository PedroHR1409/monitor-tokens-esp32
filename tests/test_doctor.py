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


class DoctorNotifyCheckTests(unittest.TestCase):
    """The notify channel is secondary; hiding its absence would leave the
    operator relying on a toast that silently never fires."""

    def test_available_fixture_reports_ok(self):
        fixture = {"notify": {"available": True, "detail": "/usr/bin/notify-send"}}
        result = doctor.check_notify(fixture)
        self.assertEqual("ok", result.status)

    def test_unavailable_fixture_reports_warn_never_fail(self):
        """WARN, never FAIL: the panel is the primary channel and the daemon
        works fine without the secondary toast."""
        fixture = {"notify": {"available": False, "detail": "ausente"}}
        result = doctor.check_notify(fixture)
        self.assertEqual("warn", result.status)
        self.assertNotEqual("fail", result.status)

    def test_notify_check_is_part_of_run_checks(self):
        config = MonitorConfig.load(ROOT / "missing-monitor.toml", environ={
            "MONITOR_API_TOKEN": "configured-token-must-never-appear",
        })
        results = doctor.run_checks(config, FIXTURES / "healthy.json")
        self.assertIn("notify", {result.code for result in results})


class DoctorProtocolTests(unittest.TestCase):
    """Protocol v2 is a reserved contract; the doctor must not imply it verified
    a capability the firmware does not serve."""

    def test_live_check_reports_the_reserved_contract_not_a_missing_probe(self):
        result = doctor.check_protocol({})

        self.assertEqual("warn", result.status)
        self.assertIn("reserved", result.message)
        self.assertNotIn("cannot be verified", result.message)

    def test_fixture_can_still_report_v2_compatibility(self):
        result = doctor.check_protocol({"device": {"protocols": [1, 2]}})

        self.assertEqual("ok", result.status)

    def test_fixture_can_still_report_legacy_v1_only(self):
        result = doctor.check_protocol({"device": {"protocols": [1]}})

        self.assertEqual("warn", result.status)
        self.assertIn("legacy", result.message)


class DoctorCommandCodeTests(unittest.TestCase):
    """The Command Code provider must appear in the same diagnostics as the rest."""

    def test_healthy_fixture_reports_the_commandcode_path_and_hook(self):
        results = doctor.run_checks(self._config(), FIXTURES / "healthy.json")
        codes = {result.code: result.status for result in results}
        self.assertEqual("ok", codes["paths.commandcode"])
        self.assertEqual("ok", codes["hooks.commandcode"])

    def test_missing_commandcode_degrades_to_warn(self):
        results = doctor.check_paths({"paths": {"commandcode": False}})
        codes = {result.code: result.status for result in results}
        self.assertEqual("warn", codes["paths.commandcode"])
        results = doctor.check_hooks({"hooks": {"commandcode": False}})
        codes = {result.code: result.status for result in results}
        self.assertEqual("warn", codes["hooks.commandcode"])

    def _config(self) -> MonitorConfig:
        return MonitorConfig.load(ROOT / "missing-monitor.toml", environ={})


if __name__ == "__main__":
    unittest.main()
