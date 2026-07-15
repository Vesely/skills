# screencast

Turn an [agent-browser](https://www.npmjs.com/package/agent-browser) session into a polished,
professional product-demo video — fully local, free, no cloud upload. The agent drives a browser flow;
this skill records it and post-processes the raw capture into a cinematic MP4 with automatic
zoom-to-click, a smooth animated cursor and trail, click ripples, an on-screen keystroke overlay,
idle-time trimming, chapter markers (on-screen lower-thirds **and** embedded MP4 chapters), and a
gradient background with a rounded, shadowed browser card.

Think of it as a Screen-Studio-style look, produced by the agent itself rather than a human editor.

## Install

```
npx skills@latest add Vesely/skills/screencast
```

## Requires

- `agent-browser` on PATH
- `ffmpeg` + `ffprobe` on PATH
- Node 18+ (the renderer auto-installs the prebuilt `@napi-rs/canvas` on first run — no compilation)

## Usage

```bash
screencast start demo https://app.example.com
screencast chapter "Sign in"
screencast type @e3 "ada@example.com"
screencast press Enter
screencast stop            # -> ./demo.mp4
```

Invoke as `node <skill-dir>/bin/screencast.mjs …`, or symlink that file onto your PATH as `screencast`.
See `SKILL.md` for the full command reference, tips, and tuning options.
