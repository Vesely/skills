# dynamic-agents

Orchestrate a large task across multiple agents with cost-aware model routing. Decomposes the task, routes each subtask to the cheapest model that handles it well (session model for judgment-heavy work, Sonnet for mechanical work, Fable or GPT-5.6-sol+ via Codex CLI for the hardest nodes and cross-model review), picks fan-out vs team topology, presents the plan (gating on approval only for large or atypical runs), then executes and verifies.

## Install

```
npx skills@latest add Vesely/skills/dynamic-agents
```

## Requires

- Optional: the [Codex CLI plugin](https://github.com/openai/codex) (`codex:codex-rescue` agent type) with a Codex subscription, for the cross-model GPT review tier. Without it the skill falls back to the session model for review passes.
