"""Cota de uso: o oficial do Codex e o estimado do Claude.

O teste central aqui e o da classificacao por `window_minutes`. Os rollouts reais
trazem a mesma janela ora em `primary`, ora em `secondary`, e as vezes com o outro
bucket null — ler pela posicao daria 5h quando era semanal.
"""
from __future__ import annotations

import json
import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import quota  # noqa: E402

NOW = datetime(2026, 8, 27, 12, 0, tzinfo=timezone.utc)


def rollout_line(ts: datetime, rate_limits) -> str:
    return json.dumps({"timestamp": ts.isoformat().replace("+00:00", "Z"),
                       "type": "token_count",
                       "payload": {"type": "token_count",
                                   "rate_limits": rate_limits}})


def write_rollout(base: Path, name: str, lines) -> Path:
    day = base / "2026" / "08" / "27"
    day.mkdir(parents=True, exist_ok=True)
    path = day / f"rollout-2026-08-27T12-00-00-{name}.jsonl"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def turn(ts: datetime, tokens: int) -> str:
    return json.dumps({
        "timestamp": ts.isoformat().replace("+00:00", "Z"),
        "type": "assistant",
        "message": {"model": "claude-opus-5",
                    "usage": {"input_tokens": tokens, "output_tokens": 0,
                              "cache_creation_input_tokens": 0}},
    })


def write_transcript(projects: Path, project: str, lines) -> Path:
    folder = projects / project
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / "sessao.jsonl"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


class CodexOfficialQuotaTests(unittest.TestCase):
    def test_classifies_windows_by_duration_not_by_bucket_name(self):
        """A semanal veio em `primary` e a de 5h em `secondary` — invertido em relacao
        ao caso comum. Ler pela posicao trocaria os dois numeros."""
        with TemporaryDirectory() as tmp:
            base = Path(tmp)
            write_rollout(base, "aaa", [rollout_line(NOW, {
                "primary":   {"used_percent": 61.0, "window_minutes": 10080,
                              "resets_at": 1788452748},
                "secondary": {"used_percent": 7.0, "window_minutes": 300,
                              "resets_at": 1787865948},
                "plan_type": "plus",
            })])
            q = quota.codex_quota(base, NOW)
        self.assertTrue(q["ok"])
        self.assertEqual(7, q["h5_pct"])
        self.assertEqual(61, q["week_pct"])
        self.assertEqual(1787865948, q["h5_reset"])
        self.assertEqual(1788452748, q["week_reset"])

    def test_resolves_each_window_independently_when_buckets_are_null(self):
        """Evento real observado: `limit_id: codex` traz so a semanal e `secondary` e
        null. A janela de 5h tem que vir do outro evento, nao ficar zerada."""
        with TemporaryDirectory() as tmp:
            base = Path(tmp)
            write_rollout(base, "aaa", [
                rollout_line(NOW - timedelta(minutes=5), {
                    "primary": {"used_percent": 12.0, "window_minutes": 300},
                    "secondary": None, "plan_type": "plus"}),
                rollout_line(NOW, {
                    "primary": {"used_percent": 40.0, "window_minutes": 10080},
                    "secondary": None}),
            ])
            q = quota.codex_quota(base, NOW)
        self.assertEqual(12, q["h5_pct"])
        self.assertEqual(40, q["week_pct"])

    def test_latest_event_wins_over_an_earlier_one(self):
        with TemporaryDirectory() as tmp:
            base = Path(tmp)
            write_rollout(base, "aaa", [
                rollout_line(NOW - timedelta(hours=2), {
                    "primary": {"used_percent": 5.0, "window_minutes": 300}}),
                rollout_line(NOW, {
                    "primary": {"used_percent": 44.0, "window_minutes": 300}}),
            ])
            self.assertEqual(44, quota.codex_quota(base, NOW)["h5_pct"])

    def test_ignores_windows_of_other_durations(self):
        with TemporaryDirectory() as tmp:
            base = Path(tmp)
            write_rollout(base, "aaa", [rollout_line(NOW, {
                "primary": {"used_percent": 90.0, "window_minutes": 60}})])
            q = quota.codex_quota(base, NOW)
        self.assertFalse(q["ok"], "janela de 60min nao e nem 5h nem semanal")

    def test_discards_a_window_whose_reset_already_passed(self):
        """Ficar dias sem abrir o Codex nao pode fazer o painel exibir com confianca o
        percentual da semana passada. `resets_at` no passado prova que a janela virou."""
        with TemporaryDirectory() as tmp:
            base = Path(tmp)
            expirado = int((NOW - timedelta(hours=1)).timestamp())
            write_rollout(base, "aaa", [rollout_line(NOW - timedelta(days=4), {
                "primary": {"used_percent": 88.0, "window_minutes": 300,
                            "resets_at": expirado}})])
            q = quota.codex_quota(base, NOW)
        self.assertFalse(q["ok"])
        self.assertEqual(0, q["h5_pct"], "88% de uma janela encerrada nao vale nada")

    def test_discards_an_old_window_that_has_no_resets_at(self):
        """Sem `resets_at`, o criterio e a idade: 5h medidas ha 9h ja rolaram."""
        with TemporaryDirectory() as tmp:
            base = Path(tmp)
            write_rollout(base, "aaa", [rollout_line(NOW - timedelta(hours=9), {
                "primary": {"used_percent": 71.0, "window_minutes": 300}})])
            self.assertFalse(quota.codex_quota(base, NOW)["ok"])

    def test_keeps_the_weekly_window_while_its_reset_is_still_ahead(self):
        """A semanal sobrevive a um evento de dias atras — a janela dela ainda nao virou."""
        with TemporaryDirectory() as tmp:
            base = Path(tmp)
            futuro = int((NOW + timedelta(days=3)).timestamp())
            write_rollout(base, "aaa", [rollout_line(NOW - timedelta(days=2), {
                "primary": {"used_percent": 55.0, "window_minutes": 10080,
                            "resets_at": futuro},
                "secondary": {"used_percent": 91.0, "window_minutes": 300,
                              "resets_at": int((NOW - timedelta(days=2)).timestamp())}})])
            q = quota.codex_quota(base, NOW)
        self.assertTrue(q["ok"])
        self.assertEqual(55, q["week_pct"])
        self.assertEqual(0, q["h5_pct"], "a de 5h do mesmo evento ja tinha expirado")

    def test_reports_how_old_the_reading_is(self):
        """Oficial nao e o mesmo que atual. Bug observado em 27/08/2026: o painel
        mostrou 37% enquanto o consumo real era 100% — a leitura tinha 3h porque o
        Codex CLI parara de escrever o rollout, e nada na tela dizia isso. A janela
        continuava valida (`resets_at` no futuro), entao so a idade denuncia."""
        with TemporaryDirectory() as tmp:
            base = Path(tmp)
            futuro = int((NOW + timedelta(minutes=20)).timestamp())
            write_rollout(base, "aaa", [rollout_line(NOW - timedelta(hours=3), {
                "primary": {"used_percent": 37.0, "window_minutes": 300,
                            "resets_at": futuro}})])
            q = quota.codex_quota(base, NOW)
        self.assertTrue(q["ok"], "a janela ainda nao virou, o dado continua valido")
        self.assertEqual(37, q["h5_pct"])
        self.assertEqual(3 * 3600, q["age_s"], "a idade e o que revela o atraso")

    def test_a_fresh_reading_reports_a_small_age(self):
        with TemporaryDirectory() as tmp:
            base = Path(tmp)
            write_rollout(base, "aaa", [rollout_line(NOW - timedelta(seconds=12), {
                "primary": {"used_percent": 4.0, "window_minutes": 300}})])
            self.assertEqual(12, quota.codex_quota(base, NOW)["age_s"])

    def test_reports_not_ok_when_no_rollout_has_rate_limits(self):
        with TemporaryDirectory() as tmp:
            base = Path(tmp)
            write_rollout(base, "aaa", [json.dumps(
                {"timestamp": NOW.isoformat(), "payload": {"type": "reasoning"}})])
            q = quota.codex_quota(base, NOW)
        self.assertFalse(q["ok"])
        self.assertEqual(0, q["h5_pct"])

    def test_missing_directory_is_not_an_error(self):
        q = quota.codex_quota(Path("/nao/existe/em/lugar/nenhum"))
        self.assertFalse(q["ok"])

    def test_trims_credit_balance_to_two_decimals(self):
        """Vem com 10 casas ("93.8120090000") e o card tem 96px de largura."""
        with TemporaryDirectory() as tmp:
            base = Path(tmp)
            write_rollout(base, "aaa", [rollout_line(NOW, {
                "primary": {"used_percent": 1.0, "window_minutes": 300},
                "plan_type": "plus",
                "credits": {"balance": "93.8120090000"}})])
            self.assertEqual("93.81", quota.codex_quota(base, NOW)["credits"])


class ClaudeEstimateTests(unittest.TestCase):
    def test_sums_only_turns_inside_the_five_hour_window(self):
        with TemporaryDirectory() as tmp:
            projects = Path(tmp)
            write_transcript(projects, "proj-a", [
                turn(NOW - timedelta(hours=9), 500_000),   # fora da janela
                turn(NOW - timedelta(hours=1), 30_000),
                turn(NOW - timedelta(minutes=5), 12_000),
            ])
            out = quota.claude_consumption(projects, NOW)
        self.assertTrue(out["ok"])
        self.assertEqual(42_000, out["tokens"])

    def test_has_no_percentage_without_a_declared_ceiling(self):
        """Sem teto do plano, percentual seria denominador inventado."""
        with TemporaryDirectory() as tmp:
            projects = Path(tmp)
            write_transcript(projects, "proj-a", [turn(NOW, 90_000)])
            out = quota.claude_consumption(projects, NOW, budget=0)
        self.assertEqual(0, out["pct"])
        self.assertEqual(90_000, out["tokens"], "o consumo continua sendo verdade")

    def test_declared_ceiling_turns_consumption_into_a_percentage(self):
        with TemporaryDirectory() as tmp:
            projects = Path(tmp)
            write_transcript(projects, "proj-a", [turn(NOW, 90_000)])
            out = quota.claude_consumption(projects, NOW, budget=200_000)
        self.assertEqual(45, out["pct"])

    def test_sums_across_projects(self):
        with TemporaryDirectory() as tmp:
            projects = Path(tmp)
            write_transcript(projects, "proj-a", [turn(NOW, 10_000)])
            write_transcript(projects, "proj-b", [turn(NOW, 25_000)])
            self.assertEqual(35_000,
                             quota.claude_consumption(projects, NOW)["tokens"])

    def test_missing_projects_directory_is_not_an_error(self):
        out = quota.claude_consumption(Path("/nao/existe"), NOW)
        self.assertFalse(out["ok"])
        self.assertEqual(0, out["tokens"])


class QuotaBlockTests(unittest.TestCase):
    def test_block_marks_which_number_is_official(self):
        """A assimetria e o ponto: o firmware rotula a tela a partir destes flags, e
        um deles nunca pode virar True por acidente."""
        with TemporaryDirectory() as tmp:
            base = Path(tmp) / "codex"
            projects = Path(tmp) / "projects"
            projects.mkdir()
            write_rollout(base, "aaa", [rollout_line(NOW, {
                "primary": {"used_percent": 33.0, "window_minutes": 300}})])
            write_transcript(projects, "proj-a", [turn(NOW, 1_000)])
            block = quota.collect(projects, NOW, sessions_dir=base)
        self.assertTrue(block["codex"]["official"])
        self.assertFalse(block["claude"]["official"])
        self.assertEqual(33, block["codex"]["h5_pct"])
        self.assertEqual(1_000, block["claude"]["tokens"])
        self.assertEqual(quota.CLAUDE_WINDOW_H, block["window_h"])

    def test_opencode_block_is_estimated_and_gated_by_explicit_db(self):
        """Sem caminho explicito o coletor NAO toca o banco real: hermetico por padrao."""
        self.assertFalse(quota.collect(Path("/nao/existe"), NOW)["opencode"]["ok"])

    def test_opencode_block_sums_tokens_inside_the_5h_window(self):
        import sqlite3
        with TemporaryDirectory() as tmp:
            db = Path(tmp) / "opencode.db"
            con = sqlite3.connect(db)
            con.execute("CREATE TABLE message (id TEXT PRIMARY KEY, session_id TEXT, "
                        "data TEXT, time_created INTEGER, time_updated INTEGER)")
            data = json.dumps({"role": "assistant", "tokens": {
                "input": 100, "output": 50, "reasoning": 0,
                "cache": {"read": 900, "write": 10}}})
            fresh = int((NOW - timedelta(minutes=30)).timestamp() * 1000)
            stale = int((NOW - timedelta(hours=7)).timestamp() * 1000)
            con.execute("INSERT INTO message VALUES (?,?,?,?,?)",
                        ("m1", "s", data, fresh, fresh))
            con.execute("INSERT INTO message VALUES (?,?,?,?,?)",
                        ("m2", "s", data, stale, stale))
            con.commit()
            con.close()
            block = quota.collect(Path("/nao/existe"), NOW, opencode_db=db)
        self.assertTrue(block["opencode"]["ok"])
        self.assertFalse(block["opencode"]["official"])
        self.assertEqual(160, block["opencode"]["tokens"])   # 150 do turno fresco; fora da janela não conta
        # cache.read nunca entra como consumo: input+output+reasoning+cache.write
        self.assertNotEqual(160 + 900, block["opencode"]["tokens"])


class PayloadContractTests(unittest.TestCase):
    def test_daemon_payload_carries_the_quota_block(self):
        import session_daemon
        with TemporaryDirectory() as tmp:
            projects = Path(tmp) / "projects"
            projects.mkdir()
            payload = session_daemon.build_payload(
                projects, Path(tmp) / "sem-indice.jsonl", 6,
                timezone(timedelta(hours=-3)), NOW)
        self.assertIn("quota", payload["stats"])
        self.assertIn("codex", payload["stats"]["quota"])
        self.assertIn("claude", payload["stats"]["quota"])


if __name__ == "__main__":
    unittest.main()
