#!/usr/bin/env python3
"""Falha se valores do secrets.h reaparecerem em arquivos compartilháveis."""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

SECRET_DEFINE = re.compile(
    rb'^\s*#define\s+([A-Za-z0-9_]*(?:SSID|PASSWORD|SECRET|TOKEN|API_KEY)[A-Za-z0-9_]*)'
    rb'\s+"([^"]+)"', re.MULTILINE)
SKIP_PARTS = {".git", ".pio", ".vscode", "__pycache__"}
SKIP_NAMES = {"secrets.h"}


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
    leaks = find_leaks(args.root.resolve())
    if leaks:
        print("Credencial local encontrada em arquivo compartilhavel:", file=sys.stderr)
        for path in leaks:
            print("- {}".format(path), file=sys.stderr)
        return 1
    print("Nenhuma credencial local encontrada fora de include/secrets.h.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
