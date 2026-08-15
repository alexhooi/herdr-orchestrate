---
name: herdr-orchestrate-pi
description: PI-harness variant of herdr-orchestrate — same doctrine, but every worker lane the orchestrator spawns is a pi pane with the model selected per role via pi providers. Use when an orchestration run must stay entirely inside the pi harness.
---

# Herdr Orchestration — PI-harness variant

Precondition: `test "${HERDR_ENV:-}" = 1` — otherwise say so and stop.

Read and follow the base skill in full: the sibling `herdr-orchestrate` skill's `SKILL.md` (the `herd` tool it documents lives at `herdr-orchestrate/bin/herd`; both skills install side by side in `~/.claude/skills/`). Everything there applies except the overrides below, which win on conflict.

## Overrides

**1. Every lane is pi.** Spawn every worker lane — implementer, reviewer, frontend, sub-lane — with `--kind pi`. Never `--kind claude` or `--kind codex`. The model is selected per role with extra args after `--`.

**2. Roles table remap** (same responsibilities as the base table; only the harness/model columns change):

| lane name | spawn as |
|---|---|
| `impl-fable[-<slice>]` | `herd spawn <lane> --kind pi ... -- --model claude-bridge/claude-fable-5` |
| `impl-sol[-<slice>]` | `herd spawn <lane> --kind pi ... -- --model openai-codex/gpt-5.6-sol` |
| `frontend-kimi` | `herd spawn <lane> --kind pi ...` (pi default kimi-k3 — no override) |
| `review-sol` | `--kind pi ... -- --model openai-codex/gpt-5.6-sol` |
| `review-fable` | `--kind pi ... -- --model claude-bridge/claude-fable-5` |
| exploration/scout sub-lanes | `--kind pi ... -- --model claude-bridge/claude-sonnet-5` |

**3. Model verification is built into spawn.** `herd spawn --kind pi ... -- --model <id>` now confirms the model itself against pi-powerline's plain-text breadcrumb and returns `"model_verified": true|false` in its JSON (waits up to ~35s for the banner). On `false`, fix in place before sending work: `herdr agent prompt <lane> "/model <provider/model>"` (it confirms with a `Model: <id>` line), then re-check the breadcrumb — never proceed on the wrong model. (Appending `--model` produces two `--model` flags; last-wins holds — verified 2026-08-16.)

**4. Pi-internal delegation is legal.** Pi's built-in subagent routing (its role files already map to fable/sol/sonnet/kimi via pi providers) counts as pi-harness; a lane using it needs no extra dispensation.

**5. Codex-sandbox lore doesn't apply.** Base-skill notes about codex seatbelt sandboxing, `-a never`, and codex network flags are irrelevant here — no codex CLI lanes exist. Pi lanes run with `--approve` as the base skill's spawn already bakes in.
