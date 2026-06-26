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

### Code quality

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

### Utilities

- **catbox** — Upload files to catbox.moe for free, anonymous hosting with direct links. No account needed.

  ```
  npx skills@latest add Vesely/skills/catbox
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
