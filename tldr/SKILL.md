---
name: tldr
description: Compress the whole thread — the problem or feature being worked on and how it was solved — into a single TL;DR line, then propose exactly three terse next-step labels (≤8 words each, slash commands welcome) the user can take. Use whenever the user types `/tldr`, `/recap`, says "tldr", "tl;dr", "summarize and suggest next steps", "recap that", "what should I do next", "give me the gist", or otherwise asks for a quick summary of what's been going on plus suggestions for what to do next. Trigger even when the user phrases it casually ("ok so what now?", "give me the short version + next steps") — this skill exists exactly for those moments where a long thread needs distilling and a clear handoff to action. Use the "Variant: dyslexia-friendly visual preview" section on `/tldr visual` or `/tldr dyslexia`, or when the user asks for a dyslexia-friendly, visual, or cmux recap.
---

# tldr

Distill the whole thread into one line — the problem or feature being worked on and how it was solved — then offer three concrete, takeable actions.

## Why this exists

Long threads are useful while you're living them, but expensive to re-read later or to act on under time pressure. A reader who has already followed along doesn't need the full transcript again — they need (a) a one-line anchor that captures what the work was and how it landed and (b) a short, ordered menu of moves they can make right now. That's the whole job.

## Scope

By default, summarize **the entire thread**: what problem or feature was being worked on, and how it was (or is being) solved. Read across the whole conversation, not just the last message — anchor the one-liner on the through-line of the work, the thing the user would want to remember a week from now. Skip the blow-by-blow; collapse dead ends, retries, and side-quests into the outcome that survived.

Only narrow the scope when the user explicitly asks for it (e.g. "tldr that last message", "just the previous answer", "recap only what you just said") — then summarize just that slice instead.

## Output format

Always use this exact shape — nothing before, nothing after:

```
**TL;DR:** <one sentence, ≤160 characters, no preamble>

1. <next step>
2. <next step>
3. <next step>
```

Rules that make this shape work:

- **The TL;DR names the problem/feature and how it was solved.** That's the spine of the line: *what* the thread was about and *how* it landed (or where it stands). A recap that says what happened but not the resolution has missed the point.
- **The TL;DR is one sentence.** Not two. If you need a comma or semicolon, fine — but no second sentence and no trailing parenthetical that's secretly another sentence.
- **No "In summary,", "To recap,", "Basically,"** or any other warm-up. Start with the substance.
- **Each next step is a short, terse label — ideally 1–6 words.** Think menu items, slash commands, or chip labels: `Run tests`, `Apply fix`, `/ui-review`, `Pick option B`, `Open PR`. *Not* full sentences with file paths, rationale, or how-to detail. The user reading the recap doesn't need instructions — they already followed the conversation. They need a short menu of moves they can take. If a step needs explaining beyond the label, the label is wrong; pick a sharper one.
- **Order the steps by what makes sense to do first**, not by importance. If step 2 only makes sense after step 1, that ordering is doing real work.
- **Exactly three steps.** Not four "in case", not two "to keep it tight". Three is the contract — it's enough to give a sense of options without becoming a checklist the user has to triage.
- **Use slash commands when one fits.** If the next move maps cleanly to an installed skill or command (`/commit`, `/ui-review`, `/pr-feedback`), prefer that over prose. It tells the user exactly what to type.

## How to pick good next steps

The thread usually contains the raw material. Pull from where the work currently stands:

- **Loose ends the thread left open** — "we still need to verify X", "you might want to test Y" → those are next steps.
- **The natural follow-up to whatever was just delivered** — if the work fixed a bug, step 1 is usually "ship it" (test, commit, open PR). If the thread ended on open options, step 1 is "pick one" framed as a decision.
- **Adjacent moves the user hasn't thought of yet** — one of the three slots is well spent on something the thread didn't explicitly mention but that a careful reader would do anyway (write a test, update the docs, check the related call site).

If the thread currently rests on a question to the user, the next steps should be ways to answer it or things to gather before answering.

Avoid generic filler like "review the changes", "let me know if you have questions", or "consider edge cases" — these are not actions, they're throat-clearing.

## Examples

**Example 1 — after a bug-fix explanation:**

```
**TL;DR:** Missing `await` on `db.users.find()` in `auth/login.ts:34` — added it, route works.

1. Run tests
2. Grep for other unawaited calls
3. Add lint rule
```

**Example 2 — after presenting two architectural options:**

```
**TL;DR:** Redis (faster, more infra) vs per-request memo (simpler, less win) — depends on whether you need cross-request hits.

1. Pick approach
2. Prototype on hottest endpoint
3. Benchmark
```

**Example 3 — after a long research dump on a library:**

```
**TL;DR:** TanStack Query covers caching, retries, and stale-while-revalidate out of the box; only the auth-refresh interceptor stays custom.

1. Install + provider setup
2. Migrate one read-heavy hook
3. Port mutations
```

**Example 4 — when a slash command fits the next move:**

```
**TL;DR:** Component looks ready — passes a11y check and matches the design system.

1. /ui-review
2. /commit
3. /pr-feedback
```

## Variant: dyslexia-friendly visual preview

Triggers: `/tldr visual`, `/tldr dyslexia`, or any ask for a dyslexia-friendly, visual, or cmux recap. Write the recap in English by default; use another language only when the user asks for it.

Keep the content contract (one recap plus exactly three next steps) but override the exact inline shape with a dyslexia-friendly layout: short lines, one idea per line, bold key words as anchors, large headings, generous whitespace, simple words, and a small table for status facts. Emoji as visual anchors are welcome. Stay minimal and direct: the recap, the three steps, at most one small status table and one or two cropped screenshots — nothing else.

Open it as a cmux markdown page only when the user asks for a panel or preview, or the thread has something visual to show (a rendered page, UI change, chart). Otherwise answer inline in that layout. For the cmux page:

- Write a temporary markdown file (prefer the scratchpad directory when one exists), then `cmux markdown open <path>`. The panel live-reloads, so updates just rewrite the file.
- Embed screenshots as base64 data URIs (JPEG, cropped to the regions that prove the point, ~900px wide) — file paths do not render in the cmux viewer. Compose the file in bash (`base64 -i img.jpg` into a heredoc); data URIs are too large to write by hand.

## When to bend the rules

- **The thread is trivial or a single short exchange.** Don't recap a recap. Tell the user "nothing much to compress here — next steps:" and skip the TL;DR line.
- **User narrows the scope.** If they ask to tldr just the last message or a specific slice, honor it and summarize only that instead of the whole thread.
- **There's nothing meaningful to do next.** Rare, but it happens (e.g. the work shipped and the deploy succeeded). In that case, give the TL;DR and explicitly say next steps are optional, then offer three *optional* moves (verify, document, monitor).
- **User asks for more or fewer steps.** Honor it. Three is the default, not a religion.
