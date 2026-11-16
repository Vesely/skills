# Codex binding

Native interface: `spawn_agent` and its companions (`wait_agent`, `followup_task`, `send_message`, `interrupt_agent`, `list_agents`; namespaced `collaboration.*` in CLI 0.169). Names and parameters have changed between Codex releases — read your live schema and adapt. If `delegate_task` is also present, read [t3-code.md](t3-code.md) too; where it differs, it wins.

| Role | Call |
|---|---|
| Session model | `spawn_agent`, no `model` |
| Cheap tier | `spawn_agent` with `fork_turns: "none"`, `model:` the model your catalog describes as the fast, affordable one for easier tasks (`gpt-6-luna` in Nov 2026), and an explicit `reasoning_effort`. If no description marks one clearly, inherit. |
| Read-only recon | an `agent_type` whose config in `~/.codex/agents/*.toml` sets `sandbox_mode = "read-only"`. A role name alone proves nothing — check the file. |
| Peer reader | none is bound here. If your catalog clearly describes a second top-tier reasoning model, use it; otherwise an inherited child with `fork_turns: "none"` (fresh context), labelled as such. |
| Cross-family reader | Claude through the Claude Code CLI, one read-only shot (below) |
| Parallel children | several `spawn_agent` calls, then `wait_agent` |
| Scripted pipeline | none — you run the phases yourself |
| Follow-up with context | `followup_task` (starts a turn); `send_message` only adds context |
| Team | children you keep and drive with `followup_task` across rounds |
| Separate checkout | none on `spawn_agent`; children share your directory. Prefer disjoint ownership or sequential writes. An independent `codex exec --worktree` session is the fallback (see below), and you merge it back. |
| Stop a child | `interrupt_agent` stops its current turn. There is no close call: a child that has reported needs nothing more. |

- Context: `fork_turns` defaults to `"all"`, which hands the child your whole conversation and rejects `model` and `reasoning_effort` overrides. Route with `fork_turns: "none"` and a self-contained brief. Use `"all"` only for an inherited child that truly needs the history.
- Concurrency is capped per session (four agents including you was observed). Check the limit and fan out in waves that fit it.
- `spawn_agent` has no per-call sandbox. When no read-only agent config fits, either run that leg as `codex exec --sandbox read-only` or say in the plan that the child is read-only by instruction only.
- A separate `codex exec` session (`--sandbox read-only`, `--worktree`) loads its own config, not your runtime settings: pass the working directory, `--model` and `-c 'model_reasoning_effort="..."'` explicitly.
- Cross-family review, with the diff or file paths in the brief:

  ```sh
  claude -p --model <claude-model> --effort high --tools "Read,Grep,Glob" \
    --strict-mcp-config --permission-mode plan --no-session-persistence \
    --output-format json < review-brief.txt
  ```

  The tool list is what keeps it read-only. For `--model`, the aliases `fable` and `opus` resolve to the newest of that line; Fable ranks above Opus, and neither Sonnet nor Haiku is a frontier reader. In the JSON, `result` is the review and the keys of `modelUsage` are the model that actually ran — report that ID, not the alias. If `claude` is not installed or not logged in, the cross-family reader is unavailable: apply the fallback in SKILL.md §2.
