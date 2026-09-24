#!/usr/bin/env python3
import contextlib
import io
import json
import unittest
from unittest import mock

from test_debrief_fixes import DebriefBase


class Refocus(DebriefBase):
    def send(self, argv):
        calls = []

        def fake_deliver(lane, prompt, evidence, **kw):
            calls.append((lane, prompt, evidence))
            return True, 1, ""
        out = io.StringIO()
        with mock.patch.object(self.herd, "deliver", fake_deliver), \
                contextlib.redirect_stdout(out):
            try:
                self.herd.cmd_send(argv)
                code = 0
            except SystemExit as exc:
                code = exc.code
        return code, calls, out.getvalue()

    def test_send_records_brief_and_refocus_replays_it(self):
        self.lane("impl-a")
        code, calls, _ = self.send(["impl-a", "Build the doghouse. Acceptance: dog fits.",
                                    "--state", "implementing"])
        self.assertEqual(code, 0)
        rec = self.read_ledger()["lanes"]["impl-a"]
        self.assertTrue(rec["brief"].endswith("brief-impl-a.md"))
        self.assertEqual(open(rec["brief"]).read(), "Build the doghouse. Acceptance: dog fits.")
        tok = rec["token"]

        code, calls, out = self.send(["impl-a", "--refocus"])
        self.assertEqual(code, 0)
        lane, prompt, evidence = calls[0]
        self.assertTrue(evidence.startswith("refocus-"))
        self.assertIn("Build the doghouse", prompt)
        self.assertIn("do not restart", prompt)
        self.assertIn(tok, prompt)
        rec = self.read_ledger()["lanes"]["impl-a"]
        self.assertEqual(rec["token"], tok)  # in-flight watch keeps its token
        self.assertEqual(rec["refocused"], 1)
        self.assertTrue(json.loads(out.splitlines()[-1])["refocus"])

    def test_review_send_does_not_overwrite_brief(self):
        self.lane("impl-a")
        self.send(["impl-a", "the brief"])
        self.send(["impl-a", "--review", "review this"])
        rec = self.read_ledger()["lanes"]["impl-a"]
        self.assertEqual(open(rec["brief"]).read(), "the brief")

    def test_refocus_without_brief_dies(self):
        self.lane("impl-a")
        code, calls, _ = self.send(["impl-a", "--refocus"])
        self.assertNotEqual(code, 0)
        self.assertEqual(calls, [])

    def test_refocus_rejects_prompt(self):
        self.lane("impl-a", brief="/nonexistent")
        code, calls, _ = self.send(["impl-a", "--refocus", "extra text"])
        self.assertNotEqual(code, 0)
        self.assertEqual(calls, [])


if __name__ == "__main__":
    unittest.main()
