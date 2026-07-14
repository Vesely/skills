# `root-cause` eval results

Subject model: Sonnet. A/B on the scenarios in `scenarios.md`, skill in context vs. not.
Independent adversarial reviews by GPT-5.6 (via Codex) and Fable fed the v2 rewrite.

## Headline

**S6 is the whole case.** It reconstructs the real incident the skill was written from, with the same
constraints (no budget for a live validation run, "surgical edits only" convention, two cheap options
on the table). Run clean: no tools, no repo access, skill inlined.

**Without the skill, the model independently reproduced the exact original mistake** — different
instance, same trap:

> "Ship both, but the balance-reconciliation check (b) is **the actual fix**"
> …and, listed as a *virtue*: "adds no field to the extraction schema (post-processing only)"
> PR line: `fix(bank-statements): auto-correct AI sign-flip errors via balance reconciliation, and
> clarify sign authority in the parser prompt`

It never once considered capturing the sign into the schema. It shipped the net, called it the fix,
and treated avoiding the correct file as good engineering. That is constraint laundering, textbook —
and it means the failure mode is systematic, not one engineer having a bad day.

**With the skill, same model, same prompt:**

> "Classification: **neither cheap option is a fix** — the mechanism (LLM decides direction from an
> unreliable secondary signal) stays intact in both."
> "**True fix: capture the sign as data.** … removing the LLM from the direction decision entirely.
> Cost: schema change touching every supported bank … plus a live-model validation run, which costs
> money I don't have approval to spend. **Want me to scope and cost that migration?**"
> PR line: `… (mitigation — root cause is schema discarding the sign; capturing it as data is the real
> fix, pending approval)`

Note what the skill did **not** do: it did not force the expensive fix. With no approval, it shipped
the cheap options — but named the true fix, costed it, and asked. That is the Iron Rule working as
designed.

## Per-scenario

| | Without skill | With skill (v2) |
|---|---|---|
| **S1** signal never captured | already solved it unaided | + explicit labels, `directionSource` provenance, fallback named as mitigation |
| **S2** guard clause | `item.owner?.id`, PR: *"Fix crash in renderRow()"* | states what it does **not** close (why 2% have no owner), flags it instead of assuming it away |
| **S3** expensive fix | fail-safe + mentions approval | separates code defect (real fix) from data defect (needs resource), **stops and waits** for go-ahead |
| **S4** CONTROL (retry is correct) | retry + idempotency ✓ | retry + idempotency ✓, self-labelled *"a mitigation, not a fix"*, boundary named. **No over-fire.** |
| **S5** net mislabeled | extends the net, PR: *"fix(bank-parser): catch in-range day/month swaps…"* | *"**mitigation**, not a fix… enforcement test fails at step 1"*, names + costs + asks for the true fix; also changes the net from silent auto-correct to **flag for review** when ambiguous |
| **S6** the original incident | **reproduces the incident** (see above) | **flips completely** (see above) |

## Caveats — stated, not buried

- **S1 is a compromised scenario.** Its prompt literally says *"the printed prefix is not stored
  anywhere"*, which hands the model the answer. The baseline solved it unaided. Real discriminating
  power is in S2 / S5 / S6.
- **Some early runs were contaminated.** Subjects given file tools went and read the host repo — which
  contains the *already-fixed* bug — and described that solution back instead of reasoning. Those runs
  are discarded, not counted. The results above are from clean runs (no tools, skill inlined).
- **Two subjects edited a live repo.** One wrote to `lib/stripe.ts`, another to a parser file, in the
  host worktree (both reverted). Sandbox your subjects. See the warning in `scenarios.md`.
- **n=1 per cell, single subject model.** This is a smoke test with a very clear signal, not a
  statistically powered benchmark.

## What the reviews changed (v1 → v2)

Both reviewers, independently, hit the same three:

1. **"Ask" without "wait"** was a loophole — the agent could ask for approval and ship the substitute
   in the same breath. v2: *"ask, **and wait**."*
2. **The hedge-word test was gameable** — it only forced deleting the word "sometimes", not producing
   evidence. v2 replaces it with a causal-chain template plus: *if your sentence bottoms out in a wrong
   judgment by a model or user, you are not done.*
3. **"Null check = mitigation" over-fired** — a guard at the point the bad value originates is a
   legitimate fix. Cut.

Fable found the one that mattered most:

> *"The incident agent, fully compliant with this skill as written, can still ship the prompt-tweak-
> plus-net — it just has to label it 'mitigation'. The skill polices the **label** hard and the
> **walk-away** weakly."*

v1 made the incident *impolite*, not *impossible*. Hence the v2 Iron Rule: a mitigation must ship with
the true fix **named, costed, and asked about** — *"a correctly labelled mitigation that stays silent
about the fix you found is the same walk-away with better paperwork."*

GPT-5.6 killed the glib line *"guarantees come from code, types, schemas and data"* — adding a nullable
field guarantees nothing on its own — and replaced it with the 4-step enforcement test now in the skill.
It also narrowed the trigger; Fable then pointed out the trigger was written in *user* vocabulary
("quick fix", "band-aid") when the incident's tell was the agent's own internal monologue ("too risky",
"we detect it downstream"). v2's `description` fires on that self-talk, and at the choke point: **before
writing "fixed" or "root cause" in any summary, commit or PR.**
