---
name: root-cause
description: Use when a defect's mechanism is known and the change you are about to ship may leave it intact — prompt/instruction tweaks, retries, warnings, post-hoc repair, fallbacks, guards downstream of the bad value — or when cost, risk, validation difficulty or scope is steering you toward a substitute. Fires on YOUR OWN reasoning, not just the user's words: "too risky to change", "hard to validate", "we detect and correct it downstream", "the prompt now instructs it to", "out of scope for this fix", "we don't have that information", "that's decided by the model". ALWAYS load before writing "fixed" or "root cause" in any summary, commit or PR. Not for initial diagnosis (use systematic-debugging), nor for routine fixes that plainly remove the mechanism.
---

# Root Cause

`systematic-debugging` gets you **to** the root cause. This stops you **walking away from it** once you are standing on it.

## The Iron Rule

**A mitigation is allowed. A mitigation that hides the fix you already found is not.**

Shipping anything less than a fix obliges you, **in the user-facing report**, to:

1. **name** the true fix,
2. **state what it costs** (money, migration, schema change, a live run, scope, risk),
3. **ask** whether to do it — and **wait for the answer**.

> A correctly labelled mitigation that stays silent about the fix you found is the same walk-away with better paperwork.

Once a human has knowingly chosen the mitigation, **ship it and stop re-litigating**. The goal is an informed decision, not the expensive fix.

*(Precedence: if another rule tells you "symptom fixes are always failure" — a labelled mitigation shipped with the true fix offered is not failure. An unlabelled one is.)*

## The gate

### 1. State the causal chain, with evidence

> When **[condition]**, **[component]** loses / misinterprets **[specific signal]**, producing **[wrong output]**.
> Evidence: **[observation]**.

If your sentence bottoms out in a wrong **judgment** by a model, a user, or an upstream system, **you are not done** — the real mechanism is that the deciding signal is not data. Go to Tell #1.

Do not redefine the mechanism to fit the patch you already have in mind.

### 2. Classify — in the report, not in your head

| | The mechanism… | |
|---|---|---|
| **Fix** | can no longer occur, on the stated inputs and paths | ship it |
| **Mitigation** | is intact; you made it rarer, or you repair it afterwards | Iron Rule applies |
| **Workaround** | is intact; a human absorbs the cost | Iron Rule applies |

The label goes in the summary / commit / PR. A label that exists only in your reasoning is not a label.

### 3. Enforcement test — for anything you want to call a fix

A guarantee is not a vibe. Adding a field or a code path proves nothing on its own. Show all four:

1. the signal is **captured** from the authoritative source;
2. it **survives** every transformation between there and the decision;
3. the outcome is **derived or validated by machine-enforced logic**;
4. a missing or invalid signal **cannot silently fall back** to the old judgment.

If any step still rests on an LLM complying, a human remembering, or unenforced prose — it is a mitigation. Say **which step**.

## Tell #1: the word "can't" marks the spot

The moment you think:

> "we don't have that information" · "that's decided by the model / the user / upstream" · "it isn't captured anywhere"

**That sentence _is_ the root cause.** It is not an obstacle standing in front of it.

Turn the **judgment into data**: capture the signal at its source, then decide in code. Go get the missing thing — or ask for what getting it requires (Tell #2).

**Boundary case:** if the signal genuinely does not exist at any source you control or can request, that is a real system boundary, not a defect. Then a named mitigation *is* the right answer. Say so explicitly.

## Tell #2: constraint laundering

Watch a constraint about **how you work** turn into a decision about **what you build**:

| What you told yourself | What actually happened |
|---|---|
| "I can only verify X cheaply, so I'll build X" | your validation budget picked the architecture |
| "surgical edits only, don't touch the schema" | blast-radius discipline became avoidance of the correct file |
| "too risky / too expensive / out of scope" | you made the human's call for them |

When the correct fix needs a resource — money, a live run, an approval, a migration, a schema change, scope, **or accepting risk** — **ask, and wait.** Risk acceptance is the human's call, not yours. Do not ask and ship the substitute in the same breath.

## Report honestly

Claim only what the mechanism guarantees. A prompt cannot make anything *"authoritative"* — only code can. Separate what is **guaranteed** from what is merely **more likely**, and state what remains uncovered.

## Before you write "fixed" or "root cause"

- [ ] Causal chain stated with evidence, and it does **not** bottom out in "the model/user judged wrong"
- [ ] The label (fix / mitigation / workaround) appears **in the report**
- [ ] Anything called a fix passes all four steps of the enforcement test
- [ ] If it is **not** a fix: the true fix is named, costed, and asked about — **and you waited**
- [ ] The summary claims exactly what the mechanism guarantees, no more
