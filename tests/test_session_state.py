from __future__ import annotations

import sys
import unittest
from pathlib import Path

TOOLS = Path(__file__).resolve().parents[1] / "tools"
sys.path.insert(0, str(TOOLS))

from session_state import session_display_name


class SessionDisplayNameTests(unittest.TestCase):
    def test_non_main_branch_wins_over_project(self):
        self.assertEqual("fix-28796-ajustes",
                         session_display_name("lakehouse-tech-fabric", "fix-28796-ajustes"))
        self.assertEqual("feat/27816-remover-monolitico",
                         session_display_name("lakehouse-tech-fabric",
                                              "feat/27816-remover-monolitico"))

    def test_main_or_master_or_empty_keeps_project(self):
        self.assertEqual("monitor-tokens-esp32",
                         session_display_name("monitor-tokens-esp32", "master"))
        self.assertEqual("monitor-tokens-esp32",
                         session_display_name("monitor-tokens-esp32", "Main"))
        self.assertEqual("monitor-tokens-esp32",
                         session_display_name("monitor-tokens-esp32", ""))

    def test_case_insensitive_and_accents(self):
        self.assertEqual("projeto", session_display_name("projeto", "MAIN"))
        self.assertEqual("fix-ao", session_display_name("projeto", "fix-ão"))


if __name__ == "__main__":
    unittest.main()
