# root-cause

Stops you from shipping a patch and calling it a fix. Forces you to state the defect mechanism in one unhedged sentence, label what you are actually shipping (fix / mitigation / workaround), and refuse to let cost, risk or scope constraints quietly redefine the problem. Catches the two classic tells: the word "can't" (the thing you say you cannot know *is* the root cause), and constraint laundering (your validation budget silently choosing the architecture).

Complements `systematic-debugging`: that one gets you **to** the root cause, this one stops you **walking away from it**.

## Install

```
npx skills@latest add Vesely/skills/root-cause
```
