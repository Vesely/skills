#!/usr/bin/env bash
# Builds a JS lib repo with a consistent baseline (committed) and off-style
# uncommitted changes: one new untracked file + one off-style edit to a tracked file.
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

cat > .prettierrc <<'EOF'
{
  "singleQuote": true,
  "semi": true,
  "trailingComma": "all",
  "printWidth": 100
}
EOF

cat > .editorconfig <<'EOF'
root = true

[*]
indent_style = space
indent_size = 2
charset = utf-8
insert_final_newline = true
EOF

cat > package.json <<'EOF'
{
  "name": "shop-lib",
  "version": "1.0.0",
  "type": "module",
  "scripts": {
    "format": "prettier --write .",
    "lint": "eslint ."
  }
}
EOF

cat > src/users.js <<'EOF'
const DEFAULT_ROLE = 'member';

export const normalizeUser = (user) => {
  return {
    id: user.id,
    name: user.name.trim(),
    role: user.role || DEFAULT_ROLE,
  };
};

export const activeUsers = (users) => {
  return users.filter((user) => user.isActive);
};
EOF

cat > src/orders.js <<'EOF'
export const orderTotal = (order) => {
  return order.lineItems.reduce((sum, lineItem) => sum + lineItem.amount, 0);
};

export const paidOrders = (orders) => {
  return orders.filter((order) => order.status === 'paid');
};
EOF

cat > src/utils.js <<'EOF'
export const sum = (numbers) => {
  return numbers.reduce((total, number) => total + number, 0);
};

export const unique = (items) => {
  return [...new Set(items)];
};
EOF

cat > src/index.js <<'EOF'
export { normalizeUser, activeUsers } from './users.js';
export { orderTotal, paidOrders } from './orders.js';
export { sum, unique } from './utils.js';
EOF

git add -A
git commit -qm "baseline shop-lib"

# --- off-style uncommitted changes ---
cat > src/products.js <<'EOF'
var TAX_RATE = 0.2
var DEFAULT_CATEGORY = "general"

export function calculateTotal(products) {
    var total_price = products.map(p => p.price).reduce((a, b) => a + b, 0)
    var with_tax = total_price + total_price * TAX_RATE
    return with_tax
}

export function categoryOf(product) {
    return product.category || DEFAULT_CATEGORY
}
EOF

# off-style append to a tracked file (double quotes, no semicolon)
printf '%s\n' 'export { calculateTotal, categoryOf } from "./products.js"' >> src/index.js

echo "Repo ready at: $REPO"
