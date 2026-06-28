---
name: handsfree
description: Hands-free voice loop for driving Claude by voice. Combines the say skill (Gemini TTS audio out), a focus-pull back to the caller's cmux prompt, Wispr Flow dictation (voice in), and an appendix-stop listener so the user ENDS and SUBMITS each turn by saying the word appendix. When active, every reply is spoken aloud and the mic is auto-armed, so the user answers and sends without touching the keyboard. Use when the user asks for hands-free mode, to control Claude by voice, to start the voice flow, or voice mode on. Turn it off with hands-free off, stop voice mode, or stop the voice flow.
---

# handsfree

A super-lightweight wrapper around two existing skills — **`say`** (Gemini TTS,
voice Charon) and **`wispr`** (Wispr Flow dictation) — plus a cmux focus-pull and a
small **appendix-stop** keyword listener, so the user can run a whole Claude session
by voice while away from the keyboard (e.g. driving). One script, `say-listen.sh`,
does a full turn; `appendix-stop.sh` closes it by voice.

## What one turn does

`say-listen.sh "<short reply text>"`:

1. **Speaks** the text via `~/.claude/skills/say/gemini-say.ts` (blocks until the
   audio finishes — `afplay` is synchronous). Playback is sped up slightly with
   ffmpeg `atempo` (pitch preserved; default ~1.07, tune via `GEMINI_SAY_RATE`). The
   `say` helper also ducks background audio (Spotify / Music / browser) for that span.
2. **Arms Wispr** hands-free listening (`stop-hands-free` then `start-hands-free`,
   both via `open -g`) so the user can immediately reply by voice.
3. **Pulls focus** back to the **caller's** cmux prompt (window by UUID, pane by ref,
   resolved live from `cmux identify`) so dictation lands in the prompt that invoked
   it even if the user wandered off to another app while Claude was thinking.
4. **Ensures the appendix-stop listener is running** (idempotent) so the user can end
   and submit the turn by voice. Opt out with `HANDSFREE_NO_APPENDIX=1`.

## Ending a turn by voice — the appendix-stop listener

Wispr's only built-in stop is the **Fn** key, impossible while driving. The
`appendix-stop.sh` listener closes that gap: **the user just speaks, then says
"appendix"** — the listener stops Wispr, the dictation pastes into the prompt, and it
presses Return to submit. No keyboard, no "press enter".

```bash
~/.claude/skills/handsfree/appendix-stop.sh start    # arm (say-listen does this for you)
~/.claude/skills/handsfree/appendix-stop.sh status   # running? recent triggers
~/.claude/skills/handsfree/appendix-stop.sh stop     # disarm
~/.claude/skills/handsfree/appendix-stop.sh selftest # speaker->mic check (dry-run, safe)
```

### How it actually works (and why)

The listener is its own local speech-to-text on the mic. Several hard-won design
choices are baked in, each fixing a real failure:

- **ffmpeg capture, not SDL.** `whisper-stream`'s built-in SDL mic capture opens the
  device but on some macOS builds delivers **pure silence** (verified: SDL dead while
  `ffmpeg` read the same mic at −23 dB). So the engine is **ffmpeg (avfoundation) →
  rolling WAV segments → `whisper-cli`**. `APPENDIX_ENGINE=auto` uses ffmpeg when the
  binary is present, else falls back to SDL.
- **Built-in mic, explicitly.** A connected iPhone Continuity mic can hijack the
  "default" input and read as silence. The ffmpeg engine picks the first avfoundation
  audio device that is **not** an iPhone/iPad/Continuity mic.
- **Multilingual `small` model + `-l cs`.** A Czech speaker saying the English word
  "appendix" transcribes as garbage under the English `tiny.en` ("upend it", "(upbeat
  music)"). The multilingual **`small`** model (~480 MB, auto-downloaded) with Czech
  reads it cleanly as "Appendix" at ~1.1 s per window. `-sns` (suppress non-speech
  tokens) stops "(zvuk)"/"(hudba)" hallucinations from road noise.
- **Pronunciation-tolerant match.** `APPENDIX_REGEX` matches "appendix" plus the
  common mis-hears (`a pendix`, `habendix`, `pandix`, `opendiks`, `a bendej`…) without
  firing on normal Czech speech. Overlapping windows catch the word even when it
  straddles a 2 s segment boundary.
- **Repeated Return, not one.** Wispr pastes the dictated text an unpredictable moment
  after `stop-hands-free`, so a single timed Return races the paste and hits an empty
  prompt. The listener presses Return several times across a ~4 s window (tune with
  `APPENDIX_ENTER_TRIES` / `APPENDIX_ENTER_EVERY`); the press after the paste submits,
  the rest are no-ops. `open -g` for the stop deeplink keeps focus on the prompt
  (foregrounding Wispr makes its paste path drop the text).

**Why not read Wispr's own transcript?** Tempting (Wispr's ASR is excellent), but
Wispr writes the text — to the prompt and to its `flow.sqlite` `History` table — only
**when the dictation ends**, not live. So there is no on-the-fly signal to trigger
the stop; an independent local STT on the mic is required.

**One-shot.** The listener self-stops after a real fire; `say-listen.sh` re-arms both
Wispr and the listener next turn. `APPENDIX_WATCH_WISPR=1` additionally stops it when
Wispr leaves hands-free (Escape/Fn), but it is **default off**: in hands-free Wispr's
`activeDictationSession` also goes null between utterances, so the watchdog would kill
the listener during a natural pause.

**Trigger word leaks into the text.** Wispr also hears "appendix", so it lands in the
dictated text. Strip it with a Wispr **Snippet** mapping `appendix` → a single space
(Settings → Dictionary / Snippets; they live in Wispr's sqlite `Dictionary` table).
`add-wispr-snippet.sh` can insert it as a guarded fallback (refuses while Wispr runs,
backs up the DB first).

First `start` auto-downloads the model (~480 MB) to `~/.cache/whisper-cpp/`. Tunables
(env): `APPENDIX_ENGINE` (auto/ffmpeg/sdl), `APPENDIX_MODEL`, `APPENDIX_LANG` (cs),
`APPENDIX_REGEX`, `APPENDIX_CAPTURE` (mic index, default 0), `APPENDIX_SEG_SEC` (2),
`APPENDIX_COOLDOWN` (6), `APPENDIX_PRESS_ENTER` (1), `APPENDIX_ENTER_TRIES` (6),
`APPENDIX_ENTER_EVERY` (0.7), `APPENDIX_WATCH_WISPR` (0), `APPENDIX_DEBUG` (logs every
transcription to `heard.log` for tuning), `APPENDIX_DRY_RUN`.

### Want true "Hey Siri" robustness?

For bullet-proof, low-latency keyword spotting in noisy environments, a dedicated
wake-word engine (Picovoice Porcupine / openWakeWord) beats general STT — but it needs
a one-time setup (a custom "appendix" keyword from the vendor console + an access key)
that can't be done hands-free. Offer it as an upgrade for when the user is at a desk.

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
- **Never say "appendix" in a spoken reply** — the mic hears your own TTS and would
  fire the listener. Refer to it as "the trigger word" / "the ending word".
- If a real decision is needed, end with a clear spoken question; the mic is already
  armed for the answer.
- The on-screen text reply can stay fuller (the user can read it later); the spoken
  part is the summary.

## Activating / deactivating

- **On:** invoked via `/handsfree` (or the trigger phrases). Acknowledge by speaking
  through the script, then keep using it for subsequent replies. The appendix-stop
  listener auto-starts on the first turn.
- **Off:** `/handsfree off`, "vypni hands-free", etc. → stop calling the script,
  disarm the mic once with `open "wispr-flow://stop-hands-free"`, stop the listener
  with `appendix-stop.sh stop`, and confirm in text (no need to speak it).

## Gotchas

- **Focus is intentional.** The script yanks cmux to the foreground on purpose so
  dictation can't leak into another app. Turn the mode off if it gets in the way.
- **Caller-relative.** The focus target is whoever invoked the script. Run it from the
  session you want the user talking back into (normally the orchestrator session).
- **Requirements:** Wispr Flow running (Microphone permission), `say` skill + Vertex
  creds, cmux CLI, `bun`, `python3`, **`ffmpeg`** (capture + atempo), and
  **`whisper-cpp`** (`whisper-cli`); plus Accessibility/Automation permission for the
  terminal so the auto-Return works. `whisper-cpp` is auto-installed via Homebrew on
  first use; the model auto-downloads. Verified against Wispr Flow 1.5.980.
