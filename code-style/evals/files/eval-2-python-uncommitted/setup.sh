#!/usr/bin/env bash
# Builds a Python package with a consistent baseline (committed) and an off-style
# uncommitted new module that violates the project's Python conventions.
set -euo pipefail
TARGET="${1:?usage: setup.sh <target-dir>}"
REPO="$TARGET/repo"
rm -rf "$REPO"
mkdir -p "$REPO/store"
cd "$REPO"
git -c init.defaultBranch=main init -q
git config user.email "test@example.com"
git config user.name "Test"
git config commit.gpgsign false

cat > pyproject.toml <<'EOF'
[project]
name = "store"
version = "1.0.0"

[tool.black]
line-length = 88

[tool.ruff]
line-length = 88

[tool.ruff.lint]
select = ["E", "F", "I", "N"]
EOF

cat > store/__init__.py <<'EOF'
EOF

cat > store/users.py <<'EOF'
"""User helpers."""

DEFAULT_ROLE = "member"


def normalize_user(user: dict) -> dict:
    """Return a cleaned-up copy of a user record."""
    return {
        "id": user["id"],
        "name": user["name"].strip(),
        "role": user.get("role", DEFAULT_ROLE),
    }


def describe_user(user: dict) -> str:
    """Return a human-readable label for a user."""
    return f"{user['name']} ({user['role']})"
EOF

cat > store/orders.py <<'EOF'
"""Order helpers."""


def order_total(order: dict) -> float:
    """Sum the amounts of every line item on an order."""
    return sum(line_item["amount"] for line_item in order["line_items"])


def summarize_order(order: dict) -> str:
    """Return a one-line summary of an order."""
    total = order_total(order)
    return f"Order {order['id']}: {total}"
EOF

git add -A
git commit -qm "baseline store package"

# --- off-style uncommitted new module ---
# Violations vs the project: 2-space indent, single quotes, camelCase names,
# missing type hints, no docstrings, %/.format() instead of f-strings.
cat > store/pricing.py <<'EOF'
TAX_RATE = 0.2

def calcTotal(lineItems):
  subTotal = sum(item['amount'] for item in lineItems)
  withTax = subTotal + subTotal * TAX_RATE
  return withTax

def describePrice(order):
  total = calcTotal(order['line_items'])
  return 'Order %s costs %s' % (order['id'], total)
EOF

echo "Repo ready at: $REPO"
