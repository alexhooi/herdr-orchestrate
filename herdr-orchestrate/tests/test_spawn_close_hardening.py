#!/usr/bin/env python3
import contextlib
import io
import json
import os
from pathlib import Path
from unittest import mock

from test_worktree_profile_and_land import HerdBase, run_git


class HomeLedgerGuard(HerdBase):
    def use_home_as_project(self):
        home = Path(self.tmp.name) / "guarded-home"
        home.mkdir()
        self.herd.PROJECT = str(home)
        self.herd.HERD_DIR = str(home / ".herd")
        self.herd.LEDGER = str(home / ".herd" / "ledger.json")
        return home

    def test_read_without_home_ledger_returns_empty(self):
        home = self.use_home_as_project()
        real_expanduser = os.path.expanduser
        with mock.patch.object(
                self.herd.os.path, "expanduser",
                side_effect=lambda path: (str(home) if path == "~"
                                          else real_expanduser(path))):
            ledger = self.herd.load()

        self.assertEqual(ledger, {"ship_mode": "scratch", "lanes": {}})
        self.assertFalse((home / ".herd").exists())

    def test_spawn_refuses_home_before_side_effects(self):
        home = self.use_home_as_project()
        (home / ".git").mkdir()
        ignore = home / ".gitignore"
        ignore.write_bytes(b"dotfiles\n")
        calls = []
        real_expanduser = os.path.expanduser
        err = io.StringIO()
        with mock.patch.object(
                self.herd.os.path, "expanduser",
                side_effect=lambda path: (str(home) if path == "~"
                                          else real_expanduser(path))), \
                mock.patch.object(
                    self.herd, "herdr",
                    side_effect=lambda *args: calls.append(args)), \
                contextlib.redirect_stderr(err), \
                self.assertRaises(SystemExit) as cm:
            self.herd.cmd_spawn(["home", "--kind", "codex"])

        self.assertEqual(cm.exception.code, 1)
        detail = json.loads(err.getvalue())
        self.assertIn("refusing to create a ledger in your home directory",
                      detail["error"])
        self.assertIn("HERD_PROJECT", detail["error"])
        self.assertEqual(calls, [])
        self.assertEqual(ignore.read_bytes(), b"dotfiles\n")
        self.assertFalse((home / ".herd").exists())

    def test_mutating_command_refuses_home_without_lock_residue(self):
        home = self.use_home_as_project()
        real_expanduser = os.path.expanduser
        out, err = io.StringIO(), io.StringIO()
        with mock.patch.object(
                self.herd.os.path, "expanduser",
                side_effect=lambda path: (str(home) if path == "~"
                                          else real_expanduser(path))), \
                contextlib.redirect_stdout(out), \
                contextlib.redirect_stderr(err), \
                self.assertRaises(SystemExit) as cm:
            self.herd.cmd_set(["ship_mode", "merge"])

        self.assertEqual(cm.exception.code, 1)
        self.assertEqual(out.getvalue(), "")
        self.assertIn("HERD_PROJECT", json.loads(err.getvalue())["error"])
        self.assertFalse((home / ".herd").exists())

    def test_existing_home_ledger_loads(self):
        home = self.use_home_as_project()
        ledger = {"ship_mode": "scratch", "lanes": {"kept": {}}}
        (home / ".herd").mkdir()
        (home / ".herd" / "ledger.json").write_text(json.dumps(ledger))
        real_expanduser = os.path.expanduser
        with mock.patch.object(
                self.herd.os.path, "expanduser",
                side_effect=lambda path: (str(home) if path == "~"
                                          else real_expanduser(path))):
            self.assertEqual(self.herd.load(), ledger)


class SpawnHardening(HerdBase):
    def setUp(self):
        super().setUp()
        self.tab_count = 0
        self.calls = []

        def fake_herdr(*args):
            self.calls.append(args)
            if args[:2] == ("tab", "create"):
                self.tab_count += 1
                return 0, {"result": {
                    "root_pane": {"pane_id": f"p{self.tab_count}"},
                    "tab": {"tab_id": f"t{self.tab_count}"},
                }}
            if args[:2] == ("worktree", "create"):
                self.tab_count += 1
                return 0, {"result": {
                    "root_pane": {"pane_id": f"p{self.tab_count}",
                                  "cwd": str(self.repo / "fake-worktree")},
                    "tab": {"tab_id": f"t{self.tab_count}"},
                    "workspace": {"workspace_id": f"w{self.tab_count}"},
                }}
            return 0, {}

        for name, replacement in [
            ("herdr", fake_herdr),
            ("live_agents", lambda: {}),
            ("pretrust", lambda *_: None),
        ]:
            patcher = mock.patch.object(self.herd, name, replacement)
            patcher.start()
            self.addCleanup(patcher.stop)

    def spawn(self, lane, *args):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.herd.cmd_spawn([lane, "--kind", "codex", *args])
        return json.loads(out.getvalue())

    def test_subdirectory_cwd_warns(self):
        subdir = self.repo / "Packages" / "ScanUICore"
        subdir.mkdir(parents=True)

        result = self.spawn("subdir", "--cwd", str(subdir))

        self.assertIn("warning", result)
        self.assertIn(f"spawn cwd {subdir.resolve()}", result["warning"])
        self.assertIn(f"project root {self.repo.resolve()}", result["warning"])
        self.assertIn("nested .herd/ = forked ledger", result["warning"])

    def test_project_root_cwd_does_not_warn(self):
        result = self.spawn("root", "--cwd", str(self.repo))
        self.assertNotIn("warning", result)

    def test_relative_cwd_is_resolved_from_project(self):
        subdir = self.repo / "sub"
        subdir.mkdir()

        result = self.spawn("relative", "--cwd", "sub")

        expected = str(subdir.resolve())
        tab = next(call for call in self.calls
                   if call[:2] == ("tab", "create"))
        self.assertEqual(tab[tab.index("--cwd") + 1], expected)
        self.assertEqual(result["cwd"], expected)
        self.assertEqual(self.read_ledger()["lanes"]["relative"]["cwd"],
                         expected)

    def test_subdir_of_project_worktree_still_warns(self):
        worktree = Path(self.herd.WORKTREES) / "proj-orchestrator"
        worktree.parent.mkdir(parents=True)
        run_git(self.repo, "worktree", "add", "-b", "lane/orchestrator",
                str(worktree))
        self.herd.PROJECT = str(worktree)
        self.herd.HERD_DIR = str(worktree / ".herd")
        self.herd.LEDGER = str(worktree / ".herd" / "ledger.json")
        subdir = worktree / "Packages" / "ScanUICore"
        subdir.mkdir(parents=True)

        result = self.spawn("worktree-subdir", "--cwd", str(subdir))

        self.assertIn("warning", result)
        self.assertIn(f"spawn cwd {subdir.resolve()}", result["warning"])

    def test_worktree_spawn_from_subdirectory_does_not_warn(self):
        subdir = self.repo / "Packages" / "ScanUICore"
        subdir.mkdir(parents=True)

        result = self.spawn("new-worktree", "--cwd", str(subdir),
                            "--worktree")

        self.assertNotIn("warning", result)

    def test_missing_gitignore_is_created(self):
        (self.repo / ".gitignore").unlink()

        self.spawn("missing-ignore")

        self.assertEqual((self.repo / ".gitignore").read_bytes(), b".herd/\n")

    def test_gitignore_entry_is_appended_once(self):
        ignore = self.repo / ".gitignore"
        ignore.write_bytes(b"build/")

        self.spawn("append-ignore-1")
        self.spawn("append-ignore-2")

        self.assertEqual(ignore.read_bytes(), b"build/\n.herd/\n")

    def test_existing_gitignore_entry_is_unchanged(self):
        ignore = self.repo / ".gitignore"
        original = b"build/\n.herd/\n# keep this exact\n"
        ignore.write_bytes(original)

        self.spawn("keep-ignore-1")
        after_first = ignore.read_bytes()
        self.spawn("keep-ignore-2")

        self.assertEqual(after_first, original)
        self.assertEqual(ignore.read_bytes(), original)

    def test_non_git_project_gets_no_gitignore(self):
        project = Path(self.tmp.name) / "not-git"
        project.mkdir()
        self.herd.PROJECT = str(project)
        self.herd.HERD_DIR = str(project / ".herd")
        self.herd.LEDGER = str(project / ".herd" / "ledger.json")

        self.spawn("not-git")

        self.assertFalse((project / ".gitignore").exists())


class CloseIntegrated(HerdBase):
    def make_worktree_lane(self, lane):
        worktree = Path(self.tmp.name) / f"worktree-{lane}"
        branch = f"lane/{lane}"
        run_git(self.repo, "worktree", "add", "-b", branch, str(worktree))
        self.write_ledger({"ship_mode": "scratch", "lanes": {
            lane: {"kind": "codex", "state": "done", "ours": True,
                   "pane": None, "tab": None, "workspace": None,
                   "cwd": str(worktree), "git_worktree": str(self.repo),
                   "branch": branch, "base": "main"},
        }})
        return worktree

    def close(self, lane, *args):
        out, err = io.StringIO(), io.StringIO()
        code = 0
        with mock.patch.object(self.herd, "agent_status", return_value=None), \
                contextlib.redirect_stdout(out), \
                contextlib.redirect_stderr(err):
            try:
                self.herd.cmd_close([lane, *args])
            except SystemExit as exc:
                code = exc.code
        return code, out.getvalue(), err.getvalue()

    def test_identical_dirty_paths_are_integrated(self):
        worktree = self.make_worktree_lane("identical")
        (worktree / "copied.txt").write_text("same\n")
        (self.repo / "copied.txt").write_text("same\n")

        code, out, err = self.close("identical", "--integrated")

        self.assertEqual(code, 0, err)
        self.assertTrue(json.loads(out)["ok"])
        self.assertFalse(worktree.exists())

    def test_unintegrated_differing_path_is_listed(self):
        worktree = self.make_worktree_lane("differing")
        (worktree / "copied.txt").write_text("lane copy\n")
        (self.repo / "copied.txt").write_text("uncommitted project copy\n")

        code, out, err = self.close("differing", "--integrated")

        self.assertEqual((code, out), (4, ""))
        self.assertEqual(json.loads(err)["differing"], ["copied.txt"])
        self.assertTrue(worktree.exists())

    def test_newer_committed_project_copy_is_integrated(self):
        worktree = self.make_worktree_lane("committed")
        lane_copy = worktree / "copied.txt"
        project_copy = self.repo / "copied.txt"
        lane_copy.write_text("integrated lane copy\n")
        project_copy.write_text("integrated lane copy\n")
        run_git(self.repo, "add", "copied.txt")
        run_git(self.repo, "commit", "-m", "integrate lane copy")
        project_copy.write_text("newer follow-up copy\n")
        run_git(self.repo, "add", "copied.txt")
        run_git(self.repo, "commit", "-m", "edit integrated file")
        os.utime(lane_copy, ns=(1_000_000_000, 1_000_000_000))

        code, out, err = self.close("committed", "--integrated")

        self.assertEqual(code, 0, err)
        self.assertTrue(json.loads(out)["ok"])
        self.assertFalse(worktree.exists())

    def test_unrelated_newer_committed_copy_is_not_integrated(self):
        worktree = self.make_worktree_lane("unrelated")
        lane_copy = worktree / "copied.txt"
        lane_copy.write_text("lane-only work\n")
        (self.repo / "copied.txt").write_text("unrelated project work\n")
        run_git(self.repo, "add", "copied.txt")
        run_git(self.repo, "commit", "-m", "unrelated project edit")
        os.utime(lane_copy, ns=(1_000_000_000, 1_000_000_000))

        code, out, err = self.close("unrelated", "--integrated")

        self.assertEqual((code, out), (4, ""))
        self.assertEqual(json.loads(err)["differing"], ["copied.txt"])
        self.assertTrue(worktree.exists())

    def test_integrated_is_plain_close_for_non_worktree_lane(self):
        self.write_ledger({"ship_mode": "scratch", "lanes": {
            "plain": {"kind": "codex", "state": "done", "ours": True,
                      "pane": None, "tab": None, "workspace": None,
                      "cwd": str(self.repo), "git_worktree": None},
        }})
        (self.repo / "plain-dirty.txt").write_text("dirty\n")

        code, out, err = self.close("plain", "--integrated")

        self.assertEqual(code, 0, err)
        self.assertTrue(json.loads(out)["ok"])
