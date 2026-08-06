---
name: screencast
description: >-
  Turn an agent-browser session into a polished, professional product-demo video — fully local, free, no
  cloud upload. Records the browser to WebM while logging every action, then composites an MP4 with
  automatic zoom-to-click, a smooth animated cursor with trail, click ripples, an on-screen keystroke
  overlay (keycast), idle-time trimming, chapter markers (both burned-in lower-thirds and embedded MP4
  chapters), and a gradient background with a rounded, shadowed browser card. Use this whenever the user
  wants to record or generate a demo video, screencast, walkthrough, "how it works" clip, or animated
  screen recording of a web flow — especially one that looks like Screen Studio (auto-zoom, keystrokes,
  chapters) but produced by the agent itself. Trigger on "record a demo", "make a screencast", "generate
  a walkthrough video", "screen recording of this flow", "demo video with zooms and chapters", "record the
  signup/onboarding flow". Built on top of the
  agent-browser CLI; requires ffmpeg and Node. Not for live screen capture of the whole desktop — it
  records a browser flow the agent drives.
---

# screencast

Produce a polished product-demo video from a browser flow that the agent drives with `agent-browser`.
The agent performs the demo (clicks, typing, navigation); this skill records it and post-processes the
raw capture into a cinematic MP4 — locally, with no paid tool and no upload.

## What it renders

- **Punch-in / pull-back zoom + pan** — the camera zooms to an element only while something happens
  there, then pulls straight back to 1x so the whole app, and what the action just changed, stays
  visible between beats. Element-fit sizing (small controls get a closer zoom, wide ones barely any),
  pan clamped so the page always fills the card. Back-to-back actions keep the zoom instead of
  strobing once per click
- **Animated cursor** with a subtle trail and a click "pop" (synthesized — the raw capture has no cursor)
- **Click ripples** on every click
- **Keystroke overlay** (keycast) showing typed text and pressed keys
- **Element highlight** — spotlight (dim everything else) or a glowing ring around an element
- **Annotations** — labelled callouts with a connector pointing at an element or point
- **Idle trimming** — dead time freezes then hard-cuts, never fast-forwards
- **Chapters** — on-screen lower-thirds *and* real MP4 chapter markers
- **Framing** — gradient + accent glows, rounded corners, layered shadow, padding, intro/outro fades

## Requirements

- `agent-browser` on PATH with its browser binaries installed (`agent-browser install`, plus
  `--with-deps` on Linux). The browser is driven and recorded through it.
- `ffmpeg` + `ffprobe` on PATH
- Node 24+ — the renderer itself only needs 18+, but current `agent-browser` declares
  `engines.node >= 24`, so that is the real floor. It auto-installs `@napi-rs/canvas` (a prebuilt
  binary, no compilation) into the skill directory on first run, at the exact version `package.json`
  pins, so the renderer never moves onto an untested build behind your back. To upgrade it, change
  that version and delete `node_modules/`.

Rendering is entirely local. The *capture* is whatever `agent-browser` is configured to drive, so
"no cloud" holds for a local browser; a remote/cloud provider would host the page itself elsewhere.

## How to use it

Invoke the wrapper instead of `agent-browser` for the actions you want in the video. It is a thin
passthrough: anything it does not handle itself runs unchanged. Three caveats worth knowing —
`start`, `stop`, `render`, `chapter`, `highlight` and `note` are the wrapper's own commands (and
`highlight` shadows the upstream one of that name); only the actions listed under *Commands* below
produce timeline events; and `--private` is consumed before the call rather than forwarded.

Run it as `node <SKILL_DIR>/bin/screencast.mjs …` (or symlink that file onto your PATH as `screencast`).

```bash
# 1. Start: sets a fixed 1280x720 viewport, starts recording, drops a sync flash.
screencast start demo https://app.example.com/login

# 2. Explore normally (not logged as an action):
screencast snapshot -i

# 3. Drive the demo. Mark chapters as you go; run actions through the wrapper:
screencast chapter "Sign in"
screencast type @e3 "ada@example.com"
screencast type @e4 --private "$DEMO_PASSWORD"   # kept out of the log and the keycast
screencast press Enter

screencast chapter "Create a project"
screencast click @e12
screencast type @e15 "My first project"
screencast click @e18

# 4. Stop → renders ./demo.mp4
screencast stop
```

Output: `./<name>.mp4` in the current directory (1920×1080, 30 fps, H.264, with chapters).

### Commands

| Command | Purpose |
|---|---|
| `screencast start <name> [url]` | Set viewport, start recording, inject the sync flash |
| `screencast <agent-browser cmd…>` | Run any agent-browser command; actions are logged |
| `screencast chapter "<title>"` | Mark a chapter at the current moment |
| `screencast highlight @ref [dur]` | Spotlight (or ring) an element and zoom to it |
| `screencast note "<text>" @ref [dur]` | Point a labelled callout at an element or point |
| `screencast stop` | Stop recording and render `<name>.mp4` |
| `screencast render [name]` | Re-render from an existing take (fast iteration on styling) |

Logged actions: `click`, `dblclick`, `type`, `fill`, `press`, `keyboard`, `hover`, `check`, `uncheck`,
`select`. Everything else (`snapshot`, `get`, `wait`, `screenshot`, `open`, …) passes straight through
without adding an event.

### Secrets

Typed text is written to the event log *and* drawn into the keystroke overlay, so anything you type
lands in the shipped MP4. Two things guard against that:

- Fields that declare themselves (`<input type="password">`) are redacted automatically.
- `--private` forces redaction on `type`, `fill` and `keyboard`, for fields that do not — API keys,
  tokens, one-time codes, a password rendered as a plain text input.

Redacted actions still show a chip (`••••••••`) so the demo reads correctly; only the value is
dropped, and it is never written to `.screencast/<name>/events.jsonl` in the first place. The flag is
consumed by the wrapper and never reaches `agent-browser`. If the type of a field cannot be read, the
value is redacted anyway and a warning is logged — the wrapper does not guess when a leak is the cost
of guessing wrong.

**What it cannot do:** the recording is a video of the page, so `--private` only keeps a value out of
the event log and the keystroke overlay. It cannot un-draw what the browser itself renders. A
password field shows dots and is therefore safe; a token typed into a normal text input is on screen
in the video regardless of the flag. For those, either use a field the browser masks, or do not type
the real value on camera.

To type a literal `--private`, put it after `--`: `screencast type @e1 -- --private`.

Redaction covers the recording, not your machine: the expanded value is still an argument to the
wrapper and to `agent-browser`, so it is visible in the process list while the command runs. Passing
it as `"$DEMO_PASSWORD"` keeps the secret itself out of shell history (the history holds the variable
name), which is why the examples above do that — prefer an environment variable or a credential store
over pasting the literal.

### Highlights & annotations

Both hold the element on screen for their duration automatically (they issue a matching `wait`), so the
recording actually contains the moment you are pointing at.

```bash
# Spotlight: dim everything except the element, glowing outline, zoom in (default 2.5s)
screencast highlight @e9
screencast highlight @e9 3 --mode ring   # just a glowing outline, no dimming
screencast highlight @e9 --no-zoom        # keep the current framing

# Note: a labelled callout with a connector pointing at the element (default 3s)
screencast note "Pick your plan here" @e12
screencast note "This updates live" --at 640,360 4   # anchor at a viewport point
screencast note "Read this first" @e5 --side top --zoom
```

`--mode spotlight|ring`, `--no-zoom`, `--side auto|top|bottom|left|right`, `--zoom` (needs an element
target — a point anchored with `--at` has no box to frame), `--at x,y`
(viewport CSS pixels). Highlights and notes are frame-local: anchor a fresh one after the page scrolls or
navigates rather than expecting one to track across a reflow.

## Tips for good-looking demos

- **Leave ~1 second between actions** (e.g. `screencast wait 900`) so the cursor travel and zoom have
  time to animate. Back-to-back actions look rushed.
- **Leave ~3 seconds after an action whose result matters** — that is what buys the pull-back to 1x
  where the viewer actually sees the row move, the count change, the panel appear. With the default
  timings the next action has to be at least 2.85 s later (`zoomHold` + `zoomOutTime` + `zoomInTime`
  + `zoomRestMin`) or the camera stays pushed in and the result happens off-frame.
- **One `chapter` per logical step.** The title appears as a lower-third and as an MP4 chapter.
- Long pauses are fine — idle trimming removes them. You don't have to rush.
- **Scroll the subject into view before recording** if the page opens with a tall hero or upload
  zone above it. The camera only frames what the viewport holds, so a demo of a table two viewport heights
  below the fold otherwise spends its whole runtime showing an empty dropzone.
- Auth: `record start` opens a fresh context and *may or may not* carry the existing session. Check
  it (`screencast get url`, or grep the page for a logged-in marker) right after `start`; if it
  landed logged out, sign in inside the recording with `--private` on the password field. Idle
  trimming will *not* remove the login: typing is activity, so it is kept. Plan for it to be in the
  video, or re-record with a session that is already signed in. Do not assume a login done before
  `start` survives.

## Troubleshooting

- **Clicks report `✓ Done` but nothing happens.** `agent-browser` reports the dispatch, not the
  effect, so a click on a stale ref still exits 0. Refs go stale whenever the page re-renders, which
  includes the `wait` that `highlight` and `note` issue. Re-snapshot and click again with the fresh
  ref. Verify state rather than trusting the exit code: `screencast get text ...`, or an `eval` that
  reads the property the click was supposed to change. If several clicks in a row no-op, the take is
  not recoverable — stop, discard it, and start over.
- **Overlays drift out of sync with the video.** The render logged `no flash found (wall-clock
  fallback)`: the sync flash was missed, usually because the recorder started on `about:blank`
  (navigation raced `start`), so events are aligned on wall-clock instead. It renders, but timing is
  approximate. Discard the take and restart with the page already open.
- **Two renders of the same take at once.** Not supported: they share the extracted-frame directory
  and would delete frames from under each other. Render takes one at a time.
- **Framing is wrong but the actions were fine.** Do not re-record. Framing, zoom, trimming and all
  cosmetics are render-time: edit `CONFIG` in `lib/util.mjs` and re-run `screencast render <name>`.
  `captureScale` and `viewport` are the exceptions — both shape the capture itself, so changing
  either needs a fresh recording.

## How it works (internals)

1. **Capture** — `agent-browser record start` streams the page to `raw.webm` (CDP screencast, ~10 fps, no
   cursor). The viewport is set with a `deviceScaleFactor` (`CONFIG.captureScale`, default 2), so a
   1280×720 layout is captured at 2560×1440; the compositor detects that ratio and supersamples, keeping
   text crisp after framing and zoom instead of upscaling a 720p source. Each wrapped action is
   timestamped; click/type targets are resolved to coordinates via `agent-browser get box`. A one-shot
   full-viewport colour flash is injected at start to align the event log with the video timeline.
2. **Timeline** (`lib/timeline.mjs`) — events are converted to video-time (anchored on the detected flash
   frame), then turned into zoom/pan keyframes, a cursor path, ripples, key chips, chapters, and an
   idle-trim remap between source-time and output-time. A focus point normally gets a matching rest
   keyframe back at 1x (`zoomHold` after the action, or the end of the effect, whichever is later),
   which is what produces the punch-in/pull-back rhythm — a keyframe holds until the next one, so
   focus points alone would park the camera at high zoom for the entire take. The rest is dropped
   when the next action leaves no room for it (`zoomRestMin`) or when it would land past the end of
   the recording, which is what keeps rapid sequences from strobing. Rests carry their own
   keep-intervals so the trimmer cannot cut the beat that shows the result.
3. **Composite** (`lib/render.mjs` + `lib/draw.mjs`) — frames are extracted with ffmpeg; every output
   frame is drawn in `@napi-rs/canvas` (background, zoomed/rounded/shadowed card, cursor, trail, ripple,
   keystroke chip, chapter) and streamed as raw RGBA to ffmpeg, which encodes H.264 and muxes the
   chapters. All text is drawn in canvas (the local ffmpeg has no `drawtext`).

## Tuning

All cosmetics live in `CONFIG` at the top of `lib/util.mjs`: `captureScale` (retina capture factor — drop
to 1 only if a headless browser renders black at 2×), output size and fps, gradient colours, zoom,
transition timing, cursor size/trail, ripple, chip and chapter durations, and the idle-trim thresholds.
Edit and re-run `screencast render <name>` to preview without re-recording (styling, trim and framing are
all render-time; only `captureScale` and `viewport` need a fresh recording).

The zoom knobs are the ones worth knowing:

| Key | Default | Effect |
|---|---|---|
| `zoomTargetFrac` | `0.34` | how much of the frame the focused element fills — **lower = wider, more context** |
| `zoomMax` | `1.7` | ceiling. Keep it modest; past ~1.8 a demo shows a control, not a product |
| `zoomMin` | `1.0` | `1.0` lets an already-large element get no zoom at all |
| `zoomHold` | `0.85` | seconds held in close after the action before pulling back to 1x (a `highlight`/`note` holds until its effect ends instead, if that is later) |
| `zoomRestMin` | `0.55` | minimum calm at 1x for a pull-back to be worth it; under this the camera stays in, which is what stops rapid clicks from strobing |

To make the camera calmer still, lower `zoomTargetFrac` and `zoomMax` together. To make it hold on
each action longer before pulling back, raise `zoomHold`.

Environment overrides: `SCREENCAST_FPS=60` (silkier overlay motion, ~2× render time),
`SCREENCAST_SESSION` (dedicated agent-browser session), `SCREENCAST_KEEP=1` (keep extracted source frames
for debugging), `SCREENCAST_AB_BIN` (path to the agent-browser binary).
