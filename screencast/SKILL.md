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

- **Element-fit auto-zoom + pan** — frames each target element (small controls get a closer zoom, wide
  ones a gentle one), pan clamped so the page always fills the card, easing back out at the end
- **Animated cursor** with a subtle trail and a click "pop" (synthesized — the raw capture has no cursor)
- **Click ripples** on every click
- **Keystroke overlay** (keycast) showing typed text and pressed keys
- **Element highlight** — spotlight (dim everything else) or a glowing ring around an element
- **Annotations** — labelled callouts with a connector pointing at an element or point
- **Idle trimming** — dead time freezes then hard-cuts, never fast-forwards
- **Chapters** — on-screen lower-thirds *and* real MP4 chapter markers
- **Framing** — gradient + accent glows, rounded corners, layered shadow, padding, intro/outro fades

## Requirements

- `agent-browser` on PATH (the browser is driven and recorded through it)
- `ffmpeg` + `ffprobe` on PATH
- Node 18+ (the renderer auto-installs `@napi-rs/canvas` — a prebuilt binary, no compilation — into the
  skill directory on first run)

## How to use it

Invoke the wrapper instead of `agent-browser` for the actions you want in the video. It is a thin
passthrough — every normal `agent-browser` subcommand works unchanged and is transparently logged.

Run it as `node <SKILL_DIR>/bin/screencast.mjs …` (or symlink that file onto your PATH as `screencast`).

```bash
# 1. Start: sets a fixed 1280x720 viewport, starts recording, drops a sync flash.
screencast start demo https://app.example.com/login

# 2. Explore normally (not logged as an action):
screencast snapshot -i

# 3. Drive the demo. Mark chapters as you go; run actions through the wrapper:
screencast chapter "Sign in"
screencast type @e3 "ada@example.com"
screencast type @e4 "hunter2"
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

`--mode spotlight|ring`, `--no-zoom`, `--side auto|top|bottom|left|right`, `--zoom`, `--at x,y`
(viewport CSS pixels). Highlights and notes are frame-local: anchor a fresh one after the page scrolls or
navigates rather than expecting one to track across a reflow.

## Tips for good-looking demos

- **Leave ~1 second between actions** (e.g. `screencast wait 900`) so the cursor travel and zoom have
  time to animate. Back-to-back actions look rushed.
- **One `chapter` per logical step.** The title appears as a lower-third and as an MP4 chapter.
- Long pauses are fine — idle trimming removes them. You don't have to rush.
- Log in *before* `start` if the flow needs auth: `record start` keeps cookies/localStorage but opens a
  fresh context, so a page needing login should already have its session cookie.

## How it works (internals)

1. **Capture** — `agent-browser record start` streams the page to `raw.webm` (CDP screencast, ~10 fps, no
   cursor). The viewport is set with a `deviceScaleFactor` (`CONFIG.captureScale`, default 2), so a
   1280×720 layout is captured at 2560×1440; the compositor detects that ratio and supersamples, keeping
   text crisp after framing and zoom instead of upscaling a 720p source. Each wrapped action is
   timestamped; click/type targets are resolved to coordinates via `agent-browser get box`. A one-shot
   full-viewport colour flash is injected at start to align the event log with the video timeline.
2. **Timeline** (`lib/timeline.mjs`) — events are converted to video-time (anchored on the detected flash
   frame), then turned into zoom/pan keyframes, a cursor path, ripples, key chips, chapters, and an
   idle-trim remap between source-time and output-time.
3. **Composite** (`lib/render.mjs` + `lib/draw.mjs`) — frames are extracted with ffmpeg; every output
   frame is drawn in `@napi-rs/canvas` (background, zoomed/rounded/shadowed card, cursor, trail, ripple,
   keystroke chip, chapter) and streamed as raw RGBA to ffmpeg, which encodes H.264 and muxes the
   chapters. All text is drawn in canvas (the local ffmpeg has no `drawtext`).

## Tuning

All cosmetics live in `CONFIG` at the top of `lib/util.mjs`: `captureScale` (retina capture factor — drop
to 1 only if a headless browser renders black at 2×), output size and fps, gradient colours, zoom factor,
transition timing, cursor size/trail, ripple, chip and chapter durations, and the idle-trim thresholds.
Edit and re-run `screencast render <name>` to preview without re-recording (styling, trim and framing are
all render-time; only `captureScale` needs a fresh recording).

Environment overrides: `SCREENCAST_FPS=60` (silkier overlay motion, ~2× render time),
`SCREENCAST_SESSION` (dedicated agent-browser session), `SCREENCAST_KEEP=1` (keep extracted source frames
for debugging), `SCREENCAST_AB_BIN` (path to the agent-browser binary).
