#!/usr/bin/env bash
# Builds a Python package where a module already contains a PRE-EXISTING committed
# "legacy" function in an off-style (camelCase, 2-space, single-char vars, no hints)
# sitting right next to clean code. The uncommitted change appends a new off-style
# function. The correct move: align ONLY the new function to the clean house style
# and leave the committed legacy function untouched (it is outside the diff).
set -euo pipefail
TARGET="${1:?usage: setup.sh <target-dir>}"
REPO="$TARGET/repo"
rm -rf "$REPO"
mkdir -p "$REPO/analytics"
cd "$REPO"
git -c init.defaultBranch=main init -q
git config user.email "test@example.com"
git config user.name "Test"
git config commit.gpgsign false

cat > pyproject.toml <<'EOF'
[project]
name = "analytics"
version = "1.0.0"

[tool.black]
line-length = 88

[tool.ruff]
line-length = 88

[tool.ruff.lint]
select = ["E", "F", "I", "N"]
EOF

cat > analytics/__init__.py <<'EOF'
EOF

# This module mixes a pre-existing legacy function with clean code.
cat > analytics/aggregate.py <<'EOF'
"""Aggregation helpers."""


def legacyMean(values):
  total = 0
  for v in values:
    total = total + v
  return total / len(values)


def mean(values: list) -> float:
    """Return the arithmetic mean of values."""
    return sum(values) / len(values)
EOF

cat > analytics/summary.py <<'EOF'
"""Summary helpers."""


def describe(values: list) -> str:
    """Return a short textual summary of a series of values."""
    count = len(values)
    return f"{count} values, mean {sum(values) / count}"
EOF

git add -A
git commit -qm "baseline analytics package"

# --- off-style uncommitted addition appended to aggregate.py ---
cat >> analytics/aggregate.py <<'EOF'


def calcVariance(values):
  m = sum(values) / len(values)
  return sum((x - m) ** 2 for x in values) / len(values)
EOF

echo "Repo ready at: $REPO"
