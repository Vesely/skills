# screencast

Turn an [agent-browser](https://www.npmjs.com/package/agent-browser) session into a polished,
professional product-demo video — fully local, free, no cloud upload. The agent drives a browser flow;
this skill records it and post-processes the raw capture into a cinematic MP4 with a punch-in /
pull-back camera, a smooth animated cursor and trail, click ripples, an on-screen keystroke overlay,
idle-time trimming, chapter markers (on-screen lower-thirds **and** embedded MP4 chapters), and a
gradient background with a rounded, shadowed browser card.

Think of it as a Screen-Studio-style look, produced by the agent itself rather than a human editor.

The camera zooms to an element only while something is happening there, then pulls straight back to
1x so the viewer sees the whole app — and what the action just changed — between beats. Rapid
sequences keep the zoom instead of strobing once per click.

## Install

```
npx skills@latest add Vesely/skills/screencast
```

## Requires

- `agent-browser` on PATH, with its browser binaries installed:

  ```bash
  npm install -g agent-browser
  agent-browser install              # add --with-deps on Linux
  ```

- `ffmpeg` + `ffprobe` on PATH
- Node 24+ (required by current `agent-browser`; the renderer itself needs only 18+). It
  auto-installs the prebuilt `@napi-rs/canvas` on first run — no compilation.

"Fully local" assumes a local browser: rendering never leaves your machine, but the capture is
whatever `agent-browser` is pointed at, so a cloud-browser provider would put the page itself
elsewhere.

## Usage

```bash
screencast start demo https://app.example.com
screencast chapter "Sign in"
screencast type @e3 "ada@example.com"
screencast press Enter
screencast stop            # -> ./demo.mp4
```

Typed text is drawn into the keystroke overlay and stored in the event log, so anything you type ends
up in the video. Password fields are redacted automatically, and `--private` forces it for anything
else:

```bash
screencast type @e4 --private "$DEMO_PASSWORD"
```

This keeps the value out of the overlay and the log. It cannot hide what the page itself draws — a
password field renders dots and is safe, but a token typed into a plain text input is visible on
screen no matter what. See `SKILL.md` for the full picture.

Invoke as `node <skill-dir>/bin/screencast.mjs …`, or symlink that file onto your PATH as `screencast`.
See `SKILL.md` for the full command reference, tips, and tuning options.
