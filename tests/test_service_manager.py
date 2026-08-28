from __future__ import annotations

import io
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ElementTree
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / "tools"
sys.path.insert(0, str(TOOLS))


class ServiceRenderingTests(unittest.TestCase):
    """The production breaks named here are unsafe service command rendering."""

    def paths_with_spaces(self) -> tuple[Path, Path, Path]:
        root = Path(tempfile.gettempdir()).resolve() / "Ada User"
        return (
            root / "Python 3.13" / "python",
            root / "Desktop" / "Monitor AI",
            root / "AppData" / "monitor-ai" / "monitor.toml",
        )

    def test_windows_task_keeps_spaced_paths_as_single_arguments(self):
        """Dropping quotes would start Python with a truncated executable or config path."""
        import service_manager

        python, repository, config = self.paths_with_spaces()
        root = ElementTree.fromstring(service_manager.render_windows_task(
            python, repository, config))
        namespace = {"task": "http://schemas.microsoft.com/windows/2004/02/mit/task"}

        self.assertEqual(str(python), root.findtext(".//task:Command", namespaces=namespace))
        self.assertEqual('"{}" run --config "{}"'.format(
            repository / "tools" / "monitor.py", config),
                         root.findtext(".//task:Arguments", namespaces=namespace))
        self.assertEqual(str(repository), root.findtext(".//task:WorkingDirectory",
                                                         namespaces=namespace))

    def test_windows_task_runs_at_least_privilege_for_the_interactive_user(self):
        """Changing to an elevated startup task would make normal installation require admin."""
        import service_manager

        python, repository, config = self.paths_with_spaces()
        rendered = service_manager.render_windows_task(python, repository, config)

        self.assertIn("<LogonType>InteractiveToken</LogonType>", rendered)
        self.assertIn("<RunLevel>LeastPrivilege</RunLevel>", rendered)
        self.assertNotIn("HighestAvailable", rendered)

    def test_systemd_unit_quotes_spaced_paths_and_hardens_the_daemon(self):
        """An unquoted ExecStart or absent hardening would break service startup or widen access."""
        import service_manager

        python, repository, config = self.paths_with_spaces()
        rendered = service_manager.render_systemd_unit(python, repository, config)
        quote = lambda path: '"{}"'.format(str(path).replace("\\", "\\\\"))

        self.assertIn("ExecStart={} {} run --config {}".format(
            quote(python), quote(repository / "tools" / "monitor.py"), quote(config)), rendered)
        self.assertIn("NoNewPrivileges=true", rendered)
        self.assertIn("PrivateTmp=true", rendered)
        self.assertIn("ProtectSystem=strict", rendered)
        self.assertIn("ProtectHome=read-only", rendered)
        self.assertIn("ReadWritePaths={}".format(quote(config.parent)), rendered)

    def test_renderers_reject_relative_paths(self):
        """Accepting a relative executable could run a different program after a service restart."""
        import service_manager

        with self.assertRaisesRegex(ValueError, "absolute"):
            service_manager.render_systemd_unit(Path("python"), Path("/repo"), Path("/config"))


class ServiceOperationTests(unittest.TestCase):
    """The production breaks named here are accidental real-service mutations in dry-runs."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.home = Path(self.temp.name) / "user home"
        self.python = Path(self.temp.name).resolve() / "Python" / "python"
        self.repository = Path(self.temp.name).resolve() / "repo with spaces"
        self.config = Path(self.temp.name).resolve() / "config" / "monitor.toml"

    def test_linux_install_dry_run_is_idempotent_and_never_writes_user_unit(self):
        """Writing a unit during preview would unexpectedly enable a background daemon."""
        import service_manager

        def no_subprocess(*_args, **_kwargs):
            self.fail("dry-run must not execute systemctl")

        first = service_manager.service_install(
            self.python, self.repository, self.config, dry_run=True,
            platform="linux", home=self.home, runner=no_subprocess)
        second = service_manager.service_install(
            self.python, self.repository, self.config, dry_run=True,
            platform="linux", home=self.home, runner=no_subprocess)
        destination = self.home / ".config" / "systemd" / "user" / "monitor-ai.service"

        self.assertFalse(destination.exists())
        self.assertEqual(first, second)
        self.assertFalse(first.changed)
        self.assertIn(str(destination), first.message)
        self.assertNotIn("/etc/systemd/system", first.message)

    def test_linux_remove_and_status_dry_runs_do_not_touch_a_real_service(self):
        """A preview remove/status must not delete a unit or invoke systemctl."""
        import service_manager

        destination = self.home / ".config" / "systemd" / "user" / "monitor-ai.service"
        destination.parent.mkdir(parents=True)
        destination.write_text("keep me", encoding="utf-8")

        def no_subprocess(*_args, **_kwargs):
            self.fail("dry-run must not execute systemctl")

        removed = service_manager.service_remove(dry_run=True, platform="linux",
                                                 home=self.home, runner=no_subprocess)
        status = service_manager.service_status(dry_run=True, platform="linux",
                                                home=self.home, runner=no_subprocess)

        self.assertEqual("keep me", destination.read_text(encoding="utf-8"))
        self.assertFalse(removed.changed)
        self.assertFalse(status.changed)
        self.assertIn("would remove", removed.message)
        self.assertIn("would query", status.message)


class ServiceCommandTests(unittest.TestCase):
    def test_service_status_dry_run_is_available_from_the_unified_cli(self):
        """Omitting the service command from monitor.py would leave users no safe preview path."""
        import monitor

        output = io.StringIO()
        with redirect_stdout(output):
            code = monitor.main(["service", "status", "--dry-run"], environ={})

        self.assertEqual(0, code)
        self.assertIn("dry-run", output.getvalue())


if __name__ == "__main__":
    unittest.main()
