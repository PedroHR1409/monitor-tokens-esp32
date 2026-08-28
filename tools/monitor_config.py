"""Typed runtime configuration for Monitor.AI.

Configuration is deliberately read-only after loading so every daemon, CLI, and
service consumer sees one validated snapshot of the user's settings.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
import math
import os
from pathlib import Path
import sys
import tomllib
from typing import Any, Mapping


CONFIG_SECTIONS = frozenset({
    "daemon", "device", "storage", "node", "transport", "usage", "alerts", "service",
})


def config_path() -> Path:
    """Return the per-user location of ``monitor.toml`` for this platform."""
    if sys.platform == "win32":
        base = Path(os.environ.get("APPDATA") or Path.home() / "AppData" / "Roaming")
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
    else:
        base = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config")
    return base / "monitor-ai" / "monitor.toml"


@dataclass(frozen=True)
class DaemonSettings:
    role: str = "standalone"
    interval_s: float = 5.0
    timezone: str = "America/Sao_Paulo"


@dataclass(frozen=True)
class DeviceSettings:
    host: str = "monitor-ai.local"
    port: int = 80
    id: str = "monitor-ai"


@dataclass(frozen=True)
class StorageSettings:
    database_path: Path = Path("monitor-ai.db")
    retention_days: int = 30
    hourly_retention_days: int = 365


@dataclass(frozen=True)
class NodeSettings:
    id: str = "monitor"


@dataclass(frozen=True)
class TransportSettings:
    api_token: str = ""
    prefer_websocket: bool = True
    timeout_s: float = 5.0

    @property
    def token(self) -> str:
        """Compatibility spelling for callers that refer to the shared token."""
        return self.api_token


@dataclass(frozen=True)
class UsageSettings:
    claude_context_window: int = 0
    claude_5h_budget: int = 0
    opencode_context_window: int = 0


@dataclass(frozen=True)
class AlertSettings:
    warning_after_s: int = 90
    critical_after_s: int = 300
    snooze_minutes: int = 15


@dataclass(frozen=True)
class ServiceSettings:
    enabled: bool = False


@dataclass(frozen=True)
class MonitorConfig:
    daemon: DaemonSettings = DaemonSettings()
    device: DeviceSettings = DeviceSettings()
    storage: StorageSettings = StorageSettings()
    node: NodeSettings = NodeSettings()
    transport: TransportSettings = TransportSettings()
    usage: UsageSettings = UsageSettings()
    alerts: AlertSettings = AlertSettings()
    service: ServiceSettings = ServiceSettings()

    @classmethod
    def load(cls, path: Path | str | None = None,
             environ: Mapping[str, str] = os.environ) -> "MonitorConfig":
        """Load TOML configuration, applying environment overrides for secrets.

        ``MONITOR_API_TOKEN`` is intentionally the only environment override:
        environment variables are a suitable secret delivery mechanism, whereas
        operational settings remain reproducible in ``monitor.toml``.
        """
        source = Path(path) if path is not None else config_path()
        values = _read_toml(source)
        _validate_root_keys(values)
        base = source.parent
        daemon = DaemonSettings(**_section(values, "daemon", {
            "role": "standalone", "interval_s": 5.0, "timezone": "America/Sao_Paulo",
        }))
        device = DeviceSettings(**_section(values, "device", {
            "host": "monitor-ai.local", "port": 80, "id": "monitor-ai",
        }))
        storage_values = _section(values, "storage", {
            "database_path": base / "monitor-ai.db", "retention_days": 30,
            "hourly_retention_days": 365,
        })
        storage_values["database_path"] = _resolve_path(storage_values["database_path"], base)
        storage = StorageSettings(**storage_values)
        node = NodeSettings(**_section(values, "node", {"id": "monitor"}))
        transport_values = _section(values, "transport", {
            "api_token": "", "prefer_websocket": True, "timeout_s": 5.0,
        })
        raw_environment_token = environ.get("MONITOR_API_TOKEN", "")
        if not isinstance(raw_environment_token, str):
            raise ValueError("MONITOR_API_TOKEN must be a string")
        environment_token = raw_environment_token.strip()
        if environment_token:
            transport_values["api_token"] = environment_token
        transport = TransportSettings(**transport_values)
        usage = UsageSettings(**_section(values, "usage", {
            "claude_context_window": 0, "claude_5h_budget": 0,
            "opencode_context_window": 0,
        }))
        alerts = AlertSettings(**_section(values, "alerts", {
            "warning_after_s": 90, "critical_after_s": 300, "snooze_minutes": 15,
        }))
        service = ServiceSettings(**_section(values, "service", {"enabled": False}))
        config = cls(daemon, device, storage, node, transport, usage, alerts, service)
        _validate(config)
        return config

    def redacted_dict(self) -> dict[str, Any]:
        """Return a diagnostics-safe representation of this configuration."""
        return _redact(asdict(self))

    @staticmethod
    def write_example(path: Path | str) -> Path:
        """Write a new safe example file; see :func:`write_example`."""
        return write_example(path)


EXAMPLE_TOML = """# Monitor.AI runtime configuration. Keep credentials in MONITOR_API_TOKEN.
[daemon]
# role = \"standalone\"
# interval_s = 5.0
# timezone = \"America/Sao_Paulo\"

[device]
# host = \"monitor-ai.local\"
# port = 80
# id = \"monitor-ai\"

[storage]
# database_path = \"monitor-ai.db\"
# retention_days = 30
# hourly_retention_days = 365

[node]
# id = \"monitor\"

[transport]
api_token = \"\"
# prefer_websocket = true
# timeout_s = 5.0

[usage]
# claude_context_window = 0
# claude_5h_budget = 0
# opencode_context_window = 0

[alerts]
# warning_after_s = 90
# critical_after_s = 300
# snooze_minutes = 15

[service]
# enabled = false
"""


def write_example(path: Path | str) -> Path:
    """Create a private TOML example without ever embedding a credential.

    The function refuses to replace an existing file, preserving a user's live
    configuration when a CLI command is accidentally repeated.
    """
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as file:
        file.write(EXAMPLE_TOML)
    try:
        os.chmod(destination, 0o600)
    except OSError:
        pass
    return destination


def _read_toml(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        with path.open("rb") as file:
            parsed = tomllib.load(file)
    except (OSError, tomllib.TOMLDecodeError) as error:
        raise ValueError("cannot read monitor configuration: {}".format(error)) from error
    if not isinstance(parsed, dict):
        raise ValueError("monitor configuration must contain TOML tables")
    return parsed


def _validate_root_keys(values: Mapping[str, Any]) -> None:
    unknown = set(values) - CONFIG_SECTIONS
    if unknown:
        raise ValueError("unknown root setting(s): {}".format(", ".join(sorted(unknown))))


def _redact(value: Any, field_name: str = "") -> Any:
    normalized = field_name.lower().replace("-", "_")
    if any(marker in normalized for marker in ("token", "secret", "password", "api_key")):
        return "***redacted***"
    if isinstance(value, dict):
        return {str(key): _redact(item, str(key)) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_redact(item) for item in value]
    if isinstance(value, Path):
        return str(value)
    return value


def _section(values: Mapping[str, Any], name: str,
             defaults: Mapping[str, Any]) -> dict[str, Any]:
    raw = values.get(name, {})
    if not isinstance(raw, dict):
        raise ValueError("[{}] must be a TOML table".format(name))
    unknown = set(raw) - set(defaults)
    if unknown:
        raise ValueError("unknown [{}] setting(s): {}".format(name, ", ".join(sorted(unknown))))
    return {key: raw.get(key, default) for key, default in defaults.items()}


def _resolve_path(value: object, base: Path) -> Path:
    if not isinstance(value, (str, Path)):
        raise ValueError("storage.database_path must be a path string")
    if isinstance(value, str) and not value.strip():
        raise ValueError("storage.database_path must not be empty")
    path = Path(value)
    return path if path.is_absolute() else base / path


def _validate(config: MonitorConfig) -> None:
    _non_empty_string(config.daemon.role, "daemon.role")
    if config.daemon.role not in {"standalone", "satellite", "aggregator"}:
        raise ValueError("daemon.role must be standalone, satellite, or aggregator")
    _positive_number(config.daemon.interval_s, "daemon.interval_s")
    _non_empty_string(config.daemon.timezone, "daemon.timezone")
    _non_empty_string(config.device.host, "device.host")
    if not isinstance(config.device.port, int) or isinstance(config.device.port, bool) \
            or not 1 <= config.device.port <= 65535:
        raise ValueError("device.port must be between 1 and 65535")
    _non_empty_string(config.device.id, "device.id")
    _non_empty_string(config.node.id, "node.id")
    _non_negative_int(config.storage.retention_days, "storage.retention_days")
    _non_negative_int(config.storage.hourly_retention_days, "storage.hourly_retention_days")
    _positive_number(config.transport.timeout_s, "transport.timeout_s")
    if not isinstance(config.transport.api_token, str):
        raise ValueError("transport.api_token must be a string")
    if not isinstance(config.transport.prefer_websocket, bool):
        raise ValueError("transport.prefer_websocket must be a boolean")
    _non_negative_int(config.usage.claude_context_window, "usage.claude_context_window")
    _non_negative_int(config.usage.claude_5h_budget, "usage.claude_5h_budget")
    _non_negative_int(config.usage.opencode_context_window, "usage.opencode_context_window")
    _non_negative_int(config.alerts.warning_after_s, "alerts.warning_after_s")
    _non_negative_int(config.alerts.critical_after_s, "alerts.critical_after_s")
    _non_negative_int(config.alerts.snooze_minutes, "alerts.snooze_minutes")
    if config.alerts.critical_after_s < config.alerts.warning_after_s:
        raise ValueError("alerts.critical_after_s must not precede warning_after_s")
    if not isinstance(config.service.enabled, bool):
        raise ValueError("service.enabled must be a boolean")


def _positive_number(value: object, label: str) -> None:
    if not isinstance(value, (int, float)) or isinstance(value, bool) or value <= 0 \
            or isinstance(value, float) and not math.isfinite(value):
        raise ValueError("{} must be positive".format(label))


def _non_negative_int(value: object, label: str) -> None:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise ValueError("{} must be a non-negative integer".format(label))


def _non_empty_string(value: object, label: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("{} must be a non-empty string".format(label))
