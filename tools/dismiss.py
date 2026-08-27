#!/usr/bin/env python3
"""
Remove (ou devolve) uma sessão do dashboard, por ID estável — sem precisar reiniciar o
daemon nem mexer no ESP32. session_daemon.py relê esse arquivo a cada ciclo (poucos
segundos), então o card correspondente some do grid rapidinho depois do "add".

Uso:
    python tools/dismiss.py add "<id-completo>"     # não mostra mais essa sessão
    python tools/dismiss.py remove "<id-completo>"  # volta a mostrar
    python tools/dismiss.py list                            # lista o que está dispensado

Use o ID completo mostrado pelo diagnóstico do daemon. Nomes e prefixos iguais não
colidem.
"""
import json
import os
import sys
import tempfile
from pathlib import Path

DISMISS_FILE = Path(__file__).parent / ".dismissed.json"


def load() -> set:
    if DISMISS_FILE.exists():
        try:
            return set(json.loads(DISMISS_FILE.read_text(encoding="utf-8")))
        except (json.JSONDecodeError, OSError):
            return set()
    return set()


def save(items: set) -> None:
    fd, tmp = tempfile.mkstemp(dir=str(DISMISS_FILE.parent), suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(sorted(items), handle, ensure_ascii=False, indent=2)
        os.replace(tmp, DISMISS_FILE)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def main():
    if len(sys.argv) < 2 or sys.argv[1] not in ("add", "remove", "list"):
        print(__doc__)
        sys.exit(1)

    cmd = sys.argv[1]
    items = load()

    if cmd == "list":
        if not items:
            print("(nenhuma sessão dispensada)")
        for session_id in sorted(items):
            print(session_id)
        return

    if len(sys.argv) < 3:
        print(__doc__)
        sys.exit(1)
    session_id = sys.argv[2]

    if cmd == "add":
        items.add(session_id)
        save(items)
        print(f"sessão dispensada: {session_id}")
    elif cmd == "remove":
        if session_id in items:
            items.discard(session_id)
            save(items)
            print(f"sessão restaurada: {session_id}")
        else:
            print(f"'{session_id}' não estava dispensado")


if __name__ == "__main__":
    main()
