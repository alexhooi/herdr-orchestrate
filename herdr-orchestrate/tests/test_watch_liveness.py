#!/usr/bin/env python3
import contextlib
import io
import json
from unittest import mock

from test_worktree_profile_and_land import HerdBase


class Clock:
    def __init__(self):
        self.now = 0

    def time(self):
        return self.now

    def sleep(self, seconds):
        self.now += seconds


class Sequence:
    def __init__(self, values):
        self.values = list(values)
        self.index = 0

    def next(self):
        value = self.values[min(self.index, len(self.values) - 1)]
        self.index += 1
        return value


class WatchLiveness(HerdBase):
    lane_name = "w1"
    token = "REPORT-END-w1"

    def lane(self, **updates):
        rec = {"kind": "pi", "state": "implementing", "ours": True,
               "pane": "pane-w1", "tab": "tab-w1",
               "token": self.token}
        rec.update(updates)
        self.write_ledger({"ship_mode": "scratch", "lanes": {self.lane_name: rec}})

    def run_watch(self, argv, tails, statuses, herdr=None, revisions=None):
        clock = Clock()
        tail_values = Sequence(tails)
        status_values = Sequence(statuses)
        revision_values = Sequence(revisions or [None])
        out, err, code = io.StringIO(), io.StringIO(), 0
        herdr = herdr or mock.Mock(return_value=(0, {}))
        with mock.patch.object(self.herd, "read_pane",
                               side_effect=lambda *_args: tail_values.next()), \
                mock.patch.object(self.herd, "agent_status",
                                  side_effect=lambda *_a: status_values.next()), \
                mock.patch.object(self.herd, "agent_revision",
                                  side_effect=lambda *_a: revision_values.next()), \
                mock.patch.object(self.herd, "herdr", herdr), \
                mock.patch.object(self.herd, "notify"), \
                mock.patch.object(self.herd.time, "time", side_effect=clock.time), \
                mock.patch.object(self.herd.time, "sleep", side_effect=clock.sleep), \
                contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            try:
                self.herd.cmd_watch(argv)
            except SystemExit as exc:
                code = exc.code
        return code, out.getvalue(), err.getvalue(), herdr

    def run_send(self, argv, token_hex, herdr=None):
        out, err, code = io.StringIO(), io.StringIO(), 0
        herdr = herdr or mock.Mock(return_value=(0, {}))
        with mock.patch.object(self.herd.secrets, "token_hex",
                               return_value=token_hex), \
                mock.patch.object(self.herd, "herdr", herdr), \
                mock.patch.object(self.herd, "read_pane", return_value=""), \
                mock.patch.object(self.herd, "agent_status",
                                  return_value="working"), \
                mock.patch.object(self.herd.time, "sleep"), \
                contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            try:
                self.herd.cmd_send(argv)
            except SystemExit as exc:
                code = exc.code
        return code, out.getvalue(), err.getvalue(), herdr

    def test_quiet_idle_nudges_once_then_accepts_sentinel(self):
        self.lane()
        quiet = "finished report without footer"
        code, out, err, herdr = self.run_watch(
            ["w1", "--nudge-after", "60", "--timeout", "120"],
            [quiet] * 12 + ["do NOT reply to this message",
                            quiet + "\n" + self.token + "\n"],
            ["idle"] * 13)

        self.assertEqual((code, err), (0, ""))
        self.assertTrue(json.loads(out)["ok"])
        prompts = [call.args for call in herdr.call_args_list
                   if call.args[:2] == ("agent", "prompt")]
        self.assertEqual(len(prompts), 1)
        self.assertEqual(prompts[0][3],
                         "If your task is finished, send the final report "
                         "(plain markdown, no box-drawing tables) ending with "
                         "a lone line REPORT-END-w1. If you are still working "
                         "— including waiting on background lanes/tasks — do "
                         "NOT reply to this message.")
        rec = self.read_ledger()["lanes"]["w1"]
        self.assertEqual(rec["nudged_token"], self.token)
        self.assertEqual(rec["watched_token"], self.token)

    def test_working_status_resets_idle_counter(self):
        self.lane()
        quiet = "report in progress"
        tails = ([quiet] * 11 + [quiet] + [quiet] * 11
                 + [quiet + "\n" + self.token + "\n"])
        statuses = ["idle"] * 11 + ["working"] + ["done"] * 12
        code, _, err, herdr = self.run_watch(
            ["w1", "--nudge-after", "60", "--timeout", "180"], tails, statuses)

        self.assertEqual((code, err), (0, ""))
        herdr.assert_not_called()
        self.assertNotIn("nudged_token",
                         self.read_ledger()["lanes"]["w1"])

    def test_tail_advance_resets_idle_counter(self):
        self.lane()
        old, new = "partial report", "complete report"
        tails = ([old] * 11 + [new] + [new] * 11
                 + [new + "\n" + self.token + "\n"])
        code, _, err, herdr = self.run_watch(
            ["w1", "--nudge-after", "60", "--timeout", "180"], tails, ["idle"] * 24)

        self.assertEqual((code, err), (0, ""))
        herdr.assert_not_called()
        self.assertNotIn("nudged_token",
                         self.read_ledger()["lanes"]["w1"])

    def test_existing_nudged_token_prevents_second_nudge(self):
        self.lane(nudged_token=self.token)
        quiet = "already nudged"
        code, _, err, herdr = self.run_watch(
            ["w1", "--nudge-after", "60", "--timeout", "120"],
            [quiet] * 12 + [quiet + "\n" + self.token + "\n"],
            ["done"] * 13)

        self.assertEqual((code, err), (0, ""))
        herdr.assert_not_called()
        self.assertEqual(self.read_ledger()["lanes"]["w1"]["nudged_token"],
                         self.token)

    def test_nudge_retries_after_prompt_failure(self):
        self.lane()
        quiet = "footer missing"
        herdr = mock.Mock(side_effect=[(1, {"raw": "eaten"}), (0, {})])
        code, _, err, herdr = self.run_watch(
            ["w1", "--nudge-after", "60", "--timeout", "120"],
            [quiet] * 12 + ["do NOT reply to this message",
                            quiet + "\n" + self.token + "\n"],
            ["idle"] * 13, herdr)

        self.assertEqual((code, err), (0, ""))
        prompts = [call.args for call in herdr.call_args_list
                   if call.args[:2] == ("agent", "prompt")]
        self.assertEqual(len(prompts), 2)

    def test_bare_token_is_not_nudge_delivery_evidence(self):
        self.lane()
        quiet = "footer missing"
        original_echo = "original prompt says token " + self.token
        code, _, err, herdr = self.run_watch(
            ["w1", "--nudge-after", "60", "--timeout", "120"],
            ([quiet] * 12 + [original_echo] * 3
             + ["do NOT reply to this message",
                quiet + "\n" + self.token + "\n"]),
            ["idle"])

        self.assertEqual((code, err), (0, ""))
        prompts = [call.args for call in herdr.call_args_list
                   if call.args[:2] == ("agent", "prompt")]
        self.assertEqual(len(prompts), 2)

    def test_failed_nudge_attempts_do_not_rewrite_ledger_each_poll(self):
        self.lane()
        herdr = mock.Mock(return_value=(1, {"raw": "eaten"}))
        with mock.patch.object(self.herd, "mutate",
                               wraps=self.herd.mutate) as mutate:
            code, _, _, herdr = self.run_watch(
                ["w1", "--nudge-after", "60", "--timeout", "120"], ["quiet"], ["idle"], herdr)

        self.assertEqual(code, 4)
        self.assertEqual(mutate.call_count, 1)
        self.assertEqual(herdr.call_count, 3)

    def test_scrolled_out_working_sentinel_does_not_suppress_nudge(self):
        self.lane()
        quiet = "footer scrolled away"
        tails = ([self.token + "\n"] + [quiet] * 13
                 + ["do NOT reply to this message",
                    quiet + "\n" + self.token + "\n"])
        statuses = ["working"] + ["idle"] * 14
        code, _, err, herdr = self.run_watch(
            ["w1", "--nudge-after", "60", "--timeout", "180"], tails, statuses)

        self.assertEqual((code, err), (0, ""))
        prompts = [call.args for call in herdr.call_args_list
                   if call.args[:2] == ("agent", "prompt")]
        self.assertEqual(len(prompts), 1)

    def test_blocked_lane_never_nudges(self):
        self.lane()
        code, _, err, herdr = self.run_watch(
            ["w1", "--nudge-after", "60", "--timeout", "120"], ["dialog"] * 3, ["blocked"] * 3)

        self.assertEqual(code, 3)
        self.assertEqual(json.loads(err)["reason"], "dialog")
        herdr.assert_not_called()

    def test_review_findings_array_exits_and_claims_token(self):
        findings = self.repo / ".herd" / "findings-w1-1.json"
        findings.parent.mkdir(exist_ok=True)
        findings.write_text("[]")
        self.lane(findings=str(findings), findings_token=self.token, reviews=1)

        code, out, err, herdr = self.run_watch(
            ["w1", "--nudge-after", "60", "--timeout", "60"], ["review complete"] * 12,
            ["idle"] * 12)

        self.assertEqual((code, err), (0, ""))
        result = json.loads(out)
        self.assertEqual(result["reason"], "findings-file")
        self.assertEqual(result["status"], "idle")
        self.assertEqual(self.read_ledger()["lanes"]["w1"]["watched_token"],
                         self.token)
        herdr.assert_not_called()

    def test_invalid_or_non_array_findings_do_not_complete_watch(self):
        findings = self.repo / ".herd" / "findings-w1-1.json"
        findings.parent.mkdir(exist_ok=True)
        for content in ("not json", "{}"):
            with self.subTest(content=content):
                findings.write_text(content)
                self.lane(findings=str(findings), findings_token=self.token,
                          reviews=1)
                code, out, err, _ = self.run_watch(
                    ["w1", "--nudge-after", "60", "--timeout", "60"], ["review complete"] * 12,
                    ["idle"] * 12)
                self.assertEqual((code, out), (4, ""))
                result = json.loads(err)
                self.assertEqual(result["reason"], "timeout")
                self.assertNotIn("watched_token",
                                 self.read_ledger()["lanes"]["w1"])

    def test_plain_send_clears_previous_review_findings_link(self):
        self.lane()
        code, out, err, _ = self.run_send(
            ["w1", "review task", "--review"], "review1")
        self.assertEqual((code, err), (0, ""))
        findings = self.read_ledger()["lanes"]["w1"]["findings"]
        with open(findings, "w") as f:
            json.dump([], f)

        code, out, err, _ = self.run_send(["w1", "fix task"], "plain1")
        self.assertEqual((code, err), (0, ""))
        token = json.loads(out)["token"]
        rec = self.read_ledger()["lanes"]["w1"]
        self.assertIsNone(rec["findings"])
        self.assertIsNone(rec["findings_token"])

        quiet = "plain report without footer"
        code, out, err, herdr = self.run_watch(
            ["w1", "--nudge-after", "60", "--timeout", "120"],
            [quiet] * 12 + ["do NOT reply to this message",
                            quiet + "\n" + token + "\n"],
            ["idle"] * 13)
        self.assertEqual((code, err), (0, ""))
        self.assertNotIn("reason", json.loads(out))
        self.assertTrue(findings.endswith("findings-w1-1.json"))
        self.assertEqual(herdr.call_count, 1)

    def test_review_send_removes_stale_findings_before_prompt(self):
        self.lane(reviews=0)
        stale = self.repo / ".herd" / "findings-w1-1.json"
        stale.write_text("[]")

        def prompt(*_args):
            self.assertFalse(stale.exists())
            return 0, {}

        code, out, err, _ = self.run_send(
            ["w1", "review task", "--review"], "review1",
            mock.Mock(side_effect=prompt))

        self.assertEqual((code, err), (0, ""))
        result = json.loads(out)
        rec = self.read_ledger()["lanes"]["w1"]
        self.assertEqual(rec["findings"], str(stale))
        self.assertEqual(rec["findings_token"], result["token"])
        self.assertFalse(stale.exists())

    def test_normal_sentinel_path_has_no_reason_or_nudge(self):
        self.lane()
        tail = "final report\n" + self.token + "\n"
        code, out, err, herdr = self.run_watch(
            ["w1"], [tail], ["done"])

        self.assertEqual((code, err), (0, ""))
        result = json.loads(out)
        self.assertTrue(result["ok"])
        self.assertNotIn("reason", result)
        herdr.assert_not_called()
        self.assertNotIn("nudged_token",
                         self.read_ledger()["lanes"]["w1"])

    def test_stable_revision_ignores_changing_rendered_tail(self):
        self.lane()
        tails = [f"spinner rendering {poll}" for poll in range(12)]
        herdr = mock.Mock(return_value=(1, {"raw": "eaten"}))
        code, _, err, herdr = self.run_watch(
            ["w1", "--nudge-after", "60", "--timeout", "60"], tails, ["done"], herdr,
            revisions=[861])

        self.assertEqual(code, 4)
        result = json.loads(err)
        self.assertFalse(result["advanced"])
        self.assertEqual(herdr.call_count, 3)
        self.assertEqual(self.read_ledger()["lanes"]["w1"]["nudged_token"],
                         self.token)

    def test_advancing_revision_prevents_nudge_and_reports_advanced(self):
        self.lane()
        revisions = list(range(861, 873))
        code, _, err, herdr = self.run_watch(
            ["w1", "--nudge-after", "60", "--timeout", "60"], ["same rendered tail"], ["done"],
            revisions=revisions)

        self.assertEqual(code, 4)
        self.assertTrue(json.loads(err)["advanced"])
        herdr.assert_not_called()
        self.assertNotIn("nudged_token",
                         self.read_ledger()["lanes"]["w1"])

    def test_missing_revision_falls_back_to_tail_changes(self):
        self.lane()
        tails = [f"real tail change {poll}" for poll in range(12)]
        code, _, err, herdr = self.run_watch(
            ["w1", "--nudge-after", "60", "--timeout", "60"], tails, ["idle"],
            revisions=[None])

        self.assertEqual(code, 4)
        self.assertTrue(json.loads(err)["advanced"])
        herdr.assert_not_called()
        self.assertNotIn("nudged_token",
                         self.read_ledger()["lanes"]["w1"])

    def test_timeout_reports_recent_advance_and_last_status(self):
        self.lane()
        code, _, err, _ = self.run_watch(
            ["w1", "--nudge-after", "60", "--timeout", "10"], ["first", "second"],
            ["working", "idle"])

        self.assertEqual(code, 4)
        result = json.loads(err)
        self.assertEqual(result["reason"], "timeout")
        self.assertEqual(result["agent_status"], "idle")
        self.assertTrue(result["advanced"])
        self.assertIn("watch w1 timed out after 10s", result["error"])

    def test_timeout_reports_no_recent_advance(self):
        self.lane()
        code, _, err, _ = self.run_watch(
            ["w1", "--nudge-after", "60", "--timeout", "10"], ["same", "same"],
            ["working", "working"])

        self.assertEqual(code, 4)
        result = json.loads(err)
        self.assertEqual(result["agent_status"], "working")
        self.assertFalse(result["advanced"])

    def test_any_timeout_reports_each_lane_status(self):
        self.write_ledger({"ship_mode": "scratch", "lanes": {
            "a": {"kind": "pi", "state": "implementing",
                  "token": "REPORT-END-a"},
            "b": {"kind": "pi", "state": "implementing",
                  "token": "REPORT-END-b"},
        }})
        clock = Clock()
        reads = {"a": 0, "b": 0}

        def read(lane, *_args):
            reads[lane] += 1
            if lane == "a" or reads[lane] == 1:
                return "steady"
            return "advanced"

        statuses = {"a": "working", "b": "done"}
        out, err, code = io.StringIO(), io.StringIO(), 0
        with mock.patch.object(self.herd, "read_pane", side_effect=read), \
                mock.patch.object(self.herd, "agent_status",
                                  side_effect=lambda lane, *_a: statuses[lane]), \
                mock.patch.object(self.herd, "notify"), \
                mock.patch.object(self.herd.time, "time", side_effect=clock.time), \
                mock.patch.object(self.herd.time, "sleep", side_effect=clock.sleep), \
                contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            try:
                self.herd.cmd_watch(["--any", "a", "b", "--timeout", "10"])
            except SystemExit as exc:
                code = exc.code

        self.assertEqual(code, 4)
        result = json.loads(err.getvalue())
        self.assertEqual(result["agent_status"], {"a": "working", "b": "done"})
        self.assertEqual(result["advanced"], {"a": False, "b": True})

    def test_any_lane_idle_counter_nudges_only_quiet_lane(self):
        self.write_ledger({"ship_mode": "scratch", "lanes": {
            "a": {"kind": "pi", "state": "implementing",
                  "token": "REPORT-END-a"},
            "b": {"kind": "pi", "state": "implementing",
                  "token": "REPORT-END-b"},
        }})
        clock = Clock()
        reads = {"a": 0, "b": 0}

        def read(lane, *_args):
            reads[lane] += 1
            if lane == "a":
                return "a still working"
            if reads[lane] <= 12:
                return "b quiet"
            if reads[lane] == 13:
                return "do NOT reply to this message"
            return "b report\nREPORT-END-b\n"

        herdr = mock.Mock(return_value=(0, {}))
        out, err, code = io.StringIO(), io.StringIO(), 0
        with mock.patch.object(self.herd, "read_pane", side_effect=read), \
                mock.patch.object(self.herd, "agent_status",
                                  side_effect=lambda lane, *_a:
                                  "working" if lane == "a" else "idle"), \
                mock.patch.object(self.herd, "herdr", herdr), \
                mock.patch.object(self.herd, "notify"), \
                mock.patch.object(self.herd.time, "time", side_effect=clock.time), \
                mock.patch.object(self.herd.time, "sleep", side_effect=clock.sleep), \
                contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            try:
                self.herd.cmd_watch(
                    ["--any", "a", "b", "--nudge-after", "60", "--timeout", "120"])
            except SystemExit as exc:
                code = exc.code

        self.assertEqual((code, err.getvalue()), (0, ""))
        self.assertEqual(json.loads(out.getvalue())["lane"], "b")
        prompts = [call.args for call in herdr.call_args_list
                   if call.args[:2] == ("agent", "prompt")]
        self.assertEqual(len(prompts), 1)
        self.assertEqual(prompts[0][2], "b")
        lanes = self.read_ledger()["lanes"]
        self.assertNotIn("nudged_token", lanes["a"])
        self.assertEqual(lanes["b"]["nudged_token"], "REPORT-END-b")


    def test_no_nudge_before_default_threshold(self):
        self.lane()
        code, out, _err, herdr = self.run_watch(
            ["w1", "--timeout", "300"], ["quiet"], ["idle"], revisions=[7])
        self.assertEqual(code, 4)
        self.assertFalse([c for c in herdr.call_args_list
                          if c.args[:2] == ("agent", "prompt")])
        self.assertNotIn("nudged_token", self.read_ledger()["lanes"]["w1"])

    def test_nudge_after_default_threshold_fires(self):
        self.lane()
        code, out, _err, herdr = self.run_watch(
            ["w1", "--timeout", "900"], ["quiet"], ["idle"], revisions=[7])
        self.assertEqual(code, 4)
        prompts = [c.args[3] for c in herdr.call_args_list
                   if c.args[:2] == ("agent", "prompt")]
        # no delivery evidence in the mocked pane → the 3 delivery attempts
        self.assertTrue(prompts)
        for prompt in prompts:
            self.assertIn("do NOT reply to this message", prompt)
            self.assertIn("If your task is finished", prompt)
        self.assertEqual(self.read_ledger()["lanes"]["w1"]["nudged_token"],
                         self.token)

    def test_no_nudge_flag_never_nudges(self):
        self.lane()
        code, out, _err, herdr = self.run_watch(
            ["w1", "--no-nudge", "--nudge-after", "60", "--timeout", "600"],
            ["quiet"], ["idle"], revisions=[7])
        self.assertEqual(code, 4)
        self.assertFalse([c for c in herdr.call_args_list
                          if c.args[:2] == ("agent", "prompt")])

    def test_spawn_no_nudge_recorded_in_ledger_disables_nudge(self):
        self.lane(no_nudge=True)
        code, out, _err, herdr = self.run_watch(
            ["w1", "--nudge-after", "60", "--timeout", "600"],
            ["quiet"], ["idle"], revisions=[7])
        self.assertEqual(code, 4)
        self.assertFalse([c for c in herdr.call_args_list
                          if c.args[:2] == ("agent", "prompt")])
        self.assertNotIn("nudged_token", self.read_ledger()["lanes"]["w1"])

    def test_help_explains_advanced_timeout_rearm(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.herd.cmd_watch(["--help"])
        self.assertIn("exit 4 with advanced:true = re-arm, not escalate", out.getvalue())
        self.assertIn("engine rewrite → --timeout 3600", out.getvalue())


if __name__ == "__main__":
    import unittest
    unittest.main()
