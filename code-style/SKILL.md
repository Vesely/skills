---
name: code-style
description: >-
  Align recently written or changed code so it matches the surrounding project's
  established conventions — formatting, naming, imports, comments, and idioms —
  learned from the codebase itself, then apply the fixes. Use this whenever the
  user wants their changes to "match the codebase / our conventions / the rest of
  the app", asks to make a diff or PR style-consistent, wants a style pass or
  style review before opening a PR, says code "feels off" or inconsistent with the
  project, or invokes /code-style. Works in any language or framework — it
  discovers the rules from the repo rather than assuming them. Reach for this
  even when the user doesn't say the word "style" but clearly wants new code to
  blend in with existing code. Also covers de-slopping AI-generated artifacts
  from the diff — over-commenting, defensive checks or try/catch abnormal for
  the code path, casts to any / type-ignore escape hatches, needless nesting —
  so use it when the user says "remove AI slop", "de-slop", "this looks
  AI-written", or wants AI artifacts cleaned from a branch.
---

# Code Style

Make new or changed code indistinguishable from code a long-time maintainer of *this* project would have written. The goal is that a reviewer reading the diff cannot tell which lines are new based on style alone.

## The one principle that matters

**Match the project's actual conventions — as evidenced by its own code and config — not your own preferences or generic "best practices."**

This is the trap to avoid. A project might use patterns you'd personally write differently: 4-space indent, no semicolons, `require()` over ESM imports, terse names, no JSDoc, a particular import order. Your job is to make the new code look like its neighbors, even when that means writing code you wouldn't choose on a blank slate. "Cleaner" is not the goal; *consistent with this repo* is the goal.

Two hard boundaries that keep this safe and reviewable:

- **Style only — never change behavior.** Naming *is* style, and it's where blending in is most visible. Renaming a **local variable** or a **private/callback parameter** to fit the project's conventions — casing *and* descriptiveness — is safe and expected: if neighbors spell names out, don't leave terse `a`/`b`/`x` in the new code just because it reads fine to you. Be careful with **public/exported** symbols: renaming an exported identifier — or a public function's parameter, which callers may pass by keyword (e.g. Python kwargs) or rely on via reflection/codegen — can break callers. Only rename those when the symbol is brand-new and unreferenced, and call it out. Anything that changes what the code *does* (reordering arguments, changing a default, restructuring logic) is out of scope. When in doubt whether a change is behavior-preserving, leave it.
- **Surgical — only touch the changed code.** Align the lines in the diff (and what's needed to make them consistent). Do not reformat, rename, or "fix" pre-existing code outside the change, even if it's inconsistent. That would bury the real change in noise and is exactly what reviewers hate.

## Workflow

### 1. Scope the changes

Run the bundled helper to auto-detect what to align and what tooling exists:

```bash
bash <skill-dir>/scripts/style-scope.sh
```

It prints the **scope** (uncommitted changes if any exist, otherwise this branch vs. the default branch), the **formatter/linter configs** present, and the **style docs** to read. Then read the actual changes it points you to (`git diff …`, plus any new untracked files in full) so you know exactly which lines are in play.

If the user named a narrower target ("just the changes in `src/auth/`"), respect that within the detected scope.

Skip files you shouldn't restyle even if they're in the diff: generated/compiled output, vendored/third-party code, minified bundles, lockfiles, and submodules. If one of these is genuinely in scope, regenerate it via its generator or report it as skipped — don't hand-edit it. The helper also flags deletions and renames; a deleted file has nothing to align, and a pure rename (no content change) needs no style work.

### 2. Let the project's own tooling do the mechanical work first

A configured formatter/linter *is* the project's rule for what it covers — whitespace, quotes, semicolons, line length, trailing commas — so don't hand-replicate that; let the tool do it:

- JS/TS: `npx prettier --write`, `npx eslint --fix`, `npx biome check --write`, or the project script (`bun run lint`, `npm run format`).
- Python: `ruff format` / `ruff check --fix`, `black`, `isort`.
- Others: `gofmt -w`, `cargo fmt`, `rubocop -a`, `mix format`, etc.

**Keep the diff surgical** — this is the trap with formatters. They rewrite *entire files*, so running one on a file that also contains pre-existing off-style code will churn lines you never touched and break the surgical guarantee. So: on a **brand-new file**, run the tool freely. On a **modified file**, run it only if the rest of the file is already clean; otherwise apply the rules by hand to your changed lines, or run the tool and then revert every edit outside your changed ranges (compare `git diff` before vs. after to see exactly what it touched). Never keep unrelated formatting churn, and never edit the tool's config to make code "pass" — the config is the source of truth.

If a tool isn't installed and can't be run quickly (no network/install available or appropriate), don't get stuck — read its config and apply the same rules by hand in step 4, noting in the summary that you couldn't run it.

### 3. Learn the conventions tooling can't enforce

Formatters don't cover the conventions that most make code "look native": naming, structure, idioms, comments. Learn these from evidence, not assumption. For each changed file, read **2–4 neighbor files of the same kind** (same directory, same extension, similar role — e.g. a sibling component, another route handler, another test) and skim any style docs the helper found (`CLAUDE.md`, `CONTRIBUTING`, `.editorconfig`). Comments are where AI-written code most often gives itself away — it over-narrates, restating what the code plainly does — so by default trim that redundancy on your changed lines down to the neighbors' density (e.g. drop `// loop over users` above `for (const user of users)`), keeping any comment that carries intent the code can't show (a *why*, a warning, a TODO/FIXME, a legal header, a lint/type pragma). This is a default lean, not a blanket rule — it applies because AI output skews verbose, so evidence the target density from the neighbors, and if the project is genuinely comment-heavy, match that instead.

`references/conventions-checklist.md` is the catalog of dimensions to inspect — read it so you know what to look for (naming, imports, exports, error handling, comments, types, test shape, framework idioms). Pull the conventions from the neighbors; use the checklist as the lens.

When the codebase is inconsistent, follow the **nearest, most-recent, most-relevant** neighbors (same module first), not the global majority. Match what a maintainer would write in *that* file today.

### 4. Align the changed code

Apply surgical edits so the changed code follows the conventions you found. Stay strictly within the scope from step 1. Keep the change set tight: if aligning one line forces a cascade into untouched code, stop and prefer the smaller consistent option, or flag it rather than sprawl.

**De-slop pass.** In the same sweep, hunt the changed lines for AI-generated patterns a human maintainer of this repo wouldn't have written. The tell is always the same: the pattern is *inconsistent with the file and its neighbors*, not wrong in the abstract.

- **Comments a human wouldn't add** — beyond the density trim from step 3: banner/section comments narrating obvious structure, docstrings on trivial private helpers when neighbors have none, comments addressed to the reviewer ("now we handle X", "this fixes the bug by…"). Remove them when they add no intent or constraint beyond what the code already shows.
- **Defensive checks and try/catch abnormal for that area** — null-guards, existence checks, or catch blocks on trusted/validated code paths where neighbors call the same things bare. Remove only when the in-scope runtime path makes the branch unreachable AND evaluating the check has no observable effects, with that proof visible locally (e.g. a dominating validation or exhaustive branch). Types and neighboring reliance on the invariant are supporting evidence, not proof. Otherwise leave it and flag it.
- **Type-escape hatches** — `as any` / `any` params, `@ts-ignore`, `# type: ignore`, casts or added optionality whose only purpose is silencing the checker. Replace with the correct type only when the change is local, type-only in that language/toolchain, and behavior-preserving; otherwise flag rather than launder.
- **Dead fallbacks** — `|| default` / `?? default` on values that can't be absent, re-checking a condition guaranteed one line up. Apply the same local proof standard as for defensive checks; otherwise leave it and flag it.
- **Needless nesting** — flag deeply nested conditionals when the file's own shape favors early returns / guard clauses; simplify only when the local rewrite is mechanically behavior-equivalent.

Apply the same guardrails as everything else in this skill: preserve behavior, prefer minimal focused edits over rewrites, and never touch slop that predates the diff.

### 5. Verify you changed style, not meaning

Confirm the edits are behavior-preserving and didn't break anything cheap to check:

- Re-run the formatter/linter on the changed files if you ran one — it should now pass clean.
- Re-read your diff: every edit should be cosmetic/naming/structure and behavior-preserving, nothing semantic. For every removed dead check or fallback, re-verify the local redundancy proof.
- If there's a fast type-check or the file's own test and it's quick, run it.

### 6. Summarize

Report concisely what you aligned and why, grouped by convention, with `file:line` references — e.g. "double→single quotes (matches prettier config)", "renamed `e`→`event` in callbacks (project bans single-char params, see CLAUDE.md)", "reordered imports to external→internal (matches neighbors)". Call out anything you deliberately left alone (pre-existing inconsistencies outside the diff) and any tool you couldn't run. This is the value: the user sees that the change now blends in, and can trust it via `git diff`.

## When this skill is a poor fit

- The user wants behavior changes, refactors, or bug fixes — that's not this skill (do that work, then optionally run a style pass after).
- There's no established codebase to match (brand-new/empty repo, single file with no neighbors) — there are no conventions to learn; say so and fall back to the language's standard tooling defaults.
- The user wants to *set up* linting/formatting config or a CI style gate — that's tooling configuration, not aligning existing changes.
