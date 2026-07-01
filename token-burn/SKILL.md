---
name: token-burn
description: >-
  Analyze recent Claude Code sessions and report where the most tokens (and estimated cost) were burned, with
  data-driven tips to cut usage and avoid rate limits. Scans ~/.claude/projects session logs over a
  window (default last 5h, configurable), ranks the heaviest sessions and projects, breaks down cache
  efficiency and model spend, and renders a minimalist report — in a cmux markdown panel when cmux is
  available, otherwise as an ASCII summary in the terminal. Use this whenever the user wants to know
  where their tokens went, why they're hitting (or nearing) usage/rate limits, what their recent Claude
  Code activity cost, which sessions or projects are the most expensive, or how to optimize token usage.
  Trigger on phrases like "token burn", "where did my tokens go", "token/usage report", "what's burning
  tokens", "session cost", "how much have I spent on Claude", "why am I hitting rate limits", "analyze my
  claude sessions", "token breakdown", "/token-burn", and "/burn".
---

# Token Burn Report

Show, at a glance, where Claude Code tokens were spent over a recent window so the user can see what's
expensive and how to avoid hitting rate limits. The heavy lifting is a deterministic script — your job is
to run it, pick the right preview surface, and surface the headline.

## Why this exists

Claude Code writes a JSONL transcript per session under `~/.claude/projects/<slug>/<session>.jsonl`. Every
assistant turn carries a `message.usage` block (`input_tokens`, `cache_read_input_tokens`,
`cache_creation_input_tokens` with a 5m/1h split, `output_tokens`) and `message.model`. The script sums
those across all sessions touched in the window, prices them per model (with cache discounts), and ranks
the burn. Reading raw transcripts by hand is hopeless at this scale (often thousands of files) — the
script is the only sane way.

## Workflow

1. **Run the script** (stdlib Python 3, no deps). From the skill directory:

   ```bash
   python3 scripts/burn_report.py --hours 5 --out /tmp/token-burn.md
   ```

   - `--out` writes a Markdown report; the ASCII version also prints to stdout (unless `--no-ascii`).
   - Prefer writing the Markdown to your session scratchpad dir instead of `/tmp` when you have one.

2. **Pick the preview surface:**
   - **cmux available** (the `cmux` binary is on `PATH`, or `CMUX_PANEL_ID` / `CMUX_SOCKET_PATH` is set):
     open the Markdown report in a live panel so the user gets the rich rendering they asked for:

     ```bash
     cmux markdown open /tmp/token-burn.md
     ```

     The ASCII summary still prints in the terminal — that's fine, it's the fallback view.
   - **No cmux**: skip the `cmux` call. The ASCII report on stdout is the deliverable. (You can drop
     `--out` entirely in that case.)

3. **Surface the headline in chat** — one or two lines, e.g. the total $/tokens, the single biggest
   session or project, and the most actionable tip. Don't re-paste the whole report; it's already shown.

## Arguments

| Flag | Default | Meaning |
|---|---|---|
| `--hours N` | `5` | Window length in hours. Accepts fractions (`--hours 0.5`). |
| `--project X` | `all` | `all`, `current` (only the cwd's project), or a substring to match project slugs (e.g. `myrepo`). |
| `--top N` | `15` | Rows in each ranking (top sessions, top projects). |
| `--out PATH` | — | Write the Markdown report here (for the cmux viewer). |
| `--json` | off | Print computed data as JSON to stdout (for piping/inspection) instead of the ASCII report. |
| `--no-ascii` | off | Suppress the ASCII report (use with `--out` when you only want the panel). |
| `--projects-dir` | `~/.claude/projects` | Where session logs live. |
| `--now ISO` | now | Override "now" (UTC ISO-8601) — for reproducible runs/tests. |

Honor the user's intent: if they say "today" use a larger `--hours`, "this project" → `--project current`,
"just the frontend repo" → `--project frontend`, "top 3" → `--top 3`.

## What the report shows

- **Total** $ and tokens, session/project counts, model split, and overall cache read/write shares.
- **Top sessions by burn** and **top projects by burn**, ranked by cost (tokens shown alongside — both
  metrics side by side).
- **Cache efficiency**: share of input-side tokens served from cache (cheap, 0.1×) vs (re)written
  (pricey, 1.25–2×) vs fresh (full price). High write share = context churn.
- **Tips**: data-driven, e.g. model down-shift opportunities, a single session dominating burn,
  cache churn, heavy subagent fan-out, and rate-limit pacing.

## Cost model & keeping prices current

Cost is **estimated** from public per-model pricing, applied per token class:

- input (uncached) = full input price; output = full output price
- cache **read** = 0.10× input; cache **write 5m** = 1.25× input; cache **write 1h** = 2× input

Prices live in the `PRICES`/`FAMILY` tables at the top of `scripts/burn_report.py` (USD per 1M tokens).
They drift over time — refresh them from Anthropic's pricing page
(<https://platform.claude.com/docs/en/about-claude/pricing>) and edit the tables. Dated model snapshots
match the longest known model id first, then fall back to their family price; truly unknown ids (and
`<synthetic>`) are counted in tokens but billed at $0 and flagged in a note. Treat the dollar figures as a
**relative, API-equivalent guide** to where burn concentrates, not an invoice — subscription (Pro/Max)
usage isn't billed per token, so the "cost" is the equivalent pay-as-you-go value, not a charge.

## Notes

- The window is by **message timestamp**, not file mtime — a long-running session counts only the turns
  that happened inside the window, so partial sessions are partially counted (correct for "last N hours").
- Subagent/sidechain turns are included (they burn real tokens); a tip calls out when they dominate.
- Runtime scales with how many session files were touched in the window; a 5h scan is typically a few
  seconds to ~15s.
- Reports include local project names, git branches, and AI-generated session titles — don't share a
  generated report unredacted if any of that is sensitive.
