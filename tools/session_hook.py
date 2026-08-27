#!/usr/bin/env python3
"""Hook comum Claude/Codex que registra somente eventos estruturados de sessão."""
from __future__ import annotations

import json
import os
import sys
import tempfile
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from agent_events import MAX_FUTURE_SKEW_S, parse_aware_timestamp

QUESTION_TOOLS = frozenset({"AskUserQuestion", "ExitPlanMode"})

# Onde cada agente declara seus hooks. Sao arquivos GLOBAIS do usuario, editados por
# outros produtos alem deste projeto — em 27/08/2026 o Orca substituiu todos os hooks
# do Claude pelo handler dele, e o Monitor.AI ficou sem receber `work`/`ask`. O painel
# nao tinha como perceber: cada sessao virava stale em 90s e mostrava `?`, que e
# tecnicamente correto e completamente inutil para achar a causa. Por isso a saude do
# hook virou algo consultavel. Ver docs/SPEC.md secao 16.
CLAUDE_SETTINGS = Path.home() / ".claude" / "settings.json"
CODEX_HOOKS = Path.home() / ".codex" / "hooks.json"
ACTION_STATE = {
    "work": "work",
    "ask": "ask",
    "permission_request": "perm",
    "free": "free",
    "ended": "ended",
}


@contextmanager
def _exclusive_lock(path: Path):
    """Serializa o read-modify-write entre processos sem polling temporal."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+b") as lock:
        if os.name == "nt":
            import msvcrt
            if lock.tell() == 0:
                lock.write(b"\0")
                lock.flush()
            lock.seek(0)
            msvcrt.locking(lock.fileno(), msvcrt.LK_LOCK, 1)
            try:
                yield
            finally:
                lock.seek(0)
                msvcrt.locking(lock.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(lock.fileno(), fcntl.LOCK_UN)


def hook_installed(path: Path, agent: str, events: frozenset | None = None) -> bool:
    """Algum grupo do arquivo chama session_hook.py para este agente?

    Procura o par (script, agente) no comando, do mesmo jeito que os instaladores
    reconhecem os proprios grupos. Basta um evento: se o arquivo foi reescrito por
    outra ferramenta, os grupos somem todos juntos, nao um a um.
    """
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, ValueError):
        return False
    hooks = data.get("hooks") if isinstance(data, dict) else None
    if not isinstance(hooks, dict):
        return False
    for event, groups in hooks.items():
        if events is not None and event not in events:
            continue
        if not isinstance(groups, list):
            continue
        for group in groups:
            if not isinstance(group, dict):
                continue
            for handler in group.get("hooks", []) or []:
                command = str(handler.get("command") or "") if isinstance(handler, dict) else ""
                if "session_hook.py" in command and " {} ".format(agent) in command + " ":
                    return True
    return False


def hook_health() -> dict:
    """{'claude': bool, 'codex': bool} — o hook de cada agente esta instalado?"""
    return {"claude": hook_installed(CLAUDE_SETTINGS, "claude"),
            "codex": hook_installed(CODEX_HOOKS, "codex")}


def load_event_store(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, json.JSONDecodeError):
        return {}
    if not isinstance(data, dict):
        return {}
    return {str(key): value for key, value in data.items() if isinstance(value, dict)}


def _atomic_save(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(data, handle, separators=(",", ":"), sort_keys=True)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def record_event(payload: dict, action: str, state_path: Path,
                 now: datetime | None = None) -> bool:
    session_id = str(payload.get("session_id") or payload.get("sessionId") or "").strip()
    if not session_id or action not in ACTION_STATE:
        return False
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None or now.utcoffset() is None:
        return False
    now = now.astimezone(timezone.utc)

    tool = str(payload.get("tool_name") or payload.get("toolName") or "").strip()
    state = ACTION_STATE[action]
    if action == "permission_request" and tool in QUESTION_TOOLS:
        state = "work"

    lock_path = state_path.with_suffix(state_path.suffix + ".lock")
    with _exclusive_lock(lock_path):
        data = load_event_store(state_path)
        previous = data.get(session_id)
        if previous:
            previous_at = parse_aware_timestamp(previous.get("timestamp"))
            future_poisoned = (previous_at is not None and
                               (previous_at - now).total_seconds() > MAX_FUTURE_SKEW_S)
            if previous_at is not None and now < previous_at and not future_poisoned:
                return False
        data[session_id] = {
            "session_id": session_id,
            "state": state,
            "timestamp": now.isoformat(),
            "event": str(payload.get("hook_event_name") or action),
            "tool": tool,
            "cwd": str(payload.get("cwd") or ""),
        }
        _atomic_save(state_path, data)
    return True


def _default_path(provider: str) -> Path:
    base = ".codex" if provider == "codex" else ".claude"
    return Path.home() / base / "monitor-ai-events.json"


def main() -> None:
    provider = sys.argv[1] if len(sys.argv) > 1 else "claude"
    action = sys.argv[2] if len(sys.argv) > 2 else "free"
    try:
        payload = json.loads(sys.stdin.read() or "{}")
        if not isinstance(payload, dict):
            payload = {}
        record_event(payload, action, _default_path(provider))
    except BaseException:
        pass


if __name__ == "__main__":
    main()
    raise SystemExit(0)
