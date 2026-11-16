# T3 Code overlay

`delegate_task` adds a second way to start a child: its own thread, on any provider and model in the catalog. It sits on top of your native binding ([claude-code.md](claude-code.md) or [codex.md](codex.md)). T3's own instructions in your system prompt win over this file.

Which call for which child:

| Child | Call |
|---|---|
| Same provider as you, a model your native tool offers, no extra settings | native tool, waited on in this turn (Claude: `Agent` with `run_in_background: false`, several in one message; Codex: `spawn_agent`, then wait) |
| Another provider's model — the cross-family reader | `delegate_task` with `target.providerInstanceId` and `target.model` |
| A setting the user asked for, or one the native tool cannot give (effort, service tier) | `delegate_task` with `target.options` |
| The user asked for `delegate_task` by name | `delegate_task` |
| Must run in the background | `delegate_task` (default `mode: "async"`), never a background native child |
| Separate checkout | `delegate_task` with `isolation: "worktree"` |

- Call `orchestrator_capabilities` once, before the first `delegate_task`. It is the catalog: take the cross-family model ID and its option names from there (`reasoningEffort` for Codex, `effort` for Claude) and set the effort explicitly. Skip disabled provider instances. The catalog lists models without ranking them: settle the frontier pick as SKILL.md §2 says (in the Claude family, Fable ranks above Opus). A plan with no `delegate_task` in it needs no catalog call.
- This replaces the native cross-family route: no `codex:codex-rescue` plugin from a Claude session, no `claude -p` from a Codex session.
- A delegate gets only `task` — no history. It can read the repo, so paths are enough in a shared checkout. A `worktree` child starts from the parent commit and does not see uncommitted edits: commit first or inline the diff. `role` and `runtimeMode` do not make a child read-only; say so if it matters.
- Completion wakes your thread. Follow the `next` field the call returns: do other work, do not poll or sleep, and end the turn when nothing else is left.
- Fix small confirmed review findings yourself. A re-check or a second review is a new `delegate_task` with the brief, the findings and your objections — not a message into the old child thread.
- A larger fix goes back to the implementer that still has the context: `t3_thread_send` to its `childThreadId`, without `freshContext`, and keep the `taskId` it returns. Native children keep whatever follow-up your native file gives them.
- A finished delegate needs no cleanup, and neither does a native child you waited on. Cancel a delegate you replace or no longer need with `task_cancel`.
- If the provider or model you planned is unavailable, say so and stop that leg; do not switch provider or fall back on your own, not even to the same-family fallback in SKILL.md §2. Offer what else the catalog has and let the user choose.
- Scripted pipelines (`Workflow`) only when the user asked for one.
- When the plan needs approval, make sure the user can read all of it before you ask (`send_to_user` if you have it).
