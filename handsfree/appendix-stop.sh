#!/bin/zsh
# appendix-stop.sh — lightweight voice trigger that STOPS Wispr Flow hands-free
# dictation when the user says the English word "appendix".
#
# Pipeline:  mic --> whisper.cpp (whisper-stream, tiny.en) --> substring matcher
#            --> open -g "wispr-flow://stop-hands-free" + Return  (debounced, once)
#
# Saying "appendix" ends the turn: it stops Wispr (so the dictation pastes) and
# presses Return to submit. The listener then STOPS ITSELF, so it is active only
# while Wispr is — say-listen.sh re-arms both Wispr and the listener next turn.
#
# Usage:
#   appendix-stop.sh start          # arm the listener (background)
#   appendix-stop.sh stop           # disarm
#   appendix-stop.sh status         # is it running? recent triggers
#   appendix-stop.sh test FILE...   # OFFLINE: transcribe wav(s), show if matcher fires
#   appendix-stop.sh selftest       # LIVE self-test: speak "appendix" -> detect (dry-run)
#   appendix-stop.sh install        # install whisper-cpp + model if missing
#   appendix-stop.sh run            # foreground listener (for debugging; Ctrl-C to quit)
#
# Env overrides:
#   APPENDIX_MODEL      path to ggml model        (default ~/.cache/whisper-cpp/ggml-tiny.en.bin)
#   APPENDIX_REGEX      ERE matched per utterance (default below)
#   APPENDIX_COOLDOWN   seconds between fires      (default 6)
#   APPENDIX_DRY_RUN    1 = log "WOULD FIRE", never open the deeplink (default 0)
#   APPENDIX_STEP_MS    whisper-stream step; 0 = VAD mode, low CPU (default 0)
#   APPENDIX_LENGTH_MS  max audio window ms        (default 6000)
#   APPENDIX_VAD_THOLD  VAD threshold 0..1         (default 0.6)
#   APPENDIX_THREADS    decode threads             (default 4)
#   APPENDIX_LANG       whisper language           (default en)
#   APPENDIX_WATCH_WISPR   1 = also stop the listener when Wispr leaves hands-free
#                          (Escape/Fn). DEFAULT 0: in hands-free mode Wispr's
#                          activeDictationSession also goes null BETWEEN utterances,
#                          so the watchdog would kill the listener during a natural
#                          speaking pause (fatal while driving). Off => the trigger
#                          word is the sole stop — the listener self-stops on fire,
#                          and `/handsfree off` stops it explicitly.
#   APPENDIX_WATCH_INTERVAL  Wispr-state poll seconds  (default 0.4)
#   APPENDIX_WISPR_CONFIG    path to Wispr's config.json (default below)

set -u
emulate -L zsh 2>/dev/null || true

SELF="${0:A}"                       # absolute path to this script (zsh)
SKILL_DIR="${SELF:h}"

# ---- config (env-overridable) ----------------------------------------------
# Multilingual SMALL model (NOT tiny.en): a Czech speaker saying "appendix" with a
# Czech accent transcribes as garbage under the English model ("upend it", "been
# dicks", "(upbeat music)"). Multilingual + LANG=cs (below) reads it reliably; small
# (244M) nails "appendix" cleanly where base mishears it ("Opendiks"/"A pandix"),
# at ~1.1 s per 4 s window on Apple Silicon. Override APPENDIX_MODEL/APPENDIX_LANG.
MODEL="${APPENDIX_MODEL:-$HOME/.cache/whisper-cpp/ggml-small.bin}"
MODEL_URL="https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-small.bin"
# Trigger set: English spelling plus the Czech transcriptions of "appendix"
# (apendix / apendyx / apendiks…). normalize() drops diacritics, so match the
# "pend…" core too. Tune via APPENDIX_REGEX once you see real transcriptions.
TRIGGER_REGEX="${APPENDIX_REGEX:-appendix|apendix|[pb][ae]nd[iy][xkc]s?|[pb][ae]nd[ae]j}"
COOLDOWN="${APPENDIX_COOLDOWN:-6}"
THREADS="${APPENDIX_THREADS:-4}"
VAD_THOLD="${APPENDIX_VAD_THOLD:-0.6}"
STEP_MS="${APPENDIX_STEP_MS:-0}"           # 0 => VAD mode (transcribe on silence; low CPU)
LENGTH_MS="${APPENDIX_LENGTH_MS:-6000}"
LANG="${APPENDIX_LANG:-cs}"
DRY_RUN="${APPENDIX_DRY_RUN:-0}"
# SDL capture device for whisper-stream. Default 0 = the FIRST device, which on a
# Mac is the built-in mic. This matters: whisper-stream's "SDL default" can resolve
# to a phantom/silent device (e.g. a connected iPhone Continuity mic at -91 dB) even
# when the macOS system default input is the built-in mic, so the listener would hear
# nothing. Pin to 0 to track the built-in mic. Set APPENDIX_CAPTURE= (empty) to fall
# back to SDL's own default, or to another index from `whisper-stream` startup output.
CAPTURE="${APPENDIX_CAPTURE-0}"

# Audio capture backend:
#   ffmpeg : continuous avfoundation capture -> rolling segments -> whisper-cli.
#            Native macOS capture path; the reliable engine.
#   sdl    : whisper-stream's built-in SDL mic capture (low idle CPU via VAD), but
#            on some macOS/whisper-cpp builds SDL opens the device yet delivers pure
#            silence (verified: SDL capture dead while ffmpeg reads the same mic at
#            -23 dB), so the listener hears nothing.
#   auto   : ffmpeg if the ffmpeg binary is present, else sdl. (default)
ENGINE="${APPENDIX_ENGINE:-auto}"
SEG_SEC="${APPENDIX_SEG_SEC:-2}"           # ffmpeg engine: rolling segment length (s)

RUN_DIR="${APPENDIX_RUN_DIR:-$HOME/.cache/wispr-appendix-stop}"
PIDFILE="$RUN_DIR/listener.pid"
LOG="$RUN_DIR/listener.log"
EVENTS="$RUN_DIR/events.log"
COOLDOWN_FILE="$RUN_DIR/last-fire.epoch"
FIFO="$RUN_DIR/stream.fifo"
WSPIDFILE="$RUN_DIR/whisper.pid"
# Wispr's live config: prefs.activeDictationSession is an object while hands-free
# is dictating and null when it stops (Escape / Fn / appendix / off) — verified.
# Polled to keep the listener alive only while Wispr is.
WISPR_CONFIG="${APPENDIX_WISPR_CONFIG:-$HOME/Library/Application Support/Wispr Flow/config.json}"
mkdir -p "$RUN_DIR"

# ---- helpers ----------------------------------------------------------------

log_line() { print -r -- "$@"; }

# Lines in the events log (0 if absent); selftest uses it to detect a fire.
event_count() { wc -l < "$EVENTS" 2>/dev/null | tr -d ' '; }

ensure_model() {
  if [[ -f "$MODEL" ]]; then return 0; fi
  log_line "appendix-stop: model not found at $MODEL — downloading ggml-tiny.en.bin (~75 MB)…"
  mkdir -p "${MODEL:h}"
  if curl -L --fail --retry 3 -o "$MODEL.part" "$MODEL_URL"; then
    mv "$MODEL.part" "$MODEL"
    log_line "appendix-stop: model downloaded -> $MODEL"
  else
    rm -f "$MODEL.part"
    log_line "appendix-stop: ERROR downloading model from $MODEL_URL" >&2
    return 1
  fi
}

# Ensure the whisper-stream binary (live listener) and whisper-cli (offline
# `test`) are present — both ship with the whisper-cpp Homebrew formula. Auto-
# installs on first use so a fresh skill install does not silently fail to listen
# (say-listen.sh starts us with output discarded, so a missing binary is unseen).
ensure_whisper() {
  if command -v whisper-stream >/dev/null 2>&1; then return 0; fi
  log_line "appendix-stop: whisper-stream not found — installing whisper-cpp…"
  if ! command -v brew >/dev/null 2>&1; then
    log_line "appendix-stop: ERROR — whisper-stream missing and Homebrew not found." >&2
    log_line "  Install Homebrew (https://brew.sh), then run: brew install whisper-cpp" >&2
    return 1
  fi
  if ! brew install whisper-cpp; then
    log_line "appendix-stop: ERROR — 'brew install whisper-cpp' failed." >&2
    return 1
  fi
  hash -r 2>/dev/null || rehash 2>/dev/null || true
  if command -v whisper-stream >/dev/null 2>&1; then
    log_line "appendix-stop: whisper-cpp installed -> $(command -v whisper-stream)"
    return 0
  fi
  log_line "appendix-stop: ERROR — whisper-cpp installed but whisper-stream is not on PATH." >&2
  return 1
}

# Listener preconditions (whisper binaries + model), ensured at each entry point.
ensure_deps() { ensure_whisper && ensure_model; }

# Is the ffmpeg binary available (the reliable capture engine)?
have_ffmpeg() { command -v ffmpeg >/dev/null 2>&1; }

# Resolve which engine to actually use for a given configured ENGINE value.
resolve_engine() {
  case "$ENGINE" in
    ffmpeg) print -r -- ffmpeg ;;
    sdl)    print -r -- sdl ;;
    *)      have_ffmpeg && print -r -- ffmpeg || print -r -- sdl ;;
  esac
}

# Pick the avfoundation AUDIO device index for the built-in mic: the first audio
# device whose name is not an iPhone/iPad Continuity mic (those read as silence
# unless actively handing off). Falls back to 0. NOTE: avfoundation indices are a
# SEPARATE numbering from SDL's — they are not interchangeable.
_ffmpeg_audio_index() {
  ffmpeg -hide_banner -f avfoundation -list_devices true -i "" 2>&1 | awk '
    /AVFoundation audio devices:/ { aud=1; next }
    aud && match($0, /\] \[[0-9]+\] /) {
      s = substr($0, RSTART, RLENGTH); gsub(/[^0-9]/, "", s)   # device index
      name = $0; sub(/.*\] \[[0-9]+\] /, "", name)             # device name
      lname = tolower(name)
      if (lname ~ /iphone|ipad|continuity/) next
      print s; exit
    }
  '
}

# Normalize a raw transcription line to lowercase, letters/digits only.
normalize() {
  # strip ANSI escapes, lowercase, turn every non-alphanumeric run into one space
  sed -E 's/\x1b\[[0-9;?]*[a-zA-Z]//g' \
    | tr '[:upper:]' '[:lower:]' \
    | tr -cs 'a-z0-9' ' '
}

matches_trigger() {  # arg: normalized text -> exit 0 if trigger present
  print -r -- "$1" | grep -Eq "$TRIGGER_REGEX"
}

fire() {  # arg: raw heard text. Debounced. Returns 0 ONLY on a real fire (so the
          # caller can self-stop the listener); 1 on debounce-skip or dry-run.
  local heard="$1" now last
  now=$(date +%s)
  last=0
  [[ -f "$COOLDOWN_FILE" ]] && last=$(cat "$COOLDOWN_FILE" 2>/dev/null || print 0)
  if (( now - last < COOLDOWN )); then return 1; fi
  print -r -- "$now" > "$COOLDOWN_FILE"
  local ts; ts=$(date '+%Y-%m-%d %H:%M:%S')
  if [[ "$DRY_RUN" == "1" ]]; then
    print -r -- "[$ts] WOULD FIRE (dry-run) stop-hands-free | heard: $heard" | tee -a "$EVENTS"
    return 1
  fi
  print -r -- "[$ts] TRIGGER -> open wispr-flow://stop-hands-free | heard: $heard" | tee -a "$EVENTS"
  # -g keeps focus on the prompt: foregrounding Wispr makes its paste path
  # see a non-editable target and DROP the dictated text (couldNotGetTextBoxInfo).
  open -g "wispr-flow://stop-hands-free" 2>/dev/null || true
  # Auto-submit: press Return so the trigger word alone ends the turn. Wispr pastes
  # the dictated text an UNPREDICTABLE moment after stop-hands-free (engine + Wispr
  # finalize latency), so a single timed Return races the paste and often hits a
  # still-empty prompt. Press it repeatedly across a ~4 s window instead: the press
  # after the (atomic) paste submits; presses on the empty prompt are no-op. Toggle
  # off with APPENDIX_PRESS_ENTER=0; tune cadence with APPENDIX_ENTER_EVERY /
  # APPENDIX_ENTER_TRIES. `&!` disowns it so it outlives the listener self-stopping.
  if [[ "${APPENDIX_PRESS_ENTER:-1}" == "1" ]]; then
    ( typeset n=0
      while (( ++n <= ${APPENDIX_ENTER_TRIES:-6} )); do
        sleep "${APPENDIX_ENTER_EVERY:-0.7}"
        osascript -e 'tell application "System Events" to key code 36' >/dev/null 2>&1 || true
      done ) &!
  fi
  return 0
}

running() { [[ -f "$PIDFILE" ]] && kill -0 "$(cat "$PIDFILE" 2>/dev/null)" 2>/dev/null; }

# True (exit 0) while Wispr Flow has an active hands-free dictation session.
# Only an explicit `null` counts as "stopped"; anything ambiguous (file missing or
# mid-write, key absent) is treated as active so the listener is never killed by a
# transient misread. Cheap: a grep, no JSON parse / python spawn per poll.
_wispr_dictating() {
  [[ -r "$WISPR_CONFIG" ]] || return 0
  local v
  v=$(grep -oE '"activeDictationSession"[[:space:]]*:[[:space:]]*[^,}[:space:]]+' "$WISPR_CONFIG" 2>/dev/null | head -1)
  [[ -z "$v" ]] && return 0
  [[ "$v" == *null* ]] && return 1
  return 0
}

# Watchdog: stop the listener (PID $1) as soon as Wispr leaves hands-free for ANY
# reason — appendix, Escape, or Fn. Self-validating: it only manages the lifetime
# after it has SEEN a session go active, so if the signal is unavailable it never
# prematurely kills (the listener then falls back to appendix/explicit stop).
wispr_watch() {
  local main_pid="$1" i armed=0 misses=0 iv="${APPENDIX_WATCH_INTERVAL:-0.4}"
  for i in {1..25}; do                        # grace (~10s) to observe a session start
    kill -0 "$main_pid" 2>/dev/null || return 0
    _wispr_dictating && { armed=1; break; }
    sleep "$iv"
  done
  (( armed )) || return 0                      # never saw it active -> don't manage it
  while kill -0 "$main_pid" 2>/dev/null; do
    if _wispr_dictating; then misses=0
    else
      misses=$((misses+1))                     # 2 consecutive misses -> Wispr stopped
      if (( misses >= 2 )); then
        print -r -- "[$(date '+%Y-%m-%d %H:%M:%S')] WISPR ENDED (Escape/Fn/off) -> stopping listener" >> "$EVENTS"
        kill -TERM "$main_pid" 2>/dev/null
        return 0
      fi
    fi
    sleep "$iv"
  done
}

# ---- core listener ----------------------------------------------------------
# ffmpeg engine: continuous avfoundation capture -> rolling WAV segments, each
# transcribed offline by whisper-cli and matched. Used when SDL capture is dead
# (whisper-stream opens the mic but delivers silence on some macOS builds).
run_listener_ffmpeg() {
  local idx; idx="$(_ffmpeg_audio_index)"; [[ -n "$idx" ]] || idx=0
  local segdir="$RUN_DIR/seg"
  rm -rf "$segdir"; mkdir -p "$segdir"
  local ff_pid=""
  cleanup() { [[ -n "$ff_pid" ]] && kill "$ff_pid" 2>/dev/null; rm -rf "$segdir"; rm -f "$WSPIDFILE" "$PIDFILE"; exit 0; }
  trap cleanup TERM INT HUP

  log_line "appendix-stop: listening (ffmpeg engine) | avfoundation audio idx=$idx model=${MODEL:t} seg=${SEG_SEC}s cooldown=${COOLDOWN}s dry_run=${DRY_RUN}"

  # -reset_timestamps so every segment is a standalone playable/decodable WAV.
  ffmpeg -hide_banner -loglevel error -nostdin -f avfoundation -i ":$idx" \
      -ar 16000 -ac 1 -f segment -segment_time "$SEG_SEC" -reset_timestamps 1 \
      "$segdir/seg_%05d.wav" 2>>"$LOG" &
  ff_pid=$!
  print -r -- "$ff_pid" > "$WSPIDFILE"

  if [[ "${APPENDIX_WATCH_WISPR:-0}" == "1" && "$DRY_RUN" != "1" ]]; then
    wispr_watch $$ &!
  fi

  # Transcribe each CLOSED segment together with the PREVIOUS one (an overlapping
  # window), so the trigger word is caught even when it straddles a segment
  # boundary — the main reason a first "appendix" was sometimes missed. The 6 s
  # cooldown dedupes the word reappearing across two consecutive windows.
  local cur prev="" txt norm i
  local winlist="$segdir/_win.txt" win="$segdir/_win.wav"
  while kill -0 "$ff_pid" 2>/dev/null; do
    # Numeric-sorted, nullglob: the last entry is the newest (still being written),
    # so process every entry before it.
    local -a segs
    segs=("$segdir"/seg_*.wav(Nn))
    if (( ${#segs} < 2 )); then sleep 0.2; continue; fi
    for (( i = 1; i <= ${#segs} - 1; i++ )); do
      cur="${segs[i]}"
      [[ -f "$cur" ]] || continue
      if [[ -n "$prev" && -f "$prev" ]]; then
        printf "file '%s'\nfile '%s'\n" "$prev" "$cur" > "$winlist"
        if ffmpeg -hide_banner -loglevel error -y -f concat -safe 0 -i "$winlist" -c copy "$win" 2>/dev/null; then
          txt=$(whisper-cli -m "$MODEL" -f "$win" -l "$LANG" -nt -np -sns -t "$THREADS" 2>/dev/null \
                  | tr -d '\n' | sed 's/^ *//;s/ *$//')
        else
          txt=""
        fi
        rm -f "$prev" "$win" "$winlist"
      else
        txt=$(whisper-cli -m "$MODEL" -f "$cur" -l "$LANG" -nt -np -sns -t "$THREADS" 2>/dev/null \
                | tr -d '\n' | sed 's/^ *//;s/ *$//')
      fi
      prev="$cur"          # keep cur for the next window's overlap
      norm=$(print -r -- "$txt" | normalize)
      [[ -z "${norm// /}" ]] && continue
      # Debug: log EVERY transcription (not only matches) so we can see what whisper
      # actually hears for a given pronunciation and tune the regex/model/language.
      [[ "${APPENDIX_DEBUG:-0}" == "1" ]] && \
        print -r -- "[$(date '+%H:%M:%S')] heard: $txt" >> "$RUN_DIR/heard.log"
      if matches_trigger "$norm"; then
        # fire returns 0 only on a real (non-debounced, non-dry) fire -> self-stop.
        if fire "$txt"; then cleanup; fi
      fi
    done
    sleep 0.15
  done
  cleanup
}

# Reads whisper-stream stdout through a FIFO so we keep an explicit child PID we
# can kill on stop. No setsid / process-group trickery needed.
run_listener() {
  ensure_deps || return 1
  # Each listener instance is one-shot (it self-stops after a real fire), so clear
  # the cross-instance cooldown on start — otherwise a quick next-turn "appendix"
  # could be debounced away by the previous instance's fire timestamp.
  rm -f "$COOLDOWN_FILE"
  # Route to the reliable engine. ffmpeg (avfoundation) when available, else SDL.
  local engine; engine="$(resolve_engine)"
  if [[ "$engine" == "ffmpeg" ]]; then
    if have_ffmpeg; then run_listener_ffmpeg; return; fi
    log_line "appendix-stop: ffmpeg engine requested but ffmpeg not found — using sdl" >&2
  fi
  rm -f "$FIFO"; mkfifo "$FIFO"
  local ws_pid=""
  cleanup() { [[ -n "$ws_pid" ]] && kill "$ws_pid" 2>/dev/null; rm -f "$FIFO" "$WSPIDFILE" "$PIDFILE"; exit 0; }
  trap cleanup TERM INT HUP

  log_line "appendix-stop: listening | model=${MODEL:t} capture=${CAPTURE:-<SDL default>} step=${STEP_MS}ms length=${LENGTH_MS}ms vad=${VAD_THOLD} cooldown=${COOLDOWN}s dry_run=${DRY_RUN}"

  # zsh does not word-split unquoted expansions, so build the optional -c flag as a
  # real two-element array (passing ${CAPTURE:+-c "$CAPTURE"} sends "-c 0" as ONE arg).
  local -a cap_flag=()
  [[ -n "$CAPTURE" ]] && cap_flag=(-c "$CAPTURE")
  whisper-stream -m "$MODEL" -t "$THREADS" --step "$STEP_MS" --length "$LENGTH_MS" \
      -vth "$VAD_THOLD" -l "$LANG" -mt 24 "${cap_flag[@]}" > "$FIFO" 2>>"$LOG" &
  ws_pid=$!
  print -r -- "$ws_pid" > "$WSPIDFILE"

  # Stop the moment Wispr leaves hands-free (Escape/Fn/off), not only on "appendix".
  # Disowned (&!) so it is independent of the read loop; it TERMs us -> trap cleanup.
  if [[ "${APPENDIX_WATCH_WISPR:-0}" == "1" && "$DRY_RUN" != "1" ]]; then
    wispr_watch $$ &!
  fi

  # Open the FIFO once for the whole loop (reopening per-iteration can drop
  # lines and stall the writer). whisper-stream (the writer) is already up.
  local raw norm
  while IFS= read -r raw; do
    norm=$(print -r -- "$raw" | normalize)
    [[ -z "${norm// /}" ]] && continue
    if matches_trigger "$norm"; then
      # A real fire just stopped Wispr; stop the listener too so it is active only
      # while Wispr is. The auto-Return was disowned (&!), so it still submits.
      # say-listen.sh re-arms Wispr and restarts this listener on the next turn.
      if fire "${raw## }"; then break; fi
    fi
  done < "$FIFO"
  cleanup
}

# ---- subcommands ------------------------------------------------------------
cmd_start() {
  if running; then log_line "appendix-stop: already running (pid $(cat "$PIDFILE"))"; return 0; fi
  ensure_deps || return 1
  : > "$LOG"
  nohup /bin/zsh "$SELF" run >>"$LOG" 2>&1 &
  local pid=$!
  print -r -- "$pid" > "$PIDFILE"
  disown 2>/dev/null || true
  sleep 0.4
  if running; then
    log_line "appendix-stop: started (pid $pid)"
    log_line "  log:    $LOG"
    log_line "  events: $EVENTS"
    [[ "$DRY_RUN" == "1" ]] && log_line "  (DRY-RUN: will log WOULD FIRE, not open the deeplink)"
  else
    log_line "appendix-stop: FAILED to start — see $LOG" >&2
    tail -n 20 "$LOG" >&2 2>/dev/null
    return 1
  fi
}

cmd_stop() {
  local pid
  if [[ -f "$PIDFILE" ]]; then
    pid=$(cat "$PIDFILE" 2>/dev/null)
    if [[ -n "$pid" ]] && kill -0 "$pid" 2>/dev/null; then
      kill -TERM "$pid" 2>/dev/null
      local i; for i in {1..8}; do kill -0 "$pid" 2>/dev/null || break; sleep 0.2; done
      kill -0 "$pid" 2>/dev/null && kill -KILL "$pid" 2>/dev/null
    fi
  fi
  # belt-and-suspenders: only the whisper-stream WE started
  if [[ -f "$WSPIDFILE" ]]; then
    local wp; wp=$(cat "$WSPIDFILE" 2>/dev/null)
    [[ -n "$wp" ]] && kill -TERM "$wp" 2>/dev/null
    rm -f "$WSPIDFILE"
  fi
  rm -f "$PIDFILE" "$FIFO"
  log_line "appendix-stop: stopped."
}

cmd_status() {
  if running; then log_line "appendix-stop: RUNNING (pid $(cat "$PIDFILE"))"; else log_line "appendix-stop: stopped"; fi
  log_line "  model:  $MODEL $( [[ -f "$MODEL" ]] && print "($(du -h "$MODEL" | cut -f1))" || print '(MISSING)')"
  log_line "  regex:  $TRIGGER_REGEX"
  log_line "  log:    $LOG"
  log_line "  events: $EVENTS"
  if [[ -f "$EVENTS" ]]; then
    log_line "  --- last triggers ---"
    tail -n 5 "$EVENTS" | sed 's/^/  /'
  fi
}

cmd_test() {
  (( $# )) || { log_line "usage: appendix-stop.sh test FILE.wav [FILE2.wav ...]"; return 2; }
  ensure_deps || return 1
  local w txt norm
  for w in "$@"; do
    if [[ ! -f "$w" ]]; then log_line "MISSING  $w"; continue; fi
    txt=$(whisper-cli -m "$MODEL" -f "$w" -l "$LANG" -nt -np -sns -t "$THREADS" 2>/dev/null | tr -d '\n' | sed 's/^ *//;s/ *$//')
    norm=$(print -r -- "$txt" | normalize)
    if matches_trigger "$norm"; then
      log_line "MATCH    $w  ::  \"$txt\""
    else
      log_line "no-match $w  ::  \"$txt\""
    fi
  done
}

cmd_selftest() {
  # LIVE acoustic self-test. Forces DRY_RUN so it NEVER opens the real deeplink
  # (so it cannot disrupt a live Wispr session), then speaks "appendix" through
  # the speakers and confirms the mic->whisper->matcher path fires.
  export APPENDIX_DRY_RUN=1
  DRY_RUN=1
  local before after
  cmd_stop >/dev/null 2>&1
  : > "$EVENTS"
  log_line "appendix-stop: SELF-TEST (dry-run, will not touch live Wispr)"
  cmd_start || return 1
  log_line "  warming up mic (2s)…"; sleep 2
  before=$(event_count)
  log_line "  speaking \"appendix\" through the speakers…"
  # Prefer the project's gemini-say helper if present; fall back to macOS say.
  if [[ -f "$HOME/.claude/skills/say/gemini-say.ts" ]] && command -v bun >/dev/null 2>&1; then
    bun run "$HOME/.claude/skills/say/gemini-say.ts" "appendix" >/dev/null 2>&1 || say appendix
  else
    say appendix
  fi
  # Give VAD + decode time to flush after the audio ends.
  local i; for i in {1..10}; do
    after=$(event_count)
    (( after > before )) && break
    sleep 0.5
  done
  cmd_stop >/dev/null 2>&1
  after=$(event_count)
  log_line "  --- whisper heard (tail of log) ---"
  grep -E '^\[' "$LOG" 2>/dev/null | tail -n 8 | sed 's/^/  /'
  if (( after > before )); then
    log_line "appendix-stop: SELF-TEST PASS — detected and reached the fire step:"
    tail -n 3 "$EVENTS" | sed 's/^/  /'
    return 0
  else
    log_line "appendix-stop: SELF-TEST: no trigger detected. Check mic permission / volume."
    return 1
  fi
}

case "${1:-}" in
  start)    cmd_start ;;
  stop)     cmd_stop ;;
  status)   cmd_status ;;
  restart)  cmd_stop; cmd_start ;;
  run)      run_listener ;;          # internal: foreground listener
  test)     shift; cmd_test "$@" ;;
  selftest) cmd_selftest ;;
  install)  ensure_deps ;;
  *) cat >&2 <<EOF
appendix-stop.sh — voice "appendix" -> stop Wispr hands-free dictation
  start | stop | restart | status | install
  test FILE.wav ...   offline matcher check
  selftest            live speaker->mic check (dry-run, safe)
EOF
    exit 2 ;;
esac
