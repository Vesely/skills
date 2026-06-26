#!/bin/zsh
# say-listen.sh "<reply text>"  —  one hands-free turn of the voice loop.
# Pass the reply in whatever language the user is using; gemini-say.ts auto-detects.
#
#   1) Speak the text via Gemini TTS (blocks until afplay finishes). The `say`
#      helper also ducks background audio (Spotify/Music/browser) for that span.
#   2) Arm Wispr Flow hands-free listening with `open -g` (background) so arming
#      cannot steal focus — and so Wispr re-ducks audio promptly.
#   3) Pull keyboard focus back to the CALLER's prompt LAST, so cmux ends up
#      frontmost and dictation lands in the Claude prompt, not Wispr's own window
#      or whatever app the user wandered off to while Claude was thinking.
#
# Focus target is resolved dynamically from the caller context, so the wrapper
# re-focuses whichever session actually invoked it (survives ref/UUID churn).
#
# Requires: bun, the `say` skill (~/.claude/skills/say/gemini-say.ts), cmux CLI,
#           python3, and Wispr Flow running with Microphone permission.

set -e
TEXT="$1"

# 1) Speak (synchronous — returns only after playback ends).
bun run "$HOME/.claude/skills/say/gemini-say.ts" "$TEXT"

# 2) Arm Wispr hands-free FIRST. `-g` is CRITICAL: a bare `open wispr-flow://`
#    activates Wispr Flow to the foreground and steals focus from cmux, so the
#    dictation would land in Wispr's own window. `-g` fires the deeplink in the
#    background; hands-free listening is global regardless of foreground app.
open -g "wispr-flow://stop-hands-free" 2>/dev/null || true
open -g "wispr-flow://start-hands-free" 2>/dev/null || true

# 3) Resolve caller window/workspace/pane (pane/workspace by ref, window by UUID).
EYES=$(cmux identify --json --id-format both 2>/dev/null || true)
read -r WIN_ID WS_REF PANE_REF <<< "$(print -r -- "$EYES" | python3 -c '
import sys, json
try:
    c = json.load(sys.stdin)["caller"]
    print(c.get("window_id",""), c.get("workspace_ref",""), c.get("pane_ref",""))
except Exception:
    print("", "", "")
' 2>/dev/null)"

# Pull focus back LAST so cmux is the frontmost app and the terminal — i.e. the
# Claude prompt input — takes the keys. osascript `activate` wins the keyboard
# first-responder race more reliably than `open -b`.
osascript -e 'tell application id "com.cmuxterm.app" to activate' 2>/dev/null || open -b com.cmuxterm.app 2>/dev/null || true
[[ -n "$WIN_ID"   ]] && cmux focus-window --window "$WIN_ID" >/dev/null 2>&1 || true
[[ -n "$PANE_REF" ]] && cmux focus-pane --pane "$PANE_REF" ${WS_REF:+--workspace "$WS_REF"} >/dev/null 2>&1 || true
# Brief settle so the activation lands before the turn returns.
sleep 0.15

# Ensure the appendix-stop listener is running so the user can END and SUBMIT the
# turn by voice (say "appendix"). Idempotent; needs whisper.cpp. See appendix-stop.sh.
# Opt out with HANDSFREE_NO_APPENDIX=1.
[[ "${HANDSFREE_NO_APPENDIX:-0}" == "1" ]] || \
  "${0:A:h}/appendix-stop.sh" start >/dev/null 2>&1 || true

echo "FOCUS win=$WIN_ID ws=$WS_REF pane=$PANE_REF | WISPR ARMED"
