# Claude Code binding

Native interface: the `Agent` tool. If `delegate_task` is also present, read [t3-code.md](t3-code.md) too; where it differs, it wins.

| Role | Call |
|---|---|
| Session model | `Agent`, omit `model` |
| Cheap tier | `model: "sonnet"`. Never Haiku. |
| Read-only recon | `subagent_type: "Explore"` — cannot edit files. For a read-only review or design pass, `Plan` or another listed agent type whose tools exclude Edit and Write. |
| Peer reader | `model: "fable"`. Always resolves to the newest Fable — never pin a version. If the session model is already Fable, inherit instead. |
| Cross-family reader | GPT through the Codex plugin: `subagent_type: "codex:codex-rescue"` (Agent) or `agentType: 'codex:codex-rescue'` (Workflow) |
| Parallel children | several `Agent` calls in one message |
| Blocking child | `run_in_background: false` |
| Scripted pipeline | the `Workflow` tool (`parallel` / `pipeline`), when your tool list has it; user opt-in required |
| Follow-up with context | `SendMessage({to: name})` to a child spawned with `name:` |
| Team | named background agents (`Agent` with `name:`) coordinated with `SendMessage` |
| Separate checkout | `isolation: "worktree"` |
| Stop a child | `TaskStop` |

- Children see none of the conversation.
- Codex is an external CLI behind the plugin, not a `model:` value, and it cannot be assumed to read your working tree state: inline the diff or file contents when the work is review. Resolve the latest GPT frontier model from the current Codex catalog available to the account; if needed, check current official OpenAI guidance and confirm Codex availability. Pass the verified exact ID with `--model` in the rescue request.
- If `codex:codex-rescue` is not installed, the cross-family reader is unavailable: apply the fallback in SKILL.md §2.
- Children run in the background by default. A child you waited on (`run_in_background: false`) is finished when it returns: nothing to stop, and `SendMessage` to its agent id still reaches it for a fix. A background child does not exit on reporting; it goes idle and stays listed until the session ends, so a fan-out that skips cleanup leaves every worker parked in the agent list. A research or fetch child is done once its result is collected and verified: `TaskStop` it then. Keep an implementer alive through the cross-family review and your fix requests, and stop it afterwards. The same applies to team members after the last round, and to any child whose truncated report you still need to ask for.
