---
name: herdr-orchestrate
description: "Master-orchestrator workflow for herdr. Use when running inside a herdr pane (HERDR_ENV=1) and the user hands over a spec, feature, or read-only evaluation to execute: spawn role workers in tabs, route vertical slices, run the cross-review matrix, manage the bug backlog while staying interactive. Keywords: orchestrate, spec, workers, evaluation."
---

# Herdr Orchestration v2

Precondition: `test "${HERDR_ENV:-}" = 1` — otherwise say so and stop.

All lane plumbing lives in one tool: `<this skill dir>/bin/herd` (put it on PATH or call it by absolute path; every command below is `herd <verb>`). It wraps the herdr CLI so the conversation carries only intent — routing, triage rulings, product checks — never shell mechanics. Run herd from the project directory (or set `HERD_PROJECT`); it keeps a per-project ledger in `<project>/.herd/ledger.json`.

Preflight once per session:
- `herdr integration status --outdated-only` — update anything listed (`herdr integration install <name>`). Outdated integrations are the root cause of codex re-raising its hooks-trust dialog every spawn.
- `herd status` — if a ledger already exists, you are **resuming** someone else's run: adopt it (see Resume) instead of spawning duplicates.

## Roles

| lane name | kind | takes |
|---|---|---|
| (this session) | claude | routing, triage, status. NEVER implements or reviews |
| `impl-fable[-<slice>]` | claude (Fable, high) | owns a slice as its pseudo-orchestrator: architecture, integration, acceptance — and spawns its own Sol/kimi sub-lanes via `herd` for the scoped chunks, as naturally as spawning subagents. Fable typing out well-specified code itself is a routing smell |
| `impl-sol[-<slice>]` | codex | scoped, well-specified tasks (spawned by the orchestrator or by an impl-fable lane) |
| `frontend-kimi` | pi | frontend, design, UI |
| `review-sol` | codex | reviews fable-implemented work |
| `review-fable` | claude (Fable) | reviews sol-implemented work |

Sub-lanes an implementer spawns are namespaced under it (`impl-fable-api-sol-1`) and are that lane's to watch, review-route, and tear down — the orchestrator sees only the parent lane's report.

`herd spawn <lane> --kind <claude|codex|pi>` bakes in the verified per-kind launch flags — the single source is `KIND_ARGS` in `bin/herd`; don't restate them here. What matters operationally: approvals and sandboxing are set so routine dialogs are prevented at launch (see Failure lore for the doctrine), codex gets `--no-alt-screen` (without it completed responses are unrecoverable from scrollback), and pi's working Kimi provider is Moonshot (`kimi-coding/*` 402s). Workers are visible interactive panes the captain can watch and interrupt. Extra native args go after `--`. `--profile <name>` (pi tab lanes) runs the lane under the config dir `~/.pi/agent-<name>` via `PI_CODING_AGENT_DIR` — a profile shares auth/models/packages with `~/.pi/agent` by symlink but keeps its own settings/extensions (e.g. a lean profile for models that choke on heavy extensions). Confirm the model in the pane banner after a start — herdr can restore a default model; fix pi in place with `/model <provider/model>` rather than respawning.

Spawn lazily on first task for a role; `herd spawn` is idempotent — if the name is already bound to a live agent of the right kind it adopts it (this is also the resume path). Each lane gets its own tab; with `--worktree` it gets a herdr-managed git worktree on branch `lane/<name>` in its own workspace instead.

## Lane lifecycle (the whole loop)

```
herd spawn <lane> --kind <kind> [--worktree] [--cwd DIR] [--profile NAME] [-- extra-args]
herd send  <lane> --file prompt.md [--state implementing]   # or inline text / stdin
herd watch <lane> --timeout 600        # run in BACKGROUND, one per lane
herd send  <lane> --review --state review --file review-prompt.md
herd triage <project>/.herd/findings-<lane>-N.json --backlog <backlog-file>
herd land  <lane>                      # honors ship_mode; conflict -> handback
herd close <lane>                      # closes tab / removes worktree
```

**spawn** pre-seeds the CLI's own trust store for the lane's cwd (codex `~/.codex/config.toml`, claude `~/.claude.json`; pi via `--approve`) so folder-trust dialogs never appear. Pretrust is best-effort by decision (see README, “Pretrust”): it handles already-trusted and entry-absent only; anything else is skipped and the dialog falls to the exit-3 path.

**send** appends the report footer (a unique per-turn `REPORT-END-<hex>` token) and then *verifies delivery*: first prompts to fresh workers can get eaten, and the loss reports success — send detects and resubmits. herd answers no dialog, ever: if the lane is blocked, send exits 3 with the pane excerpt — you read it and answer it yourself (`herdr agent send-keys <lane> ...`), then resend. Concurrent sends to different lanes are safe (the ledger is flock-guarded).

**watch** blocks until the lane's current token appears as a lone line in the pane AND the agent has settled — run one `herd watch` per lane as a background task so each completion wakes you individually the moment it happens. Never gate on all lanes: one finished lane is actionable now. Escalation exits: 2 agent gone, 3 dialog, 4 timeout — all self-notify, so a stalled lane can never be silent. On exit 3, read the excerpt and answer the dialog yourself (`herdr agent send-keys <lane> enter|esc|...`, confirm the pane moved, re-attach the watch); only questions you cannot answer go to the captain — zero captain involvement is the bar, zero orchestrator involvement is not. The unique token makes stale sentinels from earlier turns harmless. **Watch the lane, never the artifact**: waiting on an output file (`until [ -s findings.json ]`) has no blocked-escape and turns a stuck worker into silence — the only legal waits are `herd watch` and its exit codes.

Every worker prompt carries:
- the whole slice with product-level acceptance, not a method — workers delegate internally as they see fit; implementer lanes are told they can spawn scoped `herd` sub-lanes (Sol for well-specified code, kimi for UI) and own their lifecycle;
- "For exploration/search subagents use `model: sonnet` (the floor tier — never haiku); keep your own tier for reasoning and synthesis only."

(The report-footer and sentinel are herd's job — don't add your own.)

## Routing

Slice count scales with spec surface: a single-domain spec may be one lane, but a full-stack spec gets one implementer per domain slice (backend, frontend, infra, ...) — each still a whole vertical slice of its domain owned end-to-end including integration; atomizing into tickets produces modules that pass in isolation and no product. Route by the roles table. Ambiguous scope → an impl-fable lane, which decomposes further itself by spawning Sol sub-lanes for the well-specified chunks rather than implementing everything first-hand. UI touching backend → frontend-kimi owns through the API it consumes; the backend lane owns providing it.

Acceptance is product-level: "the user can do X", never "module Y's tests pass". The orchestrator verifies the assembled product itself (run it — `/run`, curl, browser) before calling anything done. **Run the final thing and review the product you managed** — personally, not by trusting a lane's verification report: drive the real UI hands-on with realistic data volumes, and for anything web-facing walk it at mobile/tablet/desktop widths (390/768/1440). Lane test suites catch what they were written to catch — a 41-assertion real-browser run once still shipped a mobile layout broken at every width.

**Read-only / evaluation mode** (audit, "what's missing", UX review): route analysis slices by expertise per the table, prefix every prompt with "READ-ONLY — do not edit, write, or create files", skip the review matrix, and synthesize the lanes into one deliverable — an Artifact with findings ranked, evidence as file:line. Teardown still applies.

## Shipping modes and collisions

`herd set ship_mode scratch|merge|pr` (per project, stored in the ledger; default scratch).

- **scratch** — lanes work directly in the project tree; review happens on the git diff before the captain declares done. Don't give two scratch lanes the same files.
- **merge** — spawn implementers with `--worktree`; each owns branch `lane/<name>` and commits there. Nothing reaches main until its review passed: set `herd set <lane> state=reviewed` when the review clears, then `herd land <lane>` merges (`--no-ff`). Land enforces the gate itself — it refuses an unreviewed state, a lane worktree with uncommitted work, a dirty project tree, or a project checked out on a different branch than the lane was cut from. On conflict it aborts the merge and exits 3 with the conflicting files — hand that lane "merge main into your branch, resolve, keep both behaviors, re-run your checks", then a scoped re-review, then land again. Conflicts are resolved by the owning lane, reported to no one silently, and never by the captain.
- **pr** — like merge for implementation, but `herd land` refuses to land locally (verified: it exits 0 with a refusal note and performs no merge — local main stays untouched even for a reviewed lane). The push and the PR are the lane's manual steps: `git push -u origin lane/<name>`, then open the PR per the project's contributing docs (`gh pr create` where GitHub) — herd plays no part in either. Note the review gate is not enforced by herd in pr mode (land refuses before checking state); the PR review is the gate.

## Review matrix and bug loop

- impl-fable finished → review-sol gets the branch/diff. impl-sol finished → review-fable. Adversarial: refute-first, actionable findings only. Keep reviewer independence: a reviewer never also gets its sibling implementer's work in the same task.
- frontend-kimi finished → **reviewed before the captain ever sees it**: either spawn a UI reviewer lane armed with the spec/PRD, or the orchestrator reviews it personally — it holds all the product context. The review drives the real UI against the spec (flows, validation, empty/error states, and every viewport width with realistic data). Only then present what shipped (screenshot/URL/diff summary) to the captain for taste-level judgment; the captain is never the one to report "text box overflows on mobile." Other lanes don't gate on it.
- `herd send --review` makes findings arrive as data: it points the reviewer at `.herd/findings-<lane>-N.json` (JSON array: severity ∈ disastrous|architectural|blocking|major|minor|nit, file, line, symptom, fix_hint) — no finding is ever transcribed by hand.
- `herd triage <findings.json> --backlog <file>` applies the bug-loop rule: disastrous/architectural/blocking findings are printed for hand-back (send them to the implementing lane verbatim, re-review after the fix — scoped to the finding); everything else is appended to the backlog (your project tracker, or a plain `todo.md`) without interrupting anyone.

A slice is done when review passes or all remaining findings are backlogged — and the orchestrator has verified the product.

## Captain contact points

Exactly two kinds: decisions only they can make (unknown dialogs, real questions from workers, scope calls), and completion. Both get `herd notify "<title>" --body "<one line>" [--sound done|request]` — it raises a herdr toast and, if toasts are disabled in config, falls back to a macOS system notification; either way, also state it in-channel. Silent drops are impossible: notify never replaces the in-channel message, it accompanies it.

## Status and resume

`herd status` — the one-ask compact view: lane, kind, state (queued / implementing / review / fixing / user-review / done / backlogged-findings), liveness against `herdr agent list`, task. Keep states current with `herd set <lane> state=<s> task=<one-liner>`.

If the orchestrator dies mid-run, a fresh session resumes: the ledger on disk says which lanes exist, what each owns (`task`), its state and branch; `herd status` marks which are still live. Re-adopt live lanes with `herd spawn <lane> --kind <kind>` (idempotent), re-attach a background `herd watch` for every lane in implementing/review/fixing state (tokens persist in the ledger), and pick up the review obligations the states imply. Never re-send a slice to a live lane that already has it.

## Teardown

The orchestrator owns worker lifecycle — `herd close <lane>` as work completes: implementer when its slice landed, reviewer when no review is pending, frontend-kimi once work is committed and presented. Close only settled agents; read a blocked worker's dialog before touching it. `herd close` refuses tabs it didn't create; worktree lanes get their worktree removed (the branch stays until landed).

## Failure lore (kept because it still bites)

- Trust the pane over `agent_status`: screen-detected state lags both directions; `done` = idle after unseen work; a settled state without the token is an idle blip, not completion. `herdr agent explain <lane>` shows why detection thinks what it thinks.
- `agent read --source recent-unwrapped` can return *empty* transiently while an agent renders, and codex startup dialogs render only on the visible screen — herd's read fallback handles both; remember it if reading panes manually.
- Dialog doctrine: herd matches NO dialog text, anywhere — five adversarial review rounds refuted every text-scrape classifier (soft-wrap forgery, stale-snapshot TOCTOU, region binding, generation gaps). Dialog classes are prevented at the source instead: approvals via launch flags (`-a never`, `bypassPermissions`, `--approve`), folder trust via spawn's pretrust of the CLI config stores. Whatever still appears: watch/send exit 3 with the pane excerpt (watch self-notifies), orchestrator answers by hand. Do not reintroduce screen-text classification.
- Tool self-updates mid-run are normal (herdr drops registrations; codex/pi raise trust dialogs). Restart the agent in the same pane (`herdr agent start` again), then resend. Folder trust survives restarts (it lives in the CLI's config store), but a re-raised hooks-trust or any other dialog makes send exit 3: read the excerpt, answer it yourself (`herdr agent send-keys <lane> enter`), resend.
- Codex sandbox blast radius, measured live (`-a never -s workspace-write`, macOS seatbelt): ALL network is blocked including DNS (`CODEX_SANDBOX=seatbelt`, `CODEX_SANDBOX_NETWORK_DISABLED=1` — curl exit 6 "could not resolve", even `nslookup` gets `bind: Operation not permitted`); writes are allowed only in the lane's cwd, `/tmp`, and `$TMPDIR`; writes to `$HOME` and system paths fail `Operation not permitted`; reads are unrestricted everywhere. Escape hatch for lanes that legitimately need network: spawn with `-- -c sandbox_workspace_write.network_access=true` (verified live: HTTP 200 + DNS resolve, filesystem still sandboxed). Full-access lanes would need `-s danger-full-access` as an extra arg — unverified, use only with an explicit captain ruling.
- Codex worktree lanes cannot `git commit`: a linked worktree's git metadata lives under the main repo's `.git/worktrees/`, outside the seatbelt's writable roots (cwd + /tmp). The lane reports the work uncommitted; the orchestrator commits in the lane's worktree — that's plumbing, not implementation. (Bitten live 2026-08-15.)
- `herd notify` falls back to an osascript system notification when herdr reports `shown:false`. Toast config is read at server start — editing it mid-session does nothing.
- Claude panes bury final output under ~45 lines of composer chrome — read with `--lines 60+`.
- If a report truncates in the pane, have the worker write it as markdown to a temp file and reply with the path.
