---
name: handoff-to-worktree
description: >
  Packages the current chat (or one or more specific issues/topics) into
  self-contained handoff files and launches each in its own fresh `claude`
  session with a dedicated, meaningfully named git worktree — so work continues
  without manual context copy-paste. Each child claude inherits the CALLER
  session's permission mode (no hardcoded bypass). Requires cmux: by default each
  handoff opens as a new cmux workspace; with `--tabs` (or "in this/the same
  workspace", "as tabs") they open as tabs in the current workspace. Use when the
  user wants to hand off work to a fresh Claude in its own worktree instead of
  continuing inline. Trigger phrases: "handoff to worktree",
  "handoff-to-worktree", "spin this off into its own claude", "fork this into a
  worktree", "run it in a separate claude". No argument = handoff the whole chat
  (one worktree); argument(s) = one handoff/worktree per issue or topic.
argument-hint: "[--tabs] [issue-code|topic ...]  (empty = whole chat; --tabs = tabs in the current workspace)"
arguments:
  - target
  - placement
---

# Handoff to worktree

Packages context (the whole chat, or a specific issue/topic) into a self-contained
handoff file in the OS temp dir, and for each handoff launches a fresh `claude`
with its own meaningfully named git worktree and an opening prompt that loads the
handoff and continues the work. No manual copy-paste of context.

**Permissions — inherit the caller, never hardcode a bypass.** The child claude
must run with the SAME permission posture as the session this skill runs in. If
the caller bypasses permissions, the child does too; if the caller runs in normal
(prompted) mode, the child prompts too. See step 4 for how to detect it.

**Placement (where the child claude opens):**
- **Default — a new workspace per handoff** (`cmux new-workspace --command …`).
  Each handoff is its own workspace in the sidebar.
- **`--tabs` — new tabs in the current workspace.** When the user says "in the
  same / in this workspace", "as tabs", or passes `--tabs`, open each handoff as a
  new terminal surface (tab) in the **caller's** workspace (`new-surface` + `send`
  + `send-key Enter`, see step 4b).

MUST run inline — it needs the context of the current conversation. Do not fork.

## Requirements

- **cmux** (the launch mechanism — `new-workspace`, `new-surface`, `send`).
- A **git repository** with worktree support (`claude --worktree`).

## Inputs

- `$target`: (Optional) One or more issue codes or topics (e.g. `ABC-123` or
  `cache invalidation`). Empty = handoff of the whole chat (one worktree).
- `$placement`: (Optional) Default = a new **workspace** per handoff. If the user
  passes `--tabs` (or says so verbally, see above), open the handoffs as **tabs in
  the current workspace**. Treat `--tabs` as a mode switch, NOT as an issue/topic.

## Goal

Each handoff produces: (1) a self-contained `.md` in the OS temp dir, and (2) a
running fresh claude with its own worktree — either as a new workspace (default) or
as a new tab in the current workspace (`--tabs`).

## Steps

### 1. Determine scope, placement, and build the handoff list

- **Placement**: default = a new workspace per handoff (4a). If the arguments
  contain `--tabs`, or the user said so verbally, switch to tabs in the current
  workspace (4b) and drop `--tabs` from `$target`.
- No `$target` → one handoff = the whole chat.
- With `$target` → one handoff per issue/topic (there can be several at once).
- For each, derive a **meaningful kebab-case worktree name** (short, descriptive;
  if an issue code exists, include its short form — e.g. `abc-123-auth-retry`,
  `cache-invalidation`). Slug = `[a-z0-9-]` only, no shell metacharacters.
- **Collision check**: the slug must NOT be in `git worktree list` AND no directory
  `$REPO/.claude/worktrees/<slug>` may exist (verify with `test -d`). On collision
  add a short suffix (`-2`, `-3`) — never overwrite an existing worktree.
- Keep `label` (for `cmux --name`) short, ASCII, no quotes/`$`/backticks/newline.

**Success criteria**: You have the placement (workspace vs `--tabs`) and a list of
`{label, slug, temp-path}` for each handoff; every slug is unique and
collision-free.

### 2. Write the handoff file(s) to the OS temp dir

For each item, write an `.md` to the OS temp dir with a unique name so an older
handoff isn't overwritten:
`${TMPDIR:-/tmp}/handoff-<slug>-$(date +%Y%m%d-%H%M%S).md`.

Outline:
- **Whole chat**: a compact summary of the conversation for a fresh agent + a
  "Suggested skills" section. Don't duplicate content already captured elsewhere
  (plan, PR description, commit, diff) — link to it by path/URL.
- **Issue/topic**: a self-contained assignment — link to the issue (tracker URL),
  what's being asked, what's already verified / what is NOT the cause, a root-cause
  hypothesis, candidate files with line numbers, recommended approach, and
  suggested skills.
- **Redact PII** (emails, personal names). Keep internal IDs (record/entity IDs) —
  they're needed to reproduce.
- Carry over any **project constraints** that live in the repo's `CLAUDE.md` or the
  user's global preferences (e.g. required checks before committing, edit-scope
  rules, writing conventions). Reference them; don't invent project-specific ones.

**Success criteria**: Each handoff file is readable standalone, without knowledge
of this chat.
**Artifacts**: absolute paths to the handoff files.

### 3. Confirm the plan [human checkpoint]

Via `AskUserQuestion`, show the list: which handoffs + worktree names will be
created, the **placement** (new workspaces vs tabs), the **permission mode** the
children will inherit (step 4), and how many claude instances will launch.
Launching multiple claude instances costs tokens — let the user confirm or adjust
names/scope/placement.

**Success criteria**: The user approved the plan.
**Human checkpoint**: Always, before spawning.

### 4. Launch claude + worktree per handoff

**Find the canonical root of the main repo** (not the worktree you may be running
in):

```bash
REPO=$(dirname "$(git rev-parse --git-common-dir)")
```

When you run inside `.claude/worktrees/<something>`, this returns the original repo
root; `git rev-parse --show-toplevel` would return the worktree path (wrong).

**Detect the caller's permission posture — do NOT hardcode `--dangerously-skip-permissions`.**
cmux records the current claude's launch argv (null-separated) in
`CMUX_AGENT_LAUNCH_ARGV_B64`. Decode it and reuse the same permission flag for the
child:

```bash
PERM=""
ARGV=$(printf '%s' "${CMUX_AGENT_LAUNCH_ARGV_B64:-}" | base64 -d 2>/dev/null | tr '\0' ' ')
case " $ARGV " in
  *" --dangerously-skip-permissions "*)
    PERM="--dangerously-skip-permissions" ;;
  *--permission-mode*)
    PERM="--permission-mode $(printf '%s' "$ARGV" | sed -E 's/.*--permission-mode[ =]+([A-Za-z]+).*/\1/')" ;;
esac
# Empty PERM → the caller runs in normal (prompted) mode → the child prompts too.
echo "PERM=${PERM:-<none, prompted mode>}"   # read this value, then substitute it literally below
```

Now substitute the detected `PERM` **literally** into the launch command below
(use the concrete value, e.g. `--dangerously-skip-permissions`,
`--permission-mode plan`, or nothing when empty). If `CMUX_AGENT_LAUNCH_ARGV_B64`
is unset and you can't tell, default to **no** bypass flag (safe, prompted) and say
so in step 3.

Then, per the placement (step 1), choose **4a** (default) or **4b** (`--tabs`).
With multiple handoffs, launch **sequentially with a short pause** (`sleep 6-8`)
between them and `--focus false` — a burst of fresh claude instances at once can
overload cmux. Verify after each (step 5).

#### 4a. Default — a new workspace per handoff

```bash
cmux new-workspace --name "<label>" --cwd "$REPO" --focus false \
  --command 'claude <PERM> --worktree <slug> "Read the handoff file <temp-path> and continue per its instructions. Start by reading the handoff."'
```

Gotchas (verified):
- Replace `<PERM>` with the literal flag from the detection above (omit entirely
  when empty).
- `claude -w/--worktree <name>` creates a worktree under `.claude/worktrees/<name>`.
  The positional `prompt` in `claude "…"` is sent automatically in interactive mode.
- `cmux --command` sends ONE line + Enter. Wrap the whole `claude …` in **single**
  quotes, the prompt in **double** quotes.
- `--cwd "$REPO"` (canonical root), so `--worktree` is created correctly.
- `--focus false`, so it doesn't interrupt the user.
- To keep them in the **current window**, add `--window "<current>"` (ref from
  `cmux current-window`).

**Success criteria**: `cmux new-workspace` returns `OK workspace:N` for each handoff.

#### 4b. `--tabs` — new tabs in the current workspace

`new-surface` has no `--command`, so send the command into the new terminal tab via
`send` + `send-key Enter`. First find the **caller's workspace** from `cmux
identify` (`.caller.workspace_ref`). For each handoff:

```bash
# WS = caller workspace ref from `cmux identify`; use the ABSOLUTE repo path (not $REPO — the new shell doesn't have it)
SURF=$(cmux new-surface --type terminal --workspace "$WS" --focus false | grep -oE 'surface:[0-9]+' | head -1)
cmux rename-tab --surface "$SURF" "<label>"          # optional, for clarity
sleep 2                                               # let the shell reach its prompt
cmux send --surface "$SURF" 'cd <REPO-abs> && claude <PERM> --worktree <slug> "Read the handoff file <temp-path> and continue per its instructions. Start by reading the handoff."'
cmux send-key --surface "$SURF" Enter
```

Gotchas (verified):
- Replace `<PERM>` with the literal flag from the detection above (omit when empty).
- `new-surface` returns `OK surface:N pane:M workspace:K`; capture `surface:N`.
- `send` types text **literally**; `send-key Enter` submits it (if Enter doesn't
  work, try `Return` or `C-m`).
- **Put `cd <REPO-abs>` inside** — `new-surface` has no `--cwd`; the new shell
  starts in the workspace cwd, not necessarily the repo. `claude --worktree` then
  creates the worktree itself.
- Wrap the whole `send` command in **single** quotes, the prompt in **double**
  quotes. Keep the prompt **static** (only the safe absolute `<temp-path>` varies);
  it must NOT contain `'` `"` `` ` `` `$` `\` or a newline.
- `--focus false`, so the new tab doesn't switch you away mid-work.

**Success criteria**: `read-screen --surface "$SURF"` shows a running claude; the
worktree exists (step 5).

### 5. Verify it came up

After ~10s (`sleep 10`) check:
- `git worktree list` → the new worktrees exist (primary proof, both placements).
- **4a (workspaces)**: `cmux list-workspaces` → workspace:N with the given name is
  running.
- **4b (tabs)**: `cmux list-pane-surfaces --workspace "$WS"` or `read-screen
  --surface "$SURF"` → claude is running in the tab. If the command fails, the
  surface ref + worktree existence is enough.

Report a table: issue/topic → worktree → workspace:N / surface:N → handoff path.

**Success criteria**: Worktrees exist and the claude instances are running; the
user has an overview of where everything is.

## Rules

- Inline only — without the chat context the handoff can't be assembled.
- Always a human checkpoint before spawning (step 3).
- **Inherit the caller's permission mode** (detect via `CMUX_AGENT_LAUNCH_ARGV_B64`);
  never hardcode `--dangerously-skip-permissions`. When undetectable, default to no
  bypass.
- Meaningful, unique kebab-case worktree names (`[a-z0-9-]` only). Check collisions
  before spawning (`git worktree list` + `test -d`).
- Handoff = self-contained; reference artifacts by path/URL, don't duplicate.
- Redact PII, keep internal IDs.
- `--command` (4a) / `send` (4b): claude cmd in single quotes, prompt in double
  quotes. Keep the prompt static (only the safe temp-path), without `'` `"` `` ` ``
  `$` `\` or a newline.
- `REPO` = canonical root via `dirname "$(git rev-parse --git-common-dir)"`, not
  `--show-toplevel` (it may run inside a worktree).
- Launch multiple handoffs sequentially with a `sleep` between them and
  `--focus false` (protection against overloading cmux).
