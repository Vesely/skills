---
name: say
description: Summarize and simplify the last agent message, then speak it aloud via Gemini TTS (Vertex AI, Czech voice Charon). Falls back to sag/macOS say.
allowed-tools:
  - Bash(bun:*)
  - Bash(sag:*)
  - Bash(say:*)
when_to_use: "Use when the user wants the previous answer read aloud in a short, simplified form. Trigger phrases: '/say', 'say it', 'read that out', 'voice that', 'speak that'. Also when the user asks to hear a spoken recap of what was just said."
argument-hint: "[optional: voice name or extra instruction]"
arguments:
  - instruction
context: inline
---

# Say

Take the **last assistant message** in this conversation, compress it into a short, spoken-friendly recap, and play it aloud with the Gemini TTS helper. It auto-plays.

## Inputs

- `$instruction`: (Optional) Override, e.g. a Gemini voice name (e.g. `Kore`, `Aoede`) or a tweak like "even shorter" / "in English". If absent, use the default voice **Charon**.

## Steps

### 1. Summarize and simplify the last message

Boil the previous assistant message down to a short spoken gist. Be brief, but **never drop the parts that matter** — in priority order, keep:
1. **What changed / what was done** (high-level, simplified — no IDs, file paths, or detail).
2. **Any decision or input needed from the user** (and the options, in a few words).
3. **What's next.**

Aim for **1–2 sentences (~15–30 words)** when it's just an outcome. If there's a decision or a next step, add one more short sentence for it (≤3 sentences total). Drop markdown, code, lists, caveats, and hedging. Detect the language of the message (e.g. Czech vs English).

**Success criteria**: A terse plain-text recap (≤3 sentences, no markdown/symbols) in the original language that still conveys what changed and any pending decision or next step.

### 2. Speak it via Gemini TTS

Run the helper — it synthesizes Czech speech and auto-plays via `afplay`:

```bash
bun run ~/.claude/skills/say/gemini-say.ts "<recap, plain sentences>"
```

- Default voice is **Charon** (David's pick). To use another Gemini voice, pass it as the 2nd positional arg: `... "<recap>" Kore` (options: Kore, Puck, Charon, Aoede, Leda, Orus, Zephyr, Fenrir, …).
- Write the recap as **plain sentences** — Gemini derives pauses from punctuation. Do NOT add `[short pause]` tags (that was sag-only and gets read literally).
- The helper prints token usage + approx cost (~0.1 Kč / recap). It uses a Vertex service account (provide it via the `GEMINI_SAY_ENV` file — see `gemini-say.ts` header), region `us-central1`, model `gemini-2.5-flash-preview-tts`.
- Plays by default; `--no-play` writes the file only, `-o <path>` sets the output path.
- **Audio ducking:** during playback the helper pauses other audio (Spotify / Music / browser / YouTube) via `nowplaying-cli` and resumes only what it paused — so the voice isn't a mishmash with background media. No-op if `nowplaying-cli` (Homebrew, optional) is absent or nothing is playing.

**Fallbacks** (only if the helper errors): `sag --speed 1.1 --lang cs "<recap>"` (ElevenLabs — may be quota-exhausted) or `say -v Zuzana -r 188 "<recap>"` (macOS, low quality).

**Success criteria**: the helper prints `OK …` and audio plays. Reply with one short confirmation line; do NOT embed a `MEDIA:` reference.

## Rules

- Speak the **last assistant message**, summarized — not raw.
- Keep it brief (≤3 sentences), but never sacrifice a pending decision or next step for brevity — those always make the cut. Trim detail, not substance.
- Plain-text recap only — no markdown/symbols, they get read literally.
