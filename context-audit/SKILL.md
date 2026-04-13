---
name: context-audit
description: >
  Audit your Claude Code setup for token waste and context bloat. Use when
  the user says "audit my context", "check my settings", "why is Claude so
  slow", "token optimization", "context audit", or runs /context-audit.
  Starts by running /context to see real overhead, then audits MCP servers,
  CLAUDE.md rules, skills, settings, and file permissions. Returns a
  health score with specific fixes.
user-invocable: true
---

# Usage Audit

Bloated context costs more and produces worse output. This skill finds
the waste and tells you what to cut.

## Step 1: Get /context Data

Check the conversation history for /context output. If the user already
ran /context in this session, use that data. If not, ask:

"Run /context in this session terminal and let me know when you're done. I can't run
slash commands myself, but once I can see the breakdown I'll audit
everything it flags."

STOP HERE. Do NOT proceed to Step 2 until the user has ran /context. The context breakdown determines
what to audit and in what order. Without it, the audit is guessing.
Output the message above and wait for the user's next message.

## Step 2: Audit What's Bloated

Based on the /context output, audit each category from largest to
smallest. Run checks in parallel where possible.

### MCP Servers

Each server loads full tool definitions into context every turn
(~15,000-20,000 tokens each).

- Count configured servers from settings.json
- Flag any with CLI alternatives (Playwright, Google Workspace, GitHub
  all have CLIs that cost zero tokens when idle)
- Report total MCP overhead from /context output

### CLAUDE.md

Read all CLAUDE.md files (project root, .claude/, ~/.claude/).
Count lines. Then read every rule and test against five filters:

| Filter | Flag when... |
|--------|-------------|
| Default | Claude already does this without being told ("write clean code", "handle errors") |
| Contradiction | Conflicts with another rule in same or different file |
| Redundancy | Repeats something already covered elsewhere |
| Bandaid | Added to fix one bad output, not improve outputs generally |
| Vague | Interpreted differently every time ("be natural", "use good tone") |

If total CLAUDE.md lines > 200, check for progressive disclosure
opportunities: rules that only apply to specific tasks (API conventions,
deployment steps, testing guidelines) should move to reference files
with one-line pointers. Only recommend splitting when the file is
actually bloated -- a lean CLAUDE.md with universal context is fine
as a single file.

### Skills

Scan .claude/skills/*/SKILL.md. For each skill:
- Count lines (flag > 200, critical > 500)
- Run the same five filters on instructions
- Check for restated goals, hedging ("you may want to"), synonymous
  instructions ("be concise" + "keep it short" + "don't be verbose")

### Settings

Check settings.json for:

| Setting | Flag if | Recommended |
|---------|---------|-------------|
| autocompact_percentage_override | Missing or > 80 | 75 |
| BASH_MAX_OUTPUT_LENGTH (env) | At default (30-50K) | 150000 |

### File Permissions

Check settings.json for `permissions.deny` rules. If missing, check
whether bloat directories exist in the project:

| If this exists... | Should deny... |
|-------------------|---------------|
| package.json | node_modules, dist, build, .next, coverage |
| Cargo.toml | target |
| go.mod | vendor |
| pyproject.toml / requirements.txt | __pycache__, .venv, *.egg-info |

## Step 3: Score and Report

Score starts at 100. Deduct per issue:

| Issue | Points |
|-------|--------|
| CLAUDE.md > 200 lines | -10 |
| CLAUDE.md > 500 lines | -20 |
| Per 5 rules flagged by filters | -5 |
| Contradictions between files | -10 |
| Missing autocompact override | -10 |
| Missing bash output override | -5 |
| Skill > 200 lines | -5 each |
| Skill > 500 lines | -10 each |
| Per MCP server | -3 each |
| No deny rules + bloat dirs exist | -10 |

Floor at 0. Output this format:

```
# Usage Audit

Score: {N}/100 [{CLEAN|NEEDS WORK|BLOATED|CRITICAL}]

## Context Breakdown (from /context)
{Paste the key numbers from /context output}

## Issues Found

### [{CRITICAL|WARNING|INFO}] {Category}
{What's wrong}
Fix: {One-line actionable fix}

### Rules to Cut
{Each flagged rule: the text, which filter, one-line reason}

### Conflicts
{Contradictions between files, with paths}

## Top 3 Fixes
1. {Highest-impact fix}
2. {Second}
3. {Third}
```

Score labels: 90-100 CLEAN, 70-89 NEEDS WORK, 50-69 BLOATED, 0-49 CRITICAL.
Severity: CRITICAL > 10pts, WARNING 5-10pts, INFO < 5pts.

## Step 4: Offer to Fix

After the report:

"Want me to fix any of these? I can:
- Show you a cleaned-up CLAUDE.md with the flagged rules removed
- Add the missing settings.json configs
- Add permissions.deny rules for build artifacts
- Show which skills to compress"

Auto-apply settings.json and permissions.deny (safe, reversible).
Show diffs for CLAUDE.md and skills -- let the user confirm before
modifying instruction files.
