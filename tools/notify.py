"""Toast nativo do sistema. Stdlib puro -- nada de pip install (regra 2)."""
from __future__ import annotations

import os
import shutil
import subprocess
import sys

# Constante FIXA: titulo e corpo entram por ambiente, nunca interpolados. O nome da
# sessao vem de `cwd` (caminho controlado pelo usuario, pode ter aspas, $ e ;) --
# interpolar seria injecao de comando.
_WINDOWS_PS = (
    "Add-Type -AssemblyName System.Windows.Forms;"
    "$n = New-Object System.Windows.Forms.NotifyIcon;"
    "$n.Icon = [System.Drawing.SystemIcons]::Information;"
    "$n.Visible = $true;"
    "$n.ShowBalloonTip(10000, $env:MONITOR_TOAST_TITLE, $env:MONITOR_TOAST_BODY,"
    " [System.Windows.Forms.ToolTipIcon]::Warning);"
    "Start-Sleep -Seconds 6;"
    "$n.Dispose()"
)


def _powershell() -> str | None:
    return shutil.which("powershell") or shutil.which("pwsh")


def available() -> tuple[bool, str]:
    """Canal de notificacao existe nesta maquina? Sem efeito colateral -- o doctor
    chama isto para validar a suposicao A-003 do DEFINE."""
    if sys.platform.startswith("win"):
        found = _powershell()
        return (bool(found), found or "powershell/pwsh nao encontrado no PATH")
    found = shutil.which("notify-send")
    return (bool(found), found or "notify-send ausente (instale libnotify-bin)")


def notify(title: str, body: str) -> bool:
    """Dispara o toast e NAO espera. Devolve se o processo subiu.

    NUNCA levanta: alerta que derruba o daemon e pior que alerta que nao aparece
    -- o painel continua sendo o canal principal.

    Fire-and-forget de proposito. O balao do Windows exige que o processo fique
    vivo enquanto aparece (dai o Start-Sleep de 6s), e esperar por ele
    bloquearia o ciclo do daemon por mais tempo que o proprio intervalo de 5s:
    o payload atrasaria e o anti-replay da placa comecaria a ver ciclos fora de
    ordem. Por isso o retorno diz "consegui disparar", nao "o usuario viu" --
    nenhuma das duas plataformas confirma exibicao de qualquer forma.
    """
    env = dict(os.environ, MONITOR_TOAST_TITLE=title, MONITOR_TOAST_BODY=body)
    if sys.platform.startswith("win"):
        shell = _powershell()
        cmd = [shell, "-NoProfile", "-NonInteractive", "-Command", _WINDOWS_PS] if shell else None
    else:
        sender = shutil.which("notify-send")
        cmd = [sender, "--urgency=critical", title, body] if sender else None
    if not cmd:
        return False
    try:
        subprocess.Popen(cmd, env=env, stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL)
    except (OSError, ValueError):
        return False
    return True
