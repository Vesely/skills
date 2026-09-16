---
name: grokreview
description: >
  Trigger a GrokReview pass on the current GitHub PR by posting a tag comment
  (@GrokVesely / /grokreview). Use when the user wants Grok Bot / GrokReview to
  review the PR (Claude Code or Codex), not Greptile.
license: MIT
compatibility: Requires git and gh (GitHub CLI) authenticated to an account that can comment on the PR. Repo must have a GrokReview listener (e.g. ctenifaktur/ctenifaktur, Vesely/skills).
metadata:
  author: Vesely
  version: "1.0"
allowed-tools: Bash(gh:*) Bash(git:*)
---

# GrokReview

Lightweight trigger: post a PR comment so GrokReview runs. Does **not** fix comments or loop (unlike greploop).

## Inputs

- **PR number** (optional): e.g. `/grokreview 1040`. If omitted, detect PR for the current branch.
- **Wait** (optional): `/grokreview --wait` waits up to ~10 minutes for a new review from `grokvesely`, then summarizes it.

## Instructions

### 1. Identify the PR

```bash
if [ -n "$PR_NUMBER" ]; then
  gh pr view "$PR_NUMBER" --json number,url,headRefName,headRefOid
else
  gh pr view --json number,url,headRefName,headRefOid
fi
```

If none exists, stop and say the branch has no open PR.

### 2. Trigger GrokReview

Prefer `@GrokVesely` (real GitHub user; autocomplete + notifications). Aliases `@GrokReview` and `/grokreview` also work.

```bash
gh pr comment "$PR_NUMBER" --body "@GrokVesely please review"
```

Do **not** spam: if you already posted `@GrokVesely` / `/grokreview` in the last few minutes on this head SHA, skip and report the existing comment URL.

### 3. Optional wait (`--wait`)

Only if the user asked to wait:

```bash
HEAD_SHA=$(gh pr view "$PR_NUMBER" --json headRefOid -q .headRefOid)
BEFORE=$(date -u +%Y-%m-%dT%H:%M:%SZ)
# poll reviews by grokvesely newer than BEFORE / matching HEAD
```

Poll every 15s, max ~40 attempts (~10 min):

```bash
gh api "repos/{owner}/{repo}/pulls/$PR_NUMBER/reviews" \
  --jq '.[] | select(.user.login=="grokvesely") | {id, state, submitted_at, html_url: ("https://github.com/" + .html_url)}'
```

Also check recent issue comments from `grokvesely` if no formal review yet.

On timeout: report the trigger comment URL and that the review is still pending.

### 4. Report

```
GrokReview triggered.
  PR:       #<number> <url>
  Trigger:  @GrokVesely
  Comment:  <comment url>
  Review:   <review url or pending>
```

## Notes

- Slash in the Claude/Codex **chat** alone does nothing — the skill must post a **GitHub PR comment**.
- GrokReview listens per-repo; if the listener is missing, the comment will sit unused — tell the user.
- Do not use this skill to call xAI APIs or post as anyone other than the authenticated `gh` user for the trigger comment; the review itself is posted by account `grokvesely`.
