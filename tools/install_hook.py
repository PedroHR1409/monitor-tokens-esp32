#!/usr/bin/env python3
"""
Instala (ou remove) os hooks estruturados do Monitor.AI no ~/.claude/settings.json.

Para que serve: PermissionRequest informa exatamente quando o Claude Code esta
pedindo autorizacao. Sem esse evento o daemon nunca inventa `perm` por heuristica.

Seguranca — este arquivo e a configuracao viva do usuario e ja orquestra outras
automacoes:
  * faz backup antes de qualquer escrita;
  * ACRESCENTA um grupo novo aos arrays de hooks, nunca substitui/remove os existentes;
  * e idempotente (rodar duas vezes nao duplica);
  * valida o JSON antes de gravar, e grava de forma atomica.

Uso:
    python tools/install_hook.py            # instala
    python tools/install_hook.py --remove   # desinstala
    python tools/install_hook.py --dry-run  # so mostra o que faria
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import tempfile
from datetime import datetime
from pathlib import Path

SETTINGS = Path.home() / ".claude" / "settings.json"
HOOK_SCRIPT = (Path(__file__).parent / "session_hook.py").resolve()

# Marca que identifica os nossos grupos de hook, para remover/atualizar sem tocar
# no que e de outra automacao.
TAG = "monitor-ai-state"
LEGACY_TAG = "monitor-ai-perm"

EVENTS = {
    "SessionStart": "free",
    "UserPromptSubmit": "work",
    "PreToolUse": "pre_tool_use",
    "PermissionRequest": "permission_request",
    "PostToolUse": "work",
    "Stop": "free",
    "SessionEnd": "ended",
}


def build_group(event: str, action: str) -> dict:
    cmd = '"{}" "{}" claude {}'.format(sys.executable, HOOK_SCRIPT, action)
    group = {
        "matcher": "*",
        "hooks": [{
            "type": "command",
            "command": cmd,
            "timeout": 5,
            "_source": TAG,     # nossa marca; o Claude Code ignora chaves extras
        }],
    }
    if event in {"SessionStart", "UserPromptSubmit", "Stop", "SessionEnd"}:
        group.pop("matcher")
    if event in {"SessionStart", "UserPromptSubmit", "PostToolUse", "Stop", "SessionEnd"}:
        group["hooks"][0]["async"] = True
    return group


def is_ours(group: dict) -> bool:
    return any(h.get("_source") in {TAG, LEGACY_TAG} for h in group.get("hooks", [])
               if isinstance(h, dict))


def check() -> int:
    """Relata a saude dos hooks dos DOIS agentes. Sai 1 se algum estiver faltando.

    Existe para ser rodado depois de instalar qualquer coisa que edite
    `~/.claude/settings.json`, que e global e disputado com outros produtos. Sem isso,
    a unica evidencia de hook quebrado era o painel inteiro virar `?` — um sintoma que
    nao aponta para a causa. Ver docs/SPEC.md secao 16.
    """
    from session_hook import CLAUDE_SETTINGS, CODEX_HOOKS, hook_health
    saude = hook_health()
    arquivos = {"claude": CLAUDE_SETTINGS, "codex": CODEX_HOOKS}
    scripts = {"claude": "install_hook.py", "codex": "install_codex_hook.py"}
    for agente in ("claude", "codex"):
        ok = saude[agente]
        print("{:8s} {}  ({})".format(
            agente, "OK" if ok else "FALTANDO -> python tools/" + scripts[agente],
            arquivos[agente]))
    if all(saude.values()):
        return 0
    print("\nSem o hook, o daemon nao recebe 'work'/'ask' e o painel mostra '?'.",
          file=sys.stderr)
    return 1


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--remove", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--check", action="store_true",
                    help="so relata se os hooks dos dois agentes estao instalados")
    args = ap.parse_args()

    if args.check:
        return check()

    if not SETTINGS.is_file():
        print("ERRO: {} nao existe".format(SETTINGS), file=sys.stderr)
        return 1

    original = SETTINGS.read_text(encoding="utf-8")
    try:
        data = json.loads(original)
    except json.JSONDecodeError as e:
        print("ERRO: settings.json invalido, abortando sem tocar nele: {}".format(e),
              file=sys.stderr)
        return 1

    hooks = data.setdefault("hooks", {})
    if not isinstance(hooks, dict):
        print("ERRO: 'hooks' nao e um objeto; abortando.", file=sys.stderr)
        return 1

    mudou = False
    for event, action in EVENTS.items():
        arr = hooks.setdefault(event, [])
        if not isinstance(arr, list):
            print("AVISO: hooks.{} nao e lista, pulando".format(event))
            continue
        antes = len(arr)
        # tira qualquer versao anterior nossa (idempotencia / atualizacao de caminho)
        arr[:] = [g for g in arr if not (isinstance(g, dict) and is_ours(g))]
        removidos = antes - len(arr)
        if args.remove:
            if removidos:
                mudou = True
                print("  - {}: removido(s) {} grupo(s) do Monitor.AI".format(event, removidos))
        else:
            arr.append(build_group(event, action))
            mudou = True
            verbo = "atualizado" if removidos else "adicionado"
            print("  + {}: {} ({} outros grupos preservados)".format(
                event, verbo, len(arr) - 1))

    if not mudou:
        print("Nada a fazer.")
        return 0

    novo = json.dumps(data, indent=2, ensure_ascii=False)
    json.loads(novo)     # valida antes de gravar

    if args.dry_run:
        print("\n[dry-run] nada foi gravado.")
        return 0

    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    backup = SETTINGS.with_suffix(".json.monitor-ai-{}.bak".format(stamp))
    shutil.copy2(SETTINGS, backup)
    print("\nBackup: {}".format(backup.name))

    fd, tmp = tempfile.mkstemp(dir=str(SETTINGS.parent), suffix=".tmp")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(novo)
    os.replace(tmp, SETTINGS)
    print("settings.json atualizado.")
    print("\nReinicie as sessoes do Claude Code para o hook passar a valer.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
