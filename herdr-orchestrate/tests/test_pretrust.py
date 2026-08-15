#!/usr/bin/env python3
"""Pretrust is best-effort by decision (see README): handle the two real
cases — already trusted (no-op) and entry absent (append) — and SKIP anything
else so the dialog falls to the exit-3 path. These tests pin that contract."""
import importlib.machinery
import importlib.util
import json
import os
from pathlib import Path
import tempfile
import time
import tomllib
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
HERD_PATH = ROOT / "bin" / "herd"


def load_herd():
    name = f"herd_test_{os.getpid()}_{time.time_ns()}"
    loader = importlib.machinery.SourceFileLoader(name, str(HERD_PATH))
    spec = importlib.util.spec_from_loader(name, loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


class PretrustBase(unittest.TestCase):
    def setUp(self):
        self.home = tempfile.TemporaryDirectory()
        self.addCleanup(self.home.cleanup)
        patcher = mock.patch.dict(os.environ, {"HOME": self.home.name})
        patcher.start()
        self.addCleanup(patcher.stop)
        self.herd = load_herd()
        self.codex = Path(self.home.name) / ".codex" / "config.toml"
        self.claude = Path(self.home.name) / ".claude.json"
        self.cwd = os.path.realpath(self.home.name)


class CodexPretrust(PretrustBase):
    def read_projects(self):
        return tomllib.loads(self.codex.read_text()).get("projects", {})

    def test_absent_entry_appended_and_valid(self):
        self.codex.parent.mkdir(parents=True)
        self.codex.write_text("# a comment\nmodel = \"gpt\"\n")
        self.herd.pretrust("codex", self.cwd)
        data = tomllib.loads(self.codex.read_text())
        self.assertEqual(data["projects"][self.cwd]["trust_level"], "trusted")
        self.assertEqual(data["model"], "gpt")
        self.assertIn("# a comment", self.codex.read_text())

    def test_missing_file_created(self):
        self.herd.pretrust("codex", self.cwd)
        self.assertEqual(self.read_projects()[self.cwd]["trust_level"], "trusted")

    def test_already_trusted_untouched(self):
        self.codex.parent.mkdir(parents=True)
        text = (f'[projects.{self.herd._toml_basic(self.cwd)}]\n'
                'trust_level = "trusted"\n')
        self.codex.write_text(text)
        self.herd.pretrust("codex", self.cwd)
        self.assertEqual(self.codex.read_text(), text)

    def test_existing_untrusted_entry_skipped(self):
        # decision: no in-place rewrite — dialog falls to the exit-3 path
        self.codex.parent.mkdir(parents=True)
        text = (f'[projects.{self.herd._toml_basic(self.cwd)}]\n'
                'trust_level = "untrusted"\n')
        self.codex.write_text(text)
        self.herd.pretrust("codex", self.cwd)
        self.assertEqual(self.codex.read_text(), text)

    def test_invalid_toml_skipped(self):
        self.codex.parent.mkdir(parents=True)
        self.codex.write_text("this is not = [ toml\n")
        self.herd.pretrust("codex", self.cwd)
        self.assertEqual(self.codex.read_text(), "this is not = [ toml\n")

    def test_hostile_path_quoted(self):
        hostile = os.path.join(self.home.name, 'we"ird\\dir')
        os.makedirs(hostile)
        real = os.path.realpath(hostile)
        self.herd.pretrust("codex", real)
        self.assertEqual(self.read_projects()[real]["trust_level"], "trusted")

    def test_no_trailing_newline_appends_cleanly(self):
        self.codex.parent.mkdir(parents=True)
        self.codex.write_text('model = "gpt"')
        self.herd.pretrust("codex", self.cwd)
        data = tomllib.loads(self.codex.read_text())
        self.assertEqual(data["projects"][self.cwd]["trust_level"], "trusted")


class ClaudePretrust(PretrustBase):
    def test_flag_set_others_preserved(self):
        self.claude.write_text(json.dumps({"theme": "dark", "projects": {
            "/other": {"hasTrustDialogAccepted": True}}}))
        self.herd.pretrust("claude", self.cwd)
        data = json.loads(self.claude.read_text())
        self.assertTrue(data["projects"][self.cwd]["hasTrustDialogAccepted"])
        self.assertEqual(data["theme"], "dark")
        self.assertTrue(data["projects"]["/other"]["hasTrustDialogAccepted"])

    def test_missing_store_skipped(self):
        self.herd.pretrust("claude", self.cwd)
        self.assertFalse(self.claude.exists())

    def test_corrupt_store_skipped(self):
        self.claude.write_text("{not json")
        self.herd.pretrust("claude", self.cwd)
        self.assertEqual(self.claude.read_text(), "{not json")

    def test_already_accepted_untouched(self):
        text = json.dumps({"projects": {self.cwd: {"hasTrustDialogAccepted": True}}})
        self.claude.write_text(text)
        self.herd.pretrust("claude", self.cwd)
        self.assertEqual(self.claude.read_text(), text)


class StatGate(PretrustBase):
    def test_external_change_detected_and_retried(self):
        """A write landing between read and install is seen by the stat gate;
        the retry loop re-reads and the external content survives."""
        self.codex.parent.mkdir(parents=True)
        self.codex.write_text("a = 1\n")
        real_install = self.herd._install
        fired = {}

        def racing_install(path, tmp, st):
            if not fired.get("done"):
                fired["done"] = True
                time.sleep(0.02)  # distinct mtime_ns not guaranteed; size differs
                self.codex.write_text("a = 1\nb = 2\n")
            return real_install(path, tmp, st)

        with mock.patch.object(self.herd, "_install", racing_install):
            self.herd.pretrust("codex", self.cwd)
        data = tomllib.loads(self.codex.read_text())
        self.assertEqual(data["b"], 2)
        self.assertEqual(data["projects"][self.cwd]["trust_level"], "trusted")


if __name__ == "__main__":
    unittest.main()
