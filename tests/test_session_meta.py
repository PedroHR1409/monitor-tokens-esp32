from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

TOOLS = Path(__file__).resolve().parents[1] / "tools"
sys.path.insert(0, str(TOOLS))

from session_meta import read_git_branch


class WorktreeBranchTests(unittest.TestCase):
    def test_worktree_git_file_resolves_branch_via_gitdir(self):
        """Em worktrees, .git e um ARQUIVO (gitdir:) — a branch vive no gitdir."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo_git = root / "repo" / ".git" / "worktrees" / "fix-28796"
            repo_git.mkdir(parents=True)
            (repo_git / "HEAD").write_text("ref: refs/heads/fix-28796-ajustes" + chr(10))
            wt = root / "wt"
            wt.mkdir()
            (wt / ".git").write_text(f"gitdir: {repo_git.as_posix()}" + chr(10), encoding="utf-8")
            self.assertEqual("fix-28796-ajustes", read_git_branch(str(wt)))

    def test_worktree_with_relative_gitdir(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo_git = root / "repo" / ".git" / "worktrees" / "wt"
            repo_git.mkdir(parents=True)
            (repo_git / "HEAD").write_text("ref: refs/heads/feature/x" + chr(10))
            wt = root / "wt"
            wt.mkdir()
            (wt / ".git").write_text("gitdir: ../repo/.git/worktrees/wt" + chr(10))
            self.assertEqual("x", read_git_branch(str(wt)))

    def test_main_repo_and_no_git_unchanged(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / ".git" / "refs").mkdir(parents=True)
            (root / ".git" / "HEAD").write_text("ref: refs/heads/master" + chr(10))
            self.assertEqual("master", read_git_branch(str(root)))
        with tempfile.TemporaryDirectory() as tmp:
            plain = Path(tmp) / "proj"
            plain.mkdir()
            self.assertEqual("sem git", read_git_branch(str(plain)))

    def test_subdirectory_walks_up_to_repo_root(self):
        """Sessao aberta num subdiretorio do repo: o .git esta no nivel de cima.
        Sem walk-up o card aparecia 'sem git' e o operador nao identificava."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "repo" / ".git" / "refs").mkdir(parents=True)
            (root / "repo" / ".git" / "HEAD").write_text(
                "ref: refs/heads/feat/26925-add-sk" + chr(10))
            subdir = root / "repo" / "src" / "modules"
            subdir.mkdir(parents=True)
            self.assertEqual("26925-add-sk", read_git_branch(str(subdir)))

    def test_walk_up_stops_at_root_without_git(self):
        with tempfile.TemporaryDirectory() as tmp:
            plain = Path(tmp) / "a" / "b" / "c"
            plain.mkdir(parents=True)
            self.assertEqual("sem git", read_git_branch(str(plain)))


if __name__ == "__main__":
    unittest.main()
