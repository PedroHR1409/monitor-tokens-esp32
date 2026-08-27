"""Contrato estável e validável do snapshot Monitor.AI protocolo v2."""
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from math import isfinite
import re
from typing import Any, Mapping


SCHEMA_VERSION = 2
MESSAGE_TYPE_SNAPSHOT = "snapshot"
DEFAULT_CAPABILITIES = ("metric_quality", "composite_session_keys")
MAX_SEQUENCE = (1 << 63) - 1
_METRIC_QUALITIES = frozenset({
    "official", "measured", "estimated", "configured", "historical", "unknown",
})


class MetricQuality(str, Enum):
    OFFICIAL = "official"
    MEASURED = "measured"
    ESTIMATED = "estimated"
    CONFIGURED = "configured"
    HISTORICAL = "historical"
    UNKNOWN = "unknown"


class UnsupportedProtocolVersion(ValueError):
    """A major schema version different from the v2 contract was supplied."""


@dataclass(frozen=True, slots=True)
class SnapshotEnvelope:
    """Immutable metadata for one complete daemon-to-device v2 snapshot."""

    node_id: str
    device_id: str
    daemon_instance_id: str
    sequence: int
    generated_at_epoch_ms: int
    capabilities: tuple[str, ...] = DEFAULT_CAPABILITIES
    sessions: tuple[dict[str, Any], ...] = field(default_factory=tuple)
    catalog: tuple[dict[str, Any], ...] = field(default_factory=tuple)
    usage: Mapping[str, Any] = field(default_factory=dict)
    quota: Mapping[str, Any] = field(default_factory=dict)
    health: Mapping[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-ready, defensive copy of the immutable envelope."""
        return {
            "schema_version": SCHEMA_VERSION,
            "message_type": MESSAGE_TYPE_SNAPSHOT,
            "sequence": self.sequence,
            "generated_at_epoch_ms": self.generated_at_epoch_ms,
            "daemon_instance_id": self.daemon_instance_id,
            "node_id": self.node_id,
            "device_id": self.device_id,
            "capabilities": list(self.capabilities),
            "sessions": deepcopy(list(self.sessions)),
            "catalog": deepcopy(list(self.catalog)),
            "stats": {"usage": deepcopy(dict(self.usage)),
                      "quota": deepcopy(dict(self.quota))},
            "health": deepcopy(dict(self.health)),
            "nodes": [{"node_id": self.node_id, "device_id": self.device_id}],
        }


def _string(value: object, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty string")
    return value


def _number(value: object, name: str, *, minimum: float = 0,
            maximum: float | None = None) -> int | float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not isfinite(value):
        raise ValueError(f"{name} must be a finite number")
    if value < minimum or (maximum is not None and value > maximum):
        raise ValueError(f"{name} is outside its allowed range")
    return value


def metric_value(value: int | float | None, *, quality: MetricQuality | str,
                 unit: str) -> dict[str, Any]:
    """Build one typed metric without fabricating a value when it is unknown."""
    quality_value = quality.value if isinstance(quality, MetricQuality) else quality
    if quality_value not in _METRIC_QUALITIES:
        raise ValueError("metric quality is unsupported")
    _string(unit, "metric unit")
    if quality_value == MetricQuality.UNKNOWN.value:
        if value is not None:
            raise ValueError("an unknown metric cannot contain a numeric value")
    elif value is None:
        raise ValueError("only an unknown metric may omit its value")
    else:
        _number(value, "metric value", maximum=100 if unit == "percent" else None)
    return {"value": value, "quality": quality_value, "unit": unit}


def _session_identity(entry: Mapping[str, Any], node_id: str) -> dict[str, Any]:
    session = deepcopy(dict(entry))
    provider = session.get("provider", session.get("tool"))
    session_id = session.get("session_id", session.get("id"))
    _string(provider, "session provider")
    _string(session_id, "session id")
    if ":" in provider or ":" in session_id:
        raise ValueError("session provider and id cannot contain ':'")
    session.update({
        "node_id": node_id,
        "provider": provider,
        "session_id": session_id,
        "session_key": f"{node_id}:{provider}:{session_id}",
    })
    # O campo legado ctxPct nao traz o teto nem a proveniencia. Em especial, o Claude
    # inventava 1M antes de aprender um limite; v2 nunca deve transformar isso em fato.
    context = session.get("context")
    if isinstance(context, Mapping) and {"value", "quality", "unit"}.issubset(context):
        session["context"] = metric_value(context["value"], quality=context["quality"],
                                          unit=context["unit"])
    else:
        session["context"] = metric_value(None, quality=MetricQuality.UNKNOWN,
                                          unit="percent")
    session["ctxPct"] = None
    return session


def _is_secret_field_name(key: object) -> bool:
    raw = str(key)
    separated = re.sub(r"(?<=[a-z])(?=[A-Z])", " ", raw).lower()
    words = re.findall(r"[a-z0-9]+", separated)
    compact = "".join(words)
    if words == ["token", "window", "h"]:
        return False
    if any(word in {"secret", "password", "credential"} for word in words):
        return True
    if "secret" in compact or "password" in compact:
        return True
    if "apikey" in compact or compact in {"authorization", "privatekey", "auth", "bearer"}:
        return True
    return "token" in words or compact.endswith("token")


def _validate_metric_blocks(value: Any) -> None:
    if isinstance(value, Mapping):
        if {"value", "quality", "unit"}.issubset(value):
            metric_value(value["value"], quality=value["quality"], unit=value["unit"])
        for key, child in value.items():
            if _is_secret_field_name(key):
                raise ValueError("snapshots must not contain secrets")
            _validate_metric_blocks(child)
    elif isinstance(value, (list, tuple)):
        for child in value:
            _validate_metric_blocks(child)


def validate_snapshot_v2(snapshot: Mapping[str, Any]) -> None:
    """Validate all v2 boundary invariants before a receiver applies a snapshot."""
    if not isinstance(snapshot, Mapping):
        raise ValueError("snapshot must be an object")
    if snapshot.get("schema_version") != SCHEMA_VERSION:
        raise UnsupportedProtocolVersion("unsupported snapshot schema version")
    if snapshot.get("message_type") != MESSAGE_TYPE_SNAPSHOT:
        raise ValueError("unsupported snapshot message type")
    for name in ("node_id", "device_id", "daemon_instance_id"):
        _string(snapshot.get(name), name)
    sequence = _number(snapshot.get("sequence"), "sequence", maximum=MAX_SEQUENCE)
    if not isinstance(sequence, int):
        raise ValueError("sequence must be an integer")
    timestamp = _number(snapshot.get("generated_at_epoch_ms"), "generated_at_epoch_ms")
    if not isinstance(timestamp, int):
        raise ValueError("generated_at_epoch_ms must be an integer")
    capabilities = snapshot.get("capabilities")
    if not isinstance(capabilities, list) or not all(isinstance(item, str) and item for item in capabilities):
        raise ValueError("capabilities must be a string array")
    if len(set(capabilities)) != len(capabilities):
        raise ValueError("capabilities must not contain duplicates")
    for name in ("sessions", "catalog", "nodes"):
        if not isinstance(snapshot.get(name), list):
            raise ValueError(f"{name} must be an array")
    if not isinstance(snapshot.get("stats"), Mapping) or not isinstance(snapshot.get("health"), Mapping):
        raise ValueError("stats and health must be objects")
    if not {"usage", "quota"}.issubset(snapshot["stats"]):
        raise ValueError("stats must contain usage and quota")
    for collection_name in ("sessions", "catalog"):
        session_keys: set[str] = set()
        for session in snapshot[collection_name]:
            if not isinstance(session, Mapping):
                raise ValueError(f"{collection_name} must contain objects")
            for name in ("node_id", "provider", "session_id", "session_key"):
                _string(session.get(name), f"{collection_name} {name}")
            expected = "{}:{}:{}".format(session["node_id"], session["provider"],
                                          session["session_id"])
            if session["session_key"] != expected or session["session_key"] in session_keys:
                raise ValueError(f"{collection_name} keys must be unique composite identities")
            session_keys.add(session["session_key"])
            for numeric in ("ctxPct", "elapsed", "tokensWin", "source_age_s"):
                if session.get(numeric) is not None:
                    _number(session[numeric], numeric,
                            maximum=100 if numeric == "ctxPct" else None)
    _validate_metric_blocks(snapshot)


def build_snapshot_v2(*, sessions: list[Mapping[str, Any]], catalog: list[Mapping[str, Any]],
                      usage: Mapping[str, Any], quota: Mapping[str, Any],
                      health: Mapping[str, Any], node_id: str, device_id: str,
                      daemon_instance_id: str, sequence: int, now: datetime,
                      capabilities: tuple[str, ...] = DEFAULT_CAPABILITIES) -> dict[str, Any]:
    """Project normalized daemon data into one complete, validated v2 snapshot."""
    for name, value in (("node_id", node_id), ("device_id", device_id),
                        ("daemon_instance_id", daemon_instance_id)):
        _string(value, name)
    if not isinstance(now, datetime) or now.tzinfo is None:
        raise ValueError("now must be timezone-aware")
    if not isinstance(sessions, list) or not isinstance(catalog, list):
        raise ValueError("sessions and catalog must be lists")
    if not all(isinstance(value, Mapping) for value in (usage, quota, health)):
        raise ValueError("usage, quota and health must be objects")
    normalized_sessions = tuple(_session_identity(session, node_id) for session in sessions)
    normalized_catalog = tuple(_session_identity(entry, node_id) for entry in catalog)
    generated_at_epoch_ms = int(now.astimezone(timezone.utc).timestamp()) * 1000 + now.microsecond // 1000
    envelope = SnapshotEnvelope(
        node_id=node_id, device_id=device_id, daemon_instance_id=daemon_instance_id,
        sequence=sequence, generated_at_epoch_ms=generated_at_epoch_ms,
        capabilities=tuple(capabilities), sessions=normalized_sessions,
        catalog=normalized_catalog, usage=deepcopy(dict(usage)), quota=deepcopy(dict(quota)),
        health=deepcopy(dict(health)),
    )
    snapshot = envelope.to_dict()
    validate_snapshot_v2(snapshot)
    return snapshot
