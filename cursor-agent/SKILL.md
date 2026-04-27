---
name: cursor-agent
description: Delegate a task to Cursor's CLI agent (code review, Q&A, planning) for a second opinion from a non-Claude model
allowed-tools:
  - Bash(cursor-agent:*)
  - Bash(git diff:*)
  - Bash(git log:*)
  - Bash(git status:*)
when_to_use: "Use when the user wants to run cursor-agent (Cursor's CLI). Triggers: 'cursor review', 'ask cursor', 'use cursor', 'review with cursor', 'second opinion from cursor', 'cursor-agent', 'use cursor-agent'. Also use for verifying code/plans/texts/UI with a different model than Claude."
argument-hint: "[task for cursor-agent, e.g. 'review this branch']"
arguments:
  - task
---

# Cursor Agent

Delegate a task to Cursor's headless CLI agent (`cursor-agent`). Use this to get a second opinion from a non-Claude model on code reviews, plan critiques, text/copy review, or general Q&A.

## Inputs

- `$task`: The task to hand to cursor-agent. Usually a review or question prompt. If the user adds a model hint (e.g. "with Opus", "using GPT", "pomocí Sonnetu"), extract it and pass via `--model`.

## Goal

Run cursor-agent headless, surface its output to the user, and add a brief Claude TL;DR so the user doesn't have to re-read a wall of text.

## Steps

### 1. Parse the task

Extract from `$task` and the surrounding conversation:
- **Model hint** — look for phrasing like:
  - "Opus" / "claude" → `--model claude-opus-4-7-medium`
  - "Sonnet" → `--model claude-4.6-sonnet-medium`
  - "GPT" / "GPT-5" / "Codex" → `--model gpt-5.3-codex`
  - "Gemini" → `--model gemini-3.1-pro`
  - "Auto" → `--model auto`
  - Nothing mentioned → omit `--model` (cursor uses its default: `composer-2-fast`)
- **Mode hint**:
  - "plan" / "plan mode" / "navrhni" → `--mode plan`
  - "write" / "edit" / "implement" / "headless" → omit `--mode` (cursor can write)
  - Otherwise → `--mode ask` (read-only, default)
- **Is this a review?** If the task mentions "review", "check", "verify", "second opinion", or references a branch/PR/diff, enrich the prompt (step 2).

**Success criteria**: Flags decided, prompt ready.

### 2. Enrich the prompt (reviews only)

If the task is a code review:
- Identify the diff scope. Try in order: explicit reference in the task (PR number, branch name), current branch vs `main` (`git diff origin/main...HEAD`), or uncommitted changes (`git diff HEAD`).
- Prepend a short instruction to the prompt so cursor-agent knows what to look at:
  > "Review the branch `<name>` against main. Use `git diff origin/main...HEAD` to see the actual changes. Focus on real issues (correctness, edge cases, security); skip nitpicks. Report under ~400 words with `file:line` references."

For non-review tasks (ask/plan/text/UI), pass the task as-is.

**Success criteria**: Final prompt string ready for the CLI.

### 3. Run cursor-agent

Invoke headless via Bash:

```bash
cursor-agent -p --output-format text [--mode <mode>] [--model <model>] "<prompt>"
```

- Always use `-p` (print/headless).
- Always use `--output-format text` unless the task needs structured output.
- Workspace defaults to pwd — don't pass `--workspace` unless the user explicitly asked for a different dir.
- For runs with only non-write modes (`--mode ask` or `--mode plan`), no extra permission flags are needed. For headless write mode, do **not** silently add `--force` or `--yolo`; ask the user first.
- Pipe to `tail -n 200` if you suspect a very long response and want to cap context use. By default, take the full output.

**Success criteria**: cursor-agent returns (exit 0) with a response. If it errors (auth, model not available), surface the error to the user instead of hiding it.

### 4. Return the output

Present to the user in this order:

1. **Cursor's verbatim response** — quote it directly so the user hears the other model's voice, including file:line references.
2. **Your short TL;DR** — 3–6 bullets at most, separated by a horizontal rule. Highlight what's real vs. noise, and suggest concrete next actions. Do **not** silently filter cursor's findings; if you disagree with one, call it out explicitly.

Keep the summary tight — the goal is to save the user from re-reading, not to replace cursor's output.

**Success criteria**: User sees both cursor's raw output and a Claude-curated action list.

## Notes

- `cursor-agent --list-models` shows every available model ID. If the user asks for something exotic (e.g. "thinking tier", "max tier"), check the list first.
- `cursor-agent` reads/writes inside the current workspace like any CLI tool — it is not sandboxed by default. Treat its output the same way you'd treat a teammate's PR comment: trust but verify.
- This skill is for **one-shot** delegation. For a longer back-and-forth, the user can run `cursor-agent` interactively themselves (no `-p`).
