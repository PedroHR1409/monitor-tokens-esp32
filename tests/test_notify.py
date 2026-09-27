from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

TOOLS = Path(__file__).resolve().parents[1] / "tools"
sys.path.insert(0, str(TOOLS))

import notify as notify_module  # noqa: E402
from notify import _WINDOWS_PS, available, notify  # noqa: E402


class WindowsPowerShellTests(unittest.TestCase):
    """A regression here means the toast silently stops firing on Windows."""

    def test_windows_uses_powershell_with_safe_flags(self):
        with patch.object(notify_module.sys, "platform", "win32"), \
             patch.object(notify_module.shutil, "which", return_value="C:\\ps\\powershell.exe"), \
             patch.object(notify_module.subprocess, "Popen") as mock_popen:
            mock_popen.return_value = MagicMock()
            result = notify("title", "body")
        self.assertTrue(result)
        args, kwargs = mock_popen.call_args
        cmd = args[0]
        self.assertEqual("C:\\ps\\powershell.exe", cmd[0])
        self.assertIn("-NoProfile", cmd)
        self.assertIn("-NonInteractive", cmd)
        self.assertIn(_WINDOWS_PS, cmd)


class LinuxNotifySendTests(unittest.TestCase):
    def test_linux_uses_notify_send_with_title_and_body(self):
        """A regression here means Linux users get no toast at all, since
        notify-send is the only channel available on that platform."""
        with patch.object(notify_module.sys, "platform", "linux"), \
             patch.object(notify_module.shutil, "which", return_value="/usr/bin/notify-send"), \
             patch.object(notify_module.subprocess, "Popen") as mock_popen:
            mock_popen.return_value = MagicMock()
            result = notify("my-title", "my-body")
        self.assertTrue(result)
        args, kwargs = mock_popen.call_args
        cmd = args[0]
        self.assertEqual("/usr/bin/notify-send", cmd[0])
        self.assertIn("my-title", cmd)
        self.assertIn("my-body", cmd)


class TitleBodyNeverInterpolatedTests(unittest.TestCase):
    def test_malicious_title_never_appears_in_windows_argv_and_travels_via_env(self):
        """The session name comes from a user-controlled cwd path, which can hold
        quotes, `$`, and `;`. Interpolating it into the PowerShell command string
        would be command injection; the title/body must only ever cross the
        process boundary through `env=`, never through argv."""
        malicious = 'x"; Remove-Item C:\\ -Recurse; #'
        with patch.object(notify_module.sys, "platform", "win32"), \
             patch.object(notify_module.shutil, "which", return_value="powershell"), \
             patch.object(notify_module.subprocess, "Popen") as mock_popen:
            mock_popen.return_value = MagicMock()
            notify(malicious, "body")
        args, kwargs = mock_popen.call_args
        cmd = args[0]
        for entry in cmd:
            self.assertNotIn(malicious, entry)
        self.assertEqual(malicious, kwargs["env"]["MONITOR_TOAST_TITLE"])


class NeverShellTrueTests(unittest.TestCase):
    def test_popen_never_receives_shell_true(self):
        """`shell=True` combined with attacker-influenced env/argv would reopen
        the exact injection risk the env-based design avoids."""
        with patch.object(notify_module.sys, "platform", "win32"), \
             patch.object(notify_module.shutil, "which", return_value="powershell"), \
             patch.object(notify_module.subprocess, "Popen") as mock_popen:
            mock_popen.return_value = MagicMock()
            notify("t", "b")
        _, kwargs = mock_popen.call_args
        self.assertFalse(kwargs.get("shell", False))


class MissingChannelTests(unittest.TestCase):
    def test_missing_binary_returns_false_without_raising(self):
        """No PowerShell/notify-send on PATH must degrade to a quiet False, not
        an exception that would take the daemon's poll loop down with it."""
        with patch.object(notify_module.sys, "platform", "win32"), \
             patch.object(notify_module.shutil, "which", return_value=None), \
             patch.object(notify_module.subprocess, "Popen") as mock_popen:
            result = notify("t", "b")
        self.assertFalse(result)
        mock_popen.assert_not_called()


class PopenFailureTests(unittest.TestCase):
    def test_oserror_from_popen_returns_false_and_does_not_propagate(self):
        """A broken toast channel raising OSError up into the daemon's main loop
        would be strictly worse than an alert that silently never appears."""
        with patch.object(notify_module.sys, "platform", "win32"), \
             patch.object(notify_module.shutil, "which", return_value="powershell"), \
             patch.object(notify_module.subprocess, "Popen", side_effect=OSError("boom")):
            result = notify("t", "b")
        self.assertFalse(result)


class NonBlockingTests(unittest.TestCase):
    def test_notify_never_waits_on_the_process(self):
        """Windows' balloon requires the helper process to stay alive for 6
        seconds (`Start-Sleep -Seconds 6`); waiting on it here would block the
        daemon's 5s poll cycle longer than the interval itself."""
        with patch.object(notify_module.sys, "platform", "win32"), \
             patch.object(notify_module.shutil, "which", return_value="powershell"), \
             patch.object(notify_module.subprocess, "Popen") as mock_popen:
            mock_process = MagicMock()
            mock_popen.return_value = mock_process
            notify("t", "b")
        mock_process.wait.assert_not_called()
        mock_process.communicate.assert_not_called()


class AvailableTests(unittest.TestCase):
    def test_available_true_with_path_when_binary_found(self):
        with patch.object(notify_module.sys, "platform", "win32"), \
             patch.object(notify_module.shutil, "which", return_value="C:\\ps\\powershell.exe"):
            ok, detail = available()
        self.assertTrue(ok)
        self.assertEqual("C:\\ps\\powershell.exe", detail)

    def test_available_false_with_readable_reason_when_missing(self):
        with patch.object(notify_module.sys, "platform", "linux"), \
             patch.object(notify_module.shutil, "which", return_value=None):
            ok, detail = available()
        self.assertFalse(ok)
        self.assertTrue(detail)


if __name__ == "__main__":
    unittest.main()
