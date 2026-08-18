---
name: herdr-orchestrate-pi
description: "Herdr master-orchestrator, all-pi harness. Fire when inside a herdr pane (HERDR_ENV=1) and the captain hands over a spec, feature, or read-only evaluation to orchestrate — and the run should stay in the pi harness (captain says pi, or pi is the project default). Mixed-harness runs go to herdr-orchestrate instead."
---

# Herdr Orchestration — PI harness

Precondition: `test "${HERDR_ENV:-}" = 1` — otherwise say so and stop.

Every worker lane is a pi pane; model per role via `--model` after `--`. All lane plumbing is one tool: the sibling `herdr-orchestrate` skill's `bin/herd` (both skills install side by side in `~/.claude/skills/`) — every command below is `herd <verb>`. Run it from the project directory (or set `HERD_PROJECT`); it keeps a ledger in `<project>/.herd/ledger.json`.

Preflight once per session:
- `herdr integration status --outdated-only` — update anything listed; outdated integrations re-raise trust dialogs on spawn.
- **Find the project first.** If the cwd holds no `.herd/` and no spec and the brief carries no absolute path, locate the project (mdfind/spec search; disambiguate siblings by ledger lane prefixes and freshness), then `export HERD_PROJECT=<abs>` and run every `herd` command from there. Never spawn from `$HOME` — herd refuses to create a ledger there.
- `herd status` — an existing ledger means you are **resuming**: adopt it (see Resume), don't spawn duplicates.

## Roles

| lane name | model (via `-- --model <id>:<thinking>`) | takes |
|---|---|---|
| (this session) | — | routing, triage, status. NEVER implements or reviews |
| `impl-fable[-<slice>]` | `claude-bridge/claude-fable-5:high` | owns a slice as its pseudo-orchestrator: architecture, integration, acceptance — spawns its own Sol/kimi sub-lanes for scoped chunks. Fable typing well-specified code itself is a routing smell |
| `impl-sol[-<slice>]` | `openai-codex/gpt-5.6-sol:medium` | scoped, well-specified tasks |
| `frontend-kimi` | `moonshotai/kimi-k3:high` | all UI, any platform (web, SwiftUI/native), design |
| `review-sol` | `openai-codex/gpt-5.6-sol:medium` | reviews fable-implemented work |
| `review-fable` | `claude-bridge/claude-fable-5:medium` | reviews sol-implemented work |
| `review-ui` | `openai-codex/gpt-5.6-sol:medium` | reviews frontend-kimi work by DRIVING it — sim drill (`ios-sim-drill`) / browser — Sol is the specialist UI reviewer (captain ruling 2026-08-19) |
| exploration/scout sub-lanes | `claude-bridge/claude-sonnet-5:medium` | search, recon, read-only fan-out (sonnet is the floor tier) |

Thinking level rides the model id (`:<level>` suffix; explicit `--thinking` also works) — without it a pane runs at pi's `defaultThinkingLevel` (medium). The tiering is deliberate (showdown-tested): medium lanes matched high on quality while winning speed/cost — keep it. Exception: kimi runs `:high` (owner call, 2026-08-17).

Two delegation tools, two jobs. Subagents (pi's routing) *augment* a lane and preserve its context: recon, parallel reads, scoped in-place chunks whose output the lane absorbs. Herd sub-lanes carry work that earns its own pane: observability, review routing, a lifecycle. Sub-lanes an implementer spawns are namespaced under it (`impl-fable-api-sol-1`) and are that lane's to watch, review-route, and tear down — the orchestrator sees only the parent's report. Sub-lane `--cwd` is the project root or a worktree, never a subdirectory (nested `.herd/` = forked ledger, unledgered lane; spawn warns). Codex (openai-codex) / sandboxed lanes never own build receipts (`xcodebuild`, SwiftPM manifest resolution write to `~/Library/Caches` — seatbelt blocks it): the orchestrator runs the receipt itself and reviewer briefs pre-declare it as orchestrator-verified.

## Spawning

`herd spawn` (syntax in the lifecycle block below) bakes in the verified pi launch flags (single source: `KIND_ARGS` in `bin/herd`); `--approve` at launch prevents routine dialogs. Workers are visible interactive panes the captain can watch and interrupt. `--profile <name>` runs the lane under `~/.pi/agent-<name>` — shared auth/models by symlink, own settings/extensions (e.g. a lean profile for models that choke on heavy extensions).

**Model verification is built into spawn**: it confirms the model against pi-powerline's breadcrumb and returns `"model_verified": true|false` in its JSON. Send work only on `true`. On `false`, fix in place — `herdr agent prompt <lane> "/model <provider/model>"`, then re-check the breadcrumb. Herdr restores the default model on any restart or restore: fix in place rather than respawning, and re-verify after every restart.

Spawn lazily on first task; `herd spawn` is idempotent — a live same-kind lane is adopted (also the resume path). Each lane gets its own tab; `--worktree` gives it a managed worktree on branch `lane/<name>` instead.

## Lane lifecycle (the whole loop)

```
herd spawn <lane> --kind pi [--worktree] [--cwd DIR] [--profile NAME] [--no-nudge] [-- --model ID]
herd send  <lane> --file prompt.md [--state implementing]   # or inline text / stdin
herd watch <lane> [--text] --timeout 1200                 # implementing lane
herd watch --any <lane> <lane> ... [--text] --timeout 600  # first lane wins; reviews ~600s
herd send  <lane> --review --state review --file review-prompt.md
herd triage <project>/.herd/findings-<lane>-N.json --backlog <backlog-file> [--promote ID[,ID...]]
herd land  <lane>                      # honors ship_mode; conflict -> handback
herd close <lane> [--integrated]       # closes tab / removes worktree; --integrated: dirty worktree whose files the parent already integrated
```

**spawn** pre-approves the lane so trust dialogs never appear; anything pretrust can't handle falls to the exit-3 path. It also gitignores `.herd/` in the project root.

**send** appends a unique per-turn `REPORT-END-<hex>` token and verifies delivery. herd answers no dialog, ever: a blocked lane makes send exit 3 with the pane excerpt — answer it yourself (`herdr agent send-keys <lane> ...`), then resend. Concurrent sends to different lanes are safe.

**watch** blocks until the lane's token appears as a lone line AND the agent has settled — ALWAYS run it in the background (pi-background-tasks `bg_run`), one watch per lane; a foreground watch blocks your entire turn and makes you look dead to the captain. Tokens are single-use: a re-watch with nothing pending waits instead of matching stale pane output; `--resume` (resumed sessions, missed reports) turns an already-consumed token into success reason `already-reported` plus the pane tail; a newer send supersedes an attached watch with a fast `superseded` failure; a deliberately closed lane returns reason `closed`, not a crash. Escalation exits: 2 agent gone, 3 dialog, 4 timeout — all self-notify, so a stalled lane is never silent; on a timeout that is not `advanced:true` (below), escalate rather than looping. On exit 3, answer the dialog yourself (`herdr agent send-keys`), confirm the pane moved, re-attach — only questions you cannot answer go to the captain: zero captain involvement is the bar, zero orchestrator involvement is not. **Watch the lane, never the artifact**: an output-file wait has no blocked-escape and turns a stuck worker into silence — the only legal waits are `herd watch` and its exit codes. `watch` also nudges an idle lane ONCE for its report when compaction ate the footer (non-coercive: "if still working, do not reply"; after `--nudge-after` seconds of quiet, default 600; per token, ledger-recorded) — spawn orchestrator / pseudo-orchestrator lanes with `herd spawn --no-nudge` (or watch `--no-nudge`): they idle on their own sub-lanes by design — and accepts a review lane's findings file as completion (reason `findings-file`). Exit 4 carries `agent_status` and `advanced`: `advanced:true` = the lane is still moving — re-arm the watch, don't escalate. Size fix-round timeouts to the handback: 8+ findings or an engine rewrite → `--timeout 3600`.

Every worker prompt carries:
- the whole slice with product-level acceptance, not a method — implementer lanes delegate per the two-tools rule above (sub-lanes all `--kind pi`, roles-table models) and own their lifecycle;
- "For exploration/search delegation use the sonnet tier (`claude-bridge/claude-sonnet-5`, or pi's scout role) — the floor tier; keep your own tier for reasoning and synthesis."

(Report-footer and sentinel are herd's job — don't add your own.)

**On any pane weirdness** — an unexpected watch/send exit, an empty read, a mid-run tool update, a spawn startup timeout, a missing toast — read `LORE.md` in this skill dir before diagnosing.

## Routing

Slice count scales with spec surface: a single-domain spec may be one lane; a full-stack spec gets one implementer per domain slice — each a whole vertical slice owned end-to-end including integration; atomizing into tickets produces modules that pass in isolation and no product. Ambiguous scope → impl-fable, which decomposes by spawning Sol sub-lanes rather than implementing first-hand. UI touching backend → frontend-kimi owns through the API it consumes; the backend lane owns providing it. The cross-lane API contract is the orchestrator's to sort out: settle the shape and write it into both slice prompts before sending; arbitrate any drift yourself — never leave it to review-time discovery or lane-to-lane negotiation.

Acceptance is product-level: "the user can do X", never "module Y's tests pass". **Run the final thing yourself** before calling anything done — drive the real UI hands-on with realistic data volumes, and walk anything web-facing at mobile/tablet/desktop widths (390/768/1440). Lane test suites catch what they were written to catch — a 41-assertion real-browser run once still shipped a mobile layout broken at every width.

**Read-only / evaluation mode** (audit, "what's missing", UX review): route analysis slices per the table, prefix every prompt "READ-ONLY — do not edit, write, or create files", skip the review matrix, synthesize the lanes into one Artifact — findings ranked, evidence as file:line. Teardown still applies.

## Shipping modes and collisions

`herd set ship_mode scratch|merge|pr` (per project, in the ledger; default scratch).

- **scratch** — lanes work directly in the project tree; review the git diff before the captain declares done. Scratch lanes get disjoint files. Commits land on the project's default branch, no push — that is the explicit go that satisfies "never commit to the default branch without owner go" in global AGENTS.md/CLAUDE.md.
- **merge** — implementers spawn `--worktree`, commit on `lane/<name>`. When review clears: `herd set <lane> state=reviewed`, then `herd land <lane>` merges (`--no-ff`). Land enforces the gate itself (refuses unreviewed or dirty states with exit 4 — for land/close, 4 means refused precondition, not timeout) and exits 3 on conflict with the files: hand the owning lane "merge main into your branch, resolve, keep both behaviors, re-run your checks", scoped re-review, land again. Conflicts are the owning lane's, never the captain's.
- **pr** — like merge, but `herd land` refuses to land locally; push and PR are the lane's manual steps (`git push -u origin lane/<name>`, then `gh pr create` per project docs). Herd doesn't enforce the review gate here — the PR review is the gate.

## Review matrix and bug loop

iOS/UI slices must pass the sim drill (`ios-sim-drill` skill) before review; AR/camera slices also need a device drill.

- impl-fable done → review-sol gets the branch/diff; impl-sol done → review-fable. **Parallel implementers: hold review until ALL batch lanes have reported, then ONE review pass over the combined diff** — the whole slice at once is what gives the reviewer blast-radius judgment for cuts. Cross-model: pick the reviewer opposite the model that wrote most of the batch. Reviewers are tab lanes, no `--worktree` — the branch diff is visible from the project repo. Adversarial: refute-first, actionable findings only. Reviewer independence: a reviewer never also gets its sibling implementer's work in the same task.
- frontend-kimi done → **reviewed before the captain ever sees it** by a `review-ui` lane (Sol) armed with the spec — it DRIVES the real UI (sim drill for iOS, browser for web): flows, validation, empty/error states, every viewport width, realistic data; findings arrive via `herd send --review`. The orchestrator reviews personally only when no Sol lane is available (it holds the product context). When the pass is clean, `herd set frontend-kimi state=reviewed` (landing needs it), then present what shipped (screenshot/URL/diff) for taste-level judgment; the captain is never the one to report "text box overflows on mobile." Other lanes don't gate on it.
- `herd send --review` makes findings arrive as data in `.herd/findings-<lane>-N.json` (herd gives the reviewer the format) — no finding is transcribed by hand.
- `herd triage <findings.json> --backlog <file>`: disastrous/architectural/blocking findings print for handback (send to the implementing lane verbatim, scoped re-review after the fix); the rest append to the backlog (project tracker or your own todo file) without interrupting anyone.

**Deslop is part of every review, not a separate pass.** The cut lens rides alongside the bug lens: one-caller helpers with no depth, defensive paths for impossible conditions, speculative flags/seams, comment bloat, implementation-pinning or duplicate tests, slow tests (worst `--durations`), stray files. **Tests pin product behavior through its interface** — a module-shaped or mock-exercising test is slop: cut it or rewrite it against the product surface. Keep-flags are mandatory: flag load-bearing code that merely looks like ceremony, with the reason — cutting it is the costly failure. Slop findings skip the backlog: safe cuts ride the handback and land with the slice; only risky cuts are backlogged. A whole-repo audit lane is an occasional tool for accreted fat, not a per-slice step.

A slice is done when review passes or all remaining findings are backlogged — and the orchestrator has verified the product.

## Captain contact points

Exactly two kinds: decisions only they can make (unknown dialogs, real worker questions, scope calls), and completion. Both get `herd notify "<title>" --body "<one line>" [--sound done|request]` — toast, falling back to a macOS notification — AND the same message in-channel: notify accompanies, never replaces.

## Status and resume

`herd status`: lane, kind, state (queued / implementing / review / fixing / user-review / done / backlogged-findings), liveness, task. Keep current with `herd set <lane> state=<s> task=<one-liner>`.

A fresh session resumes from the ledger: re-adopt live lanes with `herd spawn <lane> --kind pi` (idempotent), re-verify each lane's breadcrumb against its role, re-attach a background `herd watch --resume` for every lane in implementing/review/fixing (tokens persist in the ledger; `--resume` hands over an already-reported result instead of timing out on a consumed token), and pick up the review obligations the states imply. Never re-send a slice a live lane already has.

## Teardown

**Etiquette — every lane cleans up what it opened before it reports done**, and the orchestrator verifies before `herd close`: browser tabs/windows/instances it launched (never the captain's own Chrome), booted simulators it booted, dev servers, log tails, recordings, iPhone Mirroring/Mirroir sessions, background jobs, scratch files outside `.herd/`. The `ios-sim-drill` skill carries the sim teardown recipe. The captain must never come back to ten Chrome instances and a running sim. Gotcha: `osascript … tell application "X"` LAUNCHES X if it isn't running — `pgrep -x` first. **Machine-clean sweep is the orchestrator's last act before the final report** — lanes cleaning up is necessary, not sufficient; you own the end state. Run it and put the result in the report:

```bash
xcrun simctl list devices booted | grep -c Booted        # 0, or shut down what a lane booted (`xcrun simctl shutdown <udid>`)
pgrep -fl 'Simulator.app|xcodebuildmcp|mirroir|sim-use|peekaboo|recordVideo|chrome-devtools|--remote-debugging-port' | grep -v pgrep   # empty
lsof -nP -iTCP -sTCP:LISTEN | grep -v -e herdr -e rapportd | awk 'NR>1{print $1,$9}'   # no dev servers you or a lane started
herd status                                              # every lane closed
```

Kill/close what the run started (never the captain's own Chrome, sims or servers — compare against what was running when you began). A run is not done while any of it is still up.

`herd close <lane>` as work completes: implementer when its slice landed, reviewer when no review is pending, frontend-kimi once committed and presented. Close only settled agents; read a blocked worker's dialog first. Close refuses tabs it didn't create; worktree lanes lose the worktree (branch stays until landed). On spec completion, update your own project docs per your global rules.

