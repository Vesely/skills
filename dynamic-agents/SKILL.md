---
name: dynamic-agents
description: Orchestrate a complex task across multiple agents with cost-aware model routing. Decomposes the task, routes each subtask to the cheapest model that handles it well (session model for hard work, Sonnet for mechanical work, GPT-5.5 or newer via Codex CLI for cross-model review), picks fan-out vs team topology, presents the plan (waiting for approval only on large or atypical runs), then executes. Use whenever the user invokes /dynamic-agents, says "dynamic agents" or "fan out dynamic", or hands over a large multi-part task (feature spanning several subsystems, audit, migration, research plus implementation) and wants top-tier quality at reasonable cost.
---

# Dynamic Agents

Top-tier output quality with deliberate cost control: the orchestrator (you) and all judgment-heavy work stay on the session's strongest model, mechanical work goes to Sonnet, and a second model family (GPT-5.5 or newer, via the Codex CLI) is used where it genuinely adds value.

## 1. Decompose

Break the task into subtasks with explicit boundaries: input, required output, what not to touch. Subagents see none of the conversation, so every prompt must be self-contained (paths, constraints, output format). Classify each subtask as judgment-heavy, mechanical, or second-opinion before routing.

## 2. Route models

| Tier | Use for | How |
|---|---|---|
| Session model (inherit) | design, architecture, synthesis, non-trivial implementation, debugging, final decisions, anything ambiguous | omit `model` |
| Sonnet | mechanical work with a clear spec: codebase searches, fact gathering, research with a defined question, scraping/data extraction, scripted browser/device QA (explicit steps and pass criteria), low-risk well-specified single-file edits, format conversions, boilerplate from an existing pattern | `model: "sonnet"` |
| GPT-5.5+ via Codex CLI | cross-model code review, second opinion on a diagnosis, getting unstuck, copywriting drafts | `subagent_type: "codex:codex-rescue"` (Agent tool) or `agentType: 'codex:codex-rescue'` (Workflow) |

- Never set a model for judgment-heavy work. Inheriting keeps it on the session default, with nothing to maintain when the user upgrades models.
- Be conservative about "mechanical": a non-trivial task misrouted to Sonnet costs more in rework than it saves. When unsure, inherit.
- Codex sees no conversation context and is an external CLI, not a `model:` value. Inline everything it needs: the task, the actual diff or file contents (not just paths when the work is review), constraints, output format. The exact model comes from Codex CLI configuration, but it must be GPT-5.5 or newer; when uncertain, check the config (e.g. `~/.codex/config.toml`) rather than asking the model, which misreports its version. Never pass a `--model` override (specialized variants like gpt-5-codex are not the preferred mainline model); if the configured model is older than GPT-5.5, say so and route that pass to an inherited-model agent instead. It bills to the user's Codex subscription, outside API metering.
- If `codex:codex-rescue` is unavailable (plugin not installed), route that pass to an inherited-model agent instead and note the substitution in the plan.
- Cross-model review is a quality tool, not only a cost tool: a different model family finds different issues. Default to one Codex review pass (one round, not a review-fix-review loop) on any substantial implementation this skill produces — multi-file changes, migrations, security-sensitive code — and list it as a row in the checkpoint plan.

## 3. Pick topology

Default to phased fan-out (understand, design, implement, review) with you synthesizing between phases. Use the Agent tool for up to ~4 agents; use the Workflow tool when orchestration genuinely needs structure (pipelines, loops, verification rounds, many parallel branches) — explicit invocation of this skill, or the user's approval of a plan that names Workflow, counts as their explicit Workflow opt-in. Use a team (TeamCreate + SendMessage) only when roles must persist and message each other across multiple rounds; everywhere else a team is overhead, and "the subtasks are different roles" is not a reason. Give parallel mutating agents disjoint file ownership; use `isolation: "worktree"` only when overlapping writes are unavoidable.

## 4. Show the plan, gate only what's risky

Always present a compact plan before launching — it costs nothing and lets the user catch a misrouted subtask cheaply:

```
| # | Subtask | Topology | Model | Why this tier |
```

plus one line on phases and total agent count. For a small, typical plan (a handful of agents, fan-out only, no file mutation), launch right after showing it. Wait for explicit approval only when:

- the scale is large or open-ended: more than ~5 agents, Workflow loops, unknown-size discovery
- the topology is atypical: a team, worktrees, parallel file mutation
- the skill auto-triggered from task phrasing rather than being explicitly invoked — approval then also serves as the user's Workflow opt-in
- the decomposition surfaced a question only the user can answer

## 5. Execute, synthesize, verify

Launch independent agents in parallel (one message, multiple Agent calls; or Workflow `parallel`/`pipeline`). Synthesize results yourself on the session model; never delegate the final integration or the user-facing summary. Verify before reporting: a Codex cross-model review pass for code (fix confirmed findings yourself or via an inherited-model agent), adversarial verification for surprising research or audit findings. Report what was NOT covered (skipped areas, unverified claims) instead of letting truncation read as completeness.
