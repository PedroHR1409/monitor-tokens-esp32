"""Paths for the active Codex home, including app-managed CODEX_HOME setups."""
from __future__ import annotations

import os
from pathlib import Path


def codex_home() -> Path:
    """Return the Codex data directory selected by CODEX_HOME.

    Codex-compatible hosts such as Orca can keep their state and hooks outside
    ``~/.codex``. Hooks and the daemon must resolve this through the same
    environment variable or they will observe different sessions.
    """
    configured = os.environ.get("CODEX_HOME", "").strip()
    if configured:
        return Path(configured).expanduser()

    default = Path.home() / ".codex"
    # Orca sets CODEX_HOME only inside its own process tree. A Windows user
    # service may not inherit that process-only variable, so use Orca's home
    # when its Codex database is newer than the standard home.
    appdata = os.environ.get("APPDATA", "").strip()
    if os.name == "nt" and appdata:
        orca_home = Path(appdata) / "orca" / "codex-runtime-home" / "home"
        if (orca_home / "state_5.sqlite").is_file() and (orca_home / "hooks.json").is_file():
            try:
                orca_mtime = (orca_home / "state_5.sqlite").stat().st_mtime
                default_db = default / "state_5.sqlite"
                default_mtime = default_db.stat().st_mtime if default_db.is_file() else 0
                if orca_mtime > default_mtime:
                    return orca_home
            except OSError:
                pass
    return default


CODEX_HOME = codex_home()
CODEX_SESSIONS = CODEX_HOME / "sessions"
CODEX_STATE_DB = CODEX_HOME / "state_5.sqlite"
CODEX_SESSION_INDEX = CODEX_HOME / "session_index.jsonl"
CODEX_EVENT_FILE = CODEX_HOME / "monitor-ai-events.json"
CODEX_HOOKS = CODEX_HOME / "hooks.json"
