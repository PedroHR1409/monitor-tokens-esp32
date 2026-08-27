"""Uma mensagem, uma contagem.

O transcript grava uma linha por BLOCO de conteudo da mesma resposta — `thinking`,
`text`, um `tool_use` por ferramenta — e todas repetem o MESMO objeto `usage`. Somar
entrada por entrada inflava tudo que depende de tokens. Medido em 27/08/2026:

    janela de 5h : 1117 entradas para 522 mensagens reais
                   3.714.894 -> 1.540.194 tokens (2,41x)
    tokens hoje  : 8.486.888 -> 3.706.304        (2,29x)

Os 373 grupos repetidos tinham `usage` identico e viviam no mesmo arquivo: era
repeticao de serializacao, nunca consumo real.
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
import usage_tracker  # noqa: E402

NOW = datetime(2026, 8, 27, 15, 0, tzinfo=timezone.utc)
TZ = timezone(timedelta(hours=-3))


def bloco(ts: datetime, msg_id: str, tipo: str, tokens: int) -> str:
    """Uma linha do transcript: um bloco de conteudo carregando o usage da mensagem."""
    return json.dumps({
        "timestamp": ts.isoformat().replace("+00:00", "Z"),
        "type": "assistant",
        "message": {
            "id": msg_id,
            "model": "claude-opus-5",
            "content": [{"type": tipo}],
            "usage": {"input_tokens": tokens, "output_tokens": 0,
                      "cache_creation_input_tokens": 0,
                      "cache_read_input_tokens": 999_999},
        },
    })


def escreve(projects: Path, linhas) -> Path:
    pasta = projects / "proj"
    pasta.mkdir(parents=True, exist_ok=True)
    caminho = pasta / "sessao.jsonl"
    caminho.write_text("\n".join(linhas) + "\n", encoding="utf-8")
    return caminho


class DedupTokensTests(unittest.TestCase):
    def test_the_same_message_split_in_blocks_counts_once(self):
        vistos = set()
        linhas = [json.loads(bloco(NOW, "msg_a", t, 1000))
                  for t in ("thinking", "text", "tool_use", "tool_use")]
        total = sum(usage_tracker.dedup_tokens(vistos, o) for o in linhas)
        self.assertEqual(1000, total, "4 blocos, 1 resposta, 1 cobranca")

    def test_different_messages_still_add_up(self):
        vistos = set()
        total = sum(usage_tracker.dedup_tokens(vistos, json.loads(bloco(NOW, m, "text", 500)))
                    for m in ("msg_a", "msg_b", "msg_c"))
        self.assertEqual(1500, total)

    def test_an_event_without_message_id_is_counted(self):
        """Sem id nao da para saber se repete; descartar subestimaria o consumo."""
        obj = json.loads(bloco(NOW, "", "text", 700))
        del obj["message"]["id"]
        self.assertEqual(700, usage_tracker.dedup_tokens(set(), obj))

    def test_cache_read_stays_out_of_the_total(self):
        """999.999 de cache read no fixture nao podem aparecer na soma."""
        self.assertEqual(1000, usage_tracker.dedup_tokens(set(),
                                                          json.loads(bloco(NOW, "m", "text", 1000))))

    def test_non_assistant_events_contribute_nothing(self):
        self.assertEqual(0, usage_tracker.dedup_tokens(set(), {"type": "user"}))


class DailyTotalTests(unittest.TestCase):
    def test_daily_total_does_not_multiply_by_the_number_of_blocks(self):
        with TemporaryDirectory() as tmp:
            projects = Path(tmp)
            escreve(projects, [bloco(NOW, "msg_a", t, 2000)
                               for t in ("thinking", "text", "tool_use")]
                    + [bloco(NOW, "msg_b", "text", 500)])
            out = usage_tracker.collect(projects, TZ, NOW)
        self.assertEqual(2500, out["tokens_today"])

    def test_the_heatmap_bucket_is_not_multiplied_either(self):
        """O balde recebe o token na PRIMEIRA ocorrencia, nao uma vez por bloco."""
        with TemporaryDirectory() as tmp:
            projects = Path(tmp)
            escreve(projects, [bloco(NOW, "msg_a", t, 3000)
                               for t in ("thinking", "text", "tool_use")])
            out = usage_tracker.collect(projects, TZ, NOW)
        self.assertEqual(3000, sum(out["spark"]))

    def test_dedup_spans_the_whole_day_not_just_one_file(self):
        with TemporaryDirectory() as tmp:
            projects = Path(tmp)
            for nome in ("a", "b"):
                pasta = projects / nome
                pasta.mkdir()
                (pasta / "s.jsonl").write_text(
                    bloco(NOW, "msg_compartilhada", "text", 4000) + "\n", encoding="utf-8")
            out = usage_tracker.collect(projects, TZ, NOW)
        self.assertEqual(4000, out["tokens_today"],
                         "mesma mensagem em dois arquivos continua sendo uma")


class FiveHourEstimateTests(unittest.TestCase):
    def test_the_claude_estimate_counts_each_message_once(self):
        with TemporaryDirectory() as tmp:
            projects = Path(tmp)
            escreve(projects, [bloco(NOW, "msg_a", t, 10_000)
                               for t in ("thinking", "text", "tool_use", "tool_use")])
            out = quota.claude_consumption(projects, NOW)
        self.assertEqual(10_000, out["tokens"])

    def test_the_percentage_follows_the_corrected_total(self):
        """O bug dobrava o percentual: com teto de 20k, 4 blocos davam 200%."""
        with TemporaryDirectory() as tmp:
            projects = Path(tmp)
            escreve(projects, [bloco(NOW, "msg_a", t, 10_000)
                               for t in ("text", "tool_use", "tool_use", "tool_use")])
            out = quota.claude_consumption(projects, NOW, budget=20_000)
        self.assertEqual(50, out["pct"])


if __name__ == "__main__":
    unittest.main()
