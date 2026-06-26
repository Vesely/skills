#!/bin/zsh
# add-wispr-snippet.sh — OPTIONAL fallback mitigation.
#
# Adds a Wispr Flow snippet so the spoken trigger word is replaced with a single
# space in the dictated text (so "appendix" never lands in your prompt). Wispr
# stores snippets in its sqlite DB (Dictionary table: phrase -> replacement,
# isSnippet=1). There is no JSON config for this; it lives in the DB.
#
# RECOMMENDED instead: add it from the Wispr UI (Settings -> Dictionary / Snippets
# -> add phrase "appendix", replacement " "). The UI also syncs it to Wispr's
# server; a manual DB insert may not sync until Wispr reconciles.
#
# This helper is a guarded fallback: it REFUSES to touch the DB while Wispr Flow
# is running (writing the live DB can corrupt it), and it backs the DB up first.
#
#   add-wispr-snippet.sh            # phrase=appendix replacement=" "
#   add-wispr-snippet.sh WORD REPL  # custom

set -u
PHRASE="${1:-appendix}"
REPL="${2:- }"                       # default: a single space
DB="$HOME/Library/Application Support/Wispr Flow/flow.sqlite"

if pgrep -x "Wispr Flow" >/dev/null 2>&1 || pgrep -f "Wispr Flow.app/Contents/MacOS/Wispr Flow" >/dev/null 2>&1; then
  print -r -- "REFUSING: Wispr Flow is running. Quit Wispr Flow completely first" >&2
  print -r -- "(or just add the snippet from the Wispr UI, which is safer and syncs)." >&2
  exit 1
fi
[[ -f "$DB" ]] || { print -r -- "DB not found: $DB" >&2; exit 1; }

BACKUP="$DB.bak.$(date +%Y%m%d-%H%M%S)"
cp "$DB" "$BACKUP" || { print -r -- "backup failed" >&2; exit 1; }
print -r -- "backup: $BACKUP"

UUID=$(uuidgen | tr 'A-Z' 'a-z')
NOW=$(date -u '+%Y-%m-%d %H:%M:%S.000 +00:00')

# UNIQUE(phrase, teamDictionaryId); upsert so re-runs just refresh the replacement.
sqlite3 "$DB" <<SQL
INSERT INTO Dictionary
  (id, phrase, replacement, teamDictionaryId, frequencyUsed, remoteFrequencyUsed,
   manualEntry, createdAt, modifiedAt, isDeleted, source, isSnippet, isStarred)
VALUES
  ('$UUID', '$PHRASE', '$REPL', '00000000-0000-0000-0000-000000000000', 0, 0,
   1, '$NOW', '$NOW', 0, 'manual', 1, 0)
ON CONFLICT(phrase, teamDictionaryId) DO UPDATE SET
   replacement='$REPL', isSnippet=1, isDeleted=0, modifiedAt='$NOW';
SQL
rc=$?
if [[ $rc -eq 0 ]]; then
  print -r -- "OK: snippet '$PHRASE' -> '$REPL' added. Restart Wispr Flow to load it."
  sqlite3 -header "file:$DB?immutable=1" \
    "SELECT phrase, replacement, isSnippet FROM Dictionary WHERE phrase='$PHRASE';" 2>/dev/null
else
  print -r -- "sqlite insert failed (rc=$rc). DB restored from backup."; cp "$BACKUP" "$DB"
  exit 1
fi
