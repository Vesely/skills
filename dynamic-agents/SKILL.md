---
name: dynamic-agents
description: Orchestrate a large task across multiple agents with cost-aware model routing — session model for judgment-heavy work, a cheaper model of the same family for mechanical work, a peer model or the other vendor's frontier model for the hardest nodes and cross-model review. Works in Claude Code, Codex and T3 Code. Decomposes, routes, picks fan-out vs team topology, presents the plan, executes, and verifies. Use when the user invokes /dynamic-agents, says "dynamic agents" or "fan out dynamic", explicitly asks to parallelize or split work across agents or models, or hands over a task too big for one agent pass (multi-subsystem feature, repo-wide audit or migration, research plus implementation) whose subtasks are independent enough to run in parallel. NOT for tasks one agent can finish inline, even multi-file ones.
---

# Dynamic Agents

Top-tier output at controlled cost: you and all judgment-heavy work stay on the session model, mechanical work drops to a cheaper model, and a second model is used on the nodes, and only the nodes, where an independent read genuinely earns its cost. Multiple agents buy quality two ways — parallelism for reach, a second model for an independent read — never as a reflex.

The method is the same in every harness; the tools are not. §1–§5 speak in roles (spawn a child, cheap tier, cross-family reader). Bind them to real tools first.

## 0. Bind to your harness

Look at your tool list and read the matching file before planning. Deferred tools and prefixed names count (`mcp__t3-code__delegate_task` is `delegate_task`). Your live tool schemas win over anything these files say.

| You have | Read |
|---|---|
| an `Agent` tool | [harness/claude-code.md](harness/claude-code.md) |
| a `spawn_agent` tool | [harness/codex.md](harness/codex.md) |
| `delegate_task` and `orchestrator_capabilities` | also [harness/t3-code.md](harness/t3-code.md) — an overlay on the native file above, not a replacement |
| none of these | no children available: do the task inline and say so |

Plan only tools, agent types and model IDs that exist in your tool list or catalog — a harness file naming one does not make it exist, and nothing carries over from another harness's file. A role your harness cannot fill is dropped or filled by the fallback the file names, and the plan says which.

## 1. Decompose

Break the task into subtasks with explicit boundaries: input, required output, what not to touch. Write every brief as if the child sees none of the conversation (paths, constraints, output format) — in most harnesses it does not, and where it can inherit history, a self-contained brief is still what keeps a cheap child on task. Classify each subtask as judgment-heavy, mechanical, or second-opinion before routing.

## 2. Route models

| Tier | Use for |
|---|---|
| Session model (inherit) | design, architecture, synthesis, non-trivial implementation, debugging, final decisions, anything ambiguous |
| Cheap tier — the affordable current model of the session's family | mechanical work with a clear spec: codebase searches, fact gathering, research with a defined question, scripted browser/device QA (explicit steps and pass criteria), low-risk well-specified single-file edits, boilerplate from an existing pattern |
| Peer reader — a different top model of the session's family | a different reader rather than more of the same: design or architecture review, "is there a simpler implementation than this", a fresh read on a node the session model is stuck on |
| Cross-family reader — the other vendor's frontier model (GPT for a Claude session, Claude for a GPT session) | cross-model code review, second opinion on a diagnosis, getting unstuck, copywriting drafts |

Your harness file names the model and the call for each tier.

- Never set a model for ordinary judgment-heavy work. Inheriting keeps it on the session default, with nothing to maintain when the user upgrades models.
- Be conservative about "mechanical": a non-trivial task misrouted to the cheap tier costs more in rework than it saves. When unsure, inherit. A scan against a stated rule ("which handlers skip this middleware?") is still mechanical when its hits need judgment — you confirm them yourself in §5. The cheap tier is the floor — never route below it to a mini-class model; its failure rate on multi-step repo work erases the savings. Give read-only recon a child that cannot write, where the harness can enforce that; where it cannot, say the child is read-only by instruction only.
- The peer reader is the standing pick for the nodes in that row, not a last resort: the model that wrote something shares its blind spots when it reviews it. Where the family has no distinct peer (or the session already runs on it), use an inherited child with a fresh context and call it that — a weaker independence, not a second model. Cap peer nodes hard: at most two per skill invocation, and at most one of those a first-pass node, taken only where a wrong answer is expensive to unwind. Never route to the peer because work is long, touches many files, or is repetitive. If more nodes qualify, consolidate them or leave the rest inherited. If a peer child fails to start, re-run that node inherited and say so in the results.
- The cross-family reader gets no conversation context. Give it everything it needs: the task, the diff or file contents (paths are enough only when it can read the repo itself), constraints, output format. Pick the model the current catalog identifies as that vendor's frontier or flagship for reasoning quality, not a fast or lightweight variant; do not infer recency from ID sorting or assume a configured default is current. When the catalog marks none, check the vendor's current model guidance. If that still does not settle it, run the pass on the best candidate the catalog has and report it as a cross-family review on an unverified pick, not as a frontier review; ask the user to choose only when the plan is gated anyway. Pass the model explicitly, set reasoning effort explicitly where the harness has the option (`high` for a review; defaults are often low), confirm from the run's own metadata which model ran, and report the ID and where the choice came from.
- If the cross-family reader is unavailable, never present a same-family pass as a cross-model review. If the harness offers another cross-family provider, name it in the plan and wait for the user's choice. Otherwise run the pass on an inherited fresh-context child and disclose the substitution in the plan and the results.
- Cross-model review is a quality tool, not only a cost tool: a second model finds different issues. Split the two reader passes by phase and objective, as routing defaults rather than capability exclusions. The cross-family reader reviews an implementation after it exists — correctness, edge cases, security, tests; §5 filters its findings. The peer reader reviews the approach before code exists, or when review is the task itself (a design, an existing subsystem, a "simpler than this?" question), with repo access. Both can appear on a substantial change, in different phases; never two passes over the same diff. Default to one cross-family review pass (one round, not a review-fix-review loop) on any substantial implementation this skill produces — multi-file changes, migrations, security-sensitive code — and list it as a row in the checkpoint plan.

## 3. Pick topology

Default to phased fan-out (understand, design, implement, review) with you synthesizing between phases — but do the light phases yourself: don't spin up an agent for recon that is three greps, or a design that is a paragraph. A subtask earns its own agent only when doing the work costs more than writing its self-contained brief. Batch small units (4-6 scanners over 40 files, not 40 agents), and run them in waves when the harness caps concurrent children.

Spawn children directly for up to ~4 agents. Use a scripted pipeline tool, where the harness has one, only when orchestration genuinely needs structure (pipelines, loops, verification rounds, many parallel branches); it needs the user's opt-in — their approval of a plan that names it is that opt-in. Use a persistent team only when roles must message each other across multiple rounds and the harness lets you follow up with a live child; otherwise run rounds of fresh children and carry the state between them yourself. Everywhere else a team is overhead, and "the subtasks are different roles" is not a reason.

Give parallel mutating agents disjoint file ownership, and reserve cross-cutting touchpoints (route registries, barrel files, menus, shared config, lockfiles) for a single agent or your own synthesis step — that is where "disjoint" plans actually collide. Use a separate checkout per child only when overlapping writes are unavoidable, and plan the merge: you integrate each checkout back sequentially yourself, or it's a silently dropped subtask.

## 4. Show the plan, gate only what's risky

Always present a compact plan before launching — it costs nothing and lets the user catch a misrouted subtask cheaply:

```
| # | Subtask | Topology | Model | Why this tier |
```

plus one line on phases, total agent count, and the harness binding you resolved. For a small, typical plan (a handful of agents, fan-out only, no file mutation), launch right after showing it. Wait for explicit approval only when:

- the scale is large or open-ended: more than ~10 agents, pipeline loops, unknown-size discovery
- the plan uses a scripted pipeline tool at all (skip only if the user already named it)
- the topology is atypical: a team, separate checkouts, parallel file mutation
- the skill auto-triggered on a task whose user never asked for agents (naming the skill, or asking to split or fan out the work, is an explicit invocation)
- the decomposition surfaced a question only the user can answer, including which provider replaces an unavailable cross-family reader (§2)

A user who already approved this plan, or said to proceed without asking, has answered: show the plan and launch. A user who asked only for a plan gets the plan, and you stop.

## 5. Execute, synthesize, verify

Launch independent children in parallel. Never predict or fabricate a pending child's output; synthesize a phase only once every child in it has reported. Wait on a child directly when it blocks the next step.

If a child dies, returns empty, or only partially finishes: retry once with a sharper, more self-contained brief. If it failed on the cheap tier, re-run inherited rather than retrying cheap — misrouting, not flakiness, is the usual cause. Never silently absorb a failed subtask; it goes in the NOT-covered list, and partial results ship only with an explicit note of what's missing.

Synthesize results yourself on the session model; never delegate the final integration or the user-facing summary. Verify in your own loop — re-read the code or evidence behind every surprising finding yourself before reporting it; do not spawn verifier agents. The one paid exception is the single cross-family review pass on substantial code: treat its findings as bug reports, not verdicts — confirm each against the code and drop style objections that fight repo conventions. Fix confirmed findings by following up with the original implementer where the harness keeps its context (a two-line request beats a full re-brief), or yourself. Report what was NOT covered (skipped areas, unverified claims) instead of letting truncation read as completeness.

Leave no child running or parked once you are done with it; your harness file says whether that takes an explicit stop. An implementer is done only after the cross-family review and any fix requests you sent it have landed.
