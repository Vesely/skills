# Skills

A collection of Claude Code skills for file hosting, disposable email, supply-chain security, skill creation, code-style alignment, and more.

## Install

```
npx skills@latest add Vesely/skills/<skill-name>
```

Or via [skills.sh](https://skills.sh).

## Skills

### Workflow

- **use-skill** — Fetch and execute a remote skill on-the-fly without installing it. Supports skills.sh search, GitHub shorthand, direct URLs, and repo browsing.

  ```
  npx skills@latest add Vesely/skills/use-skill
  ```

- **skillify** — Capture a session's repeatable process into a reusable SKILL.md file. Interactive interview-based workflow to turn any process into an installable skill.

  ```
  npx skills@latest add Vesely/skills/skillify
  ```

- **cursor-agent** — Delegate a task to Cursor's headless CLI for a second opinion from a non-Claude model. Useful for code reviews, plan critiques, and cross-checking work with GPT, Gemini, or a different Claude tier.

  ```
  npx skills@latest add Vesely/skills/cursor-agent
  ```

- **tldr** — Compress the previous assistant response into a one-line TL;DR plus exactly three terse next-step labels (slash commands welcome). Triggers on `/tldr`, `/recap`, "tldr", "what should I do next".

  ```
  npx skills@latest add Vesely/skills/tldr
  ```

- **dynamic-agents** — Orchestrate complex tasks across multiple agents with cost-aware model routing: session model for judgment-heavy work, Sonnet for mechanical work, GPT-5.5+ via Codex CLI for cross-model review. Presents a checkpoint plan before spending tokens.

  ```
  npx skills@latest add Vesely/skills/dynamic-agents
  ```

- **handoff-to-worktree** — Package the current chat (or one or more specific issues/topics) into self-contained handoff files and launch each in a fresh `claude` with its own named git worktree — work continues without copy-pasting context. Each child claude inherits the caller session's permission mode (no hardcoded bypass). Requires cmux: default opens a new workspace per handoff; `--tabs` opens them as tabs in the current workspace.

  ```
  npx skills@latest add Vesely/skills/handoff-to-worktree
  ```

- **pr-handoff** — Turn a branch into a reviewable GitHub PR, with annotated screenshots as the primary deliverable. Reads the diff, drives [`agent-browser`](https://www.npmjs.com/package/agent-browser) over every affected surface, outlines the changed elements in red, stitches the shots into an ImageMagick collage, self-reviews it until the annotations actually land, and writes the title + description with per-panel captions. Optional GIF screencast for multi-step flows. Never uploads to an anonymous image host: hosting goes through `share-file` (your own R2 bucket, 90-day expiry) or your own `PR_HANDOFF_UPLOAD_CMD`, and otherwise stays local for drag-and-drop.

  ```
  npx skills@latest add Vesely/skills/pr-handoff
  ```

### Code quality

- **root-cause** — Stops you shipping a patch and calling it a fix. Forces you to state the defect mechanism in one unhedged sentence, label what you are actually shipping (fix / mitigation / workaround), and refuse to let cost, risk or scope constraints quietly redefine the problem. Catches the two classic tells: the word "can't" (the thing you claim you cannot know *is* the root cause) and constraint laundering (your validation budget silently choosing the architecture). Complements `systematic-debugging`, which gets you *to* the root cause.

  ```
  npx skills@latest add Vesely/skills/root-cause
  ```

- **code-style** — Align newly written or changed code with the surrounding project's conventions — formatting, naming, imports, comments, idioms — learned from the codebase itself. Auto-detects your diff (uncommitted, or branch vs. the default branch), runs the project's own formatters/linters first, then fixes what tooling can't, with surgical, behavior-preserving edits. Works in any language or framework.

  ```
  npx skills@latest add Vesely/skills/code-style
  ```

### Security

- **supply-chain-protection** — One-time setup to harden dependency management against supply-chain attacks. Detects your package manager (npm, pnpm, Yarn, Bun), installs Socket Firewall, configures a 48-hour minimum package release age, and writes persistent rules to CLAUDE.md.

  ```
  npx skills@latest add Vesely/skills/supply-chain-protection
  ```

### Diagnostics

- **context-audit** — Audit your Claude Code setup for token waste and context bloat. Checks MCP servers, CLAUDE.md rules, skills, settings, and file permissions. Returns a health score with specific fixes.

  ```
  npx skills@latest add Vesely/skills/context-audit
  ```

- **token-burn** — Analyze recent Claude Code sessions and report where the most tokens (and estimated cost) were burned, with data-driven tips to cut usage and avoid rate limits. Ranks the heaviest sessions and projects (worktrees grouped), breaks down cache efficiency, and renders a minimalist report in a cmux markdown panel — or a plain-text terminal fallback. Triggers on `/token-burn`, `/burn`, "where did my tokens go", "why am I hitting rate limits".

  ```
  npx skills@latest add Vesely/skills/token-burn
  ```

- **park-workspace** — Free the RAM held by idle Claude sessions in cmux without closing the workspaces, so they stay visible as your TODO list. Parks a single workspace, a whole window, or a picked set — stopping the claude session plus its dev servers and test browsers — and resumes the exact session later with full history. Ships a curses picker (enter freezes/unfreezes a row, `f` focuses the workspace), marks parked rows in the native cmux sidebar, and pre-fills the resume command at the parked prompt so coming back is one keypress. The ledger lives outside cmux, so a corrupted cmux state can't lose the session; `doctor` and `rebuild` recover from one. Never parks a session mid-turn and never touches git worktrees. Triggers on "park this workspace", "park the window", "unpark", "what's parked", or complaining that idle cmux sessions eat RAM.

  ```
  npx skills@latest add Vesely/skills/park-workspace
  ```

### Utilities

- **ssh-gui** — Drive the graphical desktop of a remote macOS machine over plain ssh: no VNC, no screen sharing, no agent on the far side. Clicks, drags, keystrokes, menu navigation, window geometry and screenshots via cliclick, screencapture and the accessibility API. Gets the Retina coordinate model right (clicks are logical points, screenshots are native pixels, so shots are downscaled before you measure), batches commands into one round trip over a multiplexed connection, and ships a preflight that names which of the three macOS permissions is missing before you waste a click. For headless Macs: a mini in a cupboard, a build machine, a second Mac on the desk.

  ```
  npx skills@latest add Vesely/skills/ssh-gui
  ```

- **windows** — Drive a Windows VM running in [UTM](https://mac.getutm.app) on macOS: start it, bridge its QEMU VNC port to noVNC, and control the guest from an `agent-browser` session. The VM can be on this Mac or on another one over SSH. Built out of eight months of finding out which parts of that stack lie to you — a half-click through noVNC can wedge *all* guest input until you send a bare `mouse up`, the VNC head serves one client so noVNC and `vncdo` cannot both have it, and which channel reaches the guest at all changes between sessions and between applications, so the skill probes instead of trusting a cached answer. Ships an atomic lock (the VM is a shared resource), a fast path that skips setup in ~0.3 s, and references for non-US guest keyboard layouts, UTM's WebDAV share and its failure modes, and building an in-guest agent. Everything machine-specific lives in a gitignored `config.json` — two fields to get started.

  ```
  npx skills@latest add Vesely/skills/windows
  ```

- **screencast** — Turn an agent-browser session into a polished product-demo video, fully local and free. Records the browser flow the agent drives, then composites an MP4 with auto zoom-to-click, an animated cursor + trail, click ripples, a keystroke overlay, idle trimming, chapters (lower-thirds + embedded MP4 chapters), and a gradient/rounded/shadowed frame. Screen-Studio-style output, produced by the agent. Requires agent-browser, ffmpeg, Node.

  ```
  npx skills@latest add Vesely/skills/screencast
  ```

- **gh-upload** — Put a screenshot, GIF or video straight into a GitHub PR or issue body from the terminal. `gh` has no command for this; this is the endpoint behind the web UI's drag-and-drop, so the asset **inherits the repo's visibility** — private repo, private asset — instead of living on a public host forever. Covers the traps: the repo id must be the numeric one (the GraphQL node id 404s), the allowlist is media-only (PDF, zip and logs are rejected), the filename's extension has to match the declared MIME type, `+` in `image/svg+xml` must be percent-encoded, and a video only gets a player when its URL sits bare on its own line.

  ```
  npx skills@latest add Vesely/skills/gh-upload
  ```

- **share-file** — Upload a screenshot, screencast, GIF, PDF or any artifact to your own Cloudflare R2 bucket and get back a public direct URL that expires on its own. Default retention 90 days, overridable per upload (`7d`, `30d`, `365d`, `keep`) — expiry is enforced by R2 lifecycle rules on TTL-named prefixes, so files clean themselves up. Sets the correct `Content-Type` so images and GIFs render inline in GitHub PRs instead of downloading. No API keys: auth is `wrangler login`, and the public host is discovered from your own bucket at runtime, so the skill works unchanged on any Cloudflare account. Run `share-file setup` once to create the bucket, lifecycle rules, and public access. Free at normal volume (R2 free tier: 10 GB stored, unlimited egress).

  ```
  npx skills@latest add Vesely/skills/share-file
  ```

- **temp-email** — Create disposable email inboxes via tempmail.lol. Rotating domains, no API key, just curl. Great for E2E tests and verification flows.

  ```
  npx skills@latest add Vesely/skills/temp-email
  ```

- **ai-gateway** — Generate text, images, and video from the CLI via the Vercel AI Gateway. One key, hundreds of models (Nano Banana, Flux, Imagen, Claude, GPT, Grok, Veo, Seedance, Kling). Wraps [`@vesely/ai-gateway-cli`](https://github.com/Vesely/ai-gateway-cli).

  ```
  npx skills@latest add Vesely/skills/ai-gateway
  ```

- **wispr** — Control the [Wispr Flow](https://wisprflow.ai/) voice dictation app on macOS from the shell via its `wispr-flow://` URL scheme. Lets an AI agent (Claude Code, etc.) turn Wispr Flow listening on/off for the user: start/stop hands-free dictation and switch the microphone with a single `open` call — no keystroke simulation, no API key.

  ```
  npx skills@latest add Vesely/skills/wispr
  ```

- **say** — Summarize the previous assistant message into a short spoken recap and play it aloud via Gemini TTS (Vertex AI, Czech voice Charon), automatically ducking background audio (Spotify / Music / browser). Falls back to macOS `say`. Provide Vertex service-account creds via the `GEMINI_SAY_ENV` file.

  ```
  npx skills@latest add Vesely/skills/say
  ```

- **handsfree** — Run a whole Claude Code session by voice (e.g. while driving). One wrapper combines `say` (Gemini TTS out) and `wispr` (dictation in) with a cmux focus-pull, plus an **appendix-stop** mic listener (whisper.cpp): every reply is spoken aloud and the mic is auto-armed, and saying the word **"appendix"** ends and submits your turn — so you answer and send without ever touching the keyboard. Requires cmux, Wispr Flow, the `say` skill, and `whisper-cpp` for the voice stop.

  ```
  npx skills@latest add Vesely/skills/handsfree
  ```
