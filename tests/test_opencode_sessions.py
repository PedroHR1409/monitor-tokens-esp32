from __future__ import annotations

import io
import json
import sqlite3
import struct
import sys
import tempfile
import unittest
import zlib
from datetime import datetime, timedelta, timezone
from pathlib import Path

TOOLS = Path(__file__).resolve().parents[1] / "tools"
sys.path.insert(0, str(TOOLS))

import opencode_sessions
import session_daemon
from monitor_config import MonitorConfig
from icon_convert import decode_png, resize_fit, render_c


NOW = datetime(2026, 8, 28, 12, 0, tzinfo=timezone.utc)


def _write_db(path: Path, sessions: list[dict], messages: list[dict]) -> Path:
    con = sqlite3.connect(path)
    con.execute("CREATE TABLE session (id TEXT PRIMARY KEY, title TEXT, slug TEXT, "
                "directory TEXT, model TEXT, time_created INTEGER, "
                "time_updated INTEGER, time_archived INTEGER)")
    con.execute("CREATE TABLE message (id TEXT PRIMARY KEY, session_id TEXT, "
                "data TEXT, time_created INTEGER, time_updated INTEGER)")
    for session in sessions:
        con.execute("INSERT INTO session VALUES (?,?,?,?,?,?,?,?)", (
            session["id"], session.get("title"), session.get("slug"),
            session.get("directory"), session.get("model"),
            session.get("time_created"), session.get("time_updated"),
            session.get("time_archived")))
    for message in messages:
        con.execute("INSERT INTO message VALUES (?,?,?,?,?)", (
            message["id"], message["session_id"], message.get("data"),
            message.get("time_created"), message.get("time_updated")))
    con.commit()
    con.close()
    return path


def _session(sid: str, updated: datetime, *, title: str = "Projeto Teste",
             model: str = '{"id":"glm-5.3-flash","providerID":"opencode-go",'
                          '"variant":"high"}',
             directory: str = "") -> dict:
    return {"id": sid, "title": title, "slug": sid, "directory": directory,
            "model": model, "time_created": int(updated.timestamp() * 1000),
            "time_updated": int(updated.timestamp() * 1000)}


def _assistant(session_id: str, created: datetime, *, output: int, cache_read: int,
               input: int = 0) -> dict:
    data = json.dumps({
        "role": "assistant", "modelID": "glm-5.3-flash",
        "tokens": {"input": input, "output": output, "reasoning": 0,
                   "cache": {"read": cache_read, "write": 0}},
    })
    return {"id": "msg-" + session_id + str(created.timestamp()), "session_id": session_id,
            "data": data, "time_created": int(created.timestamp() * 1000),
            "time_updated": int(created.timestamp() * 1000)}


class ProviderMappingTests(unittest.TestCase):
    def test_model_ids_map_to_icon_providers(self):
        self.assertEqual("zai", opencode_sessions.provider_of("glm-5.3-flash", "opencode-go"))
        self.assertEqual("deepseek", opencode_sessions.provider_of("deepseek-v4-flash", "x"))
        self.assertEqual("deepseek", opencode_sessions.provider_of("", "deepseek"))
        self.assertEqual("", opencode_sessions.provider_of("gpt-5.6-sol", "openai"))

    def test_short_model_drops_release_dates(self):
        self.assertEqual("glm-5.3-flash", opencode_sessions.short_model("glm-5.3-flash"))
        self.assertEqual("glm-4.5", opencode_sessions.short_model("glm-4.5-20251001"))


class ScanOpenCodeSessionsTests(unittest.TestCase):
    def test_recent_session_is_work_with_provider_effort_and_context(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = _write_db(Path(tmp) / "opencode.db", [
                _session("ses-a", NOW - timedelta(seconds=30)),
            ], [_assistant("ses-a", NOW - timedelta(seconds=60), output=205,
                           cache_read=69184, input=344)])
            sessions = opencode_sessions.scan_opencode_sessions(
                NOW, NOW - timedelta(hours=24), database=db, ctx_window=131072)
        self.assertEqual(1, len(sessions))
        session = sessions[0]
        self.assertEqual("opencode", session["tool"])
        self.assertEqual("work", session["state"])
        self.assertEqual("zai", session["provider"])
        self.assertEqual("glm-5.3-flash", session["model"])
        self.assertEqual("high", session["effort"])
        self.assertEqual(205 + 344, session["tokensWin"])     # cache.read nao e consumo
        self.assertEqual(69733, session["context_tokens"])
        self.assertEqual(int(69733 * 100 / 131072), session["ctxPct"])
        self.assertEqual("measured", session["context"]["quality"])

    def test_old_session_is_free_and_window_excludes_stale_tokens(self):
        old = NOW - timedelta(hours=2)
        with tempfile.TemporaryDirectory() as tmp:
            db = _write_db(Path(tmp) / "opencode.db", [
                _session("ses-b", old),
            ], [_assistant("ses-b", old, output=900, cache_read=0)])
            sessions = opencode_sessions.scan_opencode_sessions(
                NOW, NOW - timedelta(hours=1), database=db, ctx_window=0)
        self.assertEqual(1, len(sessions))
        self.assertEqual("free", sessions[0]["state"])
        self.assertEqual(0, sessions[0]["tokensWin"])      # fora da janela
        self.assertEqual(900, sessions[0]["context_tokens"])
        self.assertEqual(0, sessions[0]["ctxPct"])         # sem teto declarado
        self.assertEqual("unknown", sessions[0]["context"]["quality"])

    def test_inactive_for_a_day_is_dropped_and_git_branch_is_read(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "proj" / ".git").mkdir(parents=True)
            (root / "proj" / ".git" / "HEAD").write_text("ref: refs/heads/feature/x\n")
            db = _write_db(root / "opencode.db", [
                _session("ses-c", NOW - timedelta(days=2)),
                _session("ses-d", NOW - timedelta(seconds=10),
                         directory=str(root / "proj")),
            ], [])
            sessions = opencode_sessions.scan_opencode_sessions(NOW, database=db)
        self.assertEqual(1, len(sessions))
        self.assertEqual("ses-d", sessions[0]["id"])
        self.assertEqual("x", sessions[0]["branch"])   # read_git_branch devolve o ultimo segmento

    def test_project_name_prefers_directory_basename_over_title(self):
        """AC: cards DeepSeek/GLM mostram o NOME DO PROJETO, nao a 1a mensagem."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db = _write_db(root / "opencode.db", [
                _session("ses-name", NOW - timedelta(seconds=10),
                         title="New session - 2026-08-28T19:48:10.291Z",
                         directory=str(root / "projetos" / "monitor-tokens-esp32")),
                _session("ses-fb", NOW - timedelta(seconds=10),
                         title="Aula de revisao", directory=""),
            ], [])
            sessions = opencode_sessions.scan_opencode_sessions(NOW, database=db)
        by_id = {s["id"]: s["project"] for s in sessions}
        self.assertEqual("monitor-tokens-esp32", by_id["ses-name"])
        self.assertEqual("Aula de revisao", by_id["ses-fb"])   # sem directory: title

    def test_project_name_prefers_directory_basename_over_title(self):
        """AC: cards DeepSeek/GLM mostram o NOME DO PROJETO, nao a 1a mensagem."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db = _write_db(root / "opencode.db", [
                _session("ses-name", NOW - timedelta(seconds=10),
                         title="New session - 2026-08-28T19:48:10.291Z",
                         directory=str(root / "projetos" / "monitor-tokens-esp32")),
                _session("ses-fb", NOW - timedelta(seconds=10),
                         title="Aula de revisao", directory=""),
            ], [])
            sessions = opencode_sessions.scan_opencode_sessions(NOW, database=db)
        by_id = {s["id"]: s["project"] for s in sessions}
        self.assertEqual("monitor-tokens-esp32", by_id["ses-name"])
        self.assertEqual("Aula de revisao", by_id["ses-fb"])   # sem directory: title

    def test_missing_database_returns_empty(self):
        self.assertEqual([], opencode_sessions.scan_opencode_sessions(
            NOW, database=Path("Z:/inexistentes/opencode.db")))


class BuildPayloadIntegrationTests(unittest.TestCase):
    def test_opencode_sessions_enter_board_and_catalog_with_provider(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db = _write_db(root / "opencode.db", [
                _session("ses-live", NOW - timedelta(seconds=20), title="GLM Sessao"),
            ], [_assistant("ses-live", NOW - timedelta(seconds=40), output=500,
                           cache_read=0)])
            payload = session_daemon.build_payload_v1(
                root / "claude", root / "missing-index", 6, timezone.utc, now=NOW,
                opencode_db=db)
            self.assertEqual(1, len(payload["sessions"]))
            self.assertEqual("zai", payload["sessions"][0]["provider"])
            self.assertEqual(1, payload["stats"]["active_12h"])

            # Hermetico por padrao: sem opencode_db o builder ignora o OpenCode.
            payload_sem = session_daemon.build_payload_v1(
                root / "claude", root / "missing-index", 6, timezone.utc, now=NOW)
            self.assertEqual(0, len(payload_sem["sessions"]))

    def test_v2_keeps_provider_and_adds_session_key(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db = _write_db(root / "opencode.db", [
                _session("ses-v2", NOW - timedelta(seconds=20)),
            ], [])
            payload = session_daemon.build_payload_v2(
                root / "claude", root / "missing-index", 6, timezone.utc,
                node_id="n", device_id="d", daemon_instance_id="i", sequence=1,
                now=NOW, opencode_db=db)
        session = payload["sessions"][0]
        self.assertEqual("zai", session["provider"])
        self.assertEqual("n:zai:ses-v2", session["session_key"])


class ConfigOpenCodeWindowTests(unittest.TestCase):
    def test_window_defaults_to_unknown_and_validates_non_negative(self):
        config = MonitorConfig.load(None, environ={})
        self.assertEqual(0, config.usage.opencode_context_window)
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "monitor.toml"
            path.write_text("[usage]\nopencode_context_window = -1\n", encoding="utf-8")
            with self.assertRaises(ValueError):
                MonitorConfig.load(path, environ={})


def _png(width: int, height: int, rgba_rows: list[list[int]]) -> bytes:
    stride = width * 4
    raw = b"".join(b"\x00" + bytes(row) for row in rgba_rows)

    def chunk(kind: bytes, payload: bytes) -> bytes:
        return (struct.pack(">I", len(payload)) + kind + payload
                + struct.pack(">I", zlib.crc32(kind + payload) & 0xFFFFFFFF))

    ihdr = struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr)
            + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))


class IconConvertTests(unittest.TestCase):
    def test_decode_resize_and_c_render(self):
        png = _png(2, 2, [
            [255, 0, 0, 255, 0, 255, 0, 255],
            [0, 0, 255, 255, 255, 255, 255, 0],
        ])
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "t.png"
            path.write_bytes(png)
            width, height, pixels = decode_png(path)
        self.assertEqual((2, 2), (width, height))
        self.assertEqual([255, 0, 0, 255], pixels[0:4])

        canvas = resize_fit(width, height, pixels)
        self.assertEqual(40 * 40 * 4, len(canvas))
        first_quadrant = (10 * 40 + 10) * 4            # pixel (0,0) = vermelho opaco
        self.assertEqual(255, canvas[first_quadrant + 3])
        self.assertEqual(255, canvas[first_quadrant])       # canvas em RGBA; BGR so no .c
        bottom_right = (39 * 40 + 39) * 4              # pixel (1,1) = branco alfa 0
        self.assertEqual(0, canvas[bottom_right + 3])

        text = render_c("test_icon", canvas)
        self.assertIn("LV_COLOR_FORMAT_ARGB8888", text)
        self.assertIn(".w = 40,", text)
        self.assertIn("uint8_t test_icon_map[]", text)


if __name__ == "__main__":
    unittest.main()
