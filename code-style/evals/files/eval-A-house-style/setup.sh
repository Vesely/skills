#!/usr/bin/env bash
# Builds a JS repo with an unusual-but-consistent "house style" (StandardJS-ish):
# no semicolons, `function` declarations with a SPACE before the parens, 2-space
# indent, single quotes, descriptive params. The uncommitted new file is written
# in mainstream style (arrow-const, semicolons, 4-space, single-char params) and
# must be converted to match the house style.
set -euo pipefail
TARGET="${1:?usage: setup.sh <target-dir>}"
REPO="$TARGET/repo"
rm -rf "$REPO"
mkdir -p "$REPO/src"
cd "$REPO"
git -c init.defaultBranch=main init -q
git config user.email "test@example.com"
git config user.name "Test"
git config commit.gpgsign false

cat > .editorconfig <<'EOF'
root = true

[*]
indent_style = space
indent_size = 2
charset = utf-8
insert_final_newline = true
EOF

cat > .eslintrc.json <<'EOF'
{
  "extends": "standard"
}
EOF

cat > package.json <<'EOF'
{
  "name": "geo-kit",
  "version": "1.0.0",
  "type": "module",
  "scripts": {
    "lint": "eslint ."
  },
  "devDependencies": {
    "eslint": "8.57.0",
    "eslint-config-standard": "17.1.0"
  }
}
EOF

cat > src/math.js <<'EOF'
export function clamp (value, low, high) {
  if (value < low) return low
  if (value > high) return high
  return value
}

export function lerp (start, end, amount) {
  return start + (end - start) * amount
}
EOF

cat > src/strings.js <<'EOF'
export function capitalize (text) {
  return text.charAt(0).toUpperCase() + text.slice(1)
}

export function repeat (text, times) {
  return new Array(times).fill(text).join('')
}
EOF

git add -A
git commit -qm "baseline geo-kit (house style)"

# --- off-style (mainstream) uncommitted new file ---
cat > src/geometry.js <<'EOF'
export const distance = (a, b) => {
    const dx = b.x - a.x;
    const dy = b.y - a.y;
    return Math.sqrt(dx * dx + dy * dy);
};

export const midpoint = (a, b) => {
    return { x: (a.x + b.x) / 2, y: (a.y + b.y) / 2 };
};
EOF

echo "Repo ready at: $REPO"
