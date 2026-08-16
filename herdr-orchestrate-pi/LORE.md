# Failure lore (kept because it still bites)

- Trust the pane over `agent_status`: screen detection lags both ways; `done` = idle after unseen work; settled-without-token is an idle blip, not completion. `herdr agent explain <lane>` shows the reasoning.
- `agent read --source recent-unwrapped` can transiently return empty while an agent renders — herd's fallback handles it; remember it when reading panes manually.
- Dialog doctrine: herd matches NO dialog text — five adversarial review rounds refuted every text-scrape classifier. Dialogs are prevented at launch (`--approve`, pretrust); whatever still appears exits 3 with the pane excerpt, orchestrator answers by hand. Do not reintroduce screen-text classification.
- Tool self-updates mid-run are normal (herdr drops registrations; pi re-raises trust dialogs). Restart in the same pane (`herdr agent start`), re-verify the breadcrumb, resend. Folder trust survives restarts; any re-raised dialog → send exits 3: answer it (`herdr agent send-keys <lane> enter`), resend.
- First-ever spawn into a fresh cwd can time out at agent startup ("timed out waiting for agent startup") and clean itself up — retry the same spawn once before diagnosing. (Bitten live 2026-08-16; retry succeeded.)
- Toast config (`[ui.toast]` in herdr config) is read at server start — editing it mid-session does nothing; `herd notify`'s osascript fallback covers it.
- Truncated pane report → have the worker write markdown to a temp file and reply with the path.
- Pi extensions can dirty a worktree AFTER the lane commits (e.g. a deferred pi-lens whole-file reformat). If the committed version is the verified one, discard the post-commit changes — do not re-open the lane for them. (Bitten live 2026-08-16.)
