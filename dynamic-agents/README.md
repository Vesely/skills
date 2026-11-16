# dynamic-agents

Orchestrate a large task across multiple agents with cost-aware model routing. Decomposes the task, routes each subtask to the cheapest model that handles it well (session model for judgment-heavy work, a cheaper model of the same family for mechanical work, a peer model or the other vendor's frontier model for the hardest nodes and cross-model review), picks fan-out vs team topology, presents the plan (gating on approval only for large or atypical runs), then executes and verifies.

Works in Claude Code, Codex and T3 Code. The method lives in `SKILL.md`; `harness/` binds its roles to each harness's real tools, and the skill reads only the file that matches the tools it has.

## Install

```
npx skills@latest add Vesely/skills/dynamic-agents
```

## Requires

- Optional, for the cross-model review tier:
  - Claude Code: the [Codex CLI plugin](https://github.com/openai/codex) (`codex:codex-rescue` agent type) with a Codex subscription.
  - Codex: the Claude Code CLI (`claude`), logged in.
  - T3 Code: both providers enabled; the skill uses `delegate_task`.

  Without it, Claude Code and Codex fall back to a same-family review and say so; T3 Code stops that review and asks which model to use instead.
