# herdr-orchestrate

![Demo: an orchestrator pane drives worker lanes through a full build — spawn, parallel implementation, adversarial review, merge, browser-verified product](demo.gif)

*A real, unattended 20-minute run compressed to 50 seconds: the orchestrator (left workspace) is handed a spec, spawns a Codex backend lane and a Kimi frontend lane, cross-reviews with a Fable lane, triages findings, lands both branches, then drives the shipped UI in a browser before reporting done. No human touched anything between the assignment and the report.*

Two Claude Code skills and one stdlib-Python CLI for running a team of AI coding agents as visible, interruptible terminal panes. Workers are real interactive CLI sessions — Claude Code, OpenAI Codex CLI, pi — in herdr tabs you can watch, scroll, and interrupt. Not headless API calls. The orchestrator routes, triages, and verifies. It never implements. You are contacted for exactly two things: decisions only you can make, and completion.

## Why panes

Headless agents fail silently. A stuck API call looks identical to a thinking one. Panes don't have this problem: the agent's screen is ground truth, you can see it, and you can take the keyboard at any moment. Every detection rule in this repo exists because something failed in a way a log file hid. See HISTORY.md.

## How it works

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

`status`, `set`, and `notify` cover the remaining orchestrator intents.

## Design points

Each of these was earned by a failure. HISTORY.md has the full record.

1. **Dialog doctrine.** herd matches no dialog text, ever. Five adversarial review rounds refuted every screen-scrape classifier. Dialogs are prevented at launch (approval flags, sandbox flags, pre-seeded folder trust). Whatever still appears fails closed: exit 3, pane excerpt, notification. The orchestrator answers by hand.

2. **Watch the lane, never the artifact.** The only legal wait is `herd watch` — background, one per lane. It detects a unique per-turn REPORT-END sentinel plus settled agent state, and self-notifies on every escalation: agent gone, dialog, timeout. Polling an output file turns a stuck worker into silence.

3. **Reviews arrive as data.** `herd send --review` points reviewers at a findings JSON file (severity, file, line, symptom, fix_hint). `herd triage` returns blocking findings to the owning lane verbatim and backlogs the rest. Cross-review matrix: each model's work is reviewed by a different model.

4. **Ship modes per project.** `scratch`: in-tree. `merge`: worktree lanes on `lane/<name>` branches, review-gated `herd land --no-ff`, conflicts handed back to the owning lane. `pr`: the lane pushes and opens the PR — note `herd land` refuses to land locally in this mode and does *not* enforce the review gate; the PR review is the gate.

5. **Vertical slices, not tickets.** One implementer per domain slice, product-level acceptance ("the user can do X"). The orchestrator personally drives the final product before calling it done — including web UI at 390/768/1440 widths with realistic data.

6. **Resume.** The ledger survives orchestrator death. A fresh session adopts live lanes idempotently and re-attaches watches. Verified with a literal SIGKILL drill.

7. **Pretrust.** Spawn pre-seeds codex/claude folder-trust stores so trust dialogs don't appear. Deliberately best-effort: two cases, already trusted or entry absent. It was once 430 adversarially-hardened lines with a byte-safe TOML rewriter and renamex_np race detection. We deleted it after pricing the failure mode: a dialog, once, already handled. HISTORY.md tells that story.

## Install

- `brew install herdr`. Put the CLIs you plan to use on PATH: `claude`, `codex`, `pi`.
- Clone this repo into `~/.claude/skills/` so both skill dirs are siblings (or copy the two dirs in).
- Edit `KIND_ARGS` at the top of `herdr-orchestrate/bin/herd` to your own model roster and flags. The shipped ones are the authors': Codex → gpt-5.6-sol, pi → Kimi K3 via Moonshot, claude → Fable 5.
- In a herdr pane with `HERDR_ENV=1`, tell Claude Code to orchestrate a spec. The skill does the rest.

Tests: `python3 -m pytest herdr-orchestrate/tests/`

## The two skills

- `herdr-orchestrate/` — the master-orchestrator skill for mixed native harnesses. SKILL.md carries the doctrine; `bin/herd` enforces it; `LORE.md` holds the failure lore, read on demand.
- `herdr-orchestrate-pi/` — a standalone rewrite of the same doctrine with every worker lane on the pi harness, model chosen per role and the thinking level riding the model id (`provider/model:level`). Architecture-owning implementer runs high; everything else runs medium — the tiering that won our benchmark. pi fronts Anthropic, OpenAI, Moonshot, and others.

Battle-tested via a same-spec double-build showdown: native harnesses versus all-pi seats, independent scorecards. The pi side won on speed, cost, and maintainability — while accidentally running most lanes at medium thinking, which is why the tiering is now deliberate. HISTORY.md holds the war stories.

## License

MIT.
