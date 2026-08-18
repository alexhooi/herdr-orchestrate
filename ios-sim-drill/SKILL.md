---
name: ios-sim-drill
description: Run the named iOS simulator drill only when the captain explicitly invokes this skill.
disable-model-invocation: true
---

# iOS simulator drill

Set these from the slice before starting: `REPO`, project/workspace path, `SCHEME`, `SIMULATOR`, `UDID`, `BUNDLE_ID`, `DURATION_MIN`, and `MEMORY_CEILING_MB`. Run from `$REPO`. Put all drill artifacts in `.herd/drill/`; do not claim a device-only AR/camera path was tested in Simulator.

## Build, install, launch

Use Pi's single `mcp` proxy. Set session defaults once, then leave later calls argument-light:

```js
mcp({ tool: "xcodebuildmcp_session_set_defaults", args: {
  projectPath: "App/Example.xcodeproj", // use workspacePath instead when applicable
  scheme: "Example",
  simulatorName: "iPhone 17 Pro",
  bundleId: "com.example.app"
}})
mcp({ tool: "xcodebuildmcp_build_sim", args: {} })
mcp({ tool: "xcodebuildmcp_get_sim_app_path", args: {} })
mcp({ tool: "xcodebuildmcp_install_app_sim", args: { appPath: "<path returned above>" } })
mcp({ tool: "xcodebuildmcp_launch_app_sim", args: {} })
```

Record the build result/log path, launch PID, runtime stderr log, and OSLog path returned by XcodeBuildMCP. Do not substitute raw `xcodebuild`.

## Exercise the UI for N minutes

Start a timer and exercise the slice's real flows for at least `$DURATION_MIN`: navigation, state changes, text entry, scrolling, modal/sheet open-close, and one error/degraded path where applicable. Re-observe after every navigation, scroll, sheet change, or obvious layout change.

Preferred mounted MCP path:

```js
mcp({ tool: "xcodebuildmcp_snapshot_ui", args: {} })
mcp({ tool: "xcodebuildmcp_tap", args: { elementRef: "e1" } })
mcp({ tool: "xcodebuildmcp_swipe", args: { withinElementRef: "e7", direction: "up", distance: 0.7 } })
mcp({ tool: "xcodebuildmcp_type_text", args: { elementRef: "e8", text: "test", replaceExisting: true } })
```

If `snapshot_ui` returns about zero interaction targets on a screen that visibly has controls, the elementRef-only MCP path has no coordinate fallback; switch to `sim-use describe-ui` and coordinate `tap`/`touch`.

Use `sim-use` when it gives the richer tree or when coordinate control is needed:

```bash
sim-use describe-ui --device "$UDID" --json > .herd/drill/ui.json
sim-use tap @N --device "$UDID"
sim-use type 'test' --device "$UDID"
sim-use swipe --from 111,759 --to 260,759 --coordinate-space ui --device "$UDID"
```

`sim-use tap` can report success yet no-op on SwiftUI switches inside sheets. Verify state with a fresh `describe-ui`; if unchanged, use the proven low-level workaround at the switch center:

```bash
sim-use touch --x X --y Y --down --up --coordinate-space ui --device "$UDID"
```

## Screenshots, logs, memory

Take numbered screenshots at launch, after each meaningful state, at any friction point, and at the final state:

```bash
mkdir -p .herd/drill
sim-use screenshot --device "$UDID" --output .herd/drill/01-launch.png
# Continue 02-..., preserving failed/no-op states as evidence.
```

XcodeBuildMCP screenshots are also valid (`xcodebuildmcp_screenshot`, `returnFormat: "path"`); copy each returned file into the numbered evidence directory. Prefer `sim-use` when full-resolution PNG is useful.

Read memory at launch and after the full exercise using the launch PID (Simulator apps are host processes):

```bash
ps -o pid=,rss=,etime=,command= -p "$PID" | tee .herd/drill/memory-launch.txt
# after the N-minute exercise
ps -o pid=,rss=,etime=,command= -p "$PID" | tee .herd/drill/memory-final.txt
```

RSS is KB; compute `RSS / 1024` MB and compare the peak/final reading with `$MEMORY_CEILING_MB`. Preserve XcodeBuildMCP's auto-captured stderr/OSLog paths. Add a focused simulator log receipt when useful:

```bash
xcrun simctl spawn "$UDID" log show --style compact --last "${DURATION_MIN}m" \
  --predicate "process == \"${SCHEME}\"" > .herd/drill/app-log.txt
rg -ni 'crash|fatal|abort|exception|uncaught' .herd/drill/app-log.txt
```

## Evidence and verdict

Write `.herd/drill/SIM-DRILL.md` with: repo/branch/commit, simulator + OS + UDID, defaults used, exact build/install/launch results, timed interaction list and observed state after each, numbered screenshot index, log paths/findings, launch/final/peak RSS, ceiling, friction/workarounds, and AR/camera simulator limitations.

Pass only when the app launches, the UI is exercised for at least `$DURATION_MIN`, memory stays at or below `$MEMORY_CEILING_MB`, and the captured logs show no crash. Any failed condition is a drill failure. AR/camera slices additionally require a separate physical-device drill before review.

## Teardown (mandatory — leave the machine as you found it)

Record at start what was already open (`xcrun simctl list devices booted`, `pgrep -fl "Simulator|Google Chrome"`), then after the verdict:

```bash
xcrun simctl terminate "$UDID" "$BUNDLE_ID"        # always
xcrun simctl shutdown "$UDID"                     # only if YOU booted it
xcrun simctl io "$UDID" recordVideo --stop 2>/dev/null; pkill -f "recordVideo" 2>/dev/null
```

Kill every process you started (dev servers, log tails, `xcodebuildmcp` video recordings, `sim-use` sessions), close browser tabs/windows you opened (never the captain's own Chrome), stop iPhone Mirroring/Mirroir sessions you started, and delete scratch outside `.herd/drill/`. Copy durable evidence out of `.herd/drill/` before you close. A drill that leaves booted sims, stray Chrome instances or orphan processes is a failed drill regardless of verdict.
