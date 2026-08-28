"""Install and inspect the Monitor.AI daemon as a per-user service.

The module deliberately never places files in system-wide service directories.
Callers provide the absolute interpreter, checkout, and configuration paths so
the service keeps working when launched outside the interactive shell.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import os
import subprocess
import sys
import tempfile
from typing import Callable, Sequence
from xml.sax.saxutils import escape as xml_escape


SERVICE_NAME = "monitor-ai"
WINDOWS_TASK_NAME = "Monitor.AI"


@dataclass(frozen=True)
class ServiceResult:
    """A diagnostics-safe outcome for a service operation."""

    changed: bool
    message: str
    returncode: int = 0


Runner = Callable[..., subprocess.CompletedProcess[str]]


def _absolute_path(path: Path | str, label: str) -> Path:
    value = Path(path)
    if not value.is_absolute():
        raise ValueError("{} path must be absolute".format(label))
    return value


def _service_paths(python_path: Path | str, repository_path: Path | str,
                   config_path: Path | str) -> tuple[Path, Path, Path]:
    python = _absolute_path(python_path, "Python")
    repository = _absolute_path(repository_path, "repository")
    config = _absolute_path(config_path, "configuration")
    return python, repository, config


def _command_arguments(repository: Path, config: Path) -> str:
    return '"{}" run --config "{}"'.format(repository / "tools" / "monitor.py", config)


def render_windows_task(python_path: Path | str, repository_path: Path | str,
                        config_path: Path | str) -> str:
    """Render a current-user Scheduled Task XML document without elevated rights."""
    python, repository, config = _service_paths(python_path, repository_path, config_path)
    command = xml_escape(str(python))
    arguments = xml_escape(_command_arguments(repository, config))
    working_directory = xml_escape(str(repository))
    return """<?xml version="1.0" encoding="UTF-16"?>
<Task version="1.4" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
  <RegistrationInfo><Description>Monitor.AI user daemon</Description></RegistrationInfo>
  <Triggers><LogonTrigger><Enabled>true</Enabled></LogonTrigger></Triggers>
  <Principals><Principal id="CurrentUser"><LogonType>InteractiveToken</LogonType><RunLevel>LeastPrivilege</RunLevel></Principal></Principals>
  <Settings><MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy><StartWhenAvailable>true</StartWhenAvailable><ExecutionTimeLimit>PT0S</ExecutionTimeLimit></Settings>
  <Actions Context="CurrentUser"><Exec><Command>{}</Command><Arguments>{}</Arguments><WorkingDirectory>{}</WorkingDirectory></Exec></Actions>
</Task>
""".format(command, arguments, working_directory)


def _systemd_quote(path: Path) -> str:
    """Quote a systemd command argument, preserving spaces and literal backslashes."""
    return '"{}"'.format(str(path).replace("\\", "\\\\").replace('"', '\\"'))


def render_systemd_unit(python_path: Path | str, repository_path: Path | str,
                        config_path: Path | str) -> str:
    """Render a hardened systemd *user* unit for the daemon."""
    python, repository, config = _service_paths(python_path, repository_path, config_path)
    executable = _systemd_quote(python)
    script = _systemd_quote(repository / "tools" / "monitor.py")
    configuration = _systemd_quote(config)
    writable_config = _systemd_quote(config.parent)
    return """[Unit]
Description=Monitor.AI daemon
After=network-online.target

[Service]
Type=simple
WorkingDirectory={repository}
ExecStart={executable} {script} run --config {configuration}
Restart=on-failure
RestartSec=5
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=strict
ProtectHome=read-only
ReadWritePaths={writable_config}

[Install]
WantedBy=default.target
""".format(repository=_systemd_quote(repository), executable=executable, script=script,
           configuration=configuration, writable_config=writable_config)


def _platform_name(platform: str | None) -> str:
    value = platform if platform is not None else sys.platform
    if value.startswith("win"):
        return "windows"
    if value.startswith("linux"):
        return "linux"
    raise ValueError("per-user services are supported only on Windows and Linux")


def _linux_unit_path(home: Path | str | None) -> Path:
    user_home = Path(home) if home is not None else Path.home()
    return user_home / ".config" / "systemd" / "user" / "{}.service".format(SERVICE_NAME)


def _run(command: Sequence[str], runner: Runner) -> ServiceResult:
    completed = runner(list(command), check=False, capture_output=True, text=True)
    output = (completed.stdout or completed.stderr or "").strip()
    message = output or "command completed"
    return ServiceResult(completed.returncode == 0, message, completed.returncode)


def _atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except BaseException:
        try:
            os.unlink(temporary)
        except OSError:
            pass
        raise


def service_install(python_path: Path | str, repository_path: Path | str,
                    config_path: Path | str, dry_run: bool = False, *,
                    platform: str | None = None, home: Path | str | None = None,
                    runner: Runner = subprocess.run) -> ServiceResult:
    """Install the daemon as an explicit, idempotent user service."""
    target = _platform_name(platform)
    if target == "windows":
        render_windows_task(python_path, repository_path, config_path)
        if dry_run:
            return ServiceResult(False, "dry-run: would install user Scheduled Task '{}'".format(
                WINDOWS_TASK_NAME))
        descriptor, xml_file = tempfile.mkstemp(suffix=".xml")
        try:
            with os.fdopen(descriptor, "w", encoding="utf-16") as handle:
                handle.write(render_windows_task(python_path, repository_path, config_path))
            result = _run(["schtasks", "/Create", "/TN", WINDOWS_TASK_NAME, "/XML", xml_file,
                           "/F"], runner)
        finally:
            try:
                os.unlink(xml_file)
            except OSError:
                pass
        return ServiceResult(result.returncode == 0, result.message, result.returncode)

    destination = _linux_unit_path(home)
    rendered = render_systemd_unit(python_path, repository_path, config_path)
    if dry_run:
        return ServiceResult(False, "dry-run: would write and enable user unit {}".format(destination))
    if destination.exists() and destination.read_text(encoding="utf-8") == rendered:
        return ServiceResult(False, "user unit already installed: {}".format(destination))
    _atomic_write(destination, rendered)
    reload_result = _run(["systemctl", "--user", "daemon-reload"], runner)
    if reload_result.returncode:
        return reload_result
    enable_result = _run(["systemctl", "--user", "enable", "--now",
                          "{}.service".format(SERVICE_NAME)], runner)
    return ServiceResult(enable_result.returncode == 0, enable_result.message,
                         enable_result.returncode)


def service_remove(dry_run: bool = False, *, platform: str | None = None,
                   home: Path | str | None = None,
                   runner: Runner = subprocess.run) -> ServiceResult:
    """Remove the per-user service without touching system-wide destinations."""
    target = _platform_name(platform)
    if target == "windows":
        if dry_run:
            return ServiceResult(False, "dry-run: would remove user Scheduled Task '{}'".format(
                WINDOWS_TASK_NAME))
        result = _run(["schtasks", "/Delete", "/TN", WINDOWS_TASK_NAME, "/F"], runner)
        return ServiceResult(result.returncode == 0, result.message, result.returncode)

    destination = _linux_unit_path(home)
    if dry_run:
        return ServiceResult(False, "dry-run: would remove user unit {}".format(destination))
    existed = destination.exists()
    if existed:
        destination.unlink()
    disable_result = _run(["systemctl", "--user", "disable", "--now",
                           "{}.service".format(SERVICE_NAME)], runner)
    reload_result = _run(["systemctl", "--user", "daemon-reload"], runner)
    returncode = disable_result.returncode or reload_result.returncode
    message = disable_result.message if disable_result.returncode else reload_result.message
    return ServiceResult(existed or returncode == 0, message, returncode)


def service_status(dry_run: bool = False, *, platform: str | None = None,
                   home: Path | str | None = None,
                   runner: Runner = subprocess.run) -> ServiceResult:
    """Report the current service state; preview mode does not query the host."""
    target = _platform_name(platform)
    if target == "windows":
        command = ["schtasks", "/Query", "/TN", WINDOWS_TASK_NAME, "/FO", "LIST", "/V"]
        label = "user Scheduled Task '{}'".format(WINDOWS_TASK_NAME)
    else:
        command = ["systemctl", "--user", "status", "{}.service".format(SERVICE_NAME), "--no-pager"]
        label = "user unit {}".format(_linux_unit_path(home))
    if dry_run:
        return ServiceResult(False, "dry-run: would query {}".format(label))
    result = _run(command, runner)
    return ServiceResult(False, result.message, result.returncode)
