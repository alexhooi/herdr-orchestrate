# How this got here

This repo is published with fresh history; the private repo it came from carries
25 commits of adversarial review spirals and live drills. The short version, kept
because the lessons are load-bearing:

## Dialog doctrine (5 adversarial review rounds)

The first designs tried to *classify* CLI dialogs from screen text and answer
them automatically. Five consecutive adversarial review rounds refuted every
classifier — soft-wrap forgery, stale-snapshot TOCTOU races, region binding,
generation gaps. The surviving doctrine inverted the problem: **prevent dialog
classes at launch** (approval flags, sandbox flags, pre-seeded folder trust) and
let anything that still appears **fail closed to the orchestrator** (exit 3 with
the pane excerpt, self-notifying). herd contains zero dialog-text matching. Do
not reintroduce it.

## The pretrust hardening spiral — and its deliberate deletion

Pre-seeding the codex/claude trust stores grew, over several review rounds, into
~430 lines: a hand-rolled TOML scanner that surgically rewrote `trust_level`
inside any existing entry byte-safely, plus macOS `renamex_np(RENAME_SWAP)`
displaced-inode verification making silent clobber of concurrent lockless
writers impossible (validated with 1000-round hammer tests: 206 genuine
mid-commit collisions, zero lost writes). It worked.

Then we deleted almost all of it. The realization: pretrust is a convenience,
not a correctness gate — its entire failure mode is *a trust dialog appears
once*, which the exit-3 path already handles in ~30 seconds. 40% of the tool was
defending against a microsecond race whose worst case was already covered. The
shipped version handles the two cases that actually occur (already trusted →
no-op; entry absent → append, which never touches existing bytes) and skips
everything else. Residual risk accepted: an external writer landing in the
stat→rename microsecond window during a first spawn per project is silently
rolled back instead of detected-and-repaired.

The lesson we kept: **before hardening a component, price its failure mode.**
If the failure is cheap and already handled, the hardening is bloat with tests.

## Production gate

v2 passed a live gate before daily use: two-lane merge-collision drill with
conflict handback, an 8-lane mixed stampede, a literal orchestrator-SIGKILL
mid-watch with a fresh session resuming from the ledger (adoption, watch
re-attach, zero doctrine deviations), and a notify-fallback exercise.

## The showdown

The same spec was built twice by two orchestrators — one on native harnesses
(Claude Code + Codex CLI), one with every seat on the pi harness (models
selected per role). Independent scorecards tied; the pi run was faster and the
captain preferred its maintainability. Two doctrine amendments came out of the
debrief and are in SKILL.md: the orchestrator personally drives the real UI at
mobile/tablet/desktop widths with realistic data before calling anything done
(a 41-assertion browser suite had shipped a mobile layout broken at every
width), and frontend work is reviewed against the spec before the captain ever
sees it. The pi-variant skill (`herdr-orchestrate-pi/`) also exists because of
this run.

## 2026-08-19: showdown round 2, ops hardening

A second showdown round surfaced live-ops gaps rather than design flaws: watch
now nudges an idle lane once when compaction eats its report footer, and
accepts a review lane's findings file as completion in its own right — neither
failure mode is a hang, so neither should read as one. Spawn hardened its
cwd handling (refuses to ledger a lane in `$HOME`) and `herd close` gained
`--integrated` for a worktree lane whose files the parent already folded in.

UI review got its own lane, `review-ui`: it drives the shipped UI directly —
simulator or browser — before the captain ever sees it, rather than trusting
a text-only diff review. The `ios-sim-drill` skill (new in this repo) is the
shared drill both orchestrator skills route iOS/UI work through: build,
install, timed interaction, screenshots, memory ceiling, teardown.

Teardown itself got promoted from convention to doctrine: every lane cleans
up what it opened, and the orchestrator runs a machine-clean sweep — booted
simulators, dev servers, stray browser processes — as its own last act before
reporting done. A run that leaves the machine dirty isn't done.

A bloat pass followed: cut speculative flags, one-caller helpers, and slop
tests that pinned implementation rather than product behavior. Closed with a
fresh all-pi demo run of the same Splitwise-lite spec, this time exercising
the hardened watch/close paths and the new `review-ui` lane end to end.
