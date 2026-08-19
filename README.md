# herdr-orchestrate

**Run a team of AI coding agents — Claude Code, Codex CLI, pi — as visible terminal panes you can watch, scroll, and interrupt. One orchestrator routes, reviews, merges. You get pinged twice: for a decision only you can make, and when it's done.**

![Demo: an all-pi herdr-orchestrate run — Sol backend lane, Kimi UI lane, batch cross-review, a review-ui lane driving the real browser, land, clean up](demo-pi.gif)

*Real unattended 26-minute run, cut to 50 seconds: spec in → Sol backend lane + Kimi UI lane → one cross-model review after both report → a `review-ui` lane drives the real browser at 390/768/1440 → land both branches → machine-clean sweep → report. No human touched anything between the assignment and the report.*

```sh
brew install herdr                  # terminal agent multiplexer; put claude / codex / pi on PATH
git clone https://github.com/alexkalinohooijunyi/herdr-orchestrate ~/.claude/skills/herdr-orchestrate
# in a herdr pane running Claude Code: hand it a spec and say "orchestrate this"
```

Two Claude Code orchestrator skills + `herd`, a ~700-line stdlib-Python CLI. No framework, no SDK, no daemon. Workers are real interactive CLI sessions in herdr tabs — not headless API calls. The orchestrator routes, triages, and verifies. It never implements.

## Why not just subagents?

Subagents are headless. A stuck API call looks identical to a thinking one; a permission dialog is an invisible hang; "done" is whatever the model says. Panes fix all three: the screen is ground truth, you can take the keyboard any time, and `herd watch` waits on a per-turn sentinel plus settled agent state — not a self-report. Subagents still have a place (recon, parallel reads inside one lane); lanes are for work that earns its own pane: implementers, reviewers, anything you'd want to watch or interrupt.

## How it works — 55 seconds

![How herdr-orchestrate works: captain → one orchestrator pane → visible worker lanes; roles; the implement/watch loop; batch review → triage → land → verify; guardrails; machine-clean sweep](explainer.gif)

*The mechanics as an evolving system picture: the captain hands a spec to one orchestrator pane; workers are real CLIs in visible panes; `herd send` mints a report token, `herd watch` runs in the background (a lone-line token, a nudge, or a reviewer's findings file all count as done); review happens once, after every implementer reports, cross-model, with a `review-ui` lane driving the real UI; `herd land` gates on review; the orchestrator runs the product itself, sweeps the machine clean, and reports. ([mp4](explainer.mp4))*

## Why panes

Headless agents fail silently. A stuck API call looks identical to a thinking one. Panes don't have this problem: the agent's screen is ground truth, you can see it, and you can take the keyboard at any moment. Every detection rule in this repo exists because something failed in a way a log file hid. See HISTORY.md.

## Under the hood

Built on [herdr](https://herdr.dev), a terminal agent multiplexer (`brew install herdr`). One orchestrator pane drives worker lanes through `bin/herd`, a ~670-line Python-stdlib CLI: one command per orchestrator intent. State lives in `<project>/.herd/ledger.json`, flock-guarded, and survives orchestrator death.

The lane loop:

```sh
herd spawn          # launch a lane; trust dialogs pre-empted
herd send           # hand the lane its task
herd watch          # the only legal wait; background, one per lane
herd send --review  # reviewers get findings as JSON
herd triage         # blocking findings back verbatim, rest to backlog
herd land           # review-gated --no-ff merge, conflicts handed back
herd close          # retire the lane
```

`status`, `set`, and `notify` cover the remaining orchestrator intents. Spawn refuses to ledger a lane in `$HOME` and auto-gitignores `.herd/` in the project root; `herd close --integrated` retires a worktree lane whose files the parent already folded in.

## Design points

Each of these was earned by a failure. HISTORY.md has the full record.

1. **Dialog doctrine.** herd matches no dialog text, ever. Five adversarial review rounds refuted every screen-scrape classifier. Dialogs are prevented at launch (approval flags, sandbox flags, pre-seeded folder trust). Whatever still appears fails closed: exit 3, pane excerpt, notification. The orchestrator answers by hand.

2. **Watch the lane, never the artifact.** The only legal wait is `herd watch` — background, one per lane. It detects a unique per-turn REPORT-END sentinel plus settled agent state, and self-notifies on every escalation: agent gone, dialog, timeout. It also nudges an idle lane once if compaction ate its report footer, and accepts a review lane's findings file as completion in its own right. Polling an output file turns a stuck worker into silence.

3. **Reviews arrive as data.** `herd send --review` points reviewers at a findings JSON file (severity, file, line, symptom, fix_hint). `herd triage` returns blocking findings to the owning lane verbatim and backlogs the rest. Cross-review matrix: each model's work is reviewed by a different model. UI work gets its own reviewer, `review-ui`: it drives the real UI — simulator or browser, every width — before the captain ever sees it.

4. **Ship modes per project.** `scratch`: in-tree. `merge`: worktree lanes on `lane/<name>` branches, review-gated `herd land --no-ff`, conflicts handed back to the owning lane. `pr`: the lane pushes and opens the PR — note `herd land` refuses to land locally in this mode and does *not* enforce the review gate; the PR review is the gate.

5. **Vertical slices, not tickets.** One implementer per domain slice, product-level acceptance ("the user can do X"). Kimi owns all UI on any platform — web, SwiftUI, native. The orchestrator personally drives the final product before calling it done — including web UI at 390/768/1440 widths with realistic data.

6. **Resume.** The ledger survives orchestrator death. A fresh session adopts live lanes idempotently and re-attaches watches. Verified with a literal SIGKILL drill.

7. **Pretrust.** Spawn pre-seeds codex/claude folder-trust stores so trust dialogs don't appear. Deliberately best-effort: two cases, already trusted or entry absent. It was once 430 adversarially-hardened lines with a byte-safe TOML rewriter and renamex_np race detection. We deleted it after pricing the failure mode: a dialog, once, already handled. HISTORY.md tells that story.

8. **Teardown etiquette.** Every lane cleans up what it opened — browser tabs, booted simulators, dev servers, log tails — before it reports done, and the orchestrator runs a machine-clean sweep as its own last act. A run isn't done while any of it is still up.

## Install

- `brew install herdr`. Put the CLIs you plan to use on PATH: `claude`, `codex`, `pi`.
- Clone this repo into `~/.claude/skills/` so both skill dirs are siblings (or copy the dirs in individually).
- Edit `KIND_ARGS` at the top of `herdr-orchestrate/bin/herd` to your own model roster and flags. The shipped ones are the authors': Codex → gpt-5.6-sol, pi → Kimi K3 via Moonshot, claude → Fable 5.
- In a herdr pane with `HERDR_ENV=1`, tell Claude Code to orchestrate a spec. The skill does the rest.

Tests: `python3 -m pytest herdr-orchestrate/tests/`

## The two skills

- `herdr-orchestrate/` — the master-orchestrator skill for mixed native harnesses. SKILL.md carries the doctrine; `bin/herd` enforces it; `LORE.md` holds the failure lore, read on demand.
- `herdr-orchestrate-pi/` — a standalone rewrite of the same doctrine with every worker lane on the pi harness, model chosen per role and the thinking level riding the model id (`provider/model:level`). Architecture-owning implementer runs high; everything else runs medium — the tiering that won our benchmark. pi fronts Anthropic, OpenAI, Moonshot, and others.

Battle-tested via a same-spec double-build showdown: native harnesses versus all-pi seats, independent scorecards. The pi side won on speed, cost, and maintainability — while accidentally running most lanes at medium thinking, which is why the tiering is now deliberate. HISTORY.md holds the war stories.

## License

MIT.
