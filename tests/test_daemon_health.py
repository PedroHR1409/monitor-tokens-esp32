"""Custo da reindexacao de rollouts e deteccao de hook ausente.

Os dois nasceram de problemas medidos em 27/08/2026, nao de hipotese: 48 varreduras
completas de diretorio por ciclo, e um painel inteiro em `?` sem nada dizer que a
causa era hook desinstalado por outra ferramenta.
"""
from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import session_hook  # noqa: E402
import session_meta  # noqa: E402
from session_daemon import hook_warnings  # noqa: E402


def claude_group(agent: str = "claude", script: str = "session_hook.py") -> dict:
    return {"hooks": [{"type": "command",
                       "command": 'python.exe "C:\\p\\tools\\{}" {} work'.format(
                           script, agent)}]}


def write_hooks(path: Path, groups: dict) -> None:
    path.write_text(json.dumps({"hooks": groups}), encoding="utf-8")


class RolloutIndexCostTests(unittest.TestCase):
    """Um id sem rollout e o caso NORMAL (53 ids para 37 rollouts, 5 cruzando)."""

    def setUp(self):
        self.original = session_meta._rollout_index
        self.chamadas = 0
        session_meta._cache, session_meta._cache_at = {}, 0.0

    def tearDown(self):
        session_meta._rollout_index = self.original
        session_meta._cache, session_meta._cache_at = {}, 0.0

    def _contar(self, resultado: dict):
        def fake():
            self.chamadas += 1
            return dict(resultado)
        session_meta._rollout_index = fake

    def test_many_missing_ids_do_not_rescan_the_disk_each_time(self):
        """O bug: 48 ids ausentes viravam 48 rglobs completos por ciclo (0,83s)."""
        self._contar({})
        for i in range(48):
            session_meta._rollout_for("id-inexistente-{}".format(i))
        self.assertEqual(1, self.chamadas,
                         "a varredura e do indice, nao do id: uma por janela basta")

    def test_first_lookup_still_builds_the_index(self):
        self._contar({})
        session_meta._rollout_for("qualquer")
        self.assertEqual(1, self.chamadas)

    def test_a_known_id_is_served_from_cache(self):
        self._contar({"conhecido": Path("rollout.jsonl")})
        session_meta._rollout_for("conhecido")
        session_meta._rollout_for("conhecido")
        self.assertEqual(1, self.chamadas)

    def test_index_is_rebuilt_once_the_window_expires(self):
        """Sessao nova precisa aparecer — o throttle atrasa, nao impede."""
        self._contar({})
        session_meta._rollout_for("novo")
        session_meta._cache_at -= session_meta.REINDEX_MIN_INTERVAL_S + 1
        session_meta._rollout_for("novo")
        self.assertEqual(2, self.chamadas)


class HookInstallationTests(unittest.TestCase):
    def test_detects_our_hook_among_third_party_groups(self):
        """O instalador faz merge: o grupo do Orca fica ao lado do nosso."""
        with TemporaryDirectory() as tmp:
            p = Path(tmp) / "settings.json"
            write_hooks(p, {"PostToolUse": [
                {"hooks": [{"command": "powershell -EncodedCommand AAAA"}]},
                claude_group(),
            ]})
            self.assertTrue(session_hook.hook_installed(p, "claude"))

    def test_third_party_hooks_alone_do_not_count_as_installed(self):
        """O caso real: o Orca substituiu tudo e o painel virou '?'."""
        with TemporaryDirectory() as tmp:
            p = Path(tmp) / "settings.json"
            write_hooks(p, {"PostToolUse": [
                {"hooks": [{"command": "powershell -EncodedCommand AAAA"}]}]})
            self.assertFalse(session_hook.hook_installed(p, "claude"))

    def test_legacy_perm_hook_does_not_count_as_installed(self):
        """perm_hook.py mapeia PostToolUse para `free` e nao entrega work/ask."""
        with TemporaryDirectory() as tmp:
            p = Path(tmp) / "settings.json"
            write_hooks(p, {"PostToolUse": [claude_group(script="perm_hook.py")]})
            self.assertFalse(session_hook.hook_installed(p, "claude"))

    def test_the_other_agents_hook_does_not_count(self):
        with TemporaryDirectory() as tmp:
            p = Path(tmp) / "settings.json"
            write_hooks(p, {"PostToolUse": [claude_group(agent="codex")]})
            self.assertFalse(session_hook.hook_installed(p, "claude"))

    def test_missing_or_corrupt_file_is_reported_as_not_installed(self):
        with TemporaryDirectory() as tmp:
            ausente = Path(tmp) / "nao-existe.json"
            self.assertFalse(session_hook.hook_installed(ausente, "claude"))
            quebrado = Path(tmp) / "quebrado.json"
            quebrado.write_text("{nao e json", encoding="utf-8")
            self.assertFalse(session_hook.hook_installed(quebrado, "claude"))


class HookWarningTests(unittest.TestCase):
    def test_warns_when_an_agent_is_on_the_board_without_its_hook(self):
        avisos = hook_warnings([{"tool": "codex"}], {"claude": True, "codex": False})
        self.assertEqual(1, len(avisos))
        self.assertIn("install_codex_hook.py", avisos[0])

    def test_stays_quiet_when_the_agent_has_no_session_on_the_board(self):
        """Sem sessao daquele agente nao ha o que avisar — seria ruido a cada 5s."""
        self.assertEqual(
            [], hook_warnings([{"tool": "claude"}], {"claude": True, "codex": False}))

    def test_stays_quiet_when_every_hook_is_installed(self):
        self.assertEqual([], hook_warnings([{"tool": "claude"}, {"tool": "codex"}],
                                           {"claude": True, "codex": True}))

    def test_reports_both_agents_when_both_are_missing(self):
        avisos = hook_warnings([{"tool": "claude"}, {"tool": "codex"}],
                               {"claude": False, "codex": False})
        self.assertEqual(2, len(avisos))


class DeadCodeTests(unittest.TestCase):
    def test_fetch_hidden_was_replaced_by_the_generic_list_reader(self):
        """Duas versoes da mesma decisao de design divergiam nas docstrings."""
        import session_daemon
        self.assertFalse(hasattr(session_daemon, "fetch_hidden"))
        self.assertTrue(hasattr(session_daemon, "fetch_id_list"))


if __name__ == "__main__":
    unittest.main()
