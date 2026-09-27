#!/usr/bin/env python3
"""Falha se valores do secrets.h reaparecerem em arquivos compartilháveis."""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

# SSID fica FORA de proposito: o roteador o transmite em beacon, entao nao e
# credencial — e mante-lo aqui fazia o nome de uma rede colidir com o sobrenome do
# autor no README, acusando um falso vazamento.
SECRET_DEFINE = re.compile(
    rb'^\s*#define\s+([A-Za-z0-9_]*(?:PASSWORD|SECRET|TOKEN|API_KEY)[A-Za-z0-9_]*)'
    rb'\s+"([^"]+)"', re.MULTILINE)
SKIP_PARTS = {".git", ".pio", ".vscode", "__pycache__"}
# The checked-in template intentionally contains placeholder values found in
# secrets.h-shaped defines; it is documentation, not a credential leak.
SKIP_NAMES = {"secrets.h", "secrets.example.h"}


def find_leaks(root: Path) -> list[Path]:
    try:
        raw = (root / "include" / "secrets.h").read_bytes()
    except OSError:
        return []
    values = {value for _, value in SECRET_DEFINE.findall(raw) if value}
    leaks: list[Path] = []
    for path in root.rglob("*"):
        if not path.is_file() or path.name in SKIP_NAMES:
            continue
        if any(part in SKIP_PARTS for part in path.relative_to(root).parts):
            continue
        try:
            content = path.read_bytes()
        except OSError:
            continue
        if any(value in content for value in values):
            leaks.append(path.relative_to(root))
    return sorted(leaks)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args()
    root = args.root.resolve()
    if not (root / "include" / "secrets.h").is_file():
        print("Verificacao local omitida: include/secrets.h nao esta presente.")
        return 0
    leaks = find_leaks(root)
    if leaks:
        print("Credencial local encontrada em arquivo compartilhavel:", file=sys.stderr)
        for path in leaks:
            print("- {}".format(path), file=sys.stderr)
        return 1
    print("Nenhuma credencial local encontrada fora de include/secrets.h.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
