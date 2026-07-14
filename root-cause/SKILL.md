---
name: root-cause
description: Use before shipping any fix, and the moment you catch yourself explaining why a problem cannot properly be fixed. Forces you to state the defect mechanism, classify what you are actually shipping (fix / mitigation / workaround), and refuse to let cost, risk or scope constraints quietly redefine the problem. Trigger on "root cause", "is this the real fix", "did you actually fix it", "quick fix", "patch", "workaround", "band-aid", "good enough for now" — or whenever a fix's reliability rests on an instruction being followed rather than on a guarantee.
---

# Root Cause

`systematic-debugging` gets you **to** the root cause. This skill stops you from **walking away from it** once you are standing on it.

The failure it prevents is not "I never investigated." It is the subtler one:

> I found the real cause, judged it too expensive / risky / out of scope, built something around it, and then described that as the fix.

## The Iron Rule

**You may ship a mitigation. You may not ship a mitigation _called_ a fix.**

## The gate: three questions before any fix lands

### 1. State the mechanism

Finish this sentence with no hedging:

> "The defect happens because ______."

If your sentence contains *sometimes*, *may*, *tends to*, *the model might*, *the user could* — you have a **symptom**, not a mechanism. Keep going.

### 2. Name what you are shipping

|  | Definition | Allowed? |
|---|---|---|
| **Fix** | The mechanism can no longer occur. | yes |
| **Mitigation** | Mechanism intact. You made it rarer, or you detect and repair it afterwards. | yes, **if named** |
| **Workaround** | Mechanism intact. A human absorbs the cost. | yes, **if named** |

Write the label down. Ambiguity here is how mitigations get promoted to "fixed" by accident.

### 3. Apply the compliance test

Does correctness depend on someone **choosing to comply** — an LLM following an instruction, a human remembering a convention, a caller honoring a comment?

**Then it is a mitigation.** Guarantees come from code, types, schemas and data. Never from prose.

## Tell #1: the word "can't" marks the spot

The moment you write or think any of these:

- "we don't have that information"
- "that's decided by the model / the user / upstream"
- "there is no deterministic way to know"
- "it isn't captured anywhere"

**That sentence _is_ the root cause.** It is not an obstacle standing in front of the root cause.

So do not build a clever structure around the absence. **Go get the missing thing.** Nearly always this means turning a *judgment* into *data*: capture the signal, add the field, record the input, make the implicit explicit — and then decide in code, where it is deterministic and testable.

Ask: **what would make this deterministic?**

## Tell #2: constraint laundering

Watch for a constraint about **how you work** quietly becoming a decision about **what you build**:

| What you told yourself | What actually happened |
|---|---|
| "I can only verify X cheaply, so I'll build X" | Your validation budget picked the architecture |
| "Surgical edits only, don't touch the schema" | Blast-radius discipline became avoidance of the correct file |
| "That edge case makes this approach messy" | One case you would have had to model vetoed the whole design |
| "The proper fix is expensive / needs approval" | You designed around the ask instead of making it |

**Rule:** when the correct fix needs a resource — money, a live run, an approval, a schema change, more scope — **ask for it**. Surface the tradeoff and let the human decide. Never quietly ship a worse thing that happens to fit your budget.

## Layering is good. Mislabeling is not.

Defence in depth is correct engineering: a root-cause fix **plus** a net beneath it for what the fix cannot cover. What is not allowed is shipping **only the net** and reporting it as the cure.

## Report honestly

Your summary may not claim more than the mechanism guarantees.

If the direction is still chosen by an LLM, you may not write *"now authoritative"* — a prompt cannot make anything authoritative, only code can. Separate what is **guaranteed** from what is merely **more likely**, and say plainly what remains uncovered.

## Red flags

Each of these describes a mitigation. All are fine to ship. None may be called a fix.

- "the prompt now tells it to…"
- "we detect it and repair it afterwards"
- "we warn the user"
- "the user can correct it manually"
- "this should make it much less likely"
- "added a retry / a guard clause / a null check"

## Done means

- [ ] Mechanism stated in one unhedged sentence
- [ ] What you are shipping is labelled: fix / mitigation / workaround
- [ ] If a "can't" appeared, you tried to obtain the missing thing — or explicitly asked to
- [ ] Constraints were surfaced, not laundered into the design
- [ ] Verified against the **original** failing input, not a synthetic stand-in
- [ ] The summary claims exactly what the mechanism guarantees, no more

## Related

- **systematic-debugging** — the investigation process that gets you to the root cause. Use it first; use this one before you ship.
