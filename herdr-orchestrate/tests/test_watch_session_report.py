#!/usr/bin/env python3
"""Compaction redraws the pane over the lane's report; watch must still find
the token in pi's session jsonl (pi-blackhole compacts at agent_end)."""
import json
import os
import tempfile
from unittest import mock

from test_watch_liveness import WatchLiveness


class WatchSessionReport(WatchLiveness):
    def setUp(self):
        super().setUp()
        self.pi_home = tempfile.mkdtemp()
        self.cwd = tempfile.mkdtemp()
        os.environ["HERD_PI_HOME"] = self.pi_home

    def tearDown(self):
        os.environ.pop("HERD_PI_HOME", None)
        super().tearDown()

    def write_session(self, entries, profile="agent", name="s1.jsonl"):
        safe = "--" + os.path.realpath(self.cwd).lstrip("/").replace("/", "-") + "--"
        d = os.path.join(self.pi_home, profile, "sessions", safe)
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, name), "w") as f:
            for e in entries:
                f.write(json.dumps(e) + "\n")

    def assistant(self, text):
        return {"type": "message", "message": {
            "role": "assistant", "content": [{"type": "text", "text": text}]}}

    def test_compacted_pane_report_found_in_session_file(self):
        self.lane(cwd=self.cwd)
        self.write_session([
            {"type": "message", "message": {"role": "user", "content": "go"}},
            self.assistant("all done\n\n" + self.token),
            {"type": "compaction", "summary": "..."},
            {"type": "custom", "customType": "om.observations.recorded"},
        ])
        code, out, err, herdr = self.run_watch(
            ["w1", "--nudge-after", "60", "--timeout", "120"],
            ["compaction summary only"], ["idle"])
        self.assertEqual((code, err), (0, ""))
        res = json.loads(out)
        self.assertTrue(res["ok"])
        self.assertIn(self.token, res["tail"])
        prompts = [c for c in herdr.call_args_list if c.args[:2] == ("agent", "prompt")]
        self.assertEqual(prompts, [])  # no nudge needed
        self.assertEqual(self.read_ledger()["lanes"]["w1"]["watched_token"], self.token)

    def test_stale_or_tokenless_session_does_not_match(self):
        self.lane(cwd=self.cwd)
        self.write_session([
            self.assistant("still working on it"),
        ])
        code, out, err, herdr = self.run_watch(
            ["w1", "--nudge-after", "60", "--timeout", "30"],
            ["quiet"], ["idle"])
        self.assertEqual(code, 4)  # timeout, token never seen

    def test_working_status_ignores_session_file(self):
        self.lane(cwd=self.cwd)
        self.write_session([self.assistant("done\n" + self.token)])
        code, out, err, herdr = self.run_watch(
            ["w1", "--timeout", "30"], ["quiet"], ["working"])
        self.assertEqual(code, 4)

    def test_non_pi_lane_skips_session_lookup(self):
        self.lane(cwd=self.cwd, kind="claude")
        self.write_session([self.assistant("done\n" + self.token)])
        code, out, err, herdr = self.run_watch(
            ["w1", "--timeout", "30"], ["quiet"], ["idle"])
        self.assertEqual(code, 4)


if __name__ == "__main__":
    import unittest
    unittest.main()
