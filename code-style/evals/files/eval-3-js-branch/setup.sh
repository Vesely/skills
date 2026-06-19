#!/usr/bin/env bash
# Builds a JS repo where the off-style code is already COMMITTED on a feature
# branch and the working tree is clean. Forces the skill to auto-detect "no
# uncommitted changes -> compare branch vs default branch (main)".
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

cat > src/cart.js <<'EOF'
export const addItem = (cart, item) => {
  return [...cart, item];
};

export const cartCount = (cart) => {
  return cart.reduce((total, item) => total + item.quantity, 0);
};
EOF

cat > src/format.js <<'EOF'
export const formatPrice = (amount) => {
  return `$${amount.toFixed(2)}`;
};

export const formatLabel = (name) => {
  return name.trim().toLowerCase();
};
EOF

git add -A
git commit -qm "baseline cart"

# feature branch with committed off-style code, clean working tree afterwards
git checkout -q -b feature/add-widget
cat > src/widget.js <<'EOF'
var WIDGET_PREFIX = "w-"

export function buildWidget(items) {
    var ids = items.map(i => WIDGET_PREFIX + i.id)
    var visible_items = items.filter(x => x.visible)
    return { ids: ids, count: visible_items.length }
}
EOF
git add -A
git commit -qm "add widget"

echo "Repo ready at: $REPO (on branch feature/add-widget, working tree clean)"
