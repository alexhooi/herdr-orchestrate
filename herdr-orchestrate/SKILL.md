---
name: herdr-orchestrate
description: "Master-orchestrator workflow for herdr, native harnesses (claude/codex/pi lanes). Fire when inside a herdr pane (HERDR_ENV=1) and the captain hands over a spec, feature, or read-only evaluation to orchestrate across mixed harnesses. All-pi runs go to herdr-orchestrate-pi instead."
---

# Herdr Orchestration v2

Precondition: `test "${HERDR_ENV:-}" = 1` — otherwise say so and stop.

All lane plumbing is one tool: `<this skill dir>/bin/herd` (on PATH or by absolute path) — every command below is `herd <verb>`. Run it from the project directory (or set `HERD_PROJECT`); it keeps a ledger in `<project>/.herd/ledger.json`.

Preflight once per session:
- `herdr integration status --outdated-only` — update anything listed; outdated integrations re-raise trust dialogs on spawn.
- `herd status` — an existing ledger means you are **resuming**: adopt it (see Resume), don't spawn duplicates.

## Roles

| lane name | kind | takes |
|---|---|---|
| (this session) | claude | routing, triage, status. NEVER implements or reviews |
| `impl-fable[-<slice>]` | claude (Fable, high) | owns a slice as its pseudo-orchestrator: architecture, integration, acceptance — spawns its own Sol/kimi sub-lanes for scoped chunks. Fable typing well-specified code itself is a routing smell |
| `impl-sol[-<slice>]` | codex | scoped, well-specified tasks |
| `frontend-kimi` | pi (`--profile kimi`) | frontend, design, UI |
| `review-sol` | codex | reviews fable-implemented work |
| `review-fable` | claude (Fable) | reviews sol-implemented work |

Sub-lanes an implementer spawns are namespaced under it (`impl-fable-api-sol-1`) and are that lane's to watch, review-route, and tear down — the orchestrator sees only the parent's report.

## Spawning

`herd spawn` (syntax in the lifecycle block below) bakes in the verified per-kind launch flags (single source: `KIND_ARGS` in `bin/herd`) — approvals and sandboxing are set at launch so routine dialogs are prevented, and codex gets `--no-alt-screen` (without it completed responses are unrecoverable from scrollback). Workers are visible interactive panes the captain can watch and interrupt. Extra native args go after `--`. `--profile <name>` (pi lanes) runs the lane under `~/.pi/agent-<name>` — shared auth/models by symlink, own settings/extensions (e.g. a lean profile for models that choke on heavy extensions).

Pi lanes with a `--model` override get verification built into spawn: `"model_verified": true|false` in its JSON against the pane breadcrumb. Send work only on `true`; on `false`, fix in place (`herdr agent prompt <lane> "/model <provider/model>"`), re-check. For claude/codex lanes, confirm the model in the pane banner after any restart — herdr can restore a default model; fix in place rather than respawning.

Spawn lazily on first task; `herd spawn` is idempotent — a live same-kind lane is adopted (also the resume path). Each lane gets its own tab; `--worktree` gives it a managed worktree on branch `lane/<name>` instead.

## Lane lifecycle (the whole loop)

```
herd spawn <lane> --kind <claude|codex|pi> [--worktree] [--cwd DIR] [--profile NAME] [-- extra-args]
herd send  <lane> --file prompt.md [--state implementing]   # or inline text / stdin
herd watch <lane> --timeout 600        # run in BACKGROUND, one per lane
herd send  <lane> --review --state review --file review-prompt.md
herd triage <project>/.herd/findings-<lane>-N.json --backlog <backlog-file>
herd land  <lane>                      # honors ship_mode; conflict -> handback
herd close <lane>                      # closes tab / removes worktree
```

**spawn** pre-seeds the CLI's own trust store for the lane's cwd (codex `~/.codex/config.toml`, claude `~/.claude.json`; pi via `--approve`) so folder-trust dialogs never appear; anything pretrust can't handle falls to the exit-3 path.

**send** appends a unique per-turn `REPORT-END-<hex>` token and verifies delivery (first prompts to fresh workers can get eaten — send detects and resubmits). herd answers no dialog, ever: a blocked lane makes send exit 3 with the pane excerpt — answer it yourself (`herdr agent send-keys <lane> ...`), then resend. Concurrent sends to different lanes are safe.

**watch** blocks until the lane's token appears as a lone line AND the agent has settled — run one background `herd watch` per lane so each completion wakes you the moment it happens; one finished lane is actionable now. Escalation exits: 2 agent gone, 3 dialog, 4 timeout — all self-notify, so a stalled lane is never silent. On exit 3, answer the dialog yourself (`herdr agent send-keys`), confirm the pane moved, re-attach the watch; only questions you cannot answer go to the captain — zero captain involvement is the bar, zero orchestrator involvement is not. **Watch the lane, never the artifact**: waiting on an output file has no blocked-escape and turns a stuck worker into silence — the only legal waits are `herd watch` and its exit codes.

Every worker prompt carries:
- the whole slice with product-level acceptance, not a method — workers delegate internally as they see fit; implementer lanes may spawn scoped `herd` sub-lanes (Sol for well-specified code, kimi for UI) and own their lifecycle;
- "For exploration/search subagents use `model: sonnet` — the floor tier; keep your own tier for reasoning and synthesis."

(Report-footer and sentinel are herd's job — don't add your own.)

**On any pane weirdness** — an unexpected watch/send exit, an empty read, a mid-run tool update, a spawn startup timeout, a missing toast, a codex sandbox denial — read `LORE.md` in this skill dir before diagnosing.

## Routing

Slice count scales with spec surface: a single-domain spec may be one lane; a full-stack spec gets one implementer per domain slice — each a whole vertical slice owned end-to-end including integration; atomizing into tickets produces modules that pass in isolation and no product. Ambiguous scope → impl-fable, which decomposes by spawning Sol sub-lanes rather than implementing first-hand. UI touching backend → frontend-kimi owns through the API it consumes; the backend lane owns providing it. The cross-lane API contract is the orchestrator's to sort out: settle the shape and write it into both slice prompts before sending; arbitrate any drift yourself — never leave it to review-time discovery or lane-to-lane negotiation.

Acceptance is product-level: "the user can do X", never "module Y's tests pass". **Run the final thing yourself** before calling anything done — drive the real UI hands-on with realistic data volumes, and walk anything web-facing at mobile/tablet/desktop widths (390/768/1440). Lane test suites catch what they were written to catch — a 41-assertion real-browser run once still shipped a mobile layout broken at every width.

**Read-only / evaluation mode** (audit, "what's missing", UX review): route analysis slices per the table, prefix every prompt "READ-ONLY — do not edit, write, or create files", skip the review matrix, synthesize the lanes into one Artifact — findings ranked, evidence as file:line. Teardown still applies.

## Shipping modes and collisions

`herd set ship_mode scratch|merge|pr` (per project, in the ledger; default scratch).

- **scratch** — lanes work directly in the project tree; review the git diff before the captain declares done. Scratch lanes get disjoint files.
- **merge** — implementers spawn `--worktree`, commit on `lane/<name>`. When review clears: `herd set <lane> state=reviewed`, then `herd land <lane>` merges (`--no-ff`). Land enforces the gate itself (refuses unreviewed or dirty states, explaining why) and exits 3 on conflict with the files: hand the owning lane "merge main into your branch, resolve, keep both behaviors, re-run your checks", scoped re-review, land again. Conflicts are the owning lane's, never the captain's.
- **pr** — like merge, but `herd land` refuses to land locally; push and PR are the lane's manual steps (`git push -u origin lane/<name>`, then `gh pr create` per project docs). Herd doesn't enforce the review gate here — the PR review is the gate.

## Review matrix and bug loop

- impl-fable done → review-sol gets the branch/diff; impl-sol done → review-fable. Reviewers are tab lanes, no `--worktree` — the branch diff is visible from the project repo. Adversarial: refute-first, actionable findings only. Reviewer independence: a reviewer never also gets its sibling implementer's work in the same task.
- frontend-kimi done → **reviewed before the captain ever sees it**: a UI reviewer lane armed with the spec, or the orchestrator personally (it holds the product context). The review drives the real UI against the spec — flows, validation, empty/error states, every viewport width, realistic data. When the pass is clean, `herd set frontend-kimi state=reviewed` (personal review counts as review clearing — landing needs it), then present what shipped (screenshot/URL/diff) for taste-level judgment; the captain is never the one to report "text box overflows on mobile." Other lanes don't gate on it.
- `herd send --review` makes findings arrive as data in `.herd/findings-<lane>-N.json` (herd gives the reviewer the format) — no finding is transcribed by hand.
- `herd triage <findings.json> --backlog <file>`: disastrous/architectural/blocking findings print for handback (send to the implementing lane verbatim, scoped re-review after the fix); the rest append to the backlog (project tracker, else the wiki `todo.md`) without interrupting anyone.

A slice is done when review passes or all remaining findings are backlogged — and the orchestrator has verified the product.

## Captain contact points

Exactly two kinds: decisions only they can make (unknown dialogs, real worker questions, scope calls), and completion. Both get `herd notify "<title>" --body "<one line>" [--sound done|request]` — toast, falling back to a macOS notification — AND the same message in-channel: notify accompanies, never replaces.

## Status and resume

`herd status`: lane, kind, state (queued / implementing / review / fixing / user-review / done / backlogged-findings), liveness, task. Keep current with `herd set <lane> state=<s> task=<one-liner>`.

A fresh session resumes from the ledger: re-adopt live lanes with `herd spawn <lane> --kind <kind>` (idempotent), confirm each lane's model banner, re-attach a background `herd watch` for every lane in implementing/review/fixing (tokens persist in the ledger), and pick up the review obligations the states imply. Never re-send a slice a live lane already has.

## Teardown

`herd close <lane>` as work completes: implementer when its slice landed, reviewer when no review is pending, frontend-kimi once committed and presented. Close only settled agents; read a blocked worker's dialog first. Close refuses tabs it didn't create; worktree lanes lose the worktree (branch stays until landed). On spec completion, update the wiki page per global rules.
