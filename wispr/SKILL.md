---
name: wispr
description: Control the Wispr Flow voice dictation app on macOS from the shell via its `wispr-flow://` URL scheme — lets an AI agent (e.g. Claude Code) turn Wispr Flow listening on and off for the user. Use when the user wants an agent to start or stop dictation programmatically, toggle hands-free listening, or switch the dictation microphone — e.g. "start dictation", "start wispr", "start listening", "turn on wispr", "stop listening", "stop dictation", "switch mic".
---

# wispr

Control [Wispr Flow](https://wisprflow.ai/) (the AI voice dictation app) from the command line on macOS via its registered `wispr-flow://` URL scheme. No keystroke simulation, no Accessibility permission, no API key — just `open`.

The main use case: let an AI coding agent (Claude Code, or any tool that can run a shell command) **turn Wispr Flow listening on and off for the user** — e.g. the user says "start dictation" and the agent fires the start deeplink so they can speak their next prompt hands-free.

Requires the Wispr Flow desktop app installed and running, with Microphone permission granted.

## Start listening (hands-free / toggle mode)

```bash
open "wispr-flow://start-hands-free"
```

Starts hands-free dictation — Flow keeps listening until stopped (unlike push-to-talk, which you hold). Dictated text is typed into **whatever window currently has keyboard focus**, so put the cursor where you want the text before triggering.

## Stop listening

```bash
open "wispr-flow://stop-hands-free"
```

## Switch microphone

```bash
open "wispr-flow://switch-mic?mic_name=<PREFIX>"
```

Switches to the first input device whose name starts with `<PREFIX>` (case-insensitive). Example:

```bash
open "wispr-flow://switch-mic?mic_name=MacBook"
```

## Behavior / gotchas

- **`start-hands-free` only starts when Flow is idle.** If dictation is already active it is silently ignored. To guarantee a clean start, send `stop-hands-free` first.
- **`stop-hands-free` only acts while in hands-free (locked) listening mode.** It will not cancel a push-to-talk session.
- **Text lands in the focused field.** Triggered from a terminal, Flow types into the terminal — switch focus to the target app first.
- **Undocumented / unofficial.** These deeplink actions are not in Wispr Flow's public docs; they were verified against app version **1.5.980** (Apple Silicon, macOS) and may change in future releases. The documented, supported activation path is the in-app hotkey (default **Fn** for push-to-talk, **Fn+Space** for hands-free), configurable under Settings → General → Shortcuts.
