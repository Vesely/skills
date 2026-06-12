# dynamic-agents

Orchestrate a complex task across multiple agents with cost-aware model routing. Decomposes the task, routes each subtask to the cheapest model that handles it well (session model for judgment-heavy work, Sonnet for mechanical work, GPT-5.5+ via Codex CLI for cross-model review), picks fan-out vs team topology, and presents a checkpoint plan for approval before spending tokens.

## Install

```
npx skills@latest add Vesely/skills/dynamic-agents
```

## Requires

- Optional: the [Codex CLI plugin](https://github.com/openai/codex) (`codex:codex-rescue` agent type) with a Codex subscription, for the cross-model GPT review tier. Without it the skill falls back to the session model for review passes.
