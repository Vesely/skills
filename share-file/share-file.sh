#!/usr/bin/env bash
# Upload a file to R2 temp storage and print its public URL.
# Portable: no account-specific values baked in. Run `share-file setup` once.
set -euo pipefail

BUCKET="${R2_BUCKET:-storage}"
CACHE_DIR="${XDG_CACHE_HOME:-$HOME/.cache}/share-file"
TTL="90d"
NAME=""
FILE=""

usage() {
  cat >&2 <<'EOF'
Usage: share-file <file> [--expire 7d|30d|90d|365d|keep] [--name <slug>]
       share-file setup [--bucket <name>]

  --expire, -e   Retention bucket. Default: 90d. "keep" never expires.
  --name,   -n   Override the filename slug in the URL.

  setup          Create the bucket, add lifecycle rules, enable public access.
                 Run once per Cloudflare account. Requires `wrangler login`.

Prints the public URL on stdout.
EOF
  exit 1
}

need_wrangler() {
  command -v wrangler >/dev/null 2>&1 || {
    echo "wrangler not found. Install: npm install -g wrangler" >&2; exit 1; }
  wrangler whoami >/dev/null 2>&1 || {
    echo "wrangler not authenticated. Run: wrangler login" >&2; exit 1; }
}

# Discover the bucket's public host instead of hardcoding it, so the skill works
# on any Cloudflare account. Cached because it costs an API round-trip.
resolve_public_base() {
  if [ -n "${R2_PUBLIC_BASE:-}" ]; then printf '%s' "$R2_PUBLIC_BASE"; return; fi

  local cache="$CACHE_DIR/$BUCKET.base"
  if [ -s "$cache" ]; then cat "$cache"; return; fi

  local out base
  out="$(wrangler r2 bucket dev-url get "$BUCKET" 2>&1 || true)"
  base="$(printf '%s' "$out" | grep -oE 'https://[a-z0-9-]+\.r2\.dev' | head -1)"

  if [ -z "$base" ]; then
    echo "Could not determine the public URL for bucket '$BUCKET'." >&2
    echo "Run 'share-file setup' first, or set R2_PUBLIC_BASE to a custom domain." >&2
    exit 1
  fi

  mkdir -p "$CACHE_DIR" && printf '%s' "$base" > "$cache"
  printf '%s' "$base"
}

do_setup() {
  need_wrangler
  echo "Creating bucket '$BUCKET'..." >&2
  wrangler r2 bucket create "$BUCKET" >/dev/null 2>&1 \
    || echo "  (bucket already exists, continuing)" >&2

  for d in 7 30 90 365; do
    echo "Adding lifecycle rule: ${d}d/ expires after $d days" >&2
    wrangler r2 bucket lifecycle add "$BUCKET" "expire-${d}d" "${d}d/" \
      --expire-days "$d" --force >/dev/null 2>&1 \
      || echo "  (rule expire-${d}d already exists)" >&2
  done
  echo "Note: the keep/ prefix intentionally has no rule - those never expire." >&2

  echo "Enabling public access..." >&2
  wrangler r2 bucket dev-url enable "$BUCKET" --force >/dev/null 2>&1 || true

  rm -f "$CACHE_DIR/$BUCKET.base"
  echo "" >&2
  echo "Done. Public base: $(resolve_public_base)" >&2
  exit 0
}

[ "${1:-}" = "setup" ] && { shift; \
  [ "${1:-}" = "--bucket" ] && BUCKET="${2:?--bucket needs a value}"; do_setup; }

while [ $# -gt 0 ]; do
  case "$1" in
    --expire|-e) TTL="${2:-}"; shift 2 ;;
    --name|-n)   NAME="${2:-}"; shift 2 ;;
    -h|--help)   usage ;;
    -*)          echo "unknown flag: $1" >&2; usage ;;
    *)           FILE="$1"; shift ;;
  esac
done

[ -n "$FILE" ] || usage
[ -f "$FILE" ] || { echo "no such file: $FILE" >&2; exit 1; }

case "$TTL" in
  7d|30d|90d|365d|keep) ;;
  *) echo "invalid --expire: $TTL (use 7d, 30d, 90d, 365d, keep)" >&2; exit 1 ;;
esac

need_wrangler
PUBLIC_BASE="$(resolve_public_base)"

BASE="$(basename "$FILE")"
if [ "${BASE%.*}" != "$BASE" ]; then
  EXT=".$(printf '%s' "${BASE##*.}" | tr '[:upper:]' '[:lower:]')"
  STEM="${BASE%.*}"
else
  EXT=""; STEM="$BASE"
fi
[ -n "$NAME" ] && STEM="$NAME"

SLUG="$(printf '%s' "$STEM" | tr '[:upper:]' '[:lower:]' | sed -E 's/[^a-z0-9]+/-/g; s/^-+|-+$//g')"
[ -n "$SLUG" ] || SLUG="file"
RAND="$(openssl rand -hex 4)"
KEY="${TTL}/$(date +%Y-%m)/${SLUG}-${RAND}${EXT}"

# Content-Type decides whether browsers render or download. Extension map wins
# over `file` sniffing, which mislabels some screencast and vector formats.
CT="$(file --mime-type -b "$FILE" 2>/dev/null || echo application/octet-stream)"
case "$EXT" in
  .gif)  CT="image/gif" ;;
  .png)  CT="image/png" ;;
  .jpg|.jpeg) CT="image/jpeg" ;;
  .webp) CT="image/webp" ;;
  .avif) CT="image/avif" ;;
  .svg)  CT="image/svg+xml" ;;
  .mp4)  CT="video/mp4" ;;
  .webm) CT="video/webm" ;;
  .mov)  CT="video/quicktime" ;;
  .pdf)  CT="application/pdf" ;;
  .txt|.log) CT="text/plain; charset=utf-8" ;;
  .json) CT="application/json" ;;
  .html) CT="text/html; charset=utf-8" ;;
  .zip)  CT="application/zip" ;;
esac

if ! OUT="$(wrangler r2 object put "${BUCKET}/${KEY}" \
      --file "$FILE" --content-type "$CT" --remote 2>&1)"; then
  echo "$OUT" >&2
  exit 1
fi

echo "${PUBLIC_BASE}/${KEY}"
