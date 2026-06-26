---
name: handsfree
description: Hands-free voice loop for driving Claude by voice. Combines the say skill (Gemini TTS audio out), a focus-pull back to the caller's cmux prompt, Wispr Flow dictation (voice in), and an appendix-stop listener so the user ENDS and SUBMITS each turn by saying the word appendix. When active, every reply is spoken aloud and the mic is auto-armed, so the user answers and sends without touching the keyboard. Use when the user asks for hands-free mode, to control Claude by voice, to start the voice flow, or voice mode on. Turn it off with hands-free off, stop voice mode, or stop the voice flow.
---

# handsfree

A super-lightweight wrapper around two existing skills — **`say`** (Gemini TTS,
voice Charon) and **`wispr`** (Wispr Flow dictation) — plus a cmux
focus-pull and a small **appendix-stop** keyword listener, so the user can run a
whole Claude session by voice while away from the keyboard (e.g. driving). One
script, `say-listen.sh`, does a full turn; `appendix-stop.sh` closes it by voice.

## What one turn does

`say-listen.sh "<short reply text>"`:

1. **Speaks** the text via `~/.claude/skills/say/gemini-say.ts` (blocks until the
   audio finishes playing — `afplay` is synchronous). The `say` helper also ducks
   background audio (Spotify / Music / browser / YouTube) for the duration, like
   Wispr does for dictation.
2. **Arms Wispr** hands-free listening (`stop-hands-free` then `start-hands-free`,
   both via `open -g`) so the user can immediately reply by voice.
3. **Pulls focus** back to the **caller's** cmux prompt: activates cmux, focuses
   the caller's window (by UUID) and pane. Target is resolved live from `cmux
   identify`, so dictation lands in the prompt that invoked it even if the user
   wandered off to another app while Claude was thinking.
4. **Ensures the appendix-stop listener is running** (idempotent) so the user can
   end and submit the turn by voice. Opt out with `HANDSFREE_NO_APPENDIX=1`.

## Ending a turn by voice — the appendix-stop listener

Wispr's only built-in stop is the **Fn** key, impossible while driving. The
`appendix-stop.sh` listener (a tiny whisper.cpp `whisper-stream` tiny.en spotter
on the mic) closes that gap. **The user just speaks, then says "appendix"** — the
listener stops Wispr, the dictation pastes into the prompt, and it presses Return
to submit. No keyboard, no "press enter".

```bash
~/.claude/skills/handsfree/appendix-stop.sh start    # arm (say-listen does this for you)
~/.claude/skills/handsfree/appendix-stop.sh status   # running? recent triggers
~/.claude/skills/handsfree/appendix-stop.sh stop     # disarm
```

Two details were essential (both live-tested) and are baked into the script:

- **`open -g`** for the stop deeplink: foregrounding Wispr makes its paste path
  see a non-editable target and silently **drop** the text, so `-g` keeps focus on
  the prompt and the paste lands.
- **auto-Return**: Wispr's own "press enter" command stops matching once "appendix"
  trails it, so the listener simulates Enter after a short settle
  (`APPENDIX_ENTER_DELAY`, default 1.3 s; toggle `APPENDIX_PRESS_ENTER`). That is
  what makes one word stop + paste + submit.

**Active only while Wispr is.** The listener is one-shot: it stops itself the moment
Wispr leaves hands-free — whether you end with "appendix", press **Escape**, or tap
**Fn**. It watches `prefs.activeDictationSession` in Wispr's `config.json` (an object
while dictating, `null` when stopped) and exits when it goes null; `say-listen.sh`
re-arms both Wispr and the listener on the next turn. Disable with
`APPENDIX_WATCH_WISPR=0`.

**Trigger word leaks into the text.** Wispr also hears "appendix", so it lands in
the dictated text. Strip it with a Wispr **Snippet**: map `appendix` → a single
space. Add it from the Wispr UI (Settings → Dictionary / Snippets); they live in
Wispr's sqlite `Dictionary` table. `add-wispr-snippet.sh` can insert it as a
guarded fallback (refuses while Wispr is running, backs up the DB first).

First `start` auto-downloads `ggml-tiny.en.bin` (~75 MB) to `~/.cache/whisper-cpp/`.
Tunables (env): `APPENDIX_REGEX`, `APPENDIX_COOLDOWN`, `APPENDIX_PRESS_ENTER`,
`APPENDIX_ENTER_DELAY`, `APPENDIX_WATCH_WISPR`, `APPENDIX_DRY_RUN`, `APPENDIX_MODEL`,
and the whisper `APPENDIX_STEP_MS` / `APPENDIX_VAD_THOLD` / `APPENDIX_LENGTH_MS` /
`APPENDIX_THREADS`.

## When ACTIVE (the loop)

While hands-free mode is on, deliver **every** reply to the user by running:

```bash
zsh ~/.claude/skills/handsfree/say-listen.sh "<spoken reply>"
```

Spoken-reply rules (same as the `say` skill):
- Short: 1–4 sentences. Summarize; don't read everything.
- Write the reply **in whatever language the user is using in this session** (the
  `say` helper auto-detects the language from the text — do not hardcode one).
- Plain text, **no markdown, no code, no URLs, no symbols** — it's read aloud.
- If a real decision is needed, end with a clear spoken question; the mic is
  already armed for the answer.
- The on-screen text reply can stay fuller (the user can read it later); the
  spoken part is the summary.

## Activating / deactivating

- **On:** invoked via `/handsfree` (or the trigger phrases). Acknowledge by
  speaking through the script, then keep using it for subsequent replies. The
  appendix-stop listener auto-starts on the first turn.
- **Off:** `/handsfree off`, "vypni hands-free", etc. → stop calling the script,
  disarm the mic once with `open "wispr-flow://stop-hands-free"`, stop the listener
  with `appendix-stop.sh stop`, and confirm in text (no need to speak it).

## Gotchas

- **Focus is intentional.** The script yanks cmux to the foreground on purpose so
  dictation can't leak into another app. That is the desired behavior in this
  mode; turn the mode off if it gets in the way.
- **Caller-relative.** The focus target is whoever invoked the script. Run it
  from the session you want the user talking back into (normally the orchestrator
  session).
- **Don't say "appendix" in a spoken reply** — the listener would fire on your own
  TTS. Refer to it as "the trigger word" when speaking.
- **Requirements:** Wispr Flow running (Microphone permission), `say` skill +
  Vertex creds, cmux CLI, `bun`, `python3`; `whisper-cpp` and
  Accessibility/Automation permission for the terminal (so the auto-Return works)
  for the appendix-stop feature. `whisper-cpp` is **auto-installed** via Homebrew
  on first use (`ensure_whisper`); if Homebrew is absent it logs `brew install
  whisper-cpp` and bails. Optional: `nowplaying-cli` for background-audio ducking.
  Verified against Wispr Flow 1.5.980.
