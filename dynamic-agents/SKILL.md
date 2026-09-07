---
name: dynamic-agents
description: Orchestrate a large task across multiple agents with cost-aware model routing — session model for judgment-heavy work, Sonnet for mechanical work, Fable or GPT-5.6-sol-and-newer via Codex CLI for the hardest nodes and cross-model review. Decomposes, routes, picks fan-out vs team topology, presents the plan, executes, and verifies. Use when the user invokes /dynamic-agents, says "dynamic agents" or "fan out dynamic", explicitly asks to parallelize or split work across agents or models, or hands over a task too big for one agent pass (multi-subsystem feature, repo-wide audit or migration, research plus implementation) whose subtasks are independent enough to run in parallel. NOT for tasks one agent can finish inline, even multi-file ones.
---

# Dynamic Agents

Top-tier output at controlled cost: you and all judgment-heavy work stay on the session model, mechanical work drops to Sonnet, and a second model (Fable, or GPT via Codex) is used on the nodes, and only the nodes, where an independent read genuinely earns its cost. Multiple agents buy quality two ways — parallelism for reach, a second model for an independent read — never as a reflex.

## 1. Decompose

Break the task into subtasks with explicit boundaries: input, required output, what not to touch. Subagents see none of the conversation, so every prompt must be self-contained (paths, constraints, output format). Classify each subtask as judgment-heavy, mechanical, or second-opinion before routing.

## 2. Route models

| Tier | Use for | How |
|---|---|---|
| Session model (inherit) | design, architecture, synthesis, non-trivial implementation, debugging, final decisions, anything ambiguous | omit `model` |
| Sonnet | mechanical work with a clear spec: codebase searches, fact gathering, research with a defined question, scripted browser/device QA (explicit steps and pass criteria), low-risk well-specified single-file edits, boilerplate from an existing pattern | `model: "sonnet"` |
| Fable (latest) | a different reader rather than more of the same: design or architecture review, "is there a simpler implementation than this", a fresh read on a node the session model is stuck on, a second opinion inside the Claude family distinct from Codex | `model: "fable"` |
| GPT-5.6-sol+ via Codex CLI | cross-model code review, second opinion on a diagnosis, getting unstuck, copywriting drafts | `subagent_type: "codex:codex-rescue"` (Agent tool) or `agentType: 'codex:codex-rescue'` (Workflow) |

- Never set a model for ordinary judgment-heavy work. Inheriting keeps it on the session default, with nothing to maintain when the user upgrades models.
- Be conservative about "mechanical": a non-trivial task misrouted to Sonnet costs more in rework than it saves. When unsure, inherit. Sonnet is the floor — never route to Haiku; its failure rate on multi-step repo work erases the savings. Route read-only recon with `subagent_type: "Explore"` so it can't accidentally write.
- Unless the session model is already Fable (then inherit — there is nothing to gain), Fable is the standing pick for the nodes in that row, not a last resort: the model that wrote something shares its blind spots when it reviews it, so review and second opinion go to a different reader. `model: "fable"` always resolves to the newest Fable — never pin a version. Cap it hard: at most two Fable nodes per skill invocation, and at most one of those a first-pass node, taken only where a wrong answer is expensive to unwind. Never route to Fable because work is long, touches many files, or is repetitive. If more nodes qualify, consolidate them or leave the rest inherited. If a `model: "fable"` agent fails to start, re-run that node inherited and say so in the results.
- Codex sees no conversation context and is an external CLI, not a `model:` value. Inline everything it needs: the task, the actual diff or file contents (not just paths when the work is review), constraints, output format. The exact model comes from Codex CLI configuration, but it must be GPT-5.6-sol or newer; when uncertain, check the config (e.g. `~/.codex/config.toml`) rather than asking the model, which misreports its version. Never pass a `--model` override (specialized variants like gpt-5-codex are not the preferred mainline model); if the configured model is older than GPT-5.6-sol, say so and route that pass to an inherited-model agent instead (it bills to the user's Codex subscription).
- If `codex:codex-rescue` is unavailable (plugin not installed), route that pass to an inherited-model agent instead and note the substitution in the plan.
- Cross-model review is a quality tool, not only a cost tool: a second model finds different issues. Split the two passes by phase and objective, as routing defaults rather than capability exclusions. Codex reviews an implementation after it exists — correctness, edge cases, security, tests — and needs the diff inlined; §5 filters its findings. Fable reviews the approach before code exists, or when review is the task itself (a design, an existing subsystem, a "simpler than this?" question), where it runs as a normal agent with repo access. Both can appear on a substantial change, in different phases; never two passes over the same diff. Default to one Codex review pass (one round, not a review-fix-review loop) on any substantial implementation this skill produces — multi-file changes, migrations, security-sensitive code — and list it as a row in the checkpoint plan.

## 3. Pick topology

Default to phased fan-out (understand, design, implement, review) with you synthesizing between phases — but do the light phases yourself: don't spin up an agent for recon that is three greps, or a design that is a paragraph. A subtask earns its own agent only when doing the work costs more than writing its self-contained brief. Batch small units (4-6 scanners over 40 files, not 40 agents).

Use the Agent tool for up to ~4 agents; use the Workflow tool when orchestration genuinely needs structure (pipelines, loops, verification rounds, many parallel branches). Any Workflow use needs the user's opt-in — their approval of a plan that names Workflow is that opt-in. Use a persistent team only when roles must message each other across multiple rounds: spawn each role as a named background agent (`Agent` with `name:`) and coordinate with `SendMessage({to: name})`. Everywhere else a team is overhead, and "the subtasks are different roles" is not a reason.

Give parallel mutating agents disjoint file ownership, and reserve cross-cutting touchpoints (route registries, barrel files, menus, shared config, lockfiles) for a single agent or your own synthesis step — that is where "disjoint" plans actually collide. Use `isolation: "worktree"` only when overlapping writes are unavoidable, and plan the merge: you integrate each worktree back sequentially yourself, or it's a silently dropped subtask.

## 4. Show the plan, gate only what's risky

Always present a compact plan before launching — it costs nothing and lets the user catch a misrouted subtask cheaply:

```
| # | Subtask | Topology | Model | Why this tier |
```

plus one line on phases and total agent count. For a small, typical plan (a handful of agents, fan-out only, no file mutation), launch right after showing it. Wait for explicit approval only when:

- the scale is large or open-ended: more than ~10 agents, Workflow loops, unknown-size discovery
- the plan uses the Workflow tool at all — approval is the user's Workflow opt-in (skip only if they already named Workflow)
- the topology is atypical: a team, worktrees, parallel file mutation
- the skill auto-triggered from task phrasing rather than being explicitly invoked
- the decomposition surfaced a question only the user can answer

## 5. Execute, synthesize, verify

Launch independent agents in parallel (one message, multiple Agent calls; or Workflow `parallel`/`pipeline`). Agents run in the background — never predict or fabricate a pending agent's output; synthesize a phase only once every agent in it has reported. Run one with `run_in_background: false` when it blocks the next step.

If an agent dies, returns empty, or only partially finishes: retry once with a sharper, more self-contained brief. If it failed on the Sonnet tier, re-run inherited rather than retrying Sonnet — misrouting, not flakiness, is the usual cause. Never silently absorb a failed subtask; it goes in the NOT-covered list, and partial results ship only with an explicit note of what's missing.

Synthesize results yourself on the session model; never delegate the final integration or the user-facing summary. Verify in your own loop — re-read the code or evidence behind every surprising finding yourself before reporting it; do not spawn verifier agents (the harness rightly discourages that). The one paid exception is the single Codex cross-model review pass on substantial code: treat its findings as bug reports, not verdicts — confirm each against the code and drop style objections that fight repo conventions. Fix confirmed findings by `SendMessage`-ing the original implementer (its context is intact, so a two-line request beats a full re-brief), or yourself. Report what was NOT covered (skipped areas, unverified claims) instead of letting truncation read as completeness.
