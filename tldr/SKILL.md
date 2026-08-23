---
name: tldr
description: Open with a short ✅/⚪ checklist of the milestones the thread actually hit, compress the whole thread — the problem or feature being worked on and how it was solved — into a single TL;DR line, then propose up to three terse next-step labels (≤8 words each, slash commands welcome) the user can take. Use whenever the user types `/tldr`, `/recap`, says "tldr", "tl;dr", "summarize and suggest next steps", "recap that", "what should I do next", "give me the gist", or otherwise asks for a quick summary of what's been going on plus suggestions for what to do next. Trigger even when the user phrases it casually ("ok so what now?", "give me the short version + next steps") — this skill exists exactly for those moments where a long thread needs distilling and a clear handoff to action. Use the "dyslexia-friendly visual preview" variant section on `/tldr visual` or `/tldr dyslexia`, or when the user asks for a dyslexia-friendly, visual, or cmux recap.
---

# tldr

Show where the work stands as a short checklist, distill the whole thread into one line — the problem or feature being worked on and how it was solved — then offer up to three concrete, takeable actions.

## Why this exists

Long threads are useful while you're living them, but expensive to re-read later or to act on under time pressure. A reader who has already followed along doesn't need the full transcript again — they need (a) an at-a-glance answer to "how far did this actually get?", (b) a one-line anchor that captures what the work was and how it landed and (c) a short, ordered menu of moves they can make right now. That's the whole job.

The checklist is there because prose hides state: "fixed, PR open, gates green" reads as *done* even when nothing is merged and nobody checked production.

## Scope

By default, summarize **the entire thread**: what problem or feature was being worked on, and how it was (or is being) solved. Read across the whole conversation, not just the last message — anchor the one-liner on the through-line of the work, the thing the user would want to remember a week from now. Skip the blow-by-blow; collapse dead ends, retries, and side-quests into the outcome that survived.

Only narrow the scope when the user explicitly asks for it (e.g. "tldr that last message", "just the previous answer", "recap only what you just said") — then summarize just that slice instead.

When the user points at a PR (number, URL, "this PR"), compress that PR instead: the problem, the fix, review findings and how they were handled, and current state (CI, merged, deployed). State only what you actually know — merged does not imply deployed.

## Output format

Use this exact shape (the visual variant and the rule-bending cases below aside) — nothing before, nothing after:

```
✅ <milestone>
✅ <milestone>
⚪ <milestone not reached>
⚪ <milestone not reached>

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
- **Default to three steps — never pad to hit the count.** Each step, command or prose, must be called for by the thread's current state, doable right now, and not already done. If only two real moves exist, give two. A padded slot (a topically-related slash command after the work is already merged, "update docs" with nothing to update) costs more trust than a shorter list.
- **Use slash commands when one fits — and check the precondition, not the topic.** The command must be runnable and useful *right now*: `/commit` needs uncommitted work, `/handoff-to-worktree` needs undone work to hand off, `/ui-review` needs UI changes. Topical similarity to the thread is not a fit.

## The checklist

Three to six lines above the TL;DR, each one milestone the thread reached or didn't.

| | Meaning |
|---|---|
| ✅ | Done and evidenced in the thread |
| ⚪ | Not reached yet — the default for anything unfinished |
| ⏳ | Running **right now** — a background agent still working, a CI run in progress, a deploy mid-flight |
| ❌ | Wrong right now — red CI, a failing test, an approach ruled out |

`⏳` and `❌` are both narrow. Waiting on a human is not running: "waiting for David's review" is `⚪`, "three review subagents still working" is `⏳` — and since a `⏳` line stops being true the moment the work finishes, never write one you haven't just observed. Not started is not broken: "no PR yet" is `⚪`, "CI red" is `❌`.

**Milestone vocabulary.** For a code change, prefer these labels, in this order — the spine of the usual pipeline:

`Replicated` · `Root cause` · `Fixed` · `Tests + gates` · `/ship-ready` · `Review findings fixed` · `Verified in the app` · `Committed + pushed` · `PR opened` · `CI green` · `Merged` · `Prod verified`

For anything that isn't a code change — an investigation, a design decision, a research dump — write free-form labels that fit the actual work (`Blast radius scoped`, `Design decided`, `No code written`). The vocabulary is a spine, never a template to fill.

**Rules:**

- **Tick only what the thread evidences, and never infer one milestone from another.** Merged does not imply deployed; green gates do not imply verified in the app; findings fixed does not imply the reviewer re-ran. If you'd have to guess, drop the line — a wrong ✅ is the one failure mode that makes the whole recap untrustworthy.
- **Three to six lines, labels ≤5 words** (a code token or a PR number counts as one). Fewer than three real milestones → no checklist at all; go straight to the TL;DR.
- **Order = pipeline order**, not importance, so the eye lands on the first unticked line as the boundary between done and not done.
- **The checklist carries state, the TL;DR carries the story.** Don't restate the ticks in the sentence.

## How to pick good next steps

The thread usually contains the raw material. Pull from where the work currently stands:

- **The first ⚪ or ❌ in the checklist** is very often step 1 — that's the point of ordering it by pipeline. A `⏳` line instead means step 1 is to wait for it or read its result.
- **Loose ends the thread left open** — "we still need to verify X", "you might want to test Y" → those are next steps.
- **The natural follow-up to whatever was just delivered** — if the work fixed a bug, step 1 is usually "ship it" (test, commit, open PR). If the thread ended on open options, step 1 is "pick one" framed as a decision.
- **Adjacent moves the user hasn't thought of yet** — worth a slot only when current evidence makes it useful: something the thread didn't explicitly mention but that a careful reader would do anyway (write a test, update the docs, check the related call site).
- **The user's own routine.** Prefer moves the user demonstrably makes after this kind of work — check memory files and project docs (post-merge checklists, support workflows) and what they did in similar past threads. After a merged PR that might be: verify the prod deploy, send the pending draft, update support docs.

If the thread currently rests on a question to the user, the next steps should be ways to answer it or things to gather before answering.

Avoid generic filler like "review the changes", "let me know if you have questions", or "consider edge cases" — these are not actions, they're throat-clearing.

## Examples

**Example 1 — a bug fixed but nothing shipped yet:**

```
✅ Replicated from the ticket
✅ Root cause — `raw: false` in `useExcel.js`
✅ Fixed + 118/118 tests
⚪ Uncommitted, no PR
⚪ Migration not run

**TL;DR:** Excel-imported dates hit Mongo as "14/4/2025" instead of YYYY-MM-DD — fixed via ISO conversion in useExcel + strict-parse fallback; migration script ready, not run.

1. /commit
2. Dry-run migration on koop-servis
3. Browser-test import on demo
```

**Example 2 — merged is not deployed, and the checklist is what keeps them apart:**

```
✅ Fixed + UI review
✅ Review findings fixed — gpt-5.5, Codex, CodeRabbit
✅ CI green
✅ Merged — #298 + #299
⚪ Prod deploy not verified
⚪ Newsletter not sent

**TL;DR:** Scanner mobile-handoff UX fixes (#298) + newsletter (#299) went through a multi-pass review, all findings fixed, both squash-merged to `main`.

1. Delete merged branches
2. Verify prod deploy
3. Send newsletter
```

**Example 3 — `⏳` while something executes, `❌` while something is wrong:**

```
✅ Root cause — non-atomic claim on the alert
✅ Fixed — claim → send → confirm/release
⏳ Greptile re-review running
❌ CI red — pushed peer tests without their source
⚪ Unmerged

**TL;DR:** Duplicate bounce alerts fixed via an atomic claim lifecycle (PR #580), but my push split a peer session's work in half and CI is now red.

1. Pick A (commit source) or B (roll back)
2. Ping `attendu-interface-42`
3. Read the Greptile result
```

**Example 4 — after presenting two architectural options; too little happened for a checklist:**

```
**TL;DR:** Redis (faster, more infra) vs per-request memo (simpler, less win) — depends on whether you need cross-request hits.

1. Pick approach
2. Prototype on hottest endpoint
3. Benchmark
```

## Variant: dyslexia-friendly visual preview

Triggers: `/tldr visual`, `/tldr dyslexia`, or any ask for a dyslexia-friendly, visual, or cmux recap. Write the recap in English by default; use another language only when the user asks for it.

Keep the content contract (one recap plus up to three next steps) but override the exact inline shape with a dyslexia-friendly layout: short lines, one idea per line, bold key words as anchors, large headings, generous whitespace, simple words, and a small table for status facts. Emoji as visual anchors are welcome. Stay minimal and direct: the recap, the steps, at most one small status table and one or two cropped screenshots — nothing else.

**That status table replaces the checklist here — never render both.** Same honesty rules apply: only rows the thread evidences, and merged never implies deployed.

Open it as a cmux markdown page only when the user asks for a panel or preview, or the thread has something visual to show (a rendered page, UI change, chart). Otherwise answer inline in that layout. For the cmux page:

- Write a temporary markdown file (prefer the scratchpad directory when one exists), then `cmux markdown open <path>`. The panel live-reloads, so updates just rewrite the file.
- Embed screenshots as base64 data URIs (JPEG, cropped to the regions that prove the point, ~900px wide) — file paths do not render in the cmux viewer. Compose the file in bash (`base64 -i img.jpg` into a heredoc); data URIs are too large to write by hand.

## When to bend the rules

- **The thread is trivial or a single short exchange.** Don't recap a recap. Tell the user "nothing much to compress here — next steps:" and skip both the checklist and the TL;DR line.
- **User narrows the scope.** If they ask to tldr just the last message or a specific slice, honor it and summarize only that instead of the whole thread.
- **There's nothing meaningful to do next.** Rare, but it happens (e.g. the work shipped, deployed, and verified). Give the checklist and TL;DR and say so — offer fewer steps or none rather than inventing optional ones.
- **User asks for more or fewer steps.** Honor it. Three is the default, not a religion.
