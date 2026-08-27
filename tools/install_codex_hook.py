#!/usr/bin/env python3
"""Instala hooks estruturados do Monitor.AI em ~/.codex/hooks.json."""
from __future__ import annotations

import argparse
import copy
import json
import os
import shutil
import sys
import tempfile
from datetime import datetime
from pathlib import Path

HOOKS_FILE = Path.home() / ".codex" / "hooks.json"
HOOK_SCRIPT = (Path(__file__).parent / "session_hook.py").resolve()
EVENTS = {
    "SessionStart": "free",
    "UserPromptSubmit": "work",
    "PreToolUse": "work",
    "PermissionRequest": "permission_request",
    "PostToolUse": "work",
    "Stop": "free",
    "SessionEnd": "ended",
}


def _is_ours(group: dict) -> bool:
    for handler in group.get("hooks", []):
        command = str(handler.get("command") or "") if isinstance(handler, dict) else ""
        if "session_hook.py" in command and " codex " in (command + " "):
            return True
    return False


def build_hooks_config(existing: dict, command_prefix: str, remove: bool = False) -> dict:
    data = copy.deepcopy(existing) if isinstance(existing, dict) else {}
    hooks = data.setdefault("hooks", {})
    if not isinstance(hooks, dict):
        raise ValueError("'hooks' precisa ser um objeto")
    for event, action in EVENTS.items():
        groups = hooks.setdefault(event, [])
        if not isinstance(groups, list):
            raise ValueError("hooks.{} precisa ser uma lista".format(event))
        groups[:] = [group for group in groups
                     if not (isinstance(group, dict) and _is_ours(group))]
        if not remove:
            groups.append({"hooks": [{
                "type": "command",
                "command": command_prefix + " " + action,
                "timeout": 3,
            }]})
    return data


def _atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--remove", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--path", type=Path, default=HOOKS_FILE,
                        help=argparse.SUPPRESS)
    args = parser.parse_args()

    try:
        existing = json.loads(args.path.read_text(encoding="utf-8")) if args.path.exists() else {}
        command = '"{}" "{}" codex'.format(sys.executable, HOOK_SCRIPT)
        result = build_hooks_config(existing, command, remove=args.remove)
    except (OSError, ValueError, json.JSONDecodeError) as error:
        print("ERRO: {}".format(error), file=sys.stderr)
        return 1

    rendered = json.dumps(result, indent=2, ensure_ascii=False) + "\n"
    json.loads(rendered)
    if args.dry_run:
        print("[dry-run] configuracao valida; nada foi gravado.")
        return 0

    if args.path.exists():
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        backup = args.path.with_suffix(".json.monitor-ai-{}.bak".format(stamp))
        shutil.copy2(args.path, backup)
        print("Backup: {}".format(backup))
    _atomic_write(args.path, rendered)
    print("Hooks Codex {}. Revise/confie neles com /hooks.".format(
        "removidos" if args.remove else "instalados"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
