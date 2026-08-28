"""Safe, composable diagnostics for a local Monitor.AI installation."""
from __future__ import annotations

from dataclasses import asdict, dataclass
import json
from pathlib import Path
import shutil
import sqlite3
import sys
import urllib.error
import urllib.request
from typing import Any, Mapping

from monitor_config import MonitorConfig, config_path
from opencode_sessions import db_path as opencode_default_db
from session_hook import hook_health


OK = "ok"
WARN = "warn"
FAIL = "fail"
_STATUSES = frozenset((OK, WARN, FAIL))


@dataclass(frozen=True)
class CheckResult:
    """One public diagnostic result; detail is always safe for terminals and JSON."""

    code: str
    status: str
    message: str
    detail: Mapping[str, Any]

    def __post_init__(self) -> None:
        if self.status not in _STATUSES:
            raise ValueError("invalid diagnostic status")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _result(code: str, status: str, message: str, **detail: Any) -> CheckResult:
    return CheckResult(code, status, message, _safe_detail(detail))


def _safe_detail(detail: Mapping[str, Any]) -> dict[str, Any]:
    """Redact secret-shaped fields even when a caller accidentally supplies one."""
    def redact(value: Any, name: str = "") -> Any:
        lower = name.lower().replace("-", "_")
        if any(marker in lower for marker in ("token", "secret", "password", "api_key")):
            return "***redacted***"
        if isinstance(value, Mapping):
            return {str(key): redact(item, str(key)) for key, item in value.items()}
        if isinstance(value, (list, tuple)):
            return [redact(item) for item in value]
        if isinstance(value, Path):
            return str(value)
        return value
    return redact(dict(detail))


def _load_fixture(path: Path | str | None) -> Mapping[str, Any]:
    if path is None:
        return {}
    try:
        value = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError, json.JSONDecodeError) as error:
        raise ValueError("cannot read doctor fixture") from error
    if not isinstance(value, dict):
        raise ValueError("doctor fixture must be a JSON object")
    return value


def _fixture_mapping(fixture: Mapping[str, Any], name: str) -> Mapping[str, Any]:
    value = fixture.get(name, {})
    return value if isinstance(value, Mapping) else {}


def check_config(config: MonitorConfig, fixture: Mapping[str, Any],
                 source: Path | str | None = None) -> CheckResult:
    supplied = _fixture_mapping(fixture, "config")
    present = supplied.get("present") if supplied else Path(source or config_path()).is_file()
    if present:
        return _result("config", OK, "configuration is valid")
    return _result("config", WARN, "no configuration file; using safe defaults")


def check_token(config: MonitorConfig, fixture: Mapping[str, Any]) -> CheckResult:
    supplied = _fixture_mapping(fixture, "token")
    length = supplied.get("length") if supplied else len(config.transport.api_token)
    if not isinstance(length, int) or isinstance(length, bool):
        return _result("token", FAIL, "token configuration is invalid")
    if length == 0:
        return _result("token", WARN, "no transport token configured")
    if length < 16:
        return _result("token", WARN, "transport token is shorter than 16 characters", length=length)
    return _result("token", OK, "transport token length is adequate", length=length)


def check_paths(fixture: Mapping[str, Any]) -> list[CheckResult]:
    supplied = _fixture_mapping(fixture, "paths")
    paths = {
        "claude": Path.home() / ".claude" / "projects",
        "codex": Path.home() / ".codex" / "session_index.jsonl",
        "opencode": opencode_default_db(),
    }
    results = []
    for provider, path in paths.items():
        exists = supplied.get(provider) if supplied else path.exists()
        if exists:
            results.append(_result("paths." + provider, OK, provider + " provider path found"))
        else:
            results.append(_result("paths." + provider, WARN,
                                   provider + " provider path not found", path=path))
    return results


def check_hooks(fixture: Mapping[str, Any]) -> list[CheckResult]:
    supplied = _fixture_mapping(fixture, "hooks")
    health = supplied or hook_health()
    results = []
    for provider in ("claude", "codex"):
        installed = health.get(provider)
        if installed is True:
            results.append(_result("hooks." + provider, OK, provider + " hook installed"))
        else:
            results.append(_result("hooks." + provider, WARN, provider + " hook not installed"))
    return results


def check_python(fixture: Mapping[str, Any]) -> CheckResult:
    supplied = _fixture_mapping(fixture, "python")
    version = supplied.get("version") if supplied else list(sys.version_info[:2])
    if not isinstance(version, (list, tuple)) or len(version) < 2:
        return _result("python", FAIL, "Python version could not be determined")
    pair = (version[0], version[1])
    if not all(isinstance(value, int) and not isinstance(value, bool) for value in pair):
        return _result("python", FAIL, "Python version could not be determined")
    if pair < (3, 11):
        return _result("python", FAIL, "Python 3.11 or newer is required", version="{}.{}".format(*pair))
    return _result("python", OK, "Python version is supported", version="{}.{}".format(*pair))


def check_platformio(fixture: Mapping[str, Any]) -> CheckResult:
    supplied = _fixture_mapping(fixture, "platformio")
    available = supplied.get("available") if supplied else bool(shutil.which("pio") or shutil.which("platformio"))
    if available is True:
        return _result("platformio", OK, "PlatformIO is available")
    return _result("platformio", WARN, "PlatformIO is not on PATH")


def check_storage(config: MonitorConfig, fixture: Mapping[str, Any]) -> CheckResult:
    supplied = _fixture_mapping(fixture, "storage")
    state = supplied.get("state") if supplied else None
    if state == "ok":
        return _result("storage", OK, "SQLite storage is available")
    if state == "fail":
        return _result("storage", FAIL, "SQLite storage probe failed")

    path = config.storage.database_path
    if path.is_dir():
        return _result("storage", FAIL, "SQLite storage path is a directory", path=path)
    if not path.exists():
        return _result("storage", WARN, "SQLite database has not been created yet", path=path)
    try:
        with sqlite3.connect("file:{}?mode=rw".format(path.resolve().as_posix()), uri=True) as connection:
            connection.execute("SELECT 1").fetchone()
    except sqlite3.Error:
        return _result("storage", FAIL, "SQLite storage probe failed", path=path)
    return _result("storage", OK, "SQLite storage is available", path=path)


def check_device(config: MonitorConfig, fixture: Mapping[str, Any]) -> CheckResult:
    supplied = _fixture_mapping(fixture, "device")
    state = supplied.get("state") if supplied else None
    if state == "ok":
        return _result("device", OK, "device health endpoint responded")
    if state == "unreachable":
        return _result("device", WARN, "device health endpoint is unreachable")
    url = "http://{}:{}/health".format(config.device.host, config.device.port)
    try:
        with urllib.request.urlopen(url, timeout=config.transport.timeout_s) as response:
            healthy = 200 <= response.status < 300
    except (urllib.error.URLError, OSError, ValueError):
        healthy = False
    if healthy:
        return _result("device", OK, "device health endpoint responded")
    return _result("device", WARN, "device health endpoint is unreachable", host=config.device.host,
                   port=config.device.port)


def check_protocol(fixture: Mapping[str, Any]) -> CheckResult:
    supplied = _fixture_mapping(fixture, "device")
    protocols = supplied.get("protocols") if supplied else None
    if isinstance(protocols, list) and 2 in protocols:
        return _result("protocol", OK, "device reports protocol v2 compatibility")
    if isinstance(protocols, list) and 1 in protocols:
        return _result("protocol", WARN, "device reports legacy protocol v1 only")
    return _result("protocol", WARN, "protocol v2 compatibility cannot be verified")


def run_checks(config: MonitorConfig, fixture: Path | str | None = None,
               config_source: Path | str | None = None) -> list[CheckResult]:
    """Run all diagnostics. Fixtures are opt-in and never affect real invocations."""
    values = _load_fixture(fixture)
    return [
        check_config(config, values, config_source),
        check_token(config, values),
        *check_paths(values),
        *check_hooks(values),
        check_python(values),
        check_platformio(values),
        check_storage(config, values),
        check_device(config, values),
        check_protocol(values),
    ]


def exit_code(results: list[CheckResult]) -> int:
    if any(result.status == FAIL for result in results):
        return 2
    if any(result.status == WARN for result in results):
        return 1
    return 0


def report(results: list[CheckResult]) -> dict[str, Any]:
    code = exit_code(results)
    return {"status": (OK if code == 0 else FAIL if code == 2 else WARN),
            "checks": [result.to_dict() for result in results]}
