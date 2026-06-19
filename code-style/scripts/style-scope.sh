#!/usr/bin/env bash
# style-scope.sh — orient a code-style alignment pass.
#
# Prints three things you need before aligning code to a project's conventions:
#   1. SCOPE   — which changes to align (auto-detected: uncommitted if any, else branch-vs-default)
#   2. TOOLING — formatter/linter configs + package.json scripts that already encode the rules
#   3. DOCS    — where conventions are written down (CLAUDE.md, .editorconfig, CONTRIBUTING, ...)
#
# It only reads git/state; it never edits anything. Run it from anywhere inside the repo.
set -uo pipefail

if ! git rev-parse --show-toplevel >/dev/null 2>&1; then
  echo "ERROR: not inside a git repository. This skill scopes changes via git, so it needs one." >&2
  echo "If the user wants to align a standalone file, ask them which files are 'new' vs the baseline." >&2
  exit 1
fi
ROOT=$(git rev-parse --show-toplevel)
cd "$ROOT" || exit 1

# --- detect default branch (best effort) ---
default_branch=""
if git symbolic-ref --quiet refs/remotes/origin/HEAD >/dev/null 2>&1; then
  default_branch=$(git symbolic-ref --short refs/remotes/origin/HEAD 2>/dev/null | sed 's@^origin/@@')
fi
if [ -z "$default_branch" ]; then
  for cand in main master develop trunk; do
    if git show-ref --verify --quiet "refs/heads/$cand" || git show-ref --verify --quiet "refs/remotes/origin/$cand"; then
      default_branch="$cand"; break
    fi
  done
fi

status=$(git status --porcelain 2>/dev/null || true)
has_head=1
git rev-parse --verify HEAD >/dev/null 2>&1 || has_head=0

echo "# CODE-STYLE SCOPE  (repo: $ROOT)"
echo

if [ -n "$status" ]; then
  echo "MODE: uncommitted  — aligning your working-tree + staged changes"
  if [ "$has_head" -eq 1 ]; then
    echo "BASE: HEAD"
    echo
    echo "## Changed files  (status: A added, M modified, R renamed; ?? untracked)"
    { git diff --name-status --find-renames --diff-filter=ACMR HEAD 2>/dev/null;
      git ls-files --others --exclude-standard 2>/dev/null | sed 's/^/??	/'; } | sed '/^$/d' | sort -u
    echo
    echo "## See the actual changes"
    echo "  git diff --find-renames HEAD    # tracked edits"
    echo "  # and read each ?? untracked file listed above in full"
  else
    echo "BASE: (none — repository has no commits yet; treat every file as new)"
    echo
    echo "## Changed files"
    git ls-files --others --exclude-standard 2>/dev/null | sed 's/^/??	/' | sed '/^$/d'
    echo
    echo "## See the actual changes"
    echo "  # read each file listed above in full"
  fi
else
  base_ref=""
  if [ -n "$default_branch" ]; then
    if git show-ref --verify --quiet "refs/remotes/origin/$default_branch"; then
      base_ref="origin/$default_branch"
    else
      base_ref="$default_branch"
    fi
  fi
  echo "MODE: branch  — no uncommitted changes, so comparing this branch against the default branch"
  if [ -z "$base_ref" ]; then
    echo "BASE: (could not determine default branch automatically)"
    echo
    echo "## Changed files"
    echo "  (unknown — inspect 'git branch -a' and ask the user which branch is the baseline)"
  elif ! mb=$(git merge-base "$base_ref" HEAD 2>/dev/null); then
    echo "BASE: $base_ref  (no merge-base — shallow clone or unrelated history)"
    echo
    echo "## Changed files"
    echo "  (unknown — run 'git fetch --unshallow' or ask the user for the comparison base)"
  else
    echo "BASE: $base_ref  (merge-base ${mb})"
    echo
    echo "## Changed files  (status: A added, M modified, R renamed)"
    git diff --name-status --find-renames --diff-filter=ACMR "$mb" HEAD 2>/dev/null | sed '/^$/d'
    echo
    echo "## See the actual changes"
    echo "  git diff --find-renames ${base_ref}...HEAD"
  fi
fi

echo
echo "## Detected formatters / linters (their config = the project's hard rules)"
found_tool=0
for f in \
  .prettierrc .prettierrc.json .prettierrc.yml .prettierrc.yaml .prettierrc.js .prettierrc.cjs prettier.config.js prettier.config.cjs prettier.config.mjs \
  .eslintrc .eslintrc.json .eslintrc.js .eslintrc.cjs .eslintrc.yml .eslintrc.yaml eslint.config.js eslint.config.mjs eslint.config.cjs \
  biome.json biome.jsonc \
  .stylelintrc .stylelintrc.json .stylelintrc.js stylelint.config.js stylelint.config.cjs \
  .editorconfig \
  pyproject.toml setup.cfg tox.ini .flake8 .isort.cfg ruff.toml .ruff.toml \
  .rubocop.yml .scalafmt.conf rustfmt.toml .rustfmt.toml \
  .clang-format .swiftformat .swiftlint.yml dprint.json; do
  if [ -e "$f" ]; then echo "  - $f"; found_tool=1; fi
done
[ "$found_tool" -eq 0 ] && echo "  (none at repo root — check for a language default like gofmt / cargo fmt / mix format)"

# nested configs (monorepo subprojects) — bounded scan; the nearest one to a changed file wins.
# Prune hidden dirs (.git, .claude/worktrees, .venv, ...) and heavy/vendored trees.
nested=$(find . \( -type d \( -name '.?*' -o -name node_modules -o -name vendor -o -name dist -o -name build \) \) -prune \
  -o -maxdepth 4 -type f \( \
     -name package.json -o -name pyproject.toml -o -name biome.json -o -name 'eslint.config.*' \
  -o -name '.eslintrc*' -o -name '.prettierrc*' -o -name .editorconfig -o -name Cargo.toml -o -name go.mod \
  \) -print 2>/dev/null | sed 's#^\./##' | grep '/' | sed '/^$/d' | sort)
if [ -n "$nested" ]; then
  count=$(printf '%s\n' "$nested" | wc -l | tr -d ' ')
  echo
  echo "## Nested configs (monorepo subprojects — the NEAREST config to a changed file wins, not the root)"
  printf '%s\n' "$nested" | head -30 | sed 's/^/  - /'
  [ "$count" -gt 30 ] && echo "  ... and $((count - 30)) more"
fi

if [ -f package.json ]; then
  echo
  echo "## package.json scripts (candidates to run: format / lint --fix)"
  grep -nE '"(format|fmt|lint|lint:fix|stylelint|prettier|biome)[^"]*"[[:space:]]*:' package.json 2>/dev/null \
    | grep -vE ':[[:space:]]*"[\^~0-9]' | sed 's/^/  /' \
    || echo "  (no obvious format/lint scripts — read package.json yourself)"
fi

echo
echo "## Project style docs to read for written-down conventions"
docs_found=0
for d in CLAUDE.md AGENTS.md CONTRIBUTING.md CONTRIBUTING.rst .editorconfig docs/STYLE.md STYLE.md STYLEGUIDE.md .github/CONTRIBUTING.md; do
  [ -e "$d" ] && { echo "  - $d"; docs_found=1; }
done
[ "$docs_found" -eq 0 ] && echo "  (none found — rely on neighbor files for conventions)"

echo
echo "Next: for each changed file, read 2-4 neighbor files of the SAME kind (same dir / extension)"
echo "to learn the real conventions, then align ONLY the changed lines. Tooling rules win over guesses."
