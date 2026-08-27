#!/usr/bin/env python3
"""Wrapper de compatibilidade para configuracoes antigas do hook do Claude.

Instalacoes novas usam session_hook.py para o ciclo completo. Este arquivo apenas
encaminha um evento explicito antigo; nunca infere estado por idade ou transcript.
"""
import json
import sys
from pathlib import Path

STATE_FILE = Path.home() / ".claude" / "monitor-ai-events.json"

def main() -> None:
    action = sys.argv[1] if len(sys.argv) > 1 else "clear"

    payload = {}
    try:
        raw = sys.stdin.read()
        if raw.strip():
            payload = json.loads(raw)
    except (json.JSONDecodeError, ValueError, OSError):
        payload = {}

    session_id = str(payload.get("session_id") or payload.get("sessionId") or "").strip()
    if not session_id:
        return

    # Compatibilidade com configuracoes antigas. O instalador atual aponta diretamente
    # para session_hook.py e distingue PostToolUse(work) de Stop(free).
    from datetime import datetime, timezone
    from session_hook import record_event
    mapped = "permission_request" if action == "permission_request" else "free"
    record_event(payload, mapped, STATE_FILE, datetime.now(timezone.utc))


if __name__ == "__main__":
    try:
        main()
    except Exception:
        pass          # jamais quebrar o fluxo do Claude Code do usuario
    sys.exit(0)
