---
name: park-workspace
description: Free the RAM held by idle Claude sessions in cmux workspaces without closing the workspaces, so they stay visible as a TODO list. Parks a single workspace, a whole cmux window, or a named set — stopping the claude session plus its dev servers and test browsers — and restores the exact session later with full history. Use when the user says "zaparkuj tenhle workspace", "zaparkuj celé okno", "park this workspace", "park the window", "unpark", "odparkuj", "co je zaparkované", or complains that idle cmux sessions eat RAM ("claude sessions mi žerou paměť", "mám moc otevřených workspaces", "potřebuju uvolnit RAM ale nechci nic zavírat"). Prefer this over cmux's built-in agent hibernation, which has lost live sessions before.
allowed-tools:
  - Bash(./park.py:*)
  - Bash(park:*)
  - Bash(cmux list-windows:*)
  - Bash(cmux list-status:*)
  - Bash(cmux workspace list:*)
  - Bash(cmux read-screen:*)
  - Read
---

# park-workspace

Idle Claude sessions cost ~150-350 MB each. With 40+ open workspaces that is
several GB doing nothing — but closing them loses the TODO value of an open
workspace, and cmux's own agent hibernation has lost live sessions and worktrees
before.

Parking is the middle path: **the workspace stays open, only its processes go.**

`park.py` is stdlib-only Python 3.9+ and needs the `cmux` CLI on PATH. The
commands below assume `park` itself is on PATH — link it once:

```bash
ln -sf ~/.claude/skills/park-workspace/park.py ~/.local/bin/park
```

Without that link, call it as `~/.claude/skills/park-workspace/park.py <cmd>`.

```
park                       interactive picker    [park pick <filter>]
park ls                    dashboard grouped by window   [--json]
park .                     park the workspace you are in
park park <target>...      park workspace(s)  [--dry-run] [--force] [--kill-anyway]
park park --idle 3d        park everything idle that long (asks first)
park park --all            park everything parkable (asks first)
park unpark <target>...    resume a parked workspace
park show <target>         dump the ledger entry
park forget <target>       drop a stale ledger entry without resuming
park doctor                verify every parked entry is still restorable
park repaint               put back the pill and prefill a cmux restart
                           wiped   [--dry-run]
park rekey                 re-point entries after cmux regenerated its
                           workspace uuids — run BEFORE rebuild   [--dry-run]
park rebuild               recreate workspaces cmux lost   [--dry-run]
```

Targets: `workspace:12` · `<uuid>` · `<title substring>` · `window:2` · `.` (current)

`.` resolves through `CMUX_WORKSPACE_ID` and **refuses** when that is unset.
There is no such thing as "the current workspace" outside a cmux pane: cmux's
`selected` flag is per *window*, so falling back to it made `park park .` from
a plain Terminal park one workspace in every window at once.

Reported sizes are the RSS of the **whole descendant tree**, because that is
what `kill_tree` takes. Counting only the matched roots undercounted badly — a
workspace reporting 67 MB was really holding 208 MB, and across 38 live
workspaces the totals were 4.5 GB reported against 5.2 GB actually killed.
(RSS double-counts pages shared between processes, so the memory genuinely
returned to the system is somewhat lower; this is the set of processes that go.)

`ls` groups by window — window = project in this user's mental model — and gives a
per-window "parkable" total, which is the number to quote when offering to park.
`--json` emits the same rows for scripting.

A `⚠` row is a **parked entry with a session running in it**. Something resumed
the workspace behind park's back — a hand-run `cmux restore` after a reset does
exactly this — and the row used to claim `❄ parked` and report the megabytes it
freed days ago. It now shows the memory the workspace is holding *now* and
counts as live. `park unpark` on it clears the stale entry without resuming
anything; `park forget` does the same if you want the session left alone.

**Exit codes.** `0` when every target reached the state you asked for — an
already-parked workspace or an already-unparked one counts — and `1` when any
was refused. `park doctor` exits `1` when any entry needs attention. Nothing
about the shortcut cares, but a health check or a `park . && …` has no other way
to find out, and a tool that always exits 0 reads as "fine".

`--idle <30m|6h|3d|2w>` and `--all` pick their own targets: everything with a
live session that is not parked, not mid-turn, and — for `--idle` — whose last
submitted prompt is at least that old. A workspace cmux has **no** timestamp for
is left out rather than treated as idle forever. Both ask for a typed `yes`
first (`--dry-run` shows the list without asking), neither accepts named targets,
and **neither can be combined with `--kill-anyway`**: choosing in bulk and
waiving the guards that protect a running turn are each defensible and together
are not. Every selected workspace still goes through the full guard chain, so
this narrows the list and never widens what park is willing to kill.

## The picker

Bare `park` opens a curses list grouped by window. **Enter toggles the row under
the cursor** — a live row freezes, a `❄` row thaws — and the work runs on a
worker thread so the list stays live and the row shows its own progress
(`⠏ freezing…` / `unfreezing…`, with an in-flight count in the header). A row
already in flight ignores further presses, and `q` refuses to quit while
anything is mid-kill. A turn in flight shows `●` and cannot be toggled.
`park pick <substring>` pre-filters — with 40 workspaces, scrolling is the slow
part.

`f` jumps to the workspace under the cursor (`focus-window` + `select-workspace`)
and **leaves the picker open** — glancing at a workspace and coming straight back
to the list is the normal move, and closing it every time made `f` useless for
that.

The list **re-scans itself every ~30 s while its tab is on screen, and not at
all while it is not**; `r` forces a scan, and coming back to the tab triggers
one immediately (throttled to one per 3 s, or a flurry of tab switches queues
scans behind each other). A scan is ~1.5 s of socket round-trips, so it runs on
a background thread and the result is only swapped in when nothing is
mid-freeze: worker threads mutate the very row dicts on screen, and replacing
them mid-kill would strand those mutations. The cursor stays on the same
workspace across a refresh — a list that jumps while you are aiming at a row is
worse than one that does not refresh.

Off screen there is nobody to read the list and nothing to miss (the picker has
no notifications), so scanning there is pure waste — measured live: 155 child
processes per 45 s on screen, **0 per 60 s off screen**, and a scan within 20 s
of coming back. The signal is the terminal's own focus reporting (DECSET 1004),
which cmux fires for all three ways a tab leaves the screen: another workspace
in the window, another cmux window, another app entirely. Two things about
reading it back:

- Handle **both** deliveries. With `TERM=xterm-ghostty` — what cmux sets —
  ncurses already knows focus reporting and swallows the sequence, returning the
  named keys `kxIN`/`kxOUT` (match on `curses.keyname`, the numeric codes are
  assigned at runtime). Parsing the raw `ESC [ I` bytes alone therefore fires
  *never*, silently, and the picker just keeps scanning. Terminals whose
  terminfo lacks it deliver the raw sequence, whose leading ESC would otherwise
  read as the quit key.
- Turn the mode **off on every exit path**, crash included. Left enabled, the
  shell that inherits the tty gets `[I`/`[O` typed into its prompt on every
  window switch.

`a` toggles the whole window and is the one bulk action, so it still asks for a
y/N confirmation. That gate exists because a shell command typed into a
still-running picker was once consumed as keystrokes and parked nine workspaces
in one go. Single-row Enter needs no confirm: it affects one workspace and the
same key undoes it.

Verifying focus from a script is misleading: the `*` in `cmux list-windows`
marks the window owning the *calling CLI*, not the focused one. Check the target
window's `selected_workspace` instead.

Two curses details worth keeping:

- Call `locale.setlocale(locale.LC_ALL, "")` before `curses.wrapper`, or every
  non-ASCII glyph renders as garbage.
- Draw with `addstr` on a **character**-truncated string, never `addnstr` with a
  column count — its limit is in bytes. The progress bar uses ASCII (`=`/`-`)
  for the same reason: the block/dot pair turned into U+FFFD past a certain
  byte length even with the locale set.

## Performance

A scan is ~1.4 s across 45 workspaces, down from ~25 s. Keep it that way:

- **Everything per-workspace runs through `pmap`.** `cmux list-status` is a
  ~256 ms socket round-trip; 45 of them sequentially was 11.5 s. The status and
  git fan-outs are then overlapped with each other.
- **`git_info` is one `git status --porcelain -b` call.** The five `rev-parse`
  calls it used to make cost 4.4 s. It returns only `branch` and `dirty_files`,
  which is everything any caller reads — an earlier `full=True` branch spent two
  more subprocesses per park on fields nothing ever looked at.
- **Filter before the expensive lookups.** `collect()` decides which rows are
  even displayable from `ps` data alone, then queries only those.
- **A `Spinner` covers the wait** on stderr, so it never redirects into output
  and stays silent when piped.
- **A batch parks in waves of `PARK_WAVE` (8), not one at a time.** Everything a
  park does is waiting — cmux round-trips, a CPU window, git — and the picker has
  always parked rows concurrently; only the CLI walked its targets in single
  file. `park park window:4 --dry-run` was 17.8 s for 20 targets; it now does 31
  in 11.4 s. Each wave takes its own snapshot, and `attribute()` overlaps with
  the 2 s CPU window that would otherwise be pure sleeping.
- **A wave shares one CPU window.** `cpu_snapshots()` is system-wide and
  corroborates eight workspaces as well as one. Per *wave* rather than per
  batch on purpose: the old single reading was taken once and never refreshed,
  so late targets in a long batch were judged on minutes-old numbers. Nothing
  else is traded away — that gate is the corroborating one, and each workspace
  still gets its own fresh pill, draft and transcript verdict re-run
  immediately before the kill.
- **The kill wait is polled, not slept.** `wait_gone` returns as soon as the
  tree is gone — normally well under 200 ms — and only spends its full budget
  on something genuinely stuck. Measured across three targets, the two changes
  together took a dry run from 10.1 s to 5.7 s.
- **`unpark` stays serial.** It is nearly always one target, it hands the
  terminal over with `exec` when it is, and each resume has to be folded into
  the already-running set before the next one is considered.

## Tests

`python3 test_park.py` — 116 tests, stdlib `unittest`, ~1.4 s, no cmux required.

It covers the decisions made *before* anything is killed: who counts as a dev
server, which claude processes are root sessions, whether a turn is in flight,
how a session comes back, what the ledger still owes after a partial unpark, and
the screen reads that stand between park and something the user typed. Liveness
and process identity are tested against real processes, because the zombie case
— a corpse that still answers `kill(pid, 0)` — cannot be faked and is what used
to trigger the rollback that deleted the ledger.

The suite is checked by reintroducing each fixed bug and confirming it fails:
zombie-as-survivor, unconditional `ctrl+u`, the draft guard failing open, the
lowercase-only session-id scan, subagents counted as root sessions, binary names
matched anywhere in a command line, the pill trusted without corroboration,
wrappers hiding `git` from `NEVER_KILL`, a recycled pid matched on its command
line, deleting the ledger with tabs still owed, the prefill-only prompt check,
a non-exclusive operation lock, and `rebuild` duplicating what `rekey` could
place. Every one was caught. Add tests the same way — a test that still passes
with the bug back in does not test what it claims.

## Why this is safe

A Claude session lives entirely on disk in
`~/.claude/projects/<encoded-cwd>/<session-id>.jsonl`. The RSS is a re-derivable
runtime cache. Parking records the two coordinates needed to rebuild it — **cwd
and session id** — then kills the process. Unparking runs
`claude --resume <session-id>` in that cwd and the conversation continues with
full history.

The **ledger lives outside cmux**, at `~/.claude/parked/<workspace-uuid>.json`.
That is the whole design point: cmux's built-in hibernation stores resume state
inside cmux, so a corrupted cmux state loses the process *and* the pointer to
it. Here, even if cmux loses every workspace, `park rebuild` reconstructs them
from the ledger.

Writes are atomic (`tmp` + `os.replace`), and park **claims** the ledger file
with `O_EXCL` rather than checking `exists()` first — the check and the write
straddle a 2 s CPU sample, so two concurrent parks both passed it and both
pre-filled the prompt. A file that will not parse is surfaced by `doctor` rather
than skipped: dropping it silently made `doctor` report "no parked workspaces"
while `park` still answered "already parked".

**Git is never touched.** Park only records the branch and dirty-file count;
it never checks out, stashes, prunes or removes a worktree. A worktree cannot go
missing because nothing ever deletes one. That is not left to trust:
`worktree_fingerprint()` snapshots the checkout before the kill and re-checks it
after, and any difference is reported as `WORKTREE CHANGED during park`. That
window is only ~1.5 s though, while the real risk plays out over the days a
workspace sits parked — so `doctor` re-runs the fingerprint and diffs it against
the one in the ledger.

**What it will and will not kill.** `kill_tree` takes a whole descendant tree,
so a loose match is expensive. Matching names by substring flagged
`vim vite.config.ts` (word boundary), `rg webpack src/` (the name as an
*argument*), `/node_modules/vite/…/esbuild` (a *path segment*) and — worst —
`vim /tmp/claude`, which the old `(^|/)claude(\s|$)` classified as a **root
claude session**: it was handed the workspace's real cmux binding, recorded as
the session to resume, and killed with its descendants while park reported the
workspace parked.

So a bare binary name counts only when it is the program actually being run
(`runs_binary`: the command token, or what a launcher like `node`/`npx`/
`python -m` goes on to run, on the basename, with one script extension dropped
and value-taking launcher flags skipped so `npx --package vite prettier` is
prettier). `is_claude` uses the same matcher — applying it to dev servers but
not to claude left the loosest matcher where over-matching costs the most. On
top of that, `NEVER_KILL` unconditionally spares editors, pagers, `git` and
search tools, so `git commit -m "npm run dev broke"` can never cost a buffer.

Under-matching only leaves a dev server running, and costs little in practice —
children like `esbuild` still die with their parent through the tree.

**A process that survives is not a successful park.** `park` escalates TERM to
KILL, and if anything still lives it **removes the ledger entry it just claimed**
and reports failure. Recording a park whose session is still alive is worse than
not parking: `doctor` would call it restorable and `unpark` would start a second
process on that transcript. The same rollback runs if the claim–kill window is
interrupted.

Pids are re-validated immediately before the kill. The table is sampled once per
`park` invocation and reused for every target, so by the last workspace it can be
half a minute old; `kill_tree` takes out a whole descendant tree, and macOS
reuses pids.

## Several agent tabs in one workspace

**The workspace is the unit, not the tab.** All agent tabs in it freeze together
and thaw together; there is no per-tab freeze. Each tab is still tracked
individually — `attribute()` reads a distinct `CMUX_SURFACE_ID` per tab, so the
ledger holds one `sessions[]` entry per tab with its own session id, surface and
flags, and unpark resumes each into its own surface. Verified: two tabs seeded
with different tokens came back on the correct surfaces, contexts not crossed.

Consequences worth knowing:

- `park unpark .` is pre-filled at **every** agent tab's prompt, not just the
  first, so it does not matter which tab you land on. Enter in any of them
  restores the whole workspace.
- The `claude_code` status pill is per **workspace**, not per tab, so the busy
  gate is workspace-wide: one tab mid-turn protects the whole workspace from
  being parked. That is the safe direction, but it does mean a busy tab blocks
  parking its idle neighbours.

## Coming back: the prefilled prompt

After parking, `park unpark .` is left **typed but not executed** at the
workspace's prompt, so resuming is walking into the workspace and pressing
enter. Enter runs the real unpark path — clearing the pill, the colour and the
ledger — rather than a bare resume line.

Run there, `unpark` detects it is inside the tab it is resuming and `exec`s the
resume command instead of sending keystrokes to its own surface, which would
race the shell. The match is on `CMUX_SURFACE_ID` against the session's
recorded surface — but a **rebuilt** workspace has no recorded surfaces, and
matching on the surface alone meant the resume was typed into the very tab
running park. With no surface to compare, `CMUX_WORKSPACE_ID` against the
workspace is the same statement, so that is the fallback.

**The line has to be empty before anything is typed on it.** `prepare_prompt`
clears park's own prefill, **re-reads**, and requires what remains to be a bare
prompt. Asking only "is this our prefill?" was not enough: a cmux restart wipes
the terminal buffer, so after one the prefill is gone — and if the user had
`git status` half typed, unpark left the line alone, called that success, and
appended its command plus enter. One mangled command, no session, and the ledger
entry deleted on the way out. `bare_prompt` is the other half: `❯ » ➜ ›` pass on
sight, but `$ % #` need a path- or host-looking token in front of them, or
`echo $` reads as an empty prompt. Refusing a real prompt costs a re-typed
prefill; accepting a written-on one costs the user's line.

Traps in reconstructing that command:

- **Run it through `CMUX_CLAUDE_WRAPPER_SHIM`** when present. Bypassing the shim
  works, but cmux stops maintaining the workspace's agent binding and status
  pill for the new session. Apply it in **one** place (`resume_command_for`):
  when only the `exec` path applied it, every tab resumed by `cmux send` — the
  common case — lost the binding. The shim path itself ends in `/claude`, so a
  second application would silently re-match it.
- **`cmux send` is not a shell.** It interprets exactly `\n`, `\r` and `\t` and
  passes every other backslash through untouched — there is no escape for a
  literal backslash, so payloads go verbatim. Backslash-doubling "to be safe"
  corrupts cmux's recorded commands (which contain backslash-quote runs) into a
  path the shell cannot find. Enter is a real newline **byte on the same call**,
  not a second `send-key`: splitting the two raced the shell, and against a slow
  prompt the text landed while the enter did not — a correct resume command
  typed but never run, reported as "resumed".
- **Mutating cmux calls must not retry.** A nonzero exit after the write already
  landed is itself a transient-socket symptom; retrying `send` twice more leaves
  `park unpark .park unpark .park unpark .` typed at the prompt. `cmux_do` is
  the no-retry, no-raise path, and it returns success so callers stop reporting
  actions that did not happen.
- **Never rebuild the full command from `ps`.** `ps` joins argv with spaces, so
  the `--settings {json}` cmux passes cannot be split back correctly, and
  replaying a mangled one makes claude refuse to start (`Invalid JSON provided
  to --settings`). Only a small whitelist of flags is carried across
  (`ARGV_FLAGS_BOOL` / `ARGV_FLAGS_VALUE`); the shim re-supplies the rest.
  Dropping `--dangerously-skip-permissions` here is very visible — the resumed
  session quietly starts asking for permissions again.
- **Quote the flag VALUES, not just the cwd.** Those tokens come from `ps`, and
  the result is handed to `/bin/sh -c` (and typed into a pane). Any process can
  write anything into its own argv — including `CMUX_WORKSPACE_ID=<ws>`, which
  is how it gets attributed to a workspace in the first place — so an unquoted
  `--model ;curl…|sh` would execute on the next unpark, disguised as a resume
  and through a path the skill's `allowed-tools` pre-approves.
- **The session id needs the same treatment.** Two of its three sources are
  regex-constrained, but the last-resort scan returns a raw *filename stem*, so
  a file called `x; touch /tmp/PWNED #.jsonl` in the project dir became a
  command. Ids are validated against `SESSION_ID_RE` before entering the ledger
  and quoted at both construction sites.
- **Rewrite only the token in command position.** `with_shim` matched the first
  `claude` anywhere, so for a checkout at `~/projects/claude` it rewrote the
  `cd` target; the `cd` then failed, `&&` short-circuited, and unpark reported
  "resumed" for a session that never started.

The ledger is written 0600 on **both** paths and its directory 0700: an entry
holds the cwd, the branch and the user's last prompt, and the non-claim write
was inheriting 0644 from the umask. `ledger_path` rejects any id that is not
`[A-Za-z0-9._-]+` — `rebuild`, `forget` and `unpark` take that id from a ledger
file's own contents, and `LEDGER / f"{ws_id}.json"` resolves `../settings` or an
absolute path happily, at which point `unlink()` deletes something else.

## Rules

- **Never park a session with unsent text in the prompt.** A draft lives only
  in the agent's input box — not in the transcript, not in the process table,
  nowhere on disk — so killing the session is the one operation that destroys it
  silently. `unsent_input` reads it off the screen (the `>` line fenced by box
  rules; requiring the rule above it is what stops a shell prompt reading as a
  draft) and park refuses, quoting the text back. It runs **twice** — once
  before the expensive checks and again immediately before the kill, because
  the seconds in between (a CPU window, a status round-trip, a session lookup
  per tab) are exactly when someone watching the workspace types into it.
- **Never park a session mid-turn.** The gate is the `claude_code` status pill
  (`Running` = a turn is in flight) corroborated by a CPU sample. About a third
  of workspaces carry **no pill at all**, and a session blocked on a slow tool
  call sits near 0% CPU — so for those both gates wrongly read "idle". When the
  pill is absent, the transcript's mtime is the tiebreaker: an active turn
  appends to it continuously, so anything written in the last 20 s counts as
  busy. The pre-kill re-check re-runs the **same verdict**, not a weaker one.
  Only `--kill-anyway` overrides this, and an in-flight turn is the one thing
  that is genuinely lost when it does.
- **The two overrides are deliberately not one flag.** `--force` waives the CPU
  sample and nothing else — that gate is corroboration, and it is what makes a
  workspace running one long tool call look busy for as long as it runs.
  `--kill-anyway` waives the draft guard and the in-flight verdict as well, so
  it is the only path that can lose work; it lists what it is about to kill,
  requires a typed `yes`, and refuses outright without a terminal to ask at. A
  single flag that dropped every check at once made the safe override and the
  destructive one the same keystroke.
- **park never parks the session it is running in.** `kill_tree` works
  leaves-first, so parking your own tree kills park before it reaches the
  session: ledger written, session dead, no pill, no colour, no prefill. The
  guard walks this process's ancestry and refuses if any kill target is in it —
  no flag turns it off. This is why an agent cannot park its own workspace on
  request; a new tab (⌘⌥F or any shell in the workspace) is a child of cmux,
  not of claude, and parks it fine.
- **The pill also sticks.** A workspace can read `Running` long after its turn
  ended — one was seen 45 minutes stale — and believing it makes that workspace
  permanently unparkable. So a busy pill must be corroborated: quiet for
  `STALE_PILL_SECONDS` (10 min) with the CPU gate already passed means the pill
  is lying, and park says so in a note. The window is long on purpose — a single
  tool call can legitimately write nothing while it runs, and being slow to park
  costs nothing next to killing a live turn.
- `ls` and the picker mark such rows `Running (stale)` and offer them, using
  cmux's `latest_submitted_at` as a free proxy. That is only a **hint**:
  resolving each session's real transcript here turned a 1.6 s scan into 16 s,
  and `park_one` checks the real thing anyway, so the worst case is a row that
  offers itself and then refuses with a reason.
- **`cpu_sample` reports load, not a delta.** macOS `%cpu` is already a decaying
  average, so subtracting two samples measures *acceleration*: a session pinned
  at 100% gave deltas of −4.1, +3.5, −42.1, all under the 15% threshold. For as
  long as it did that, the CPU corroboration was decorative.
- **It samples the whole tree, not the roots.** A turn that shells out to a
  compiler or a test run leaves the root claude near 0% while the machine is
  flat out. Measured on a workspace mid-turn: roots 8.8%, tree 17.6% — one side
  of the 15% threshold each. With no pill and a tool call that writes nothing
  for 20 s, this gate is the last one standing, so it has to see the work.
- **One park or unpark per workspace at a time.** Claiming the ledger entry is
  not enough: park publishes that entry *before* it kills anything, so an unpark
  arriving in that window reads it, sees every session still live, takes the
  "already running" path and deletes it — and then park kills the sessions whose
  only resume record has just gone. A per-workspace lock file recording its
  owner's pid is held across the whole transaction; a lock whose owner is gone
  is not a lock, so a park that was SIGKILLed does not wedge the workspace.
- **Never park what cannot be restored.** If the session id or cwd will not
  resolve, skip that workspace and say so, rather than killing it.
- **Dev servers and test browsers are stopped but NOT restarted** on unpark.
  Only the claude session comes back; start dev servers yourself when needed.
- **Only on request.** Never park automatically, on a timer, or as a side effect
  of another task. Parking is always something the user asked for.
- Ask before parking anything the user did not name — offer `park ls` and let
  them choose.

## How workspaces are matched to processes

Ownership comes from `CMUX_WORKSPACE_ID` / `CMUX_SURFACE_ID`, which cmux exports
into every pane and every process inherits. This is exact. Two weaker methods
were measured and rejected as primaries:

- `cmux top` process attribution misses roughly half the claude sessions.
- Working-directory matching is ambiguous when several workspaces share one repo
  root — it silently merged workspaces and produced 2.5 GB phantom totals.

cwd matching survives only as a fallback for daemonised helpers (agent-browser
reparents to init and loses the env), and it matches **longest prefix first** so
a workspace at `/repo` cannot swallow a nested worktree workspace at
`/repo/.claude/worktrees/x`.

## Resolving the session id — order matters

Getting this wrong resumes **someone else's conversation**, which is exactly the
failure that made cmux's own hibernation untrustworthy. Sources, best first:

`argv_session_id` matches **both** `--resume` and `--session-id`. cmux starts a
fresh agent with the latter, and matching only `--resume` left 18 of 54 live
sessions unable to use this path — they fell through to the last-resort scan
with their id in plain sight, and `unpark`'s "already running" guard could not
see them at all.

A binding's `cwd` is also tried against the **process's own** cwd, because cmux
records the repo root for an agent running in a worktree beneath it. Insisting
on the binding's cwd discarded an authoritative id and fell through to the scan.
The recorded command is only replayed when it belongs to the cwd that matched —
it begins `cd <binding cwd>`, so reusing it after the fallback would resume in
the wrong tree. Measured after both fixes: 39 live sessions, all resolved by
binding or argv, **none** by lsof or scan, and no two workspaces resolving to the
same session.

1. **`cmux surface resume get --json`** → `resume_binding.checkpoint_id`.
   Maintained by cmux's Claude Code hook, and it carries the **original command
   line** — replay that on unpark, because rebuilding `claude --resume <id>` by
   hand silently drops flags like `--dangerously-skip-permissions` and changes
   how the session behaves. Covers ~3/4 of sessions in practice.
2. **`--resume <uuid>` in the process argv** — claude's own or its zsh wrapper.
3. **`lsof`**, but only a transcript inside the project dir for that process's
   own cwd.
4. **Newest transcript in the project dir written after the process started** —
   last resort, and `park` prints a warning when it lands here. The sibling
   [resume-cmux-sessions] skill records that a loose "newest .jsonl in the
   worktree dir" lookup silently grabs an *old* session.

`session_id_of` **returns** which of those it took; the caller must not re-derive
it. Both branches return a path that exists, so testing the path cannot tell the
safe fd hit from the last-resort guess — that check silently labelled every
scan-derived id as `lsof`, disabling the one signal this ordering exists to
give. `doctor` flags entries that landed on the scan.

Two more rules borrowed from that skill:

- **Re-verify immediately before mutating.** Topology drifts; a session can
  start a turn between the busy check and the kill, so the check runs twice.
- **Never resume a session that is already running.** Two processes appending to
  one transcript corrupts it, so `unpark` sends no resume command — but it still
  **tears down the parked state** (pill, colour, pinned title, ledger) and
  reports `already running`. Refusing outright was wrong: once anything had
  resumed the session, the workspace was no longer parked, yet every later
  `unpark` bailed before the cleanup and the sidebar claimed `Parked` forever
  with no way out but `park forget`.

Do not write our own `surface resume set`: cmux's binding is better than
anything reconstructed here, and overwriting it degrades the fallback.

## Other details that cost real debugging time — do not regress them

- `cmux list-windows` marks the **selected** window with a leading `*`. A parser
  anchored to the line start silently drops whichever window the user is
  currently in.
- A claude process holds **other projects' transcripts** open too. Taking the
  first `.jsonl` off `lsof` resumes an unrelated session — the transcript must
  live in the project dir for that process's own cwd. When the fd is not open at
  all, fall back to the newest transcript in that dir written after the process
  started.

## Visual state

Parked workspaces are marked in the **native cmux sidebar** — nothing is
replaced or re-skinned:

| what | mechanism |
|---|---|
| ❄️ `Parked · N MB freed` pill | `cmux set-status parked` |
| dimmed workspace row | `cmux workspace-action --action set-color --color Charcoal` |
| **the title, pinned** | `cmux workspace-action --action rename` |
| last prompt kept as the note | stored in the ledger, shown by `park ls` |

**Pinning the title is not cosmetic.** cmux derives a workspace's name from its
live agent, so killing the session makes `✳ Vyhledejte trendy…` decay to
`~/Sites/foo` — and with 40 open workspaces those titles *are* how you find
anything. Park therefore renames the workspace to the title it captured while
the agent was alive. It only does so when the workspace has no custom name of
its own (`has_custom_title`), and records `pinned_title` in the ledger so unpark
clears only a name park itself set, never the user's.

cmux's **workspace and tab right-click menus are not extensible** — the only
context menus a config can reach are the `+` button's
(`ui.newWorkspace.contextMenu`, plus the per-group one under
`workspaceGroups.byCwd`). **Keyboard shortcuts are** — this doc used to claim
they were not, which was wrong: an entry in the `actions` registry of
`~/.config/cmux/cmux.json` carries its own `shortcut` and shows up in the
Command Palette.

```json
"actions": {
  "park-pick": { "type": "command", "title": "Park — freeze/unfreeze",
                 "command": "/Users/you/.local/bin/park pick",
                 "target": "newTabInCurrentPane", "shortcut": "cmd+alt+p",
                 "keywords": ["park", "freeze", "ram"] },
  "park-here": { "type": "command", "title": "Park this workspace",
                 "command": "/Users/you/.local/bin/park .",
                 "target": "newTabInCurrentPane", "shortcut": "cmd+alt+f",
                 "confirm": true }
}
```

`cmux reload-config` applies it without a restart. Four things that bite:

- `target` must be **`newTabInCurrentPane`**, never `currentTerminal` — the
  current terminal is normally the claude session being parked, so the command
  would be typed into its input box instead of a shell.
- Use an **absolute path** to `park`: the action is not run through a login
  shell, so `~/.local/bin` is not necessarily on its PATH.
- `park .` (shorthand for `park park .`) resolves `.` from the
  `CMUX_WORKSPACE_ID` the new tab inherits — so the shortcut parks the
  workspace it was pressed in, and the tab running it is a plain shell park
  does not touch.
- Take the key from the **`⌘⌥` namespace**: every ⌘⌥ letter is unbound in cmux,
  while ⌘⇧P, ⌘⇧F and most other ⌘⇧ letters are taken. `cmux config doctor`
  validates JSONC syntax only, so a shortcut that does not bind fails silently;
  the docs give the chord as a string (`"cmd+alt+p"`), but Settings > Keyboard
  Shortcuts writes built-in bindings as an object
  (`{"first": {"command": true, "option": true, "key": "p", …}}`). If the string
  form does not take, try that shape.

A **Dock control** is the other placement — the picker in the right sidebar.
Note the seam with the focus-driven refresh above: a dock panel is visible but
never focused, so it keeps its 30 s cadence only until you click into it and
back out — after that it waits for you to click in again, or for `r`.

```json
{ "controls": [
    { "id": "park", "title": "Park", "command": "park", "height": 300 } ] }
```

in `.cmux/dock.json` or `~/.config/cmux/dock.json`.

Unpark clears the pill and restores the previous colour. **`forget` shares that
teardown** — it differs only in not sending the resume commands. It used to
`clear-color` instead, destroying the user's original colour in the same breath
as the ledger entry holding the only record of it, and it left the pre-filled
`park unpark .` typed at a prompt where it could then only ever answer
"not parked".

## Never two processes on one transcript

`unpark` refuses to resume a session that is already live, and that guard is
the only thing between a double resume and a corrupted `.jsonl`. It used to
build the live set from `ps` argv alone, which **stopped working in cmux
0.64**: an agent cmux restores at launch runs as plain
`claude --dangerously-skip-permissions --resume`, with the id supplied out of
band. `argv_session_id` returns None for it, so the set came back short and
the guard read as "checked" while matching nothing.

Measured right after a cmux update: 12 of 13 live sessions still carried their
id in argv (those had been restored with an explicit
`cmux restore claude <uuid>`), and the 13th — the one cmux auto-restored on
launch — did not. That is exactly the post-restart moment when unparking
happens.

`live_session_ids` therefore falls back to `session_id_of` for any claude
without an id in argv, resolving it off the transcript it holds open. That is
an lsof per such process, so `cmd_unpark` resolves the set **once** for a whole
batch and passes it down rather than paying it per workspace — folding each
resume back into the set as it goes, so a batch is not answering from the
snapshot it took before any of them existed.

Ids are compared **lowercased** on both sides. cmux writes uppercase uuids in
places and the ledger records whatever spelling its source used, so a
case-sensitive `in` test was a guard that matched nothing at all.

The fallback can still fail — lsof denied, a cwd that will not read — and this
guard **fails open**, so `unpark` says out loud when a running claude could not
be identified rather than leaving the silence to be read as "checked".

The other half of the same rule: **a `cmux send` that succeeds is not a session
that started.** A stale cwd, a shim that moved, or claude refusing to start all
leave the tab at a shell prompt, and unpark used to delete the ledger entry —
session id, transcript and resume command — on the strength of the send alone.
It now waits for a claude process carrying that id to appear (a `ps` sweep; our
own resume command puts the id in argv) and keeps whatever did not come up. Same
for tabs it cannot resume at all: after a rebuild the workspace has one surface,
so the second and later tabs stay in the ledger with their commands instead of
being mentioned in a note that `exec` then prevents anyone from printing.

## Recovering from a cmux reset

A restart wipes what lives in cmux, not what lives in the ledger. Measured
across 44 parked workspaces right after a cmux update: the **pill** and the
typed **`park unpark .`** were gone from every one of them (the prefill lived
in the terminal buffer, which the new login shell replaced), while the dimmed
**colour** and the pinned **title** survived — cmux persists those. The ledger
itself was untouched: 44/44 restorable, uuids intact.

That matters because a parked workspace with no pill and no prefill is
indistinguishable from an ordinary empty one, which is how a parked session
gets mistaken for a lost one and "restored" by hand behind park's back.

```bash
park repaint         # put the pill and the prefill back, from the ledger
```

It never types into a prompt that is not bare: a line with anything after the
prompt glyph is left alone and reported, because appending to a half-written
command is silent and the user's text is the only copy.


```bash
park doctor          # is every parked entry still restorable?
park rekey           # workspaces came back under NEW uuids — re-point the entries
park rebuild         # only for what rekey could not place: recreate from the ledger
```

**An entry pointing at nothing has two very different causes, and the ledger
cannot tell them apart:** cmux lost the workspace, or the user closed it on
purpose. Rebuilding the second kind resurrects something deliberately shut —
which happened, on a workspace closed the day before. cmux records the answer in
`~/Library/Application Support/cmux/closed-item-history-*.json`, so `doctor` now
says *"workspace was closed 2d ago — not lost; drop the entry with: park forget"*
and `rebuild` **skips** those unless `--closed` is passed. Timestamps there are
Core Data epoch (2001-01-01), not unix. Note the history records *a* close, not
*who* closed it — the message says "was closed", because park itself closing a
workspace looks identical.

Forgetting an entry never costs the conversation: the transcript lives in
`~/.claude/projects/**/<session-id>.jsonl` and `park show` prints the resume
command before you drop it.

**Order matters, and getting it wrong duplicates the fleet.** The ledger is keyed
by cmux workspace uuid, and a reset regenerates every one of them while the
workspaces themselves come back. Every parked entry therefore orphans at once —
which looks exactly like "cmux lost them" and made `rebuild` the obvious command.
It is the wrong one: `rebuild` treats an orphan as gone and creates a **second**
workspace beside each survivor. Run `rekey` first; `rebuild` is for what is
genuinely missing — and `rebuild` now **enforces** that rather than documenting
it: any entry whose title already matches a free live workspace is held back with
a pointer to `rekey`, because a rule nothing checks is a rule that gets skipped
exactly when it matters. `rekey` in turn skips entries whose workspace the user
**closed**: that is not a lost uuid, and adopting one would mark an unrelated
live workspace as parked over a shared title.

`rekey` matches on the workspace **title**, corroborated by the cwd — not the
reverse, which was the first attempt and matched 23 of 44. `pin_title` freezes the
name at park time precisely so it survives, and measured against a real 44-entry
ledger every title still matched while 21 cwds did not: cmux records the repo
**root** for an agent living in a worktree under it (19 cases), and a reset can
point its per-panel cwd at a sibling worktree outright (2 cases). Title-keyed with
a prefix-tolerant cwd check matches 44 of 44 and reports the disagreements instead
of obeying them. What prevents a wrong adopt is **uniqueness**: the title must
match exactly one workspace still up for adoption, and one already claimed by
another entry or running a claude session is never adoptable. It also re-applies
the pill and the colour, which the reset wiped. The typed prefill does not come
back — it lived in the terminal buffer — so resume re-keyed workspaces by name.

`doctor` flags a missing cwd (per tab, not just the workspace's), a missing
transcript, a session that is already running, a corrupt ledger file, a session
id that came from the last-resort transcript scan, and a git checkout that has
changed since parking. It resolves each entry's ref **live** — refs are
positional and shift as workspaces open and close, so the one captured at park
time can later name a different workspace.

`rebuild` recreates a lost workspace and then **re-keys the ledger entry onto
the new workspace uuid**. That step is the whole recovery path: `new-workspace`
mints a fresh uuid, so an entry left under the dead one can never be found by
`unpark` again. It also clears the recorded surface ids, which died with the old
workspace. A rebuilt workspace has a single surface, so only the first agent tab
is resumed automatically; `unpark` prints the exact resume command for any
others rather than dropping them.

An entry whose workspace is gone stays reachable by uuid or title, so `show` and
`forget` still work on it — otherwise a stale entry would be unremovable except
by hand while `doctor` flagged it forever.
