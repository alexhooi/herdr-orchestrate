#!/usr/bin/env python3
import contextlib
import io
import json
from unittest import mock

from test_worktree_profile_and_land import HerdBase, run_git


class DebriefBase(HerdBase):
    def lane(self, name, **updates):
        rec = {"kind": "pi", "state": "implementing", "ours": True,
               "pane": f"pane-{name}", "tab": None,
               "token": f"REPORT-END-{name}"}
        rec.update(updates)
        led = {"ship_mode": "scratch", "lanes": {name: rec}}
        self.write_ledger(led)
        return rec

    def run_watch(self, argv):
        out, err, code = io.StringIO(), io.StringIO(), 0
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            try:
                self.herd.cmd_watch(argv)
            except SystemExit as exc:
                code = exc.code
        return code, out.getvalue(), err.getvalue()


class CloseTerminalState(DebriefBase):
    def test_reclose_repairs_missing_terminal_state(self):
        self.lane("dead", tab=None, state="implementing")
        with mock.patch.object(self.herd, "agent_status", return_value=None), \
                contextlib.redirect_stdout(io.StringIO()):
            self.herd.cmd_close(["dead"])
            self.herd.cmd_close(["dead"])
        rec = self.read_ledger()["lanes"]["dead"]
        self.assertEqual(rec["state"], "closed")
        self.assertEqual(rec["closed_from"], "implementing")

    def test_state_write_to_closed_lane_fails_loudly(self):
        self.lane("dead", tab=None, state="closed")
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err), \
                self.assertRaises(SystemExit) as cm:
            self.herd.cmd_set(["dead", "state=done"])
        self.assertEqual(cm.exception.code, 1)
        self.assertEqual(out.getvalue(), "")
        self.assertIn("state is terminal", json.loads(err.getvalue())["error"])

    def test_close_reviewed_lane_can_still_land(self):
        run_git(self.repo, "checkout", "-b", "lane/reviewed")
        (self.repo / "landed.txt").write_text("landed\n")
        run_git(self.repo, "add", "landed.txt")
        run_git(self.repo, "commit", "-m", "lane work")
        run_git(self.repo, "checkout", "main")
        self.lane("reviewed", state="reviewed", branch="lane/reviewed",
                  base="main", tab=None)
        led = self.read_ledger()
        led["ship_mode"] = "merge"
        self.write_ledger(led)
        with mock.patch.object(self.herd, "agent_status", return_value=None), \
                contextlib.redirect_stdout(io.StringIO()):
            self.herd.cmd_close(["reviewed"])
            self.herd.cmd_land(["reviewed"])
        self.assertTrue((self.repo / "landed.txt").exists())
        self.assertEqual(self.read_ledger()["lanes"]["reviewed"]["state"], "done")

    def test_failed_live_teardown_rolls_back_closing_marker(self):
        self.lane("live", tab="tab-live", state="implementing")
        with mock.patch.object(self.herd, "agent_status", return_value="idle"), \
                mock.patch.object(self.herd, "herdr", return_value=(1, {"raw": "busy"})), \
                mock.patch.object(self.herd, "read_pane", return_value="still here"):
            code, _, _ = self._close("live")
        rec = self.read_ledger()["lanes"]["live"]
        self.assertEqual(code, 1)
        self.assertEqual(rec["state"], "implementing")
        self.assertNotIn("closing", rec)
        self.assertNotIn("closed", rec)
        with mock.patch.object(self.herd, "read_pane", return_value="last tail"), \
                mock.patch.object(self.herd, "agent_status", return_value=None), \
                mock.patch.object(self.herd, "notify"):
            code, _, _ = self.run_watch(["live"])
        self.assertEqual(code, 2)

    def test_agent_gone_close_error_has_diagnostics_and_records_closed(self):
        self.lane("dead", tab="tab-dead")
        with mock.patch.object(self.herd, "agent_status", return_value=None), \
                mock.patch.object(self.herd, "herdr", return_value=(1, {"raw": "gone"})), \
                mock.patch.object(self.herd, "read_pane", return_value="last pane words"):
            code, _, err = self._close("dead")
        detail = json.loads(err)
        self.assertEqual(code, 2)
        self.assertEqual(detail["reason"], "agent_gone")
        self.assertEqual(detail["ledger_state"], "closed")
        self.assertEqual(detail["tail"], "last pane words")
        self.assertEqual(self.read_ledger()["lanes"]["dead"]["state"], "closed")

    def _close(self, lane):
        out, err, code = io.StringIO(), io.StringIO(), 0
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            try:
                self.herd.cmd_close([lane])
            except SystemExit as exc:
                code = exc.code
        return code, out.getvalue(), err.getvalue()


class WatchModes(DebriefBase):
    def test_any_returns_first_completed_lane(self):
        self.write_ledger({"ship_mode": "scratch", "lanes": {
            "a": self._watch_rec("a"), "b": self._watch_rec("b")}})
        tails = {"a": "still working", "b": "report b\nREPORT-END-b\n"}
        states = {"a": "working", "b": "done"}
        with mock.patch.object(self.herd, "read_pane", side_effect=lambda lane, *_: tails[lane]), \
                mock.patch.object(self.herd, "agent_status",
                                  side_effect=lambda lane, *_args: states[lane]):
            code, out, err = self.run_watch(["--any", "a", "b"])
        self.assertEqual((code, err), (0, ""))
        result = json.loads(out)
        self.assertEqual(result["lane"], "b")
        self.assertEqual(result["status"], "done")

    def test_completed_token_cannot_satisfy_plain_rewatch(self):
        self.lane("a")
        tail = "report a\nREPORT-END-a\n"
        with mock.patch.object(self.herd, "read_pane", return_value=tail), \
                mock.patch.object(self.herd, "agent_status", return_value="done"):
            code, _, _ = self.run_watch(["a"])
        self.assertEqual(code, 0)

        with mock.patch.object(self.herd, "read_pane", return_value=tail), \
                mock.patch.object(self.herd, "agent_status", return_value="done"), \
                mock.patch.object(self.herd, "notify"), \
                mock.patch.object(self.herd.time, "sleep"), \
                mock.patch.object(self.herd.time, "time", side_effect=[0, 0, 2]):
            code, _, err = self.run_watch(["a", "--timeout", "1"])
        self.assertEqual(code, 4)
        self.assertIn("timed out", json.loads(err)["error"])

    def test_completed_token_cannot_satisfy_any_rewatch(self):
        self.write_ledger({"ship_mode": "scratch", "lanes": {
            "a": self._watch_rec("a"), "b": self._watch_rec("b")}})
        tails = {"a": "report a\nREPORT-END-a\n", "b": "still working"}
        states = {"a": "done", "b": "working"}
        with mock.patch.object(self.herd, "read_pane",
                               side_effect=lambda lane, *_: tails[lane]), \
                mock.patch.object(self.herd, "agent_status",
                                  side_effect=lambda lane, *_args: states[lane]):
            code, _, _ = self.run_watch(["--any", "a", "b"])
        self.assertEqual(code, 0)

        with mock.patch.object(self.herd, "read_pane",
                               side_effect=lambda lane, *_: tails[lane]), \
                mock.patch.object(self.herd, "agent_status",
                                  side_effect=lambda lane, *_args: states[lane]), \
                mock.patch.object(self.herd, "notify"), \
                mock.patch.object(self.herd.time, "sleep"), \
                mock.patch.object(self.herd.time, "time", side_effect=[0, 0, 2]):
            code, _, err = self.run_watch(
                ["--any", "a", "b", "--timeout", "1"])
        self.assertEqual(code, 4)
        self.assertIn("timed out", json.loads(err)["error"])

    def test_concurrent_watch_claim_cannot_double_satisfy(self):
        self.lane("a")
        tail = "report a\nREPORT-END-a\n"

        def first_watch_wins(_lane, *_args):
            self.herd.mutate(lambda led: led["lanes"]["a"].__setitem__(
                "watched_token", "REPORT-END-a"))
            return tail

        with mock.patch.object(self.herd, "read_pane", side_effect=first_watch_wins), \
                mock.patch.object(self.herd, "agent_status", return_value="done"), \
                mock.patch.object(self.herd, "notify"), \
                mock.patch.object(self.herd.time, "sleep"), \
                mock.patch.object(self.herd.time, "time", side_effect=[0, 0, 2]):
            code, _, err = self.run_watch(["a", "--timeout", "1"])
        self.assertEqual(code, 4)
        self.assertIn("timed out", json.loads(err)["error"])

    def test_resume_after_consumed_watch_returns_already_reported(self):
        self.lane("a")
        tail = "report a\nREPORT-END-a\n"
        with mock.patch.object(self.herd, "read_pane", return_value=tail), \
                mock.patch.object(self.herd, "agent_status", return_value="done"):
            code, _, _ = self.run_watch(["a"])
            resume_code, out, err = self.run_watch(["a", "--resume"])
        self.assertEqual((code, resume_code, err), (0, 0, ""))
        result = json.loads(out)
        self.assertEqual(result["reason"], "already-reported")
        self.assertEqual(result["tail"], tail)

    def test_resume_returns_report_after_agent_is_gone(self):
        self.lane("a")
        tail = "report a\nREPORT-END-a\n"
        with mock.patch.object(self.herd, "read_pane", return_value=tail), \
                mock.patch.object(self.herd, "agent_status",
                                  side_effect=["done", None]), \
                mock.patch.object(self.herd, "notify") as notify:
            code, _, _ = self.run_watch(["a"])
            resume_code, out, err = self.run_watch(["a", "--resume"])
        self.assertEqual((code, resume_code, err), (0, 0, ""))
        self.assertEqual(json.loads(out)["reason"], "already-reported")
        notify.assert_not_called()

    def test_send_racing_claim_supersedes_in_lock(self):
        self.lane("a")
        tail = "report a\nREPORT-END-a\n"
        real_mutate = self.herd.mutate

        def racing_mutate(fn):
            real_mutate(lambda led: led["lanes"]["a"].__setitem__(
                "token", "REPORT-END-new"))
            return real_mutate(fn)

        with mock.patch.object(self.herd, "read_pane", return_value=tail), \
                mock.patch.object(self.herd, "agent_status", return_value="done"), \
                mock.patch.object(self.herd, "mutate", side_effect=racing_mutate):
            code, _, err = self.run_watch(["a"])
        result = json.loads(err)
        self.assertEqual(code, 4)
        self.assertEqual(result["reason"], "superseded")
        self.assertEqual(result["current_token"], "REPORT-END-new")

    def test_superseded_watch_fails_fast_with_current_token(self):
        self.lane("a")

        def supersede(_lane, *_args):
            self.herd.mutate(
                lambda led: led["lanes"]["a"].__setitem__(
                    "token", "REPORT-END-new"))
            return "still working"

        with mock.patch.object(self.herd, "read_pane", side_effect=supersede), \
                mock.patch.object(self.herd, "agent_status", return_value="working"):
            code, _, err = self.run_watch(["a"])
        result = json.loads(err)
        self.assertEqual(code, 4)
        self.assertEqual(result["reason"], "superseded")
        self.assertEqual(result["watched_token"], "REPORT-END-a")
        self.assertEqual(result["current_token"], "REPORT-END-new")

    def test_watch_then_close_returns_closed_instead_of_stale_match(self):
        self.lane("a", state="done", watched_token="REPORT-END-a")

        def close_lane(_seconds):
            def close(led):
                led["lanes"]["a"].update(state="closed")
            self.herd.mutate(close)

        with mock.patch.object(self.herd, "read_pane", return_value="REPORT-END-a\n"), \
                mock.patch.object(self.herd, "agent_status", side_effect=["done", None]), \
                mock.patch.object(self.herd.time, "sleep", side_effect=close_lane), \
                mock.patch.object(self.herd.time, "time", side_effect=[0, 0, 1]):
            code, out, err = self.run_watch(["a", "--timeout", "10"])
        self.assertEqual((code, err), (0, ""))
        self.assertEqual(json.loads(out)["reason"], "closed")

    def test_text_prints_report_as_real_lines(self):
        self.lane("a")
        tail = "first report line\nsecond report line\nREPORT-END-a\n"
        with mock.patch.object(self.herd, "read_pane", return_value=tail), \
                mock.patch.object(self.herd, "agent_status", return_value="done"):
            code, out, err = self.run_watch(["a", "--text"])
        self.assertEqual((code, err), (0, ""))
        self.assertEqual(out, tail)

    def test_deliberately_closed_lane_is_success_not_crash(self):
        self.lane("a", state="closed")
        with mock.patch.object(self.herd, "read_pane", return_value="last output\n"), \
                mock.patch.object(self.herd, "agent_status", return_value=None), \
                mock.patch.object(self.herd, "notify") as notify:
            code, out, err = self.run_watch(["a"])
        self.assertEqual((code, err), (0, ""))
        result = json.loads(out)
        self.assertEqual(result["reason"], "closed")
        notify.assert_not_called()

    def test_agent_gone_json_includes_cheap_diagnostics(self):
        self.lane("a", state="review", pane="p7", tab="t7")
        with mock.patch.object(self.herd, "read_pane", return_value="useful tail"), \
                mock.patch.object(self.herd, "agent_status", return_value=None), \
                mock.patch.object(self.herd, "notify"):
            code, _, err = self.run_watch(["a"])
        result = json.loads(err)
        self.assertEqual(code, 2)
        self.assertEqual(result["reason"], "agent_gone")
        self.assertEqual(result["tail"], "useful tail")
        self.assertEqual(result["ledger_state"], "review")
        self.assertEqual((result["pane"], result["tab"]), ("p7", "t7"))

    @staticmethod
    def _watch_rec(lane):
        return {"kind": "pi", "state": "implementing", "ours": True,
                "pane": f"pane-{lane}", "tab": f"tab-{lane}",
                "token": f"REPORT-END-{lane}"}


class TriagePromote(DebriefBase):
    def test_promote_forces_minor_finding_to_handback(self):
        findings = self.repo / "findings.json"
        backlog = self.repo / "todo.md"
        findings.write_text(json.dumps([
            {"id": "F1", "severity": "minor", "file": "a.py", "line": 1,
             "symptom": "promote me", "fix_hint": "fix"},
            {"id": "F2", "severity": "nit", "file": "b.py", "line": 2,
             "symptom": "backlog me", "fix_hint": "fix"},
        ]))
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.herd.cmd_triage([str(findings), "--backlog", str(backlog),
                                  "--promote", "F1"])
        result = json.loads(out.getvalue())
        self.assertEqual([f["id"] for f in result["handback"]], ["F1"])
        self.assertEqual(result["backlogged"], 1)
        self.assertIn("backlog me", backlog.read_text())
        self.assertNotIn("promote me", backlog.read_text())
