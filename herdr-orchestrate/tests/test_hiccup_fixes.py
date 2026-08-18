#!/usr/bin/env python3
import contextlib
import io
import json
from pathlib import Path
from unittest import mock

from test_worktree_profile_and_land import HerdBase, run_git


class SpawnHiccups(HerdBase):
    def setUp(self):
        super().setUp()
        self.calls = []
        self.starts = 0
        self.timeout_once = False

        def fake_herdr(*args):
            self.calls.append(args)
            if args[:2] == ("tab", "create"):
                n = sum(c[:2] == ("tab", "create") for c in self.calls)
                return 0, {"result": {"root_pane": {"pane_id": f"p{n}"},
                                      "tab": {"tab_id": f"t{n}"}}}
            if args[:2] == ("worktree", "create"):
                n = sum(c[:2] == ("worktree", "create") for c in self.calls)
                return 0, {"result": {
                    "root_pane": {"pane_id": f"wp{n}",
                                  "cwd": str(self.repo / f"wt{n}")},
                    "tab": {"tab_id": f"wt{n}"},
                    "workspace": {"workspace_id": f"w{n}"},
                }}
            if args[:2] == ("agent", "start"):
                self.starts += 1
                if self.timeout_once and self.starts == 1:
                    return 1, {"raw": "timed out waiting for agent startup"}
            return 0, {}

        for name, replacement in [
            ("herdr", fake_herdr),
            ("live_agents", lambda: {}),
            ("pretrust", lambda *_: None),
            ("read_pane", lambda *_args, **_kwargs: "MoonshotAI Kimi K3"),
        ]:
            patcher = mock.patch.object(self.herd, name, replacement)
            patcher.start()
            self.addCleanup(patcher.stop)

    def spawn(self, argv):
        out, err = io.StringIO(), io.StringIO()
        code = 0
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            try:
                self.herd.cmd_spawn(argv)
            except SystemExit as exc:
                code = exc.code
        return code, out.getvalue(), err.getvalue()

    def start_call(self):
        return next(c for c in reversed(self.calls) if c[:2] == ("agent", "start"))

    def test_baked_flag_before_kind_is_ignored(self):
        code, out, err = self.spawn(["lane", "--approve", "--kind", "pi"])
        self.assertEqual(code, 0, err)
        self.assertTrue(json.loads(out)["ok"])
        self.assertEqual(self.start_call().count("--approve"), 1)
        self.assertIn("ignoring duplicate pi launch flag --approve", err)

    def test_baked_flag_value_is_consumed_and_ignored(self):
        code, _, err = self.spawn(
            ["lane", "--model", "not/the-baked-model", "--kind", "pi"])
        self.assertEqual(code, 0, err)
        call = self.start_call()
        self.assertEqual(call.count("--model"), 1)
        self.assertIn("moonshotai/kimi-k3", call)
        self.assertNotIn("not/the-baked-model", call)

    def test_truly_unknown_flag_still_fails(self):
        code, out, err = self.spawn(["lane", "--kind", "pi", "--bogus"])
        self.assertEqual((code, out), (1, ""))
        self.assertEqual(json.loads(err)["error"], "unknown arg --bogus")

    def test_startup_timeout_cleans_up_and_retries_once(self):
        self.timeout_once = True
        code, out, err = self.spawn(["lane", "--kind", "pi", "--worktree"])
        self.assertEqual(code, 0, err)
        result = json.loads(out)
        self.assertEqual(result["pane"], "wp2")
        self.assertEqual(self.starts, 2)
        self.assertEqual(sum(c[:2] == ("worktree", "create") for c in self.calls), 2)
        self.assertEqual(sum(c[:2] == ("worktree", "remove") for c in self.calls), 1)
        self.assertIn("retrying once", err)

    def test_plain_tab_startup_timeout_retries(self):
        self.timeout_once = True
        code, out, err = self.spawn(["lane", "--kind", "pi"])
        self.assertEqual(code, 0, err)
        self.assertEqual(json.loads(out)["pane"], "p2")
        self.assertEqual(self.starts, 2)
        self.assertEqual(sum(c[:2] == ("tab", "close") for c in self.calls), 1)

    def test_profile_worktree_timeout_removes_worktree_and_reuses_branch(self):
        (Path.home() / ".pi" / "agent-test").mkdir(parents=True)
        self.timeout_once = True
        code, out, err = self.spawn(
            ["lane", "--kind", "pi", "--worktree", "--profile", "test"])
        self.assertEqual(code, 0, err)
        self.assertEqual(json.loads(out)["pane"], "p2")
        self.assertEqual(self.starts, 2)
        self.assertEqual(sum(c[:2] == ("tab", "close") for c in self.calls), 1)
        wt = Path(self.herd.WORKTREES) / "proj-lane"
        self.assertTrue(wt.is_dir())
        self.assertEqual(self.read_ledger()["lanes"]["lane"]["cwd"], str(wt))


class LandDirtyPaths(HerdBase):
    def land(self, lane):
        out, err = io.StringIO(), io.StringIO()
        code = 0
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            try:
                self.herd.cmd_land([lane])
            except SystemExit as exc:
                code = exc.code
        return code, out.getvalue(), err.getvalue()

    def make_lane_branch(self, lane):
        branch = f"lane/{lane}"
        run_git(self.repo, "checkout", "-b", branch)
        (self.repo / "lane.txt").write_text("lane\n")
        run_git(self.repo, "add", "lane.txt")
        run_git(self.repo, "commit", "-m", "lane")
        run_git(self.repo, "checkout", "main")
        return branch

    def test_project_dirty_error_lists_untracked_and_modified_paths(self):
        branch = self.make_lane_branch("project-dirty")
        self.write_ledger({"ship_mode": "merge", "lanes": {
            "project-dirty": {"kind": "pi", "state": "reviewed",
                              "branch": branch, "base": "main"}}})
        (self.repo / "seed.txt").write_text("modified\n")
        (self.repo / "new.txt").write_text("untracked\n")

        code, out, err = self.land("project-dirty")

        self.assertEqual((code, out), (4, ""))
        detail = json.loads(err)
        self.assertEqual(detail["modified"], ["seed.txt"])
        self.assertEqual(detail["untracked"], ["new.txt"])

    def test_lane_dirty_error_lists_untracked_and_modified_paths(self):
        branch = self.make_lane_branch("lane-dirty")
        worktree = Path(self.tmp.name) / "lane-worktree"
        run_git(self.repo, "worktree", "add", str(worktree), branch)
        (worktree / "seed.txt").write_text("modified\n")
        (worktree / "new.txt").write_text("untracked\n")
        self.write_ledger({"ship_mode": "merge", "lanes": {
            "lane-dirty": {"kind": "pi", "state": "reviewed",
                           "branch": branch, "base": "main",
                           "cwd": str(worktree)}}})

        code, out, err = self.land("lane-dirty")

        self.assertEqual((code, out), (4, ""))
        detail = json.loads(err)
        self.assertEqual(detail["modified"], ["seed.txt"])
        self.assertEqual(detail["untracked"], ["new.txt"])
        self.assertIn("lane lane-dirty worktree", detail["error"])
