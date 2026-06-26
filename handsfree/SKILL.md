---
name: handsfree
description: Hands-free voice loop for driving Claude by voice. Combines the `say` skill (Gemini TTS audio out), focus-pull back to the caller's cmux prompt, and Wispr Flow dictation (voice in). When active, EVERY reply to the user is spoken aloud and the mic is auto-armed so they can answer without touching the keyboard. Use when the user says "/handsfree", "turn on hands-free", "hands-free mode", "control me by voice", "start the voice flow", "voice mode on". To turn it off: "/handsfree off", "turn off hands-free", "stop voice mode", "stop the voice flow".
---

# handsfree

A super-lightweight wrapper around two existing skills — **`say`** (Gemini TTS,
Czech voice Charon) and **`wispr`** (Wispr Flow dictation) — plus a cmux
focus-pull, so the user can run a whole Claude session by voice while away from
the keyboard (e.g. driving). One script, `say-listen.sh`, does a full turn.

## What one turn does

`say-listen.sh "<short czech text>"`:

1. **Speaks** the text via `~/.claude/skills/say/gemini-say.ts` (blocks until the
   audio finishes playing — `afplay` is synchronous). The `say` helper also ducks
   background audio (Spotify / Music / browser / YouTube) for the duration, like
   Wispr does for dictation.
2. **Pulls focus** back to the **caller's** cmux prompt: brings cmux to the
   macOS foreground (`open -b com.cmuxterm.app`), focuses the caller's window
   (`focus-window`, by UUID) and pane (`focus-pane`). Target is resolved live
   from `cmux identify`, so dictation lands in the prompt that invoked it even if
   the user wandered off to another app while Claude was thinking.
3. **Arms Wispr** hands-free listening (`stop-hands-free` then
   `start-hands-free`) so the user can immediately reply by voice.

## When ACTIVE (the loop)

While hands-free mode is on, deliver **every** reply to the user by running:

```bash
zsh ~/.claude/skills/handsfree/say-listen.sh "<spoken reply>"
```

Spoken-reply rules (same as the `say` skill):
- Short: 1–4 sentences. Summarize; don't read everything.
- Plain Czech, **no markdown, no code, no URLs, no symbols** — it's read aloud.
- If a real decision is needed, end with a clear spoken question; the mic is
  already armed for the answer.
- The on-screen text reply can stay fuller (the user can read it later); the
  spoken part is the summary.

## Activating / deactivating

- **On:** invoked via `/handsfree` (or the trigger phrases). Acknowledge by
  speaking through the script, then keep using it for subsequent replies.
- **Off:** `/handsfree off`, "vypni hands-free", etc. → stop calling the script,
  disarm the mic once with `open "wispr-flow://stop-hands-free"`, and confirm in
  text (no need to speak the confirmation).

## Gotchas

- **No auto-submit.** Wispr only *types* the dictation into the focused prompt;
  the user still presses Enter to send. Fully hands-free send (on silence) is out
  of scope here — that's the `cmux-voice-remote` mobile-app idea.
- **Focus is intentional.** The script yanks cmux to the foreground on purpose so
  dictation can't leak into another app. That is the desired behavior in this
  mode; turn the mode off if it gets in the way.
- **Caller-relative.** The focus target is whoever invoked the script. Run it
  from the session you want the user talking back into (normally the orchestrator
  session).
- **Requirements:** Wispr Flow running (Microphone permission), `say` skill +
  Vertex creds, cmux CLI, `bun`, `python3`. Optional: `nowplaying-cli` (Homebrew)
  for background-audio ducking. Verified against Wispr Flow 1.5.980.
