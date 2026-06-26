---
name: medium-research
description: Two-phase research workflow for Medium articles. Phase 1 discovers candidates via RSS tag feeds plus DuckDuckGo content search; Phase 2 spawns one subagent per selected article to fetch full content through the Freedium mirror (paywall bypass) and return a structured digest. Use whenever the user wants to research a topic on Medium, surface trending or recent articles, pull full text from member-only Medium posts, or build a reading list. Triggers include "/medium-research <topic>", "research medium <topic>", "medium research", "find medium articles about X", "what's trending on medium about X". The user has paid Medium membership and treats Freedium use as acceptable for personal research. Do not invoke for non-Medium research (use /last30days for cross-platform).
allowed-tools:
  - Bash(python3:*)
  - Bash(nslookup:*)
  - Read
  - Agent
argument-hint: "<topic> [--days=N] [--top-n=N]"
---

# Medium Research

Research a topic on Medium without scraping JS-rendered pages or paying per-article. Phase 1 finds candidates from RSS tag feeds plus a content search. Phase 2 fans out one subagent per selected article to fetch the full text through the Freedium mirror, in parallel. The parent (caller) gets a compact structured report — one summary card per article — plus the full body text saved to disk for selective deep-reading.

## Inputs

- `<topic>`: Required. The research topic, e.g. `"claude code skills"`, `"AI agents in production"`, `"GraphRAG"`. Free-form phrase; the script derives tag slugs and search queries from it.
- `--days=N`: Optional. Recency window in days. Default `90`. "Trendy" topics work well at 14–30; broader surveys want 90–180.
- `--top-n=N`: Optional. How many articles to fetch in full. Default `5`. Capped at 10 to keep subagent fanout reasonable.

## Goal

Return a single structured markdown document to the caller containing:
1. A one-line summary of search totals and slugs used
2. For each of the top N articles: title, author, date, paywall flag, key bullets, link, on-disk path to full body
3. A short table of other surfaced candidates that weren't deep-fetched

The caller then synthesizes themes/trends. Synthesis is **not** this skill's job — staying out of the synthesis lane keeps this skill reusable across very different research goals (article writing, due diligence, sentiment, competitive scan).

## Steps

### 1. Verify the mirror is reachable

```bash
nslookup freedium-mirror.cfd
```

If DNS fails (NXDOMAIN), abort and tell the caller "Freedium mirror is unreachable from this network — try again later or use an authenticated Medium fetch instead." `freedium.cfd` (canonical) is often dead, and the `-mirror` clone is third-party. Failing fast saves spawning subagents that all hit the same wall.

### 2. Phase 1 — Discovery

```bash
python3 ~/.claude/skills/medium-research/scripts/discover.py \
    --topic "<topic>" \
    --days <days> \
    --top-n <top_n>
```

Internally: derives 2–8 tag slugs from the topic, fetches each candidate slug's RSS feed concurrently along with a DuckDuckGo `site:medium.com` search, dedupes by canonical URL, scores by topic match + recency + slug specificity, applies a relevance gate when the topic spans 3+ words, sorts.

Output is JSON on stdout. Fields you care about:
- `totals` — counts at each merge stage (use for the summary header)
- `tag_slugs_used` — which derived slugs returned items
- `selected` — top N for extraction
- `other` — ranked tail (up to 25) for the candidates table

**Why DuckDuckGo and not Medium's own search?** `medium.com/search` is a JavaScript SPA — `curl` gets a 5KB shell with no results. RSS tag feeds are static and parseable but only catch articles authors tagged. DDG with `site:medium.com` covers the long tail.

If `selected` is empty, tell the caller no qualifying articles were found in the window and ask whether to widen `--days`.

### 3. Phase 2 — Parallel extraction (N concurrent fetches)

For each entry in `selected`, fetch and distill the article in parallel. Choose ONE of two execution paths based on what's actually in your tool surface — don't fall back from A to B mid-run.

**Path A — Subagent per article (preferred when `Agent` is available).** Spawn one subagent per selected article in the **same message** so they run concurrently. Each subagent reads the body off disk and produces dense bullets, keeping the parent's context clean.

> **Subagent prompt template** (substitute `<title>`, `<url>`, `<index>` 1-based, `<output_dir>`):
>
> You are extracting one Medium article for a research digest. The article is "<title>" at <url>.
>
> 1. Run: `python3 ~/.claude/skills/medium-research/scripts/extract.py --url "<url>" --save-body "<output_dir>/article-<index>.md"`
> 2. Parse the JSON output (single object on stdout).
> 3. If `extraction_failed: true`, return only `{ "index": <index>, "url": "<url>", "title": "<title>", "extraction_failed": true, "reason": "<reason from script>" }`.
> 4. Otherwise read the saved body and produce 3–5 bullet `key_points` capturing the article's main claims, novel ideas, or specific tools/techniques mentioned. Skip generic intros and outros. If the article is a list (e.g., "9 things"), the bullets should be the items themselves, not a meta-summary.
> 5. Return JSON only, with these fields: `index`, `title`, `subtitle`, `author`, `date`, `url`, `paywall`, `read_min`, `word_count`, `key_points` (array of strings), `body_path`. No prose, no markdown — just JSON.
>
> Constraints: Don't re-fetch the URL yourself — the script already does Freedium + HTML strip. Don't quote large excerpts in `key_points` — the body is on disk.

**Path B — Parallel Bash calls (when `Agent` is not in your tool surface).** Run all N `extract.py` invocations as separate Bash tool calls in the **same message** so they execute concurrently. Then read each saved body file yourself and write the same bullets the subagent would have. extract.py creates `<output_dir>` itself; no separate `mkdir` needed.

```bash
python3 ~/.claude/skills/medium-research/scripts/extract.py \
    --url "<url>" \
    --save-body "<output_dir>/article-<index>.md"
```

**Success criteria**: For each selected article, you have either successful structured data (title, author, date, paywall, key_points, body_path) or a clear `extraction_failed: true` with a reason. Don't proceed past this step until all N have completed.

### 4. Assemble the report

Emit a single markdown document to the parent. Use this exact shape so callers (including future automations) can parse it:

```markdown
# Medium Research: <topic>

**Window:** last <days>d · **Selected:** <N>/<in_window> candidates · **Sources:** RSS tags [<slug1>, <slug2>, ...], DuckDuckGo (<ddg_count> results) · **Bodies:** /tmp/medium-research-<slug>/

## Articles

### 1. <title>
<author> · <date> · <read_min> min · <paywall: 🔒 paywalled | 🔓 free> · <word_count> words

<subtitle (if present)>

**Key points:**
- <bullet 1>
- <bullet 2>
- ...

**Link:** <url>
**Full text:** <body_path>

---

(repeat 2..N, separated by `---`)

## Other Candidates

| # | Title | Author | Date | Score |
|---|-------|--------|------|-------|
| 1 | ... | ... | ... | ... |
```

Cap the "Other Candidates" table at the top 15 by score. If a subagent returned `extraction_failed`, include the article in its numbered slot with a one-line failure note rather than skipping silently.

## Hard rules

- **Don't synthesize themes.** Resist adding a "Trends" or "Takeaways" section. The whole point is gathering raw material the caller can mix differently each time. A skill that hardcodes synthesis becomes useless when next week's caller wants a different angle.
- **Don't re-fetch URLs in the parent.** Subagents already saved bodies to disk. Use `Read` on the body file for quotes.
- **Don't fall back to alternative mirrors silently.** If `freedium-mirror.cfd` is down, fail loudly. The caller may want to reschedule rather than get a skill that pretends to work.
- **Don't write to `output/`.** This is a global user skill; bodies go in `/tmp/medium-research-<slug>/`. The caller can move them if they want them archived.

## Gotchas

- **DDG-only entries lack date metadata** so they pass the recency filter by default. They're penalized in scoring but can still reach top N. The subagent's `date` field (parsed from Freedium) is the source of truth.
- **Title parsing for DDG-only entries.** DDG returns just URLs, not titles. Phase 2 fills titles from Freedium during extraction — empty titles in the Phase 1 JSON are expected, not a bug.
- **Mirror flakiness.** Even when DNS resolves, the mirror sometimes returns truncated pages or rate-limits in bursts. The script returns `extraction_failed` with a `body_extraction_failed_or_short` reason. Treat as transient — a retry later usually works.

## Files in this skill

- `scripts/discover.py` — Phase 1: RSS + DDG discovery, scoring, ranking
- `scripts/extract.py` — Phase 2: Freedium fetch, HTML parsing, body extraction
- `SKILL.md` — this file
