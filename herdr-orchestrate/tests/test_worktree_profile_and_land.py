#!/usr/bin/env python3
"""Pins two fixes:

1. `spawn --kind pi --worktree --profile <name>` works: herd creates the git
   worktree + branch itself (herdr worktree create has no --env), spawns a
   tab lane with the profile env --cwd'd into it, and records real worktree
   metadata (branch/base/cwd/git_worktree) so land and close behave like a
   native worktree lane; close removes the worktree via git.

2. `land` never silently no-ops: in merge/pr ship_mode a lane without
   worktree/branch metadata dies loudly (exit 4) instead of returning ok.
"""
import contextlib
import io
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest import mock

from test_pretrust import load_herd


def run_git(cwd, *args):
    return subprocess.run(["git", "-C", str(cwd), *args],
                          capture_output=True, text=True, check=True)


def make_repo(path):
    path.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", "-b", "main", str(path)],
                   capture_output=True, check=True)
    run_git(path, "config", "user.email", "t@t")
    run_git(path, "config", "user.name", "t")
    (path / "seed.txt").write_text("seed\n")
    (path / ".gitignore").write_text(".herd/\n")
    run_git(path, "add", "-A")
    run_git(path, "commit", "-m", "seed")
    return path


class HerdBase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        patcher = mock.patch.dict(os.environ, {"HOME": str(root / "home")})
        patcher.start()
        self.addCleanup(patcher.stop)
        self.repo = make_repo(root / "proj")
        self.herd = load_herd()
        for attr, val in [("PROJECT", str(self.repo)),
                          ("HERD_DIR", str(self.repo / ".herd")),
                          ("LEDGER", str(self.repo / ".herd" / "ledger.json")),
                          ("WORKTREES", str(root / "worktrees"))]:
            setattr(self.herd, attr, val)

    def write_ledger(self, led):
        (self.repo / ".herd").mkdir(exist_ok=True)
        (self.repo / ".herd" / "ledger.json").write_text(json.dumps(led))

    def read_ledger(self):
        return json.loads((self.repo / ".herd" / "ledger.json").read_text())


class SpawnProfileWorktree(HerdBase):
    def setUp(self):
        super().setUp()
        (Path(os.environ["HOME"]) / ".pi" / "agent-test").mkdir(parents=True)
        self.calls = []

        def fake_herdr(*args, check=True):
            self.calls.append(args)
            if args[:2] == ("tab", "create"):
                return 0, {"result": {"root_pane": {"pane_id": "p1"},
                                      "tab": {"tab_id": "t1"}}}
            return 0, {}
        for name, repl in [("herdr", fake_herdr), ("live_agents", lambda: {}),
                           ("pretrust", lambda *a: None),
                           ("read_pane", lambda *a, **k: "kimi k3"),
                           ("agent_status", lambda *a: None)]:
            p = mock.patch.object(self.herd, name, repl)
            p.start()
            self.addCleanup(p.stop)

    def spawn(self):
        with contextlib.redirect_stdout(io.StringIO()):
            self.herd.cmd_spawn(["wlane", "--kind", "pi", "--worktree",
                                 "--profile", "test"])
        return self.read_ledger()["lanes"]["wlane"]

    def test_worktree_branch_env_and_ledger(self):
        rec = self.spawn()
        wt = Path(self.herd.WORKTREES) / "proj-wlane"
        self.assertTrue(wt.is_dir())
        self.assertIn(str(wt), run_git(self.repo, "worktree", "list").stdout)
        run_git(self.repo, "show-ref", "--verify", "refs/heads/lane/wlane")
        self.assertEqual(rec["branch"], "lane/wlane")
        self.assertEqual(rec["base"], "main")
        self.assertEqual(rec["cwd"], str(wt))
        self.assertEqual(rec["git_worktree"], os.path.realpath(self.repo))
        self.assertEqual(rec["profile"], "test")
        self.assertIsNone(rec["workspace"])
        tab = next(c for c in self.calls if c[:2] == ("tab", "create"))
        self.assertIn("--env", tab)
        self.assertEqual(tab[tab.index("--env") + 1],
                         "PI_CODING_AGENT_DIR="
                         + os.path.expanduser("~/.pi/agent-test"))
        self.assertEqual(tab[tab.index("--cwd") + 1], str(wt))

    def test_close_removes_git_worktree(self):
        self.spawn()
        wt = Path(self.herd.WORKTREES) / "proj-wlane"
        with contextlib.redirect_stdout(io.StringIO()):
            self.herd.cmd_close(["wlane"])
        self.assertFalse(wt.exists())
        self.assertNotIn(str(wt), run_git(self.repo, "worktree", "list").stdout)
        # branch stays until landed — same contract as native worktree lanes
        run_git(self.repo, "show-ref", "--verify", "refs/heads/lane/wlane")

    def test_close_refuses_dirty_worktree(self):
        self.spawn()
        wt = Path(self.herd.WORKTREES) / "proj-wlane"
        (wt / "uncommitted.txt").write_text("x\n")
        with contextlib.redirect_stderr(io.StringIO()) as err, \
                self.assertRaises(SystemExit) as cm:
            self.herd.cmd_close(["wlane"])
        self.assertEqual(cm.exception.code, 4)
        self.assertIn("uncommitted", err.getvalue())
        self.assertTrue(wt.exists())


class LandGate(HerdBase):
    def land(self, lane):
        out, err = io.StringIO(), io.StringIO()
        code = 0
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            try:
                self.herd.cmd_land([lane])
            except SystemExit as e:
                code = e.code
        return code, out.getvalue(), err.getvalue()

    def test_merge_mode_branchless_lane_dies(self):
        # the silent-no-op regression: old herd printed ok here
        self.write_ledger({"ship_mode": "merge", "lanes": {
            "ghost": {"kind": "pi", "state": "reviewed"}}})
        code, out, err = self.land("ghost")
        self.assertEqual(code, 4)
        self.assertNotIn('"ok": true', out)
        self.assertIn("refusing to silently skip", err)

    def test_pr_mode_branchless_lane_dies(self):
        self.write_ledger({"ship_mode": "pr", "lanes": {
            "ghost": {"kind": "pi", "state": "reviewed"}}})
        code, out, err = self.land("ghost")
        self.assertEqual(code, 4)
        self.assertIn("refusing to silently skip", err)

    def test_unrecorded_but_existing_branch_named_in_error(self):
        run_git(self.repo, "branch", "lane/ghost")
        self.write_ledger({"ship_mode": "merge", "lanes": {
            "ghost": {"kind": "pi", "state": "reviewed"}}})
        code, _, err = self.land("ghost")
        self.assertEqual(code, 4)
        self.assertIn("exists in the repo but is not in the ledger", err)

    def test_scratch_mode_still_ok(self):
        self.write_ledger({"ship_mode": "scratch", "lanes": {
            "tabby": {"kind": "pi", "state": "reviewed"}}})
        code, out, _ = self.land("tabby")
        self.assertEqual(code, 0)
        self.assertIn("scratch mode", out)

    def test_merge_mode_recorded_branch_merges(self):
        run_git(self.repo, "checkout", "-b", "lane/real")
        (self.repo / "work.txt").write_text("done\n")
        run_git(self.repo, "add", "-A")
        run_git(self.repo, "commit", "-m", "lane work")
        run_git(self.repo, "checkout", "main")
        self.write_ledger({"ship_mode": "merge", "lanes": {
            "real": {"kind": "pi", "state": "reviewed",
                     "branch": "lane/real", "base": "main"}}})
        code, out, err = self.land("real")
        self.assertEqual(code, 0, err)
        self.assertIn('"merged": "lane/real"', out)
        merges = run_git(self.repo, "log", "--merges", "--oneline").stdout
        self.assertIn("lane/real", merges)
        self.assertTrue((self.repo / "work.txt").exists())
        self.assertEqual(self.read_ledger()["lanes"]["real"]["state"], "done")


if __name__ == "__main__":
    unittest.main()
