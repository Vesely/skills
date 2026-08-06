#!/usr/bin/env python3
"""Park idle cmux workspaces: free their RAM, keep them open as TODO markers.

A Claude session lives on disk (~/.claude/projects/<enc-cwd>/<session-id>.jsonl);
the ~150 MB RSS is a re-derivable runtime cache. Parking records the two
coordinates needed to rebuild it (cwd + session id) in a ledger OUTSIDE cmux,
then kills the process. The workspace, pane, shell and git worktree are never
touched.

The ledger is the durable truth on purpose: cmux's own hibernation stores resume
state inside cmux, so a corrupted cmux state loses the process AND the pointer.
"""

import curses
import json
import locale
import os
import re
import shlex
import shutil
import signal
import stat
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

LEDGER = Path.home() / ".claude" / "parked"
PILL_KEY = "parked"
PARKED_COLOR = "Charcoal"
# Typed (not run) at a parked prompt, so the workspace comes back by walking
# into it and pressing enter. Also what `clear_prefill` matches on before it
# wipes a line, so the two must stay the same string.
PREFILL = "park unpark ."
# A session id ends up inside a command run by /bin/sh. The lsof and argv paths
# are regex-constrained, but the last-resort scan returns a raw FILENAME stem,
# so a file called `x; touch /tmp/PWNED #.jsonl` would execute on unpark.
SESSION_ID_RE = re.compile(r"^[0-9a-fA-F-]{36}$")
# How often the picker re-scans on its own while its tab is on screen, and how
# stale the list must be for coming back to the tab to trigger another scan.
# A scan is ~1.5 s of socket round-trips and a system-wide `ps`, so a tool that
# exists to reclaim resources must not burn them in the background: off screen
# it does not scan at all (see FOCUS_ON), and nothing there can change without
# the user, who would have to come back to see it.
REFRESH_SECONDS = 30.0
FOCUS_REFRESH_GAP = 3.0
# How long the draw loop waits for a key. Short while something is in flight so
# the spinner animates, longer when idle, longest off screen — getch still
# returns the instant a key arrives, so none of this costs responsiveness.
TICK_BUSY_MS, TICK_IDLE_MS, TICK_HIDDEN_MS = 120, 400, 2000
# How long a "Running" pill must go unbacked by transcript writes before it is
# treated as stale. Long on purpose: one tool call can legitimately write
# nothing while it runs.
STALE_PILL_SECONDS = 600.0
# cmux writes its closed-item history with Core Data timestamps (epoch
# 2001-01-01), so they need this added to become unix seconds.
APPLE_EPOCH = 978307200
# A ledger claim lock is held for milliseconds; older than this it belongs to a
# park that was killed mid-write, and reclaiming it is the only way back.
LOCK_STALE_SECONDS = 60.0
# The operation lock is held for a whole park or unpark — a CPU window, a kill
# and a wait for the session to come up — so it gets a much longer rope. It is
# normally released by its owner dying, not by this timeout.
OP_LOCK_STALE_SECONDS = 300.0
# How stale cmd_park lets its process snapshot get before re-taking it, so a
# session started during a long batch cannot be missed by classify().
SNAPSHOT_MAX_AGE = 5.0
# How many workspaces a batch parks at once. Each one is almost entirely
# waiting — cmux round-trips, a CPU window, git — and they share one snapshot
# per wave, so the wave size is also how fresh that snapshot stays.
PARK_WAVE = 8
# Unpark waves are smaller: each one ends by waiting for a claude to appear,
# and a wave of resumes all booting at once is real load on the machine.
UNPARK_WAVE = 6

# A turn is in flight -> never park. Anything else is fair game.
BUSY_STATES = {"running", "working", "thinking", "compacting"}

# Matching these by substring is what makes parking dangerous: kill_tree takes
# a whole descendant tree, so one loose match kills an editor with unsaved
# buffers. A bare \b hit `vim vite.config.ts` (word boundary), `rg webpack src/`
# (the name as an ARGUMENT) and `/node_modules/vite/.../esbuild` (a PATH
# SEGMENT). So a bare binary name only counts when it is the command being run
# -- see `runs_binary`. Under-matching just leaves a dev server running;
# over-matching loses the user's work.
DEV_BINARIES = {"vite", "webpack", "rollup", "parcel", "nodemon", "nuxi",
                "ts-node-dev", "uvicorn", "django"}
BROWSER_BINARIES = {"agent-browser", "playwright", "puppeteer"}
# Multi-word forms are unambiguous enough to match anywhere in the line.
DEV_SERVER_RE = re.compile(
    r"(?:^|\s)(?:next dev|astro dev|nuxt dev|remix dev|turbo run dev|"
    r"bun --hot|(?:npm|pnpm|yarn|bun) (?:run )?dev(?::[\w.-]+)?|rails s|flask run|"
    r"php artisan serve|hugo server|jekyll serve|wrangler dev)(?=\s|$)"
)
TEST_BROWSER_RE = re.compile(
    r"Chrome for Testing|chromiumdev_profile|chrome-for-testing"
)
# A dev server is often launched through one of these, so the name we want is
# the first token that is not the interpreter or one of its flags. The second
# group are wrappers that run something else without changing what it IS; not
# reading through them let `env git commit -m npm run dev broke` (as ps renders
# argv, unquoted) stop at `env`, miss NEVER_KILL, and then match `npm run dev`
# in the COMMIT MESSAGE — classifying a git commit as a dev server and killing
# its editor.
LAUNCHERS = {"node", "npx", "bun", "deno", "python", "python3", "-m", "exec",
             "env", "nice", "nohup", "sudo", "doas", "time", "command",
             "stdbuf", "setsid"}
# Launcher flags that swallow the next token, so `npx --package vite prettier`
# is prettier and not vite. `-m` belongs in LAUNCHERS, not here: `python -m
# uvicorn app` must read THROUGH it to uvicorn, not skip past it. `-n`/`-u` are
# here for `nice -n 10` and `sudo -u someone`, whose values would otherwise
# read as the program being run.
VALUE_FLAGS = {"--package", "-p", "--loader", "--require", "-r", "-c",
               "-n", "-u"}
# `env FOO=1 git …`: an assignment is neither a flag nor the program.
ENV_ASSIGNMENT_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")
# Never classify these as anything killable, whatever else the line contains.
# `git commit -m "npm run dev broke"` and `vim vite.config.ts` are the user's
# work; a phrase appearing as an ARGUMENT must never cost them a buffer.
NEVER_KILL = {"vim", "nvim", "vi", "emacs", "nano", "micro", "hx", "helix",
              "less", "more", "tail", "head", "cat", "bat", "man",
              "rg", "grep", "ag", "ack", "fzf", "git", "code", "subl"}
CLAUDE_BINARIES = {"claude"}


# --- Concurrency + feedback --------------------------------------------------
def pmap(fn, items, workers=24):
    """Run fn over items concurrently.

    Everything slow here is I/O-bound: cmux socket round-trips (~256 ms each)
    and git subprocesses.
    """
    items = list(items)
    if not items:
        return []
    with ThreadPoolExecutor(max_workers=min(workers, len(items))) as ex:
        return list(ex.map(fn, items))


def background(fn):
    """Start fn now, hand back a getter that blocks for its value.

    Not a ThreadPoolExecutor: its workers are joined at interpreter exit, so a
    park that never consults the CPU window — "already parked", "no claude
    session", any early refusal — still sat for the full two seconds before the
    process could end. A daemon thread nobody waits for costs nothing.
    """
    box, done = {}, threading.Event()

    def run():
        try:
            box["value"] = fn()
        except BaseException as ex:          # re-raised in the caller's frame
            box["error"] = ex
        finally:
            done.set()

    threading.Thread(target=run, daemon=True).start()

    def get():
        done.wait()
        if "error" in box:
            raise box["error"]
        return box["value"]
    return get


class Spinner:
    """Immediate feedback on stderr while a scan runs.

    A scan takes a second or two and silence reads as a hang. Silent when
    stderr is not a terminal.
    """

    FRAMES = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"

    def __init__(self, text):
        self.text = text
        self.on = sys.stderr.isatty()
        self._stop = threading.Event()
        self._t = None

    def _run(self):
        i = 0
        while not self._stop.wait(0.08):
            sys.stderr.write(
                f"\r\033[2K  {self.FRAMES[i % len(self.FRAMES)]} {self.text}")
            sys.stderr.flush()
            i += 1

    def __enter__(self):
        if self.on:
            self._t = threading.Thread(target=self._run, daemon=True)
            self._t.start()
        return self

    def __exit__(self, *exc):
        self._stop.set()
        if self._t:
            self._t.join(timeout=0.5)
        if self.on:
            sys.stderr.write("\r\033[2K")
            sys.stderr.flush()


# --- cmux plumbing -----------------------------------------------------------
def cmux(*args, check=True, retries=2):
    """Run a cmux command. The socket fails transiently, so read paths retry.

    Mutating calls must pass `retries=0` (see `cmux_do`): a nonzero exit after
    the write already landed is itself a transient-socket symptom, and retrying
    `send` a third time leaves `park unpark .park unpark .park unpark .` typed
    at the prompt.
    """
    env = {**os.environ, "CMUX_QUIET": "1"}
    last = ""
    for attempt in range(retries + 1):
        r = subprocess.run(
            ["cmux", *args], capture_output=True, text=True, env=env
        )
        if r.returncode == 0:
            return r.stdout
        last = r.stderr.strip()
        if attempt < retries:
            time.sleep(0.4 * (attempt + 1))
    if check:
        raise RuntimeError(f"cmux {' '.join(args)}: {last}")
    return ""


def cmux_do(*args):
    """A cmux call that changes state: never retried, never raises.

    Returns True when cmux reported success, so callers can stop claiming an
    action succeeded when it did not.
    """
    env = {**os.environ, "CMUX_QUIET": "1"}
    r = subprocess.run(["cmux", *args], capture_output=True, text=True,
                       env=env, check=False)
    return r.returncode == 0


def send_text(text, workspace, surface=None, submit=False):
    """Type text at a prompt, optionally pressing enter after it.

    `cmux send` interprets the two-character sequences \\n, \\r and \\t, and
    passes every other backslash through untouched — there is no escape for a
    literal backslash, so the payload must go verbatim. (Doubling backslashes
    "to be safe" corrupts cmux's recorded resume commands, which contain
    backslash-quote runs, into a command the shell cannot find.)

    Enter is a real newline BYTE on the same call, not a second `send-key`.
    Splitting the two raced the shell: against a slow prompt the text landed
    and the enter did not, leaving a correct resume command typed but never
    run — the workspace reported "resumed" while sitting at a shell. A literal
    newline is not one of the sequences above, so one atomic call is both safer
    and simpler.
    """
    args = ["send", "--workspace", workspace]
    if surface:
        args += ["--surface", surface]
    # `--` so a payload that happens to start with a dash is text, not flags.
    return cmux_do(*args, "--", text + ("\n" if submit else ""))


def cmux_json(*args):
    return json.loads(cmux("--id-format", "both", *args, "--json"))


def list_windows():
    out, wins = cmux("list-windows"), []
    for line in out.splitlines():
        # The selected window is marked with a leading "*" — without allowing
        # for it, whichever window the user is currently in silently vanishes.
        m = re.match(r"\s*\*?\s*(\d+):\s+(\S+)", line)
        if m:
            wins.append({"index": int(m.group(1)), "id": m.group(2)})
    return wins


def all_workspaces(missing=None):
    """Every workspace across every window. `workspace list` is per-window.

    Pass `missing` a list to be told which windows would not enumerate. That
    matters to anything about to KILL something: a window that dropped out is
    not an empty window, it is a set of workspaces this map does not contain —
    and `attribute` falls back to longest-prefix cwd matching for processes it
    cannot place, so their claude sessions get handed to whichever *listed*
    workspace sits above them in the tree. Parking that workspace then kills
    them. Reading commands are happy with a partial answer and a warning;
    `park` refuses to work from one.
    """
    wins = list_windows()

    def fetch(win):
        try:
            return win, cmux_json("workspace", "list", "--window", win["id"])
        except (RuntimeError, json.JSONDecodeError) as ex:
            # Never silent: a dropped window would hide workspaces from `ls`
            # and make an explicit target look nonexistent.
            print(f"warning: could not list window {win['index']} "
                  f"({win['id'][:8]}): {ex}", file=sys.stderr)
            return win, None

    seen, out = set(), []
    for win, data in pmap(fetch, wins):
        if data is None:
            if missing is not None:
                missing.append(win)
            continue
        for ws in data.get("workspaces", []):
            if ws["id"] in seen:
                continue
            seen.add(ws["id"])
            ws["window_id"] = data.get("window_id", win["id"])
            ws["window_index"] = win["index"]
            # cmux's own window refs are 1-based while list-windows indexes
            # from 0, so keep the ref and prefer it when resolving `window:N`.
            ws["window_ref"] = data.get("window_ref", "")
            out.append(ws)
    return out


def workspace_status(ws_id):
    """Parse `cmux list-status` into {key: value}."""
    try:
        out = cmux("list-status", "--workspace", ws_id, check=False)
    except Exception:
        return {}
    status = {}
    for line in out.splitlines():
        m = re.match(r"(\w+)=(.*?)(?:\s+icon=|\s+color=|\s+priority=|$)", line)
        if m:
            status[m.group(1)] = m.group(2).strip()
    return status


def closed_workspaces(base=None):
    """workspace uuid -> when the user closed it, from cmux's own history.

    "cmux lost this workspace" and "you closed it on purpose" are the same
    thing to the ledger — both leave an entry naming a workspace that is not
    there — and treating the second as the first makes `rebuild` resurrect
    something the user deliberately shut. cmux records the answer; read it
    rather than guess.

    Timestamps are Core Data epoch (2001-01-01), returned as unix seconds.
    Missing or unreadable history is not an error: it only means every orphan
    keeps the older, vaguer message.
    """
    out = {}
    base = base or Path.home() / "Library" / "Application Support" / "cmux"
    for f in sorted(base.glob("closed-item-history*.json")):
        try:
            records = json.loads(f.read_text()).get("records", [])
        except (OSError, ValueError):
            continue
        for r in records:
            entry = (r.get("entry") or {}).get("workspace") or {}
            inner = entry.get("_0") if isinstance(entry, dict) else None
            ws_id = (inner or entry or {}).get("workspaceId")
            when = r.get("closedAt")
            if not ws_id or not isinstance(when, (int, float)):
                continue
            unix = when + APPLE_EPOCH
            # Reopened and closed again: the latest close is the current truth.
            out[ws_id] = max(out.get(ws_id, 0), unix)
    return out


def etime_seconds(s):
    """`ps` etime ([[dd-]hh:]mm:ss) as seconds, or None if it will not parse."""
    m = re.match(r"(?:(\d+)-)?(?:(\d+):)?(\d+):(\d+)$", s.strip())
    if not m:
        return None
    d, h, mi, sec = (int(x) if x else 0 for x in m.groups())
    return d * 86400 + h * 3600 + mi * 60 + sec


def ps_table():
    """One ps sweep: pid -> {cmd, ppid, rss, start}.

    `start` is what makes a pid identifiable: a pid alone is recycled, and a
    command line alone repeats across workspaces (cmux 0.64 starts every agent
    as the same `claude --dangerously-skip-permissions --resume`). Only the two
    together say "still the process we measured" — see `pid_matches`, which
    stands between a stale snapshot and SIGKILLing an unrelated tree.
    """
    r = subprocess.run(["ps", "-Ao", "pid=,ppid=,rss=,etime=,command="],
                       capture_output=True, text=True)
    now = time.time()
    table = {}
    for line in r.stdout.splitlines():
        parts = line.split(None, 4)
        if len(parts) < 5:
            continue
        try:
            secs = etime_seconds(parts[3])
            table[int(parts[0])] = {"ppid": int(parts[1]),
                                    "rss": int(parts[2]) * 1024,
                                    "start": None if secs is None else now - secs,
                                    "cmd": parts[4]}
        except ValueError:
            pass
    return table


def read_env(pids):
    """pid -> {CMUX_WORKSPACE_ID, CMUX_SURFACE_ID}, read in one batched ps.

    cmux exports these into every pane's shell, so anything launched in a pane
    inherits them. This is an exact pid->workspace mapping, which neither cmux's
    own process attribution (misses ~half the sessions) nor cwd matching
    (ambiguous when several workspaces share one repo root) can provide.
    """
    if not pids:
        return {}
    out = {}
    pid_list = list(pids)
    for i in range(0, len(pid_list), 128):
        chunk = ",".join(str(p) for p in pid_list[i:i + 128])
        r = subprocess.run(["ps", "-Ewww", "-o", "pid=,command=", "-p", chunk],
                           capture_output=True, text=True)
        for line in r.stdout.splitlines():
            head = line.split(None, 1)
            if not head:
                continue
            try:
                pid = int(head[0])
            except ValueError:
                continue
            # `ps -E` prints argv and THEN the environment, with nothing
            # marking the boundary — so a process whose own command line
            # mentions CMUX_WORKSPACE_ID (an echo, a script, park's own test
            # harness) would be attributed to whatever it named. The last
            # occurrence is the environment's.
            w = re.findall(r"CMUX_WORKSPACE_ID=(\S+)", line)
            s = re.findall(r"CMUX_SURFACE_ID=(\S+)", line)
            out[pid] = {"workspace": w[-1] if w else None,
                        "surface": s[-1] if s else None}
    return out


def attribute(spaces):
    """Map each workspace UUID to the processes it owns.

    Primary key is the inherited CMUX_WORKSPACE_ID (exact). Processes that lost
    it — daemonised helpers such as agent-browser, which reparent to init —
    fall back to longest-prefix cwd matching, so a workspace rooted at /repo
    cannot swallow a nested worktree workspace at /repo/.claude/worktrees/x.

    Keyed by UUID and not by `ref`, because a ref is POSITIONAL: `workspace:12`
    is whatever sits twelfth right now. Targets are resolved in one scan and
    attributed in another, so a workspace closing in between shifts every ref
    after it — and this map is what decides which processes get SIGKILLed. A
    uuid cannot slide onto a different workspace.
    """
    table = ps_table()
    known = {w["id"] for w in spaces}

    interesting = {
        pid: info for pid, info in table.items()
        if is_claude(info["cmd"]) or kill_kind(info["cmd"])
    }
    envs = read_env(interesting.keys())

    dirs = sorted(
        ((w.get("current_directory") or "").rstrip("/"), w["id"])
        for w in spaces if w.get("current_directory")
    )
    dirs.sort(key=lambda t: -len(t[0]))

    by_ws, unmapped = {}, []
    for pid, info in interesting.items():
        env = envs.get(pid, {})
        ws_id = env.get("workspace") or ""
        entry = {"pid": pid, "cmd": info["cmd"], "rss": info["rss"],
                 "start": info.get("start"),
                 "surface": env.get("surface") or "", "cwd": None}
        if ws_id in known:
            by_ws.setdefault(ws_id, []).append(entry)
        else:
            unmapped.append((pid, entry))

    for pid, entry in unmapped:
        cwd = (proc_cwd(pid) or "").rstrip("/")
        if not cwd:
            continue
        entry["cwd"] = cwd
        for d, ws_id in dirs:
            if d and (cwd == d or cwd.startswith(d + "/")):
                by_ws.setdefault(ws_id, []).append(entry)
                break
    return by_ws


# --- Process inspection ------------------------------------------------------
def lsof_field(pid, *extra):
    r = subprocess.run(["lsof", "-nP", "-a", "-p", str(pid), *extra, "-Fn"],
                       capture_output=True, text=True)
    return [line[1:] for line in r.stdout.splitlines() if line.startswith("n")]


def proc_cwd(pid):
    vals = lsof_field(pid, "-d", "cwd")
    return vals[0] if vals else None


def proc_start_epoch(pid):
    """Process start time, derived from ps etime ([[dd-]hh:]mm:ss)."""
    r = subprocess.run(["ps", "-p", str(pid), "-o", "etime="],
                       capture_output=True, text=True)
    secs = etime_seconds(r.stdout)
    return None if secs is None else time.time() - secs


def project_dir(cwd):
    """~/.claude/projects/<cwd with / and . replaced by ->"""
    return Path.home() / ".claude" / "projects" / re.sub(r"[/.]", "-", cwd)


def resume_binding(ws_id, surface_id=None):
    """cmux's own record of how to restart an agent surface.

    Maintained by the cmux Claude Code hook, so it is the authoritative
    session id — and it carries the ORIGINAL command line, which hand-building
    `claude --resume <id>` would silently strip (losing e.g.
    --dangerously-skip-permissions and changing how the session behaves).
    """
    args = ["surface", "resume", "get", "--workspace", ws_id]
    if surface_id:
        args += ["--surface", surface_id]
    try:
        data = json.loads(cmux(*args, "--json", check=True, retries=1))
    except (RuntimeError, json.JSONDecodeError):
        return {}
    b = data.get("resume_binding") or {}
    if data.get("cleared") or b.get("kind") != "claude":
        return {}
    return {"session_id": b.get("checkpoint_id"), "cwd": b.get("cwd"),
            "command": b.get("command"), "source": "cmux-binding"}


def argv_session_id(cmd):
    """The session uuid out of a process argv (claude's own or its wrapper).

    Both spellings matter. cmux starts a fresh agent with `--session-id`, and
    matching only `--resume` left 18 of 54 live sessions here invisible: they
    fell through to the last-resort transcript scan even though their id was
    sitting in plain sight, and `unpark`'s "already running" guard could not
    see them at all.
    """
    # Case-insensitive and `=`-tolerant on purpose: SESSION_ID_RE accepts
    # A-F, so a lowercase-only scan here made an uppercase id invisible to
    # `unpark`'s "already running" guard — and that guard is the only thing
    # standing between a double resume and two processes appending to one
    # transcript.
    m = re.search(
        r"--(?:resume|session-id)['\"\s=]+([0-9a-fA-F]{8}-[0-9a-fA-F-]{27})",
        cmd)
    return m.group(1) if m else None


# Flags worth carrying across a park when cmux has no binding for the session.
# Deliberately a whitelist: `ps` joins argv with spaces, so any argument that
# itself contains spaces — notably the --settings JSON cmux passes — cannot be
# split back correctly, and replaying a mangled one makes claude refuse to
# start ("Invalid JSON provided to --settings"). The shim re-supplies settings
# and hooks anyway.
ARGV_FLAGS_BOOL = ("--dangerously-skip-permissions", "--verbose")
ARGV_FLAGS_VALUE = ("--model", "--permission-mode")


def command_from_argv(cmd, sid, cwd):
    """Rebuild a resume command from a running claude's own argv.

    Without this the argv fallback drops every flag the session was started
    with — most visibly --dangerously-skip-permissions, so a resumed session
    silently starts asking for permissions again.
    """
    parts = cmd.split()
    flags = []
    for i, tok in enumerate(parts):
        if tok in ARGV_FLAGS_BOOL:
            flags.append(tok)
        elif tok in ARGV_FLAGS_VALUE and i + 1 < len(parts):
            # Quote the VALUE too. It comes from ps, and the result is handed to
            # `/bin/sh -c` (and typed into a pane); a process can put anything in
            # its own argv, so an unquoted `--model ;curl$IFS...|sh` would run on
            # the next unpark, disguised as a resume.
            flags += [tok, shlex.quote(parts[i + 1])]
    return (f"cd {shlex.quote(cwd)} && claude --resume {shlex.quote(sid)}"
            + ("".join(f" {f}" for f in flags)))


def with_shim(cmd):
    """Run claude through cmux's wrapper shim when there is one.

    Bypassing it works, but cmux stops maintaining the workspace's agent
    binding and status pill for that session.

    Only the token in COMMAND position is rewritten. Matching the first
    `claude` anywhere rewrote the `cd` target for anyone whose checkout is at
    `~/projects/claude`: the cd then pointed into the shim dir, `&&`
    short-circuited, and unpark reported "resumed" for a session that never
    started.
    """
    shim = os.environ.get("CMUX_CLAUDE_WRAPPER_SHIM")
    if not shim or not os.access(shim, os.X_OK):
        return cmd
    return re.sub(r"(^|&&\s*|\|\|\s*|;\s*)((?:\S*/)?claude)(?=\s|$)",
                  lambda m: f"{m.group(1)}{shlex.quote(shim)}",
                  cmd, count=1)


def resolve_session(pid, cmd, ws_id, surface_id, cwd):
    """Resolve a live claude process to (session_id, transcript, command, source).

    Order matters. The sibling resume-cmux-sessions skill records that a loose
    "newest .jsonl in the worktree dir" lookup silently grabs an OLD session, so
    it is the last resort and every earlier source is preferred.
    """
    argv_sid = argv_session_id(cmd)
    for cand in (resume_binding(ws_id, surface_id),
                 {"session_id": argv_sid, "cwd": cwd,
                  "command": command_from_argv(cmd, argv_sid, cwd) if argv_sid
                  else None, "source": "argv"}):
        sid = cand.get("session_id")
        # cmux's checkpoint_id is JSON we did not write; the scan's is a raw
        # filename stem. Nothing that fails this gets near a shell.
        if not sid or not SESSION_ID_RE.match(str(sid)):
            continue
        # Try the candidate's own cwd first, then the process's. cmux's binding
        # records the REPO ROOT for an agent running in a worktree under it, so
        # insisting on the binding's cwd threw away an authoritative session id
        # and fell through to the transcript scan.
        for use_cwd in (cand.get("cwd"), cwd):
            if not use_cwd:
                continue
            t = project_dir(use_cwd) / f"{sid}.jsonl"
            if not t.exists():
                continue
            # Replay the recorded command ONLY if it belongs to the cwd we
            # matched; it starts with `cd <binding cwd>`, so reusing it after
            # falling back to the process cwd would resume in the wrong tree.
            command = (cand.get("command") if use_cwd == cand.get("cwd")
                       else command_from_argv(cmd, sid, use_cwd))
            return sid, str(t), command, cand["source"], use_cwd

    sid, transcript, source = session_id_of(pid, cwd)
    if sid and SESSION_ID_RE.match(sid):
        return sid, transcript, command_from_argv(cmd, sid, cwd), source, cwd
    return None, None, None, None, cwd


def session_id_of(pid, cwd=None):
    """Resolve the session transcript for a running claude process.

    Preferred: the transcript it holds open — but ONLY one living in the
    project dir for its own cwd. A claude process keeps other projects'
    transcripts open too, so taking the first match off lsof resumes a
    completely unrelated session.

    Claude also does not keep the fd open for the life of the process, so fall
    back to the newest transcript in the cwd's project dir written AFTER the
    process started — a repo root can hold hundreds of stale transcripts, and
    only that time bound makes "newest" mean "this session".

    Returns (session_id, transcript, source). The source must be reported, not
    re-derived by the caller: both branches return a path that exists, so
    testing the path cannot tell the safe fd hit apart from the last-resort
    guess — and that distinction is the whole point of the ordering.
    """
    if not cwd:
        return None, None, None
    d = project_dir(cwd)

    for path in lsof_field(pid):
        m = re.search(r"/\.claude/projects/[^/]+/([0-9a-f-]{36})\.jsonl$", path)
        if m and Path(path).parent == d:
            return m.group(1), path, "lsof"

    if not d.is_dir():
        return None, None, None
    started = proc_start_epoch(pid)
    if started is None:
        return None, None, None
    best = None
    for f in d.glob("*.jsonl"):
        try:
            mt = f.stat().st_mtime
        except OSError:
            continue
        if mt >= started and (best is None or mt > best[1]):
            best = (f, mt)
    if not best:
        return None, None, None
    return best[0].stem, str(best[0]), "scan"


def cpu_snapshots(seconds=2.0):
    """Two system-wide %CPU readings, `seconds` apart.

    Split out from `cpu_sample` so a batch can share one window: the reading is
    system-wide anyway, and it corroborates ten workspaces exactly as well as
    one — a ten-target park used to pay for ten separate 2 s waits.
    """
    def snap():
        r = subprocess.run(["ps", "-Ao", "pid=,%cpu="], capture_output=True,
                           text=True)
        d = {}
        for line in r.stdout.splitlines():
            parts = line.split()
            if len(parts) == 2:
                try:
                    d[int(parts[0])] = float(parts[1])
                except ValueError:
                    pass
        return d
    a = snap()
    time.sleep(seconds)
    b = snap()
    return a, b


def cpu_sample(pids, seconds=2.0, snaps=None):
    """Peak summed %CPU across two samples — corroborates the status pill.

    NOT a delta. macOS `%cpu` is already a decaying average, so subtracting two
    samples measures acceleration: a session pinned at 100% produced deltas of
    -4.1, +3.5, -42.1 — every one of them under the 15% threshold, so the gate
    that exists to catch a busy session waved it through.
    """
    a, b = snaps if snaps else cpu_snapshots(seconds)
    return max(sum(a.get(p, 0.0) for p in pids),
               sum(b.get(p, 0.0) for p in pids))


def runs_binary(cmd, names):
    """Is one of `names` the program this command line actually runs?

    Checks the command token and, when that is an interpreter or a wrapper,
    whatever it goes
    on to run — so `node .bin/vite` and `node .../nuxi/bin/nuxi.mjs` count while
    `rg webpack src/` and `vim vite.config.ts` do not. Compares basenames, so a
    match must be the last path component rather than any directory along the
    way, and drops one script extension so `nuxi.mjs` reads as `nuxi` while
    `vite.config.ts` stays `vite.config`.
    """
    skip_next = False
    for tok in cmd.split():
        if skip_next:
            skip_next = False
            continue
        if ENV_ASSIGNMENT_RE.match(tok):
            continue
        if tok.startswith("-") and tok not in LAUNCHERS:
            skip_next = tok in VALUE_FLAGS
            continue
        base = tok.rsplit("/", 1)[-1]
        stem = re.sub(r"\.(?:mjs|cjs|js|ts)$", "", base)
        if base in names or stem in names:
            return True
        if base not in LAUNCHERS:
            return False
    return False


def kill_kind(cmd):
    """'dev-server', 'test-browser' or None — what park stops but never restarts.

    One definition for both readers. `attribute` runs first and gates what
    `classify` ever sees, so a second copy of these predicates would not merely
    disagree with this one — it would drop processes silently.
    """
    if runs_binary(cmd, NEVER_KILL):
        return None  # the user's editor/pager/VCS is never a target
    if TEST_BROWSER_RE.search(cmd) or runs_binary(cmd, BROWSER_BINARIES):
        return "test-browser"
    if DEV_SERVER_RE.search(cmd) or runs_binary(cmd, DEV_BINARIES):
        return "dev-server"
    return None


def is_claude(cmd):
    """A root claude session, matched on the program rather than the path.

    `(^|/)claude(\\s|$)` also matched `vim /tmp/claude` and `tail -f
    /var/log/claude` — which then got the workspace's real cmux binding, were
    recorded as sessions, and were killed along with their descendants while
    park reported the workspace parked.
    """
    return runs_binary(cmd, CLAUDE_BINARIES)


def classify(procs, table=None):
    """Split a workspace's processes into claude / dev servers / test browsers.

    Only ROOT claude processes are returned: a session spawns subagent claudes
    as children, and killing the root takes the whole tree with it. Reading a
    session id off a subagent would park the wrong transcript.
    """
    table = table or ps_table()
    claude_all, dev, browser = [], [], []
    for p in procs:
        cmd = p.get("cmd") or ""
        if is_claude(cmd):
            claude_all.append(p)
            continue
        kind = kill_kind(cmd)
        if kind == "test-browser":
            browser.append(p)
        elif kind == "dev-server":
            dev.append(p)

    claude_pids = {p["pid"] for p in claude_all}

    def has_claude_ancestor(pid):
        seen, cur = set(), table.get(pid, {}).get("ppid")
        while cur and cur > 1 and cur not in seen:
            seen.add(cur)
            if cur in claude_pids:
                return True
            cur = table.get(cur, {}).get("ppid")
        return False

    claude = [p for p in claude_all if not has_claude_ancestor(p["pid"])]
    return claude, dev, browser


def tree_pids(procs, table):
    """Every pid `kill_tree` would reach from these roots, the roots included."""
    kids = {}
    for pid, info in table.items():
        kids.setdefault(info["ppid"], []).append(pid)
    seen, stack = set(), [x["pid"] for x in procs]
    while stack:
        cur = stack.pop()
        if cur in seen:
            continue
        seen.add(cur)
        stack.extend(kids.get(cur, []))
    return seen


def tree_rss(procs, table):
    """RSS of everything `kill_tree` would actually take, deduplicated.

    Summing only the matched roots undercounted badly — a claude session's
    subagents, MCP servers and node helpers are killed with it but were never
    counted, so a workspace reporting 67 MB was really holding 208 MB. Measured
    across 38 live workspaces: 4.5 GB reported vs 5.2 GB actually killed.

    (RSS double-counts pages shared between processes, so the true figure sits
    somewhere below this — but this is the set of processes that go.)
    """
    return sum(table[c]["rss"] for c in tree_pids(procs, table) if c in table)


def self_pids(table=None):
    """Our own pid and every ancestor of it.

    Anything an agent runs is a descendant of its claude session, so this chain
    is the whole test for "am I inside what I am about to kill".
    """
    table = table if table is not None else ps_table()
    chain, pid = set(), os.getpid()
    while pid and pid not in chain:
        chain.add(pid)
        pid = table.get(pid, {}).get("ppid", 0)
    return chain


def kill_tree(pid, sig=15):
    """SIGTERM a pid and its descendants, children first.

    Reads ps fresh rather than taking a caller's snapshot: a session spawns
    subagents continuously, and a stale map leaves them running.
    """
    children = {}
    for child, info in ps_table().items():
        children.setdefault(info["ppid"], []).append(child)
    order, stack = [], [pid]
    while stack:
        cur = stack.pop()
        order.append(cur)
        stack.extend(children.get(cur, []))
    killed = []
    for p in reversed(order):
        try:
            os.kill(p, sig)
            killed.append(p)
        except (ProcessLookupError, PermissionError):
            pass
    return killed


def still_running(procs):
    """Which of these processes are still holding resources.

    `kill(pid, 0)` answers the wrong question twice. A zombie answers it
    happily — it keeps a process-table entry until its parent reaps it, and
    park kills children before parents, so the naive check reports the very
    processes it just killed as survivors and triggers the rollback below.
    EPERM is the opposite trap: the process is alive, we simply may not signal
    it, and reading that as dead reports RAM freed that never was.

    One `ps` sweep answers both: absent is gone, `Z` is a corpse waiting to be
    reaped, anything else is really running.
    """
    r = subprocess.run(["ps", "-Ao", "pid=,state="], capture_output=True,
                       text=True)
    states = {}
    for line in r.stdout.splitlines():
        parts = line.split()
        if len(parts) == 2:
            try:
                states[int(parts[0])] = parts[1]
            except ValueError:
                pass
    return [p for p in procs
            if not states.get(p["pid"], "Z").startswith("Z")]


def wait_gone(procs, timeout, step=0.15):
    """Poll until these processes are gone, up to `timeout`. Returns the rest.

    A fixed sleep charged every park its worst case. A claude session and its
    children normally go in well under 200 ms, and this wait was the second
    biggest slice of a multi-workspace park after the CPU window.
    """
    left = still_running(procs)
    deadline = time.time() + timeout
    while left and time.time() < deadline:
        time.sleep(step)
        left = still_running(left)
    return left


# --- Ledger ------------------------------------------------------------------
def ensure_ledger_dir():
    """Create the ledger dir 0700, and tighten it if it already exists.

    `mkdir(mode=0o700, exist_ok=True)` does NOT chmod an existing directory, so
    a ledger created by an earlier version stays world-readable — and its
    entries record cwds, branches and the user's last prompt.
    """
    LEDGER.mkdir(parents=True, exist_ok=True, mode=0o700)
    if stat.S_IMODE(LEDGER.stat().st_mode) & 0o077:
        LEDGER.chmod(0o700)


def ledger_path(ws_id):
    """Path for a workspace's entry, refusing anything that escapes the ledger.

    The id normally comes from cmux, but `rebuild`, `forget` and `unpark` also
    take it from the ledger file's own contents — and `LEDGER / f"{ws_id}.json"`
    happily resolves "../settings" or an absolute path, at which point unlink()
    deletes a file outside the ledger entirely.
    """
    if not re.fullmatch(r"[A-Za-z0-9._-]+", str(ws_id or "")):
        die(f"refusing to use {ws_id!r} as a ledger key")
    return LEDGER / f"{ws_id}.json"


def op_lock_path(ws_id):
    return ledger_path(ws_id).with_suffix(".op.lock")


def stale_op_lock(path):
    """Is this lock a corpse? Its owner is gone, or it is impossibly old."""
    try:
        owner = int((path.read_text().strip() or "0").split()[0])
        age = time.time() - path.stat().st_mtime
    except (OSError, ValueError, IndexError):
        return True                       # unreadable: nothing to wait for
    if age > OP_LOCK_STALE_SECONDS:
        return True
    if not owner or owner == os.getpid():
        return False
    try:
        os.kill(owner, 0)
    except ProcessLookupError:
        return True
    except PermissionError:
        pass
    return False


def acquire_op_lock(ws_id):
    """One park or unpark per workspace at a time. -> path, or None if busy.

    Claiming the LEDGER ENTRY is not enough, because park publishes that entry
    BEFORE it kills anything. In that window an unpark of the same workspace
    reads it, sees every session still live, takes the "already running" path
    and deletes the entry — and then park kills the sessions whose only resume
    record has just been removed. Two unparks in parallel are the same story
    from the other side: both read the entry, both send the resume command, two
    processes end up appending to one transcript.

    Held for the whole transaction, so it has to survive a park that was
    SIGKILLed mid-run: the owner pid is written into it, and a lock whose owner
    is gone is not a lock.
    """
    ensure_ledger_dir()
    path = op_lock_path(ws_id)
    for attempt in (0, 1):
        try:
            fd = os.open(str(path), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        except FileExistsError:
            if attempt or not stale_op_lock(path):
                return None
            path.unlink(missing_ok=True)
            continue
        with os.fdopen(fd, "w") as fh:
            fh.write(str(os.getpid()))
        return path
    return None


def release_op_lock(path):
    if path:
        Path(path).unlink(missing_ok=True)


def read_entry(path):
    """Load one ledger entry, normalised so consumers can index it freely.

    Returns None if the file is unreadable — callers that report on the
    ledger (doctor) must surface that rather than treat it as absent.
    """
    try:
        e = json.loads(path.read_text())
    except (ValueError, OSError):
        return None
    if not isinstance(e, dict):
        return None
    e.setdefault("sessions", [])
    e.setdefault("killed", [])
    e.setdefault("git", {})
    e["title"] = e.get("title") or (Path(e["cwd"]).name if e.get("cwd") else "")
    return e


def read_ledger(with_broken=False):
    """Every parked entry.

    `with_broken` also yields a {"__broken__": path} marker for files that will
    not parse, which doctor needs — silently dropping them made it report a
    truncated entry as no entry at all, while park still said "already parked".
    """
    ensure_ledger_dir()
    out = []
    for f in sorted(LEDGER.glob("*.json")):
        e = read_entry(f)
        if e is not None:
            out.append(e)
        elif with_broken:
            out.append({"__broken__": str(f)})
    return out


def write_entry(path, entry, claim=False):
    """Write a ledger entry atomically.

    `claim=True` fails if the entry already exists, which is what makes the
    "already parked" guard safe: the check and the write used to straddle a 2s
    CPU sample, so two concurrent parks both passed it and both pre-filled the
    prompt.
    """
    ensure_ledger_dir()
    blob = json.dumps(entry, indent=2)
    if claim:
        # O_EXCL on the FINAL path would leave a half-written .json if this is
        # interrupted; claim a lock file instead and rename the finished blob in.
        lock = path.with_suffix(".json.lock")
        # The lock is held for the few milliseconds between creating it and
        # renaming it into place, so anything older is a corpse — a park that
        # was SIGKILLed mid-write. Left alone it wedges the workspace for good:
        # every later park reads "already parked" while no entry exists, so
        # unpark and forget both answer "not parked" and nothing short of `rm`
        # gets it back.
        try:
            if time.time() - lock.stat().st_mtime > LOCK_STALE_SECONDS:
                lock.unlink(missing_ok=True)
        except OSError:
            pass
        try:
            fd = os.open(str(lock), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        except FileExistsError:
            return False
        if path.exists():
            os.close(fd)
            lock.unlink(missing_ok=True)
            return False
        try:
            with os.fdopen(fd, "w") as fh:
                fh.write(blob)
            os.replace(str(lock), str(path))
        except BaseException:
            lock.unlink(missing_ok=True)
            raise
        return True
    # Same 0600 as the claim path: an entry records the cwd, the branch and the
    # user's last prompt, and write_text would leave it umask-derived (0644).
    tmp = path.with_suffix(".json.tmp")
    fd = os.open(str(tmp), os.O_CREAT | os.O_TRUNC | os.O_WRONLY, 0o600)
    with os.fdopen(fd, "w") as fh:
        fh.write(blob)
    os.replace(str(tmp), str(path))
    return True


def git_info(cwd):
    """Branch + dirty count in ONE git call.

    Both the listing and the ledger need exactly these two, and five
    `git rev-parse` calls per workspace cost 4.4s across 45 workspaces. The
    git-dir side of the checkout is `worktree_fingerprint`'s job.
    """
    if not cwd or not Path(cwd).exists():
        return {}
    r = subprocess.run(["git", "-C", cwd, "status", "--porcelain=v1", "-b",
                        "--no-renames"], capture_output=True, text=True)
    if r.returncode != 0:
        return {}
    lines = r.stdout.splitlines()
    branch = None
    if lines and lines[0].startswith("## "):
        branch = lines[0][3:].split("...")[0].strip()
        if branch.startswith("No commits yet on "):
            branch = branch[len("No commits yet on "):]
        lines = lines[1:]
    return {"branch": branch, "dirty_files": len(lines)}


# --- Resolve targets ---------------------------------------------------------
def resolve_targets(args, spaces=None):
    """Accept workspace refs/UUIDs/titles, `window:N`, or `.`.

    `spaces` lets a caller that already has the list hand it over. Listing the
    workspaces is a socket round-trip per window (0.42 s here), and `park .`
    used to pay it twice: once to work out what `.` means and once more to
    attribute processes to it.
    """
    spaces = all_workspaces() if spaces is None else spaces
    by_ref = {w["ref"]: w for w in spaces}
    by_id = {w["id"]: w for w in spaces}
    out, seen = [], set()

    def add(w):
        if w["id"] not in seen:
            seen.add(w["id"])
            out.append(w)

    for a in args:
        if a == ".":
            # `selected` is per WINDOW, so falling back to it would resolve `.`
            # to one workspace in every window — `park park .` from a plain
            # Terminal would kill a session in each of them. There is no
            # sensible current workspace outside a cmux pane; say so instead.
            cur = os.environ.get("CMUX_WORKSPACE_ID")
            if not cur:
                die("`.` means the workspace you are in, and this shell is not "
                    "in a cmux pane — name a target explicitly")
            if cur not in by_id:
                die(f"`.` resolved to {cur}, which cmux does not list — "
                    "name a target explicitly")
            add(by_id[cur])
            continue
        m = re.match(r"^window:(\d+)$", a)
        if m:
            hit = [w for w in spaces if w.get("window_ref") == a]
            if not hit:  # fall back to the 0-based list-windows index
                hit = [w for w in spaces if w["window_index"] == int(m.group(1))]
            if not hit:
                die(f"no window matches '{a}'")
            for w in hit:
                add(w)
            continue
        if a in by_ref:
            add(by_ref[a])
            continue
        if a in by_id:
            add(by_id[a])
            continue
        matches = [w for w in spaces if a.lower() in (w["title"] or "").lower()]
        if len(matches) == 1:
            add(matches[0])
        elif len(matches) > 1:
            die(f"'{a}' matches {len(matches)} workspaces: "
                + ", ".join(f"{w['ref']} {w['title'][:30]}" for w in matches))
        else:
            orphan = orphan_target(a, by_id)
            if orphan:
                add(orphan)
                continue
            die(f"no workspace matches '{a}'")
    return out


DURATION_RE = re.compile(r"^(\d+(?:\.\d+)?)\s*([smhdw])$")
DURATION_UNITS = {"s": 1, "m": 60, "h": 3600, "d": 86400, "w": 604800}


def parse_duration(text):
    """`3d`, `12h`, `90m` -> seconds. Dies on anything else.

    Deliberately unit-only: a bare `park park --idle 3` could mean seconds or
    days, and one of those parks the whole machine.
    """
    m = DURATION_RE.match(str(text).strip().lower())
    if not m:
        die(f"cannot read {text!r} as a duration — use 30m, 6h, 3d or 2w")
    return float(m.group(1)) * DURATION_UNITS[m.group(2)]


def human_duration(seconds):
    for unit, size in (("d", 86400), ("h", 3600), ("m", 60)):
        if seconds >= size:
            n = seconds / size
            return f"{n:.0f}{unit}" if n == int(n) else f"{n:.1f}{unit}"
    return f"{seconds:.0f}s"


def flag_value(argv, name):
    """Pull `--flag V` / `--flag=V` out of argv. -> (seconds, argv without it)

    Returned separately because the value would otherwise be left sitting in
    argv as a positional — and a positional to `park park` is a workspace.
    """
    out, value = [], None
    skip = False
    for i, a in enumerate(argv):
        if skip:
            skip = False
            continue
        if a == name:
            if i + 1 >= len(argv):
                die(f"{name} needs a duration, e.g. {name} 3d")
            value = parse_duration(argv[i + 1])
            skip = True
            continue
        if a.startswith(name + "="):
            value = parse_duration(a.split("=", 1)[1])
            continue
        out.append(a)
    return value, out


def targets_from(argv, msg="no target", spaces=None):
    """Positional args -> workspaces. Every command takes targets this way.

    resolve_targets dies on an arg it cannot match, so an empty result can only
    mean the command was given no target at all.
    """
    targets = resolve_targets([a for a in argv if not a.startswith("--")],
                              spaces)
    if not targets:
        die(msg)
    return targets


def orphan_target(a, live_by_id):
    """A parked entry whose cmux workspace is gone, matched by uuid or title.

    Without this the ledger's whole selling point leaks: once cmux loses a
    workspace, its entry can no longer be named, so `show`, `forget` and
    `unpark` all answer "no workspace matches" and the entry is unremovable
    except by hand — while `doctor` flags it forever.
    """
    hits = []
    for e in read_ledger():
        ws_id = e.get("workspace_id")
        if not ws_id or ws_id in live_by_id:
            continue
        title = e.get("title") or ""
        if a in (ws_id, e.get("workspace_ref")) or a.lower() in title.lower():
            hits.append({"id": ws_id, "ref": e.get("workspace_ref") or ws_id,
                         "title": title, "window_id": e.get("window_id"),
                         "orphan": True})
    # The live path dies on an ambiguous title; taking the first match here
    # would let `park forget api` drop whichever of api-main/api-worker sorted
    # first, with no way to tell which one went.
    if len(hits) > 1:
        die(f"'{a}' matches {len(hits)} parked entries whose workspace is gone: "
            + ", ".join(f"{h['id'][:8]} {h['title'][:30]}" for h in hits))
    return hits[0] if hits else None


def die(msg):
    print(f"error: {msg}", file=sys.stderr)
    sys.exit(1)


def mb(n):
    return n / 1024 / 1024


def human(n):
    return f"{mb(n) / 1024:.1f} GB" if mb(n) >= 1024 else f"{mb(n):.0f} MB"


# --- Commands ----------------------------------------------------------------
def bar(value, peak, width=10, plain=False):
    """Tiny RAM bar, so the heavy workspaces are findable at a glance.

    `plain` uses ASCII: inside curses the multibyte block/dot pair renders as
    U+FFFD from a certain byte length onwards, so the picker asks for ASCII.
    """
    if peak <= 0:
        return " " * width
    filled = max(1, round(width * value / peak)) if value > 0 else 0
    full, empty = ("=", "-") if plain else ("█", "·")
    return full * filled + empty * (width - filled)


def group_by_window(rows):
    """[(window label, rows)] — windows in order, heaviest live first.

    Both the listing and the picker show the same grouping; keeping one
    ordering means they cannot drift into disagreeing about what is where.
    """
    windows = {}
    for r in rows:
        windows.setdefault(r["window_ref"] or f"window?{r['window_index']}",
                           []).append(r)
    return [(win, sorted(windows[win], key=lambda r: (r["parked"], -r["bytes"])))
            for win in sorted(windows, key=lambda k: windows[k][0]["window_index"])]


def flags_of(r):
    """`2d 1b ~3` — dev servers, test browsers, dirty files. Empty when none."""
    parts = []
    if r["dev"]:
        parts.append(f"{r['dev']}d")
    if r["browser"]:
        parts.append(f"{r['browser']}b")
    if r["dirty"]:
        parts.append(f"~{r['dirty']}")
    return " ".join(parts)


def collect(spaces=None):
    """One pass over every workspace -> rows ready for display or JSON."""
    spaces = spaces if spaces is not None else all_workspaces()
    parked = {p["workspace_id"]: p for p in read_ledger()}
    by_ws = attribute(spaces)
    table = ps_table()

    # Narrow to rows we will actually show BEFORE the expensive per-workspace
    # lookups: status is a ~256 ms cmux round-trip and git is a subprocess.
    keep = []
    for w in spaces:
        procs = by_ws.get(w["id"], [])
        claude, dev, browser = classify(procs, table) if procs else ([], [], [])
        # Normalised to {} so the ledger-or-live fallbacks below can just be
        # `entry.get(x) or w.get(y)`. read_entry never yields an empty dict, so
        # this stays a faithful "is it parked" truth value.
        entry = parked.get(w["id"]) or {}
        if entry or claude:
            keep.append((w, procs, claude, dev, browser, entry))

    # Status and git are independent, so overlap the two fan-outs as well.
    with ThreadPoolExecutor(max_workers=2) as ex:
        f_state = ex.submit(
            pmap, lambda kw: workspace_status(kw[0]["id"]).get("claude_code", ""),
            keep)
        f_git = ex.submit(
            pmap, lambda kw: kw[5].get("git")
            or git_info(kw[0].get("current_directory")) or {}, keep)
        states, gits = f_state.result(), f_git.result()

    # The pill sticks: a workspace can read `Running` long after its turn ended,
    # and a display that calls it busy makes it untoggleable in the picker even
    # though `park` would now accept it. cmux's own latest_submitted_at is a
    # free proxy — globbing project dirs for the real transcript turned a 1.6 s
    # scan into 16 s. It is only a HINT: `park_one` still checks the resolved
    # session's transcript, so the worst case is a row that offers itself and
    # then refuses with a reason.
    stales = [st.lower() in BUSY_STATES
              and seconds_since(w.get("latest_submitted_at")) >= STALE_PILL_SECONDS
              for (w, _, _, _, _, _), st in zip(keep, states)]

    rows = []
    for (w, procs, claude, dev, browser, entry), state, g, is_stale in zip(
            keep, states, gits, stales):
        last = (w.get("latest_submitted_message") or "").strip().replace("\n", " ")
        # A ledger entry AND a live session. Something resumed this workspace
        # behind park's back — a hand-run `cmux restore` after a reset does it,
        # and it happened to 12 sessions here in one afternoon. The row used to
        # claim "parked" and report the megabytes it freed days ago, which is
        # both wrong and the reason nobody notices.
        conflict = bool(entry) and bool(claude)
        rows.append({
            "ref": w["ref"], "id": w["id"],
            # cmux falls back to showing the directory once the agent is gone,
            # so a parked row keeps the title captured while it was alive.
            "title": entry.get("title") or w["title"] or "",
            "window_ref": w.get("window_ref", ""),
            "window_id": w.get("window_id", ""),
            "window_index": w["window_index"],
            "parked": bool(entry),
            "conflict": conflict,
            "bytes": (entry.get("freed_bytes", 0) if entry and not conflict
                      else tree_rss(procs, table)),
            # What parking this workspace released, as recorded at the time.
            # `bytes` is what it holds NOW, and for a conflicted row those are
            # two different numbers with two different meanings — a --json
            # consumer should not have to guess which one it got.
            "freed_bytes": entry.get("freed_bytes", 0),
            "state": (state + " (stale)") if is_stale else (state or "-"),
            "busy": state.lower() in BUSY_STATES and not is_stale,
            "dev": len(dev), "browser": len(browser),
            "branch": g.get("branch"), "dirty": g.get("dirty_files") or 0,
            "note": entry.get("note") or last,
            "since": entry.get("parked_at") or w.get("latest_submitted_at"),
            "cwd": entry.get("cwd") or w.get("current_directory"),
        })
    return rows


def cmd_ls(argv):
    with Spinner("scanning workspaces…"):
        rows = collect()
    if "--json" in argv:
        print(json.dumps(rows, indent=2))
        return
    if not rows:
        print("  nothing to show\n")
        return

    peak = max((r["bytes"] for r in rows), default=1)

    # A conflicted row holds real memory right now, so it counts as live — and
    # it is not parkable, because park will answer "already parked" until the
    # entry is cleared.
    def live_now(r):
        return not r["parked"] or r["conflict"]

    tot_parked = sum(r["bytes"] for r in rows if not live_now(r))
    tot_live = sum(r["bytes"] for r in rows if live_now(r))
    tot_free = sum(r["bytes"] for r in rows
                   if not r["parked"] and not r["busy"])

    for win, group in group_by_window(rows):
        live = sum(r["bytes"] for r in group if live_now(r))
        freeable = sum(r["bytes"] for r in group
                       if not r["parked"] and not r["busy"])
        print(f"\n  {win}        {len(group):>2} ws"
              f"      {human(live):>9} live"
              f"    {human(freeable):>9} parkable")
        print(f"  {'─' * 84}")
        for r in group:
            if r["conflict"]:
                mark, tail = "⚠", "parked, but live"
            elif r["parked"]:
                mark, tail = "❄", "parked " + ago(r["since"])
            elif r["busy"]:
                mark, tail = "●", r["state"]
            else:
                mark, tail = "○", r["state"]
            extra = flags_of(r)
            flags = f"[{extra}]" if extra else ""
            print(f"  {mark} {r['ref']:<13} {r['title'][:34]:<35}"
                  f" {bar(r['bytes'], peak)} {human(r['bytes']):>8}"
                  f"  {tail:<14}{flags}")

    print(f"\n  {'═' * 84}")
    print(f"  {human(tot_live)} live · {human(tot_parked)} parked · "
          f"{human(tot_free)} parkable right now")
    print("  ❄ parked   ● turn in flight (never parked)   ○ parkable"
          "   [Nd dev · Nb browser · ~N dirty]")
    if any(r["conflict"] for r in rows):
        print("  ⚠ a parked entry with a session running in it — `park unpark` "
              "clears the entry, or `park forget` if you want it left alone")
    print()


def ago(iso):
    """Humanise a timestamp from either source.

    `since` is our own parked_at (`+00:00`) for a parked row but cmux's
    `latest_submitted_at` (`...Z`) for a live one, and Python 3.9's
    fromisoformat rejects the Z form outright.
    """
    if not isinstance(iso, str) or not iso:
        return "?"
    try:
        t = datetime.fromisoformat(iso.replace("Z", "+00:00"))
    except ValueError:
        return "?"
    if t.tzinfo is None:
        t = t.replace(tzinfo=timezone.utc)
    d = datetime.now(timezone.utc) - t
    if d.days:
        return f"{d.days}d ago"
    h = d.seconds // 3600
    return f"{h}h ago" if h else f"{d.seconds // 60}m ago"


def worktree_fingerprint(cwd):
    """What must still be true about the checkout after parking.

    Parking only kills processes, but this is the failure the user was burned
    by before, so it is asserted rather than assumed.
    """
    if not cwd or not Path(cwd).is_dir():
        return None
    r = subprocess.run(["git", "-C", cwd, "rev-parse", "--git-dir",
                        "--git-common-dir"], capture_output=True, text=True)
    if r.returncode != 0:
        return {"exists": True, "git": False}
    parts = r.stdout.split()
    return {"exists": True, "git": True, "git_dir": parts[0] if parts else None,
            "common_dir": parts[1] if len(parts) > 1 else None}


def resume_command_for(session):
    """The command that brings one agent tab back, shim included.

    with_shim belongs here rather than at the call sites: the `cmux send` path
    used to skip it, so every tab resumed that way lost cmux's agent binding
    and status pill. One application point keeps both delivery paths honest.
    """
    return with_shim(session.get("resume_command") or (
        f"cd {shlex.quote(session['cwd'])} && "
        f"claude --resume {shlex.quote(session['session_id'])}"))


def pid_matches(p):
    """Is this pid still the process we measured, or a recycled one?

    Re-reads ps for the single pid rather than trusting the batch snapshot.
    Without this, kill_tree can SIGTERM an unrelated process and its whole
    descendant tree after macOS reuses a pid.

    The command line alone does not settle it: cmux 0.64 starts every agent as
    the same `claude --dangerously-skip-permissions --resume`, so a recycled pid
    running a DIFFERENT workspace's session compares equal. The start time is
    what tells them apart. Both readings come from `ps` etime, which is whole
    seconds, so they can disagree by a second at each end.
    """
    r = subprocess.run(["ps", "-o", "etime=,command=", "-p", str(p["pid"])],
                       capture_output=True, text=True, check=False)
    if r.returncode != 0:
        return False
    parts = r.stdout.strip().split(None, 1)
    if len(parts) < 2 or parts[1].strip() != p["cmd"].strip():
        return False
    was, secs = p.get("start"), etime_seconds(parts[0])
    if was is None or secs is None:
        return True
    return abs((time.time() - secs) - was) <= 3.0


def seconds_since(iso):
    """Age of an ISO timestamp in seconds; inf when missing or unparseable."""
    if not isinstance(iso, str) or not iso:
        return float("inf")
    try:
        t = datetime.fromisoformat(iso.replace("Z", "+00:00"))
    except ValueError:
        return float("inf")
    if t.tzinfo is None:
        t = t.replace(tzinfo=timezone.utc)
    return (datetime.now(timezone.utc) - t).total_seconds()


def transcript_age(path):
    """Seconds since the transcript was last appended to; inf if unknown."""
    try:
        return max(0.0, time.time() - Path(path).stat().st_mtime)
    except OSError:
        return float("inf")


def read_screen(ws_id, surface=None):
    """The visible lines on a surface, or None when they cannot be read.

    Retried, and a failure is reported rather than swallowed: both callers use
    the screen to decide whether they are about to destroy something the user
    typed, and `check=False` hands them an empty screen — indistinguishable
    from a clean one — on any socket hiccup.
    """
    args = ["read-screen", "--workspace", ws_id]
    if surface:
        args += ["--surface", surface]
    try:
        return cmux(*args, retries=2).splitlines()
    except RuntimeError:
        return None


def prompt_line(ws_id, surface=None):
    """The last non-empty line on a surface, or None when it cannot be read.

    A parked tab sits at a SHELL prompt, which `unsent_input` deliberately
    cannot see (it requires the agent's fenced input box), so telling park's
    own prefill apart from something the user typed needs the raw line.
    """
    lines = read_screen(ws_id, surface)
    if lines is None:
        return None
    for line in reversed(lines):
        if line.strip():
            return line.rstrip()
    return ""


# Glyphs a shell prompt ends with. The first group cannot be anything else on
# a line; `$ % #` can — `echo $` ends in one — so they need corroboration.
PROMPT_GLYPHS = "❯»➜›"
AMBIGUOUS_GLYPHS = "$%#"
# What a prompt puts before `$`: a path, or user@host, or nothing at all.
PROMPT_CONTEXT = "/~@:"


def bare_prompt(line):
    """Is this a shell prompt with nothing typed after it?

    Used before typing anything into a surface. The two ways of being wrong are
    not equal: refusing a real prompt loses a re-typed prefill, which `repaint`
    prints and anyone can redo, while accepting a line that has text on it
    appends to the user's half-written command and presses enter. So it refuses
    whenever it cannot tell.

    That is why `$ % #` need a path- or host-looking token in front of them:
    `~/Sites/x $` is a prompt, `echo $` is a command someone is in the middle
    of typing, and the naive "last character is a glyph" test called both bare.
    """
    if not line:
        return False
    line = line.rstrip()
    last = line[-1:]
    if last in PROMPT_GLYPHS:
        return True
    if last not in AMBIGUOUS_GLYPHS:
        return False
    before = line[:-1].strip()
    return not before or any(c in before for c in PROMPT_CONTEXT)


def unsent_input(ws_id, surface=None):
    """Text the user typed but has not submitted, or messages queued behind the
    turn. Killing the session throws both away with no record anywhere.

    Read off the screen, because nothing else exposes it: cmux's status pill,
    the process table and the transcript all describe what claude has already
    accepted, and a draft is by definition not that.

    The agent's input box is a `>` line fenced by box rules; requiring the rule
    above it is what stops a plain shell prompt (starship uses the same glyph)
    from reading as a draft.

    Returns the draft, `""` when the screen was read and held none, and None
    when it could not be read at all — a guard against the one unrecoverable
    loss must not answer "no draft" because the socket hiccuped.
    """
    lines = read_screen(ws_id, surface)
    if lines is None:
        return None
    for i, line in enumerate(lines):
        body = line.strip()
        if not body or body[0] not in "\u276f>":
            continue
        above = lines[i - 1].strip() if i else ""
        if len(above) < 20 or set(above) - set("\u2500-"):
            continue                       # not the fenced input box
        rest = body[1:].strip()
        if rest:
            return rest
    return ""


def live_session_ids(table=None, unresolved=None):
    """Session ids of every claude process running right now.

    argv alone stopped being enough. cmux 0.64 restores an agent as plain
    `claude --dangerously-skip-permissions --resume`, supplying the id out of
    band, so `argv_session_id` returns None for it and the set comes back
    empty. That set is the only thing stopping `unpark` from starting a SECOND
    process on a transcript that is already live, and two processes appending
    to one .jsonl corrupt it. A guard that silently matches nothing is worse
    than no guard: it reads as "checked".

    So anything without an id in argv gets resolved the expensive way, off the
    transcript it holds open. That costs an lsof per such process, which is why
    callers pass the result around instead of recomputing it per workspace.

    Ids come back lowercased: cmux writes uppercase uuids in places and the
    ledger records whatever the source gave, so a case-sensitive `in` test was
    a guard that could quietly match nothing.

    Even the expensive path can fail — lsof denied, cwd unreadable — and a
    session missed here is a session unpark will start a SECOND process on.
    Pass `unresolved` a list to be told which pids those were; the caller can
    then say so out loud instead of the guard failing open in silence.
    """
    table = table if table is not None else ps_table()
    ids = set()
    for pid, info in table.items():
        cmd = info.get("cmd") or ""
        if not is_claude(cmd):
            continue
        sid = argv_session_id(cmd)
        if not sid:
            sid, _, _ = session_id_of(pid, proc_cwd(pid))
        if sid:
            ids.add(sid.lower())
        elif unresolved is not None:
            unresolved.append(pid)
    return ids


def draft_guard(ws_id, claude):
    """Why these tabs must not be killed right now, or None. Reads the screen.

    A draft exists ONLY in the agent's input box — no transcript, no process
    state, nothing on disk — so killing the session is the one operation that
    destroys it silently. Run twice per park: once before the expensive checks
    and once immediately before the kill, because the seconds in between are
    exactly when a user who is looking at the workspace types into it.
    """
    for c in claude:
        draft = unsent_input(ws_id, c.get("surface"))
        if draft is None:
            return "cannot read the prompt to check for unsent text"
        if draft:
            return f"unsent text in the prompt: {draft[:40]!r}"
    return None


def busy_verdict(state, sessions):
    """Decide whether a turn is really in flight. -> (pill_was_stale, refusal)

    Neither signal is trustworthy alone, and they fail in OPPOSITE directions:

    - No pill at all (about a third of workspaces) and a session blocked on a
      slow tool call sits near 0% CPU, so both other gates read "idle" while a
      turn is running. The transcript catches that.
    - The pill also STICKS. A workspace can read `Running` for half an hour
      after the turn ended, and believing it makes that workspace permanently
      unparkable — the user's only way out being `--force`, which throws away
      every other check at the same time.

    So a busy pill has to be corroborated. Quiet for STALE_PILL_SECONDS with
    the CPU gate already passed means the pill is lying. The window is long on
    purpose: a single tool call can legitimately write nothing while it runs,
    and being slow to park costs nothing next to killing a live turn.
    """
    quiet = min((transcript_age(s["transcript"]) for s in sessions),
                default=float("inf"))
    if state.lower() in BUSY_STATES:
        if quiet < STALE_PILL_SECONDS:
            return False, f"turn in flight ({state})"
        return True, None
    if quiet < 20:
        return False, "recent transcript activity (no status pill)"
    return False, None


def park_one(w, by_ws, table, dry=False, force=False, brutal=False,
             snaps=None):
    """Park one workspace, alone. See `_park_one` for what that involves.

    A dry run reads and reports, so it needs no lock; everything else holds the
    workspace for the whole transaction.
    """
    if dry:
        return _park_one(w, by_ws, table, True, force, brutal, snaps)
    lock = acquire_op_lock(w["id"])
    if not lock:
        return {"ref": w["ref"], "title": w.get("title") or "", "ok": False,
                "freed": 0, "notes": [],
                "msg": "another park or unpark is working on this workspace"}
    try:
        return _park_one(w, by_ws, table, False, force, brutal, snaps)
    finally:
        release_op_lock(lock)


def _park_one(w, by_ws, table, dry=False, force=False, brutal=False,
              snaps=None):
    """Park one workspace. Returns a result dict; prints nothing.

    Silence matters: the picker calls this from a worker thread while curses
    owns the screen.

    Two levels of override, because they are not the same risk. `force` waives
    the CPU sample, which is only ever corroboration and is the gate that makes
    a workspace running a heavy tool call look busy for as long as it runs.
    `brutal` (`--kill-anyway`) waives the draft guard and the in-flight verdict
    too — the two things Rule #1 is made of — so it is the only way to lose a
    running turn, and `cmd_park` makes the user type it out and confirm.
    """
    ref, title = w["ref"], (w["title"] or "")
    res = {"ref": ref, "title": title, "ok": False, "freed": 0, "notes": []}

    if ledger_path(w["id"]).exists():
        res["msg"] = "already parked"
        return res
    procs = by_ws.get(w["id"], [])
    claude, dev, browser = classify(procs, table)
    if not claude:
        res["msg"] = "no claude session"
        return res

    # Not a heuristic, and no flag turns it off: kill_tree works leaves-first,
    # so parking the tree park is running inside kills park before it ever
    # reaches the session — ledger written, session dead, and none of the pill,
    # colour or prefill that make a parked workspace recoverable by walking
    # into it. An agent asked to park its own workspace lands here. A new tab
    # (⌘⌥F, or any shell in the workspace) is a child of cmux, not of claude,
    # and parks it fine.
    mine = self_pids(table)
    if any(p["pid"] in mine for p in claude + dev + browser):
        res["msg"] = ("park is running inside this session — "
                      "park it from a new tab")
        return res

    # Checked before anything expensive, and per tab. Repeated below, right
    # before the kill.
    if not brutal:
        why = draft_guard(w["id"], claude)
        if why:
            res["msg"] = why
            return res

    state = workspace_status(w["id"]).get("claude_code", "")

    sessions = []
    for p in claude:
        cwd = p.get("cwd") or proc_cwd(p["pid"])
        sid, transcript, command, source, cwd = resolve_session(
            p["pid"], p["cmd"], w["id"], p.get("surface"), cwd)
        if not sid or not cwd:
            res["msg"] = f"cannot resolve session id/cwd for pid {p['pid']}"
            return res
        if source == "scan":
            res["notes"].append("session id came from a transcript scan, "
                                "not cmux's binding — verify after unpark")
        sessions.append({"session_id": sid, "transcript": transcript,
                         "cwd": cwd, "resume_command": command,
                         "id_source": source, "surface": p["surface"]})

    # The whole tree, not the roots. A turn that shells out to a compiler or a
    # test run leaves the root claude near 0% while the machine is flat out, so
    # sampling roots alone reported "idle" for the busiest workspaces there are
    # — and with no status pill (about a third of them) and a tool call that
    # writes nothing for 20 s, this is the only gate left standing.
    #
    # Read here rather than earlier because `snaps` may still be in flight: the
    # sample is two seconds of sleeping, and everything above — listing,
    # attribution, the draft read, the status round-trip, resolving each
    # session — runs alongside it instead of after it. `--force`/`--kill-anyway`
    # skip the gate, so they never wait for it at all.
    if not (force or brutal):
        window = snaps() if callable(snaps) else snaps
        if cpu_sample(tree_pids(claude, table), snaps=window) > 15.0:
            res["msg"] = "busy (cpu)"
            return res

    if not brutal:
        stale, why = busy_verdict(state, sessions)
        if why:
            res["msg"] = why
            return res
        if stale:
            res["notes"].append(f"status pill said {state!r} but nothing has "
                                "been written for "
                                f"{int(min(transcript_age(s['transcript']) for s in sessions) / 60)}"
                                " min — treated as idle")

    cwd = sessions[0]["cwd"]
    freed = tree_rss(procs, table)
    res["freed"] = freed
    if dry:
        res["ok"] = True
        res["msg"] = (f"would park ({len(claude)} claude, {len(dev)} dev, "
                      f"{len(browser)} browser)")
        return res

    before = worktree_fingerprint(cwd)
    note = (w.get("latest_submitted_message") or "").strip().replace("\n", " ")
    entry = {
        "workspace_id": w["id"], "workspace_ref": ref,
        "window_id": w["window_id"],
        "title": w["title"], "cwd": cwd, "sessions": sessions,
        "git": git_info(cwd),
        "worktree": before,
        # Kept whole and human-readable: unpark only says HOW MANY dev/browser
        # processes it will not restart, and `park show` is where you look up
        # which ones they were.
        "killed": [{"pid": p["pid"], "cmd": p["cmd"][:200], "rss": p["rss"],
                    "kind": k}
                   for k, group in (("dev-server", dev), ("test-browser", browser))
                   for p in group],
        "freed_bytes": freed,
        "parked_at": datetime.now(timezone.utc).isoformat(),
        "note": note[:300], "prev_color": w.get("custom_color"),
    }

    # The topology drifts: a session can start a turn between the busy gate
    # above and this kill. Re-check immediately before mutating.
    if not brutal:
        # The same verdict, not a weaker version of it: re-reading only the
        # pill was a no-op for a workspace that has none, and would have
        # re-refused the stale-pill workspace this just cleared.
        #
        # The pill read and the draft read are independent round-trips, so
        # they go together — this is the last thing standing between the user
        # and a kill, and it should not also be the slowest.
        again, draft = pmap(lambda f: f(), [
            lambda: workspace_status(w["id"]).get("claude_code", ""),
            # Seconds have passed since the first draft check — a CPU window, a
            # status round-trip and a session lookup per tab. Typing into a
            # workspace while looking at it takes less than that, and the draft
            # is the one thing here with no copy anywhere.
            lambda: draft_guard(w["id"], claude)])
        _, why = busy_verdict(again, sessions)
        if why or draft:
            res["msg"] = f"became busy — {why or draft}"
            return res

    # Claiming the ledger file atomically IS the "already parked" guard: the
    # check at the top of this function is minutes-old by now.
    if not write_entry(ledger_path(w["id"]), entry, claim=True):
        res["msg"] = "already parked"
        return res

    # The pid table was sampled before a 2s CPU window and, from cmd_park, once
    # for every target in the batch — so by now a pid may have exited and been
    # reused. kill_tree takes out a whole descendant tree; confirm each pid is
    # still the process we measured before signalling it.
    doomed = browser + dev + claude
    try:
        victims = [p for p in doomed if pid_matches(p)]
    except BaseException:
        # Ctrl-C between the claim and the kill would otherwise leave a complete
        # ledger entry with the session still alive — which `doctor` calls
        # restorable and `unpark` answers by starting a SECOND process on that
        # transcript.
        ledger_path(w["id"]).unlink(missing_ok=True)
        raise
    stale = len(doomed) - len(victims)
    if stale:
        res["notes"].append(f"{stale} process(es) vanished before the kill")
    for p in victims:
        kill_tree(p["pid"])
    survivors = wait_gone(victims, 1.5)
    for p in survivors:                     # escalate rather than report a lie
        kill_tree(p["pid"], sig=signal.SIGKILL)
    stubborn = wait_gone(survivors, 0.5) if survivors else []
    if stubborn and len(still_running(claude)) == len(claude):
        # Nothing irreplaceable is gone yet, so a clean rollback is the honest
        # answer: the ledger would otherwise claim parked while the session is
        # alive, and `unpark` would start a second process on that transcript.
        ledger_path(w["id"]).unlink(missing_ok=True)
        res["msg"] = (f"{len(stubborn)} process(es) survived TERM and KILL — "
                      "left running, nothing recorded")
        return res
    if stubborn:
        # Past this point at least one session is already dead, and the ledger
        # holds the ONLY copy of its id, transcript and resume command. Deleting
        # it to report a tidy failure would destroy exactly what park exists to
        # preserve — over a dev server that would not die. Keep it, and stop
        # counting the survivor's memory as freed.
        freed = max(0, freed - sum(p.get("rss", 0) for p in stubborn))
        res["freed"] = entry["freed_bytes"] = freed
        write_entry(ledger_path(w["id"]), entry)
        res["notes"].append(
            f"{len(stubborn)} process(es) survived TERM and KILL and are still "
            "running: " + ", ".join(f"{p['pid']} {p['cmd'][:40]}"
                                    for p in stubborn))

    # Everything left is independent: a git call and four cmux writes, each a
    # ~250 ms round-trip. Run sequentially they were the largest slice of a
    # single park after the CPU window.
    #
    # The prefill leaves a command TYPED (not run) at every agent tab's prompt,
    # so the workspace comes back by walking into any of them and pressing
    # enter. `park unpark .` rather than the raw resume line: cmux's recorded
    # command is an unreadable escaped one-liner, and this way enter also
    # clears the pill and the ledger. The pill, the colour and the pinned name
    # are how a parked workspace announces itself in the sidebar — losing one
    # silently is how a workspace ends up parked and indistinguishable from a
    # live one, so each failure is reported rather than assumed away.
    jobs = {
        "worktree": lambda: worktree_fingerprint(cwd),
        "prefill": lambda: all(send_text(PREFILL, w["id"], s.get("surface"))
                               for s in sessions),
        "pill": lambda: cmux_do("set-status", PILL_KEY,
                                f"Parked · {human(freed)} freed",
                                "--icon", "snowflake", "--color", "#5AC8FA",
                                "--priority", "90", "--workspace", w["id"]),
        "colour": lambda: cmux_do("workspace-action", "--action", "set-color",
                                  "--color", PARKED_COLOR,
                                  "--workspace", w["id"]),
        "title": lambda: pin_title(w, title),
    }
    names = list(jobs)
    outcome = dict(zip(names, pmap(lambda n: jobs[n](), names)))

    after = outcome["worktree"]
    if before and after != before:
        res["notes"].append(f"WORKTREE CHANGED during park: {before} -> {after}")
    if not outcome["prefill"]:
        res["notes"].append("the resume command could not be typed at every "
                            "prompt — unpark it by name (`park unpark <ref>`)")
    if not outcome["pill"]:
        res["notes"].append("cmux would not set the parked pill")
    if not outcome["colour"]:
        res["notes"].append("cmux would not dim the workspace colour")
    if outcome["title"]:
        # Recorded so unpark clears only a name we set, never the user's own.
        entry["pinned_title"] = True
        write_entry(ledger_path(w["id"]), entry)

    res["ok"] = True
    res["msg"] = f"{human(freed)} freed"
    return res


def restore_visual_state(ws_id, entry):
    """Undo the pill, the dimmed colour and the pinned title park applied.

    Shared with `forget`, which used to clear the colour outright — destroying
    the original in the same breath as the ledger entry holding the only record
    of it.

    Returns a note when cmux would not take one of them back, else None. The
    caller is about to delete the entry, and with it the only record that this
    workspace was ever, say, orange: a socket hiccup here used to lose that
    silently and leave the workspace dimmed and pilled with nothing saying why.
    """
    failed = []
    if not cmux_do("clear-status", PILL_KEY, "--workspace", ws_id):
        failed.append("the parked pill")
    prev = entry.get("prev_color")
    if prev:
        if not cmux_do("workspace-action", "--action", "set-color",
                       "--color", prev, "--workspace", ws_id):
            failed.append(f"the colour it had ({prev})")
    elif not cmux_do("workspace-action", "--action", "clear-color",
                     "--workspace", ws_id):
        failed.append("the parked colour")
    # Only undo a rename we made ourselves; a name the user set is theirs.
    if entry.get("pinned_title") and not cmux_do(
            "workspace-action", "--action", "clear-name", "--workspace", ws_id):
        failed.append("the pinned name")
    if failed:
        return ("cmux would not restore " + ", ".join(failed)
                + " — set it back by hand")
    return None


def pin_title(w, title):
    """Freeze the workspace's name while it is parked.

    cmux derives the sidebar title from the live agent, so killing the session
    makes a workspace called "✳ Vyhledejte trendy…" decay to "~/Sites/foo" —
    and the titles are exactly how the user finds their way around 40 open
    workspaces. Pinning it as a custom name keeps the sidebar readable.

    Returns whether it pinned, so unpark only clears a name park itself set.
    """
    if not title or w.get("has_custom_title"):
        return False
    return cmux_do("workspace-action", "--action", "rename",
                   "--title", title, "--workspace", w["id"])


def clear_prefill(ws_id, sessions):
    """Wipe the `park unpark .` park left typed at each agent tab's prompt.

    Without this, `forget` leaves a command that will only ever answer
    "not parked" sitting under the user's cursor.

    Only ever wipes park's own line. ctrl+u has no undo, and by the time this
    runs the prefill can be long gone with the user's own half-typed command in
    its place — the "resumed behind our back" path in `unpark_one` reaches here
    with a live agent prompt on screen. A line that no longer ENDS in the
    prefill is left alone; the leftover is a cosmetic annoyance, the text it
    would take with it is not.

    Returns False when a surface's screen could not be read at all, so a caller
    about to type onto that prompt can decline rather than append to whatever
    is sitting there.

    Teardown only — `forget` and the already-running path, which type nothing
    afterwards. Anything that goes on to send a command must use
    `prepare_prompt`, which also insists the line ends up EMPTY.
    """
    ok = True
    for s in sessions:
        line = prompt_line(ws_id, s.get("surface"))
        if line is None:
            ok = False
            continue
        if not line.endswith(PREFILL):
            continue
        if not send_ctrl_u(ws_id, s.get("surface")):
            ok = False
    return ok


def send_ctrl_u(ws_id, surface=None):
    keys = ["send-key", "--workspace", ws_id]
    if surface:
        keys += ["--surface", surface]
    return cmux_do(*keys, "ctrl+u")


def prepare_prompt(ws_id, surface=None):
    """Make a prompt safe to type a resume command onto. -> (ok, why)

    unpark types and then presses ENTER, so "the line is not park's prefill"
    was never enough. If the prefill was already gone — a cmux restart wipes
    the terminal buffer, and `repaint` only puts it back where the line was
    bare — and the user has `git status` half typed, the old code left the line
    alone, reported success and appended the resume command to it. The result
    ran neither: one mangled command, no session, and the ledger entry deleted
    on the way out.

    So: clear our own prefill, re-read, and require what remains to be a bare
    prompt. Anything else is the user's line, and refusing costs nothing but a
    retry.
    """
    line = prompt_line(ws_id, surface)
    if line is None:
        return False, "cannot read the prompt"
    if line.endswith(PREFILL):
        if not send_ctrl_u(ws_id, surface):
            return False, "cmux would not clear the prefilled line"
        line = prompt_line(ws_id, surface)
        if line is None:
            return False, "cannot read the prompt after clearing it"
    if not bare_prompt(line):
        return False, f"something is typed at the prompt: {line[-40:]!r}"
    return True, None


def wait_for_sessions(ids, timeout=8.0, step=0.4):
    """Which of these session ids now have a live claude process.

    `cmux send` returning success means the keystrokes landed, not that
    anything started: a bad cwd, a shim that is gone, or claude refusing to
    start all leave a workspace at a shell prompt — and unpark used to delete
    the ledger entry on the strength of the send alone, taking the session id
    and resume command with it.

    Cheap on purpose: the command we sent carries `--resume <id>` in its argv,
    so this is a `ps` sweep with no lsof behind it, and it returns the moment
    everything is up.
    """
    want = {str(i).lower() for i in ids}
    seen = set()
    deadline = time.time() + timeout
    while True:
        for info in ps_table().values():
            cmd = info.get("cmd") or ""
            if not is_claude(cmd):
                continue
            sid = argv_session_id(cmd)
            if sid and sid.lower() in want:
                seen.add(sid.lower())
        if not want - seen or time.time() >= deadline:
            return seen
        time.sleep(step)


def unpark_one(w, allow_exec=False, live_ids=None):
    """Resume one parked workspace, alone. See `_unpark_one`."""
    lock = acquire_op_lock(w["id"])
    if not lock:
        return {"ref": w["ref"], "title": w.get("title") or "", "ok": False,
                "notes": [],
                "msg": "another park or unpark is working on this workspace"}
    try:
        return _unpark_one(w, allow_exec, live_ids)
    finally:
        release_op_lock(lock)


def _unpark_one(w, allow_exec=False, live_ids=None):
    """Resume one parked workspace. Returns a result dict; prints nothing.

    `allow_exec` is for `park unpark .` run inside the very workspace being
    resumed: sending keystrokes to your own surface races the shell, so the
    process replaces itself with the resume command instead.
    """
    ref = w["ref"]
    res = {"ref": ref, "title": w.get("title") or "", "ok": False, "notes": []}
    path = ledger_path(w["id"])
    if not path.exists():
        res["msg"] = "not parked"
        return res
    e = read_entry(path)
    if e is None:
        res["msg"] = f"ledger entry is unreadable: {path}"
        return res
    res["title"] = e.get("title") or res["title"]
    if w.get("orphan"):
        # Nothing to send keystrokes to. `park rebuild` recreates the workspace
        # and re-keys this entry onto it; only then can it be resumed.
        res["msg"] = "workspace is gone from cmux — run `park rebuild` first"
        return res

    problems = []
    if not e.get("cwd") or not Path(e["cwd"]).exists():
        problems.append(f"cwd is gone: {e.get('cwd')}")
    for s in e["sessions"]:
        # Per-tab cwds genuinely diverge (a tab can sit in a worktree under the
        # workspace root), so the workspace-level check above is not enough —
        # the resume command cds into this one.
        if not s.get("cwd") or not Path(s["cwd"]).exists():
            problems.append(f"session cwd is gone: {s.get('cwd')}")
        if not s.get("transcript") or not Path(s["transcript"]).exists():
            problems.append(f"transcript is gone: {s.get('transcript')}")
    if problems:
        res["msg"] = "; ".join(problems) + f" (ledger kept at {path})"
        return res

    bare = [s for s in e["sessions"] if not s.get("resume_command")]
    if bare:
        res["notes"].append(
            f"{len(bare)} tab(s) have no recorded command and resume with "
            "defaults — check for `bypass permissions` after they start")

    old, now = e.get("git", {}), git_info(e["cwd"])
    if old.get("branch") and now.get("branch") != old.get("branch"):
        res["notes"].append(
            f"branch changed: {old['branch']} -> {now.get('branch')}")

    # Never resume a conversation that is already live: two processes
    # appending to one transcript corrupts it.
    running = live_session_ids() if live_ids is None else live_ids
    # Lowercased on both sides: `live_session_ids` normalises, and a ledger
    # entry records whatever spelling its source used.
    dupes = [s["session_id"] for s in e["sessions"]
             if str(s.get("session_id") or "").lower() in running]
    if dupes and len(dupes) == len(e["sessions"]):
        # Every session is back, so the workspace is not parked any more —
        # whatever resumed it, the ledger and the sidebar are now lying. Skip
        # the resume (a second process on one transcript corrupts it) but do
        # the rest of the teardown, or the pill, the colour and the pinned
        # title stick around forever and every later unpark refuses too.
        clear_prefill(w["id"], e["sessions"])
        note = restore_visual_state(w["id"], e)
        if note:
            res["notes"].append(note)
        path.unlink()
        res["ok"] = True
        res["msg"] = f"already running ({dupes[0][:8]}) — cleared parked state"
        return res
    if dupes:
        # Only SOME are back, which is what a half-finished unpark leaves
        # behind. Tearing the whole entry down here would delete the resume
        # record of the tabs that never came back — the one thing in it that
        # cannot be reconstructed from anywhere else. Drop the live ones and
        # carry on resuming the rest.
        e["sessions"] = [s for s in e["sessions"]
                         if s["session_id"] not in dupes]
        write_entry(path, e)
        res["notes"].append(f"{len(dupes)} tab(s) were already running and "
                            "were left alone")

    # A workspace can hold several agent tabs; each is resumed into its own
    # surface. The tab this command is running in cannot be driven by sending
    # keystrokes to itself, so it is handed over with exec at the very end.
    here = None
    sent, done = 0, set()

    def gave_up(why):
        """Stop mid-resume without losing what is still owed.

        The tabs resumed before this point are live NOW. Leaving them in the
        ledger means the next unpark finds a running session, takes the
        "already running" path and clears the entry — throwing away the resume
        record of exactly the tabs that never came back. Record what is still
        outstanding instead, so a retry picks up where this stopped.
        """
        if done:
            e["sessions"] = [s for s in e["sessions"]
                             if s["session_id"] not in done]
            write_entry(path, e)
        res["msg"] = (f"{why} — {len(done)} tab(s) resumed, "
                      f"{len(e['sessions'])} still parked (ledger at {path})")
        return res

    for idx, s in enumerate(e["sessions"], 1):
        surface = s.get("surface", "")
        # A rebuilt workspace has no recorded surfaces, so matching on the
        # surface id alone left `here` unset and the resume was TYPED into the
        # very tab running park — racing the shell that was about to get the
        # command anyway. With no surface to match, being in the workspace is
        # the same statement.
        if allow_exec and here is None and (
                os.environ.get("CMUX_SURFACE_ID") == surface if surface
                else os.environ.get("CMUX_WORKSPACE_ID") == w["id"]):
            here = s
            continue
        # After a rebuild the surfaces are gone and every session shares the
        # workspace's single one, so only the first can actually be resumed —
        # whether that first one was sent to or claimed by the exec above.
        # Say what the others need rather than dropping them on the floor.
        if not surface and (sent or here):
            res["notes"].append(
                f"tab {idx} needs a new agent tab; resume it with: "
                + resume_command_for(s))
            continue
        # The line has to be EMPTY before a command is typed and submitted —
        # park's own prefill cleared, and anything else left strictly alone.
        ok, why = prepare_prompt(w["id"], surface)
        if not ok:
            if why.startswith("cannot read"):
                # Measured: 6 of 34 parked workspaces answer `read-screen` with
                # "Failed to read terminal text" — the surface ids are valid and
                # the workspace is open, cmux just will not hand over the
                # buffer. Typing blind into that is the one thing this guard
                # exists to prevent, so say what does work instead.
                res["notes"].append(
                    "cmux would not read this terminal; open the workspace once "
                    "and retry, or restore the tab directly with: "
                    f"cmux restore claude {s['session_id']}")
            return gave_up(why + (f" of {surface}" if surface else ""))
        if not send_text(resume_command_for(s), w["id"], surface, submit=True):
            return gave_up("cmux would not accept the resume command"
                           + (f" for {surface}" if surface else ""))
        sent += 1
        done.add(s["session_id"])

    # Keystrokes landing is not a session starting: a stale cwd, a shim that
    # moved or claude refusing to start all leave the tab at a shell prompt.
    # Anything not confirmed keeps its ledger record — that record is the only
    # copy of the session id and the command that brings it back.
    unconfirmed = set()
    if done:
        up = wait_for_sessions(done)
        unconfirmed = {sid for sid in done if str(sid).lower() not in up}
        if unconfirmed:
            res["notes"].append(
                f"{len(unconfirmed)} tab(s) were sent their resume command but "
                "no process appeared — left parked; if one did come up, clear "
                "it with `park forget`")

    # `here` is handed the terminal by exec below, so it is accounted for even
    # though nothing can confirm it from inside the process being replaced.
    left = [s for s in e["sessions"]
            if s is not here
            and (s["session_id"] not in done or s["session_id"] in unconfirmed)]

    # What the caller must add to its "already running" set before the next
    # target: these transcripts have a process on them as of now.
    res["resumed_ids"] = sorted(done - unconfirmed)

    killed = e.get("killed", [])
    if killed:
        res["notes"].append(f"{len(killed)} dev/browser process(es) were "
                            f"stopped and are NOT restarted")
    if left:
        # Some tabs are still owed. Deleting the entry here would take their
        # resume commands with it — and `res["notes"]` is not a place to keep
        # them: with exec below, cmd_unpark never gets to print them.
        e["sessions"] = left
        write_entry(path, e)
        res["ok"] = bool(done - unconfirmed) or bool(here)
        res["msg"] = (f"{len(done - unconfirmed) + bool(here)} tab(s) resumed, "
                      f"{len(left)} still parked (ledger at {path})")
    else:
        note = restore_visual_state(w["id"], e)
        if note:
            res["notes"].append(note)
        path.unlink()
        res["ok"] = True
        res["msg"] = "resumed"

    if here:
        # Everything above is durable; hand this terminal straight to claude.
        # resume_command_for already applied the shim. The exec is the CALLER's
        # to run: it never returns, and doing it here meant the notes above —
        # including "tab 2 needs a new agent tab; resume it with: …" — were
        # printed by nobody.
        res["exec"] = resume_command_for(here)
    return res


def focus_surface(ws_id, surface_id):
    """Select a tab without moving it.

    cmux has no "focus this surface" verb. `move-surface --focus true` is the
    closest thing, but with no position flag it also sends the tab to the END
    of the pane — measured: a two-tab pane came back reordered. Passing the
    index the surface already has makes the move a no-op and leaves only the
    focus.
    """
    try:
        data = cmux_json("list-pane-surfaces", "--workspace", ws_id)
    except (RuntimeError, json.JSONDecodeError):
        return False
    idx = next((s.get("index") for s in data.get("surfaces", [])
                if surface_id in (s.get("id"), s.get("ref"))), None)
    if idx is None:
        return False
    return cmux_do("move-surface", "--surface", surface_id, "--workspace",
                   ws_id, "--index", str(idx), "--focus", "true")


def hand_back_tab(results):
    """Focus the agent tab and close the tab park is running in.

    For the keyboard shortcut. cmux actions have exactly two targets —
    `currentTerminal`, which would type into the agent's own prompt, and
    `newTabInCurrentPane` — so a tab is unavoidable; it does not have to STAY.
    The workspace's own pill records what was freed, which is the feedback that
    outlives the tab anyway.

    Only after a clean park of the workspace this tab is in. A refusal or a
    note is the one thing worth reading, and closing the tab is exactly how it
    would be missed.
    """
    mine, here = (os.environ.get("CMUX_SURFACE_ID"),
                  os.environ.get("CMUX_WORKSPACE_ID"))
    if not mine or not here:
        return False
    entry = read_entry(ledger_path(here))
    if not entry or not any(r["ok"] and not r["notes"] for r in results):
        return False
    for s in entry.get("sessions", []):
        # The tab the prefill was typed into: land the user on the command
        # that brings the workspace back.
        if s.get("surface") and s["surface"] != mine:
            focus_surface(here, s["surface"])
            break
    return cmux_do("close-surface", "--surface", mine, "--workspace", here)


def confirm_kill_anyway(targets):
    """Make the one flag that can lose a running turn a deliberate act.

    Everything else in park refuses when it is unsure; `--kill-anyway` is where
    the user overrules that, so it asks out loud and needs a terminal to ask
    at — a scripted `--kill-anyway` would be exactly the unattended
    turn-killing this tool exists not to do.
    """
    if not sys.stdin.isatty():
        die("--kill-anyway needs a terminal to confirm at")
    print("\n  --kill-anyway ignores unsent drafts AND turns in flight.")
    print("  Anything still working below loses the turn:\n")
    for w in targets:
        print(f"    {w['ref']:<13} {(w.get('title') or '')[:50]}")
    try:
        answer = input("\n  type 'yes' to go ahead: ").strip()
    except (EOFError, KeyboardInterrupt):
        answer = ""
    if answer != "yes":
        die("aborted")


def cmd_park(argv):
    dry = "--dry-run" in argv
    force = "--force" in argv
    brutal = "--kill-anyway" in argv
    idle, argv = flag_value(argv, "--idle")
    bulk = "--all" in argv
    close_tab = "--close-tab" in argv
    if brutal and (bulk or idle):
        # Selecting in bulk and overriding the two guards that protect a
        # running turn are individually defensible and together are not.
        die("--kill-anyway cannot be combined with --all or --idle — name the "
            "workspaces you mean")

    # The CPU window is two seconds of sleeping. Start it before the workspace
    # listing so it runs underneath everything that follows — for a single
    # target that is most of the wait. After a confirmation prompt instead,
    # where it would otherwise go stale while the user reads.
    pending = None
    if True:
        if bulk or idle:
            if [a for a in argv if not a.startswith("--")]:
                die("--all and --idle choose the targets themselves — "
                    "do not name any")
            targets, spaces = bulk_targets(idle)
            if not targets:
                print("  nothing matches\n")
                return 0
            if not dry and not confirm_bulk(targets, idle):
                return 1
        else:
            pending = background(cpu_snapshots)
            with Spinner("looking at the workspaces…"):
                spaces = workspaces_for_park()
            targets = targets_from(
                argv,
                "no target — pass a workspace ref, a title, `window:N`, or `.`",
                spaces=spaces)
            if brutal:
                confirm_kill_anyway(targets)
        return park_targets(targets, spaces, pending,
                            dry, force, brutal, close_tab)


def park_targets(targets, spaces, pending, dry, force, brutal,
                 close_tab=False):
    total, done, refused, seen = 0, 0, 0, []
    # In waves, not one at a time. Everything a park does is I/O — cmux socket
    # round-trips, a CPU window, git — and the picker has always parked rows
    # concurrently; only the CLI paid for 20 workspaces one after another
    # (measured: 17.8 s for a dry run of window:4). A wave also gets its own
    # fresh snapshot, which fixes the other half of the problem: the old code
    # re-read `ps` as the batch aged but kept the CPU sample it took at the
    # start, so late targets were judged on a reading minutes old.
    for i in range(0, len(targets), PARK_WAVE):
        wave = targets[i:i + PARK_WAVE]
        if pending is None:              # every wave gets its own reading
            pending = background(cpu_snapshots)
        with Spinner("checking what is safe to park…"):
            by_ws, table = attribute(spaces), ps_table()
        snaps, pending = pending, None
        results = pmap(
            lambda w: park_one(w, by_ws, table, dry=dry, force=force,
                               brutal=brutal, snaps=snaps),
            wave, workers=PARK_WAVE)
        # Printed in the order the targets were named, never in the order the
        # workers happened to finish.
        for r in results:
            seen.append(r)
            mark = ("would park" if dry else "❄") if r["ok"] else "skip"
            print(f"  {mark:<11} {r['ref']:<13} {r['title'][:38]:<40} {r['msg']}")
            for n in r["notes"]:
                print(f"              {n}")
            if r["ok"]:
                total += r["freed"]
                done += 1
            elif r["msg"] != "already parked":
                refused += 1
    verb = "would free" if dry else "freed"
    print(f"\n  {done} workspace(s), {verb} {human(total)}\n")
    if close_tab and not dry:
        # Never returns when it works: closing this surface ends the process.
        hand_back_tab(seen)
    return 1 if refused else 0


def workspaces_for_park():
    """The workspace map park is allowed to kill from — or a refusal.

    A window that would not enumerate is not an empty window. Its workspaces
    are absent from the map, so `attribute` cannot place their processes by
    workspace id and falls back to longest-prefix cwd matching — which hands
    them to whichever LISTED workspace sits above them in the tree. Park that
    workspace and their sessions die with it, recorded under someone else's
    ledger entry. Reading is fine with a partial answer; killing is not.
    """
    missing = []
    spaces = all_workspaces(missing)
    if missing:
        die("cmux would not list "
            + ", ".join(f"window {w['index']}" for w in missing)
            + " — refusing to park from a partial map, because the processes "
              "in it would be attributed to whichever workspace park CAN see. "
              "Try again in a moment.")
    return spaces


def bulk_targets(idle):
    """Workspaces `--idle`/`--all` picks out. -> (targets, spaces)

    Idle is measured from cmux's `latest_submitted_at` — when YOU last sent
    this workspace a prompt. A workspace with no such timestamp is left out
    rather than treated as idle forever: "we do not know" is the one answer a
    bulk selector must not read as "safe to kill".

    This only narrows the list. Every workspace it picks still goes through
    park_one's whole guard chain, so nothing here can park a busy session.
    """
    with Spinner("looking for idle workspaces…"):
        spaces = workspaces_for_park()
        rows = collect(spaces)
    by_ref = {w["ref"]: w for w in spaces}
    picked = []
    for r in rows:
        if r["parked"] or r["busy"] or not r["bytes"]:
            continue
        if idle is not None:
            age = seconds_since(r["since"])
            if age == float("inf") or age < idle:
                continue
        w = by_ref.get(r["ref"])
        if w:
            picked.append(w)
    return picked, spaces


def confirm_bulk(targets, idle):
    """Bulk parking is a lot of killing at once, so it asks first."""
    print(f"\n  About to park {len(targets)} workspace(s)"
          + (f", idle for {human_duration(idle)} or more" if idle else "")
          + ":\n")
    for w in targets[:20]:
        print(f"    {w['ref']:<13} {(w.get('title') or '')[:50]}")
    if len(targets) > 20:
        print(f"    … and {len(targets) - 20} more")
    print("\n  Dev servers and test browsers in them stop too, and unpark does "
          "not bring those back.")
    if not sys.stdin.isatty():
        die("--all/--idle needs a terminal to confirm at — "
            "use --dry-run to see the list")
    try:
        answer = input("\n  type 'yes' to go ahead: ").strip()
    except (EOFError, KeyboardInterrupt):
        answer = ""
    if answer != "yes":
        print("  aborted\n")
        return False
    return True


def cmd_unpark(argv):
    targets = targets_from(argv)
    # Resolved once: with cmux no longer putting the id in argv this costs an
    # lsof per live claude, and it is the same answer for every target.
    unresolved = []
    with Spinner("checking which sessions are already running…"):
        live_ids = live_session_ids(unresolved=unresolved)
    if unresolved:
        # The guard fails open, so say so. A session it could not identify is
        # one unpark may start a second process on.
        print(f"  warning: {len(unresolved)} running claude process(es) could "
              "not be identified; the already-running check cannot see them")

    if len(targets) == 1:
        # The single-target path is the one that can `exec`, and it is what
        # `park unpark .` at a parked prompt runs.
        results = [unpark_one(targets[0], allow_exec=True, live_ids=live_ids)]
    else:
        results = unpark_batch(targets, live_ids)

    resumed = 0
    for r in results:
        mark = "▶" if r["ok"] else "skip"
        print(f"  {mark:<5} {r['ref']:<13} {r['title'][:38]:<40} {r['msg']}")
        for n in r["notes"]:
            print(f"        {n}")
        # "not parked" is the state the caller asked for, so it is not a
        # failure — the same way an "already parked" park is not one.
        resumed += bool(r["ok"]) or r["msg"] == "not parked"
        if r.get("exec"):
            # Handing this terminal over ends the batch by definition, so
            # everything above has already been printed.
            print()
            sys.stdout.flush()
            os.execvp("/bin/sh", ["/bin/sh", "-c", r["exec"]])
    print()
    return 0 if resumed == len(targets) else 1


def unpark_batch(targets, live_ids):
    """Resume several workspaces at once. Results come back in target order.

    Each workspace holds its own operation lock for its whole transaction, so
    the only thing left to coordinate is the one collision a per-workspace lock
    cannot see: two ledger entries naming the SAME session. That should not
    happen, but a re-key onto the wrong workspace or a hand-edited ledger makes
    it happen, and the cost is the thing this tool exists to prevent — two
    processes appending to one transcript.

    So the claim is made here, in the parent, in target order, before anything
    is dispatched. A worker never has to ask "did someone else just take this",
    which is what made the serial loop's fold-as-you-go set necessary in the
    first place.
    """
    claimed, dispatch, refused = set(live_ids), [], {}
    for w in targets:
        e = read_entry(ledger_path(w["id"]))
        ids = {str(s.get("session_id") or "").lower()
               for s in (e or {}).get("sessions", [])}
        clash = ids & claimed
        if clash:
            refused[w["id"]] = {
                "ref": w["ref"], "notes": [], "ok": False,
                "title": (e or {}).get("title") or w.get("title") or "",
                "msg": f"session {sorted(clash)[0][:8]} is already being "
                       "resumed by another target in this batch"}
            continue
        claimed |= ids
        dispatch.append(w)

    out = {}
    for i in range(0, len(dispatch), UNPARK_WAVE):
        wave = dispatch[i:i + UNPARK_WAVE]
        with Spinner(f"resuming {len(wave)} workspace(s)…"):
            done = pmap(lambda w: unpark_one(w, live_ids=live_ids), wave,
                        workers=UNPARK_WAVE)
        out.update({w["id"]: r for w, r in zip(wave, done)})
    return [refused.get(w["id"]) or out[w["id"]] for w in targets]


def cmd_show(argv):
    for w in targets_from(argv):
        path = ledger_path(w["id"])
        if not path.exists():
            print(f"{w['ref']} is not parked")
            continue
        print(path.read_text())


def cmd_forget(argv):
    """Drop a ledger entry without resuming — for entries that went stale.

    Differs from unpark only in not sending the resume commands: the pill, the
    colour and the pre-filled prompt are torn down exactly the same way.
    """
    dropped = 0
    targets = targets_from(argv)
    for w in targets:
        path = ledger_path(w["id"])
        if not path.exists():
            print(f"  skip  {w['ref']}  — not parked")
            dropped += 1        # already forgotten: the asked-for state
            continue
        # The same lock park and unpark take: this deletes the entry, and
        # deleting it out from under a park that is mid-kill leaves the session
        # dead with no record of how to bring it back.
        lock = acquire_op_lock(w["id"])
        if not lock:
            print(f"  skip  {w['ref']}  — another park or unpark is working "
                  "on this workspace")
            continue
        try:
            e = read_entry(path) or {}
            clear_prefill(w["id"], e.get("sessions", []))
            note = restore_visual_state(w["id"], e)
            path.unlink()
        finally:
            release_op_lock(lock)
        dropped += 1
        print(f"  forgot  {w['ref']}  {(w['title'] or '')[:40]}")
        if note:
            print(f"          {note}")
    print()
    return 0 if dropped == len(targets) else 1


def cmd_doctor(argv):
    """Verify every ledger entry is still restorable."""
    entries = read_ledger(with_broken=True)
    if not entries:
        print("  no parked workspaces")
        return 0
    spaces = {w["id"]: w for w in all_workspaces()}
    running = live_session_ids()
    closed = closed_workspaces()
    bad = 0
    for e in entries:
        if e.get("__broken__"):
            bad += 1
            print(f"  ✗ {'-':<13} {Path(e['__broken__']).name[:38]:<40}"
                  " ledger file is corrupt (remove it by hand)")
            continue
        issues = []
        if not e.get("cwd") or not Path(e["cwd"]).exists():
            issues.append("cwd missing")
        for s in e["sessions"]:
            if not s.get("cwd") or not Path(s["cwd"]).exists():
                issues.append("session cwd missing")
            if not s.get("transcript") or not Path(s["transcript"]).exists():
                issues.append("transcript missing")
            if s.get("session_id") in running:
                issues.append("stale entry: session is already running "
                              "(clear with: park forget)")
            if s.get("id_source") == "scan":
                issues.append("session id came from a transcript scan — "
                              "verify the conversation after unpark")
        # The risk park guards against materialises WHILE parked, over days,
        # not during the moment park_one compares across.
        if e.get("worktree") and worktree_fingerprint(e.get("cwd")) != e["worktree"]:
            issues.append("git checkout changed since parking")
        live = spaces.get(e.get("workspace_id"))
        if not live:
            # Two very different causes, one symptom. cmux knows which.
            shut = closed.get(e.get("workspace_id"))
            if shut:
                issues.append(
                    "workspace was closed "
                    + ago(datetime.fromtimestamp(shut, timezone.utc)
                          .isoformat())
                    + " — not lost; drop the entry with: park forget")
            else:
                # rekey first: after a reset the workspace is usually still
                # there under a new uuid, and rebuild would make a second one
                # beside it.
                issues.append("workspace no longer open in cmux "
                              "(try: park rekey, then park rebuild)")
        # Refs are positional and shift as workspaces open and close, so the one
        # captured at park time may now name a different workspace.
        ref = live["ref"] if live else (e.get("workspace_id") or "?")[:13]
        mark = "✗" if issues else "✓"
        if issues:
            bad += 1
        print(f"  {mark} {ref:<13} {e['title'][:38]:<40}"
              f" {', '.join(issues) or 'ok'}")
    print(f"\n  {len(entries) - bad}/{len(entries)} restorable\n")
    # Nonzero means "needs attention", not "unrestorable": a scan-derived id
    # and a changed checkout are warnings. Something you can put in a health
    # check has to be able to say so.
    return 1 if bad else 0


def cmd_rebuild(argv):
    """Recreate cmux workspaces for ledger entries whose workspace is gone.

    This is the reason the ledger lives outside cmux: if cmux loses its state,
    every parked workspace can still be reconstructed from here.
    """
    dry = "--dry-run" in argv
    spaces = all_workspaces()
    before = {w["id"] for w in spaces}
    entries = read_ledger()
    lost = [e for e in entries if e.get("workspace_id") not in before]
    if not lost:
        print("  nothing to rebuild — every parked workspace is still open\n")
        return 0

    # A workspace the user closed on purpose is not a workspace cmux lost, and
    # the ledger cannot tell them apart — both leave an entry pointing at
    # nothing. Rebuilding the first kind resurrects something deliberately shut,
    # which is worse than leaving the entry sitting there. cmux records which is
    # which; skipping needs no flag, un-skipping does.
    if "--closed" not in argv:
        closed = closed_workspaces()
        keep = []
        for e in lost:
            shut = closed.get(e.get("workspace_id"))
            if shut:
                when = ago(datetime.fromtimestamp(shut, timezone.utc).isoformat())
                print(f"  skip  {(e.get('title') or '')[:40]:<42} closed {when}"
                      " — `park forget` to drop it, `--closed` to rebuild anyway")
            else:
                keep.append(e)
        lost = keep
        if not lost:
            print()
            return 1        # every one was a workspace the user closed

    # rebuild is the obvious command to reach for and the wrong one after a
    # cmux reset: the workspaces are still there under new uuids, so this would
    # build a SECOND one beside each of them — 45 duplicates, measured. The
    # docs said "run rekey first"; nothing enforced it. Now the entries that
    # rekey could place are held back rather than duplicated.
    claimed = {e["workspace_id"] for e in entries
               if e.get("workspace_id") in before}
    adoptable = [e for e in lost if rekey_match(e, spaces, claimed)[0]]
    if adoptable:
        for e in adoptable:
            print(f"  hold  {(e.get('title') or '')[:44]:<46} a live workspace "
                  "already carries this title")
        print(f"\n  {len(adoptable)} entr(ies) look like they only lost their "
              "uuid — run `park rekey` first (`park rekey --dry-run` to look), "
              "then rebuild what is left\n")
        return 1

    stuck = 0
    for e in lost:
        title = e["title"]
        if not e.get("cwd") or not Path(e["cwd"]).exists():
            print(f"  skip  {title[:40]} — cwd gone")
            stuck += 1
            continue
        if dry:
            print(f"  would rebuild  {title[:44]}  ({e['cwd']})")
            continue

        old_id = e["workspace_id"]
        args = ["new-workspace", "--name", title, "--cwd", e["cwd"],
                "--focus", "false"]
        # Window uuids are regenerated by the same cmux reset that lost the
        # workspace, so a stale --window fails the whole call. Fall back to the
        # caller's window rather than printing a success that did not happen.
        # One attempt only: `A or B` on a CREATE can make two workspaces, and
        # then neither can be identified as "the new one".
        if e.get("window_id"):
            args += ["--window", e["window_id"]]
        ok = cmux_do(*args)
        if not ok:
            print(f"  FAILED  {title[:44]} — cmux would not create it")
            stuck += 1
            continue

        # new-workspace prints no id, so find the workspace it just made and
        # move the entry onto that uuid. Without this the ledger stays keyed to
        # the dead workspace and `park unpark` can never find it again — which
        # would make the recovery path the out-of-cmux ledger exists for a
        # dead end.
        appeared = [w for w in all_workspaces() if w["id"] not in before]
        exact = [w for w in appeared if w.get("current_directory") == e["cwd"]]
        candidates = exact or appeared
        # Everything that appeared is accounted for now, whichever branch comes
        # next. Leaving any of it out of `before` would make the NEXT rebuild
        # see it again as well as its own, so a single ambiguity used to poison
        # every remaining entry in the run.
        before.update(w["id"] for w in appeared)
        if len(candidates) != 1:
            print(f"  rebuilt  {title[:44]} — but could not identify the new "
                  f"workspace; entry left under {old_id}")
            stuck += 1
            continue
        new = candidates[0]
        # The surfaces died with the old workspace, so their ids would target
        # nothing and unpark would silently type into the void. A rebuilt
        # workspace has exactly one surface; drop the ids and let unpark use it.
        for s in e["sessions"]:
            s["surface"] = ""
        e.update({"workspace_id": new["id"], "workspace_ref": new["ref"],
                  "window_id": new.get("window_id")})
        write_entry(ledger_path(new["id"]), e)
        if new["id"] != old_id:
            ledger_path(old_id).unlink(missing_ok=True)
        print(f"  rebuilt  {title[:44]}  → {new['ref']}")
    print()
    return 1 if stuck else 0


def rekey_match(entry, spaces, unavailable):
    """The live workspace a ledger entry describes. -> (workspace, note, why_not)

    Keyed on the TITLE and corroborated by the cwd, not the other way round.
    `pin_title` freezes the workspace name at park time precisely so it
    survives, and it does: measured across a real 44-entry ledger, every title
    still matched its workspace while 21 of the cwds did not. cmux records the
    repo ROOT for an agent living in a worktree under it (19 cases), and its
    per-panel cwd can be scrambled outright by a reset (2 cases, both pointing
    at a sibling worktree). A cwd-first rule would have refused half the fleet.

    What stops a wrong adopt is UNIQUENESS, not the cwd: the title must match
    exactly one workspace still up for adoption. A disagreeing cwd is reported
    rather than obeyed — the ledger wrote its own, cmux's is the guess.
    """
    title, cwd = (entry.get("title") or ""), entry.get("cwd")
    if not title:
        return None, None, "entry records no title to match on"
    hits = [w for w in spaces
            if w["id"] not in unavailable and (w.get("title") or "") == title]
    if not hits:
        return None, None, "no free live workspace carries this title"
    if len(hits) > 1:
        return None, None, f"{len(hits)} live workspaces share this title"
    w = hits[0]
    theirs = w.get("current_directory") or ""
    note = None
    if cwd and theirs and cwd != theirs and not (
            cwd.startswith(theirs.rstrip("/") + "/")
            or theirs.startswith(cwd.rstrip("/") + "/")):
        note = f"cmux reports cwd {theirs} — kept the ledger's"
    return w, note, None


def cmd_rekey(argv):
    """Re-point ledger entries at workspaces whose UUID changed under them.

    A cmux reset regenerates every workspace UUID while the workspaces
    themselves come back. The ledger is keyed by that UUID, so every parked
    entry orphans at once — and `rebuild` reads them all as lost and creates a
    SECOND workspace beside each survivor. With 45 parked that is 45
    duplicates. Re-keying puts each entry back on the workspace it already
    describes; only what is left over is a job for `rebuild`.
    """
    dry = "--dry-run" in argv
    with Spinner("looking for workspaces the entries have lost track of…"):
        spaces = all_workspaces()
        live_by_id = {w["id"] for w in spaces}
        entries = read_ledger()
        orphans = [e for e in entries if e.get("workspace_id") not in live_by_id]
        # An entry whose workspace the user CLOSED is not an entry that lost
        # its uuid. Adopting it would mark some unrelated live workspace as
        # parked because the two happen to share a title.
        closed = closed_workspaces()
        shut = [e for e in orphans if closed.get(e.get("workspace_id"))]
        orphans = [e for e in orphans if not closed.get(e.get("workspace_id"))]
        # Never adopt a workspace another entry already claims, and never adopt
        # one with a claude running in it: that would mark a workspace the user
        # is working in as parked, and the next unpark would start a second
        # process on a transcript it never killed.
        unavailable = {e["workspace_id"] for e in entries
                       if e.get("workspace_id") in live_by_id}
        if orphans:
            by_ws, table = attribute(spaces), ps_table()
            for w in spaces:
                if classify(by_ws.get(w["id"], []), table)[0]:
                    unavailable.add(w["id"])

    for e in shut:
        when = ago(datetime.fromtimestamp(closed[e["workspace_id"]],
                                          timezone.utc).isoformat())
        print(f"  skip     {(e.get('title') or '')[:44]:<46} workspace was "
              f"closed {when} — drop it with `park forget`")

    if not orphans:
        print("  nothing to re-key — every parked entry still names a live "
              "workspace\n")
        return 1 if shut else 0

    done, stuck = 0, 0
    for e in orphans:
        title = e.get("title") or ""
        new, note, why = rekey_match(e, spaces, unavailable)
        if not new:
            print(f"  skip     {title[:44]:<46} {why}")
            stuck += 1
            continue
        if dry:
            print(f"  would re-key  {title[:40]:<42} → {new['ref']}")
            if note:
                print(f"                {note}")
            done += 1
            continue
        old_id = e["workspace_id"]
        # The surfaces died with the old workspace ids, exactly as after a
        # rebuild, so unpark must fall back to the workspace's own surface.
        for s in e["sessions"]:
            s["surface"] = ""
        e.update({"workspace_id": new["id"], "workspace_ref": new["ref"],
                  "window_id": new.get("window_id")})
        if not write_entry(ledger_path(new["id"]), e):
            print(f"  FAILED   {title[:44]:<46} could not write the new entry")
            stuck += 1
            continue
        ledger_path(old_id).unlink(missing_ok=True)
        unavailable.add(new["id"])
        # The reset wiped the pill and the colour with everything else, so the
        # workspace is sitting there parked and looking live. Put them back.
        cmux_do("set-status", PILL_KEY,
                f"Parked · {human(e.get('freed_bytes') or 0)} freed",
                "--icon", "snowflake", "--color", "#5AC8FA", "--priority", "90",
                "--workspace", new["id"])
        cmux_do("workspace-action", "--action", "set-color", "--color",
                PARKED_COLOR, "--workspace", new["id"])
        done += 1
        print(f"  re-keyed  {title[:44]:<46} → {new['ref']}")
        if note:
            print(f"            {note}")

    verb = "would re-key" if dry else "re-keyed"
    print(f"\n  {verb} {done}, {stuck} left for `park rebuild`")
    if not dry and done:
        print("  the typed `park unpark .` prefill did not survive the reset — "
              "resume these by name, or put it back with `park repaint`\n")
    else:
        print()
    return 1 if stuck or shut else 0


def cmd_repaint(argv):
    """Re-assert the parked presentation cmux forgot.

    The ledger survives anything; the pill, the dimmed colour and the typed
    `park unpark .` do not — they live in cmux and its terminal buffers, and a
    restart takes all three. Measured right after a cmux update: 0 of 44 parked
    workspaces still showed any of them, so the whole fleet read as ordinary
    empty workspaces and the only way to tell what was parked was `park ls`.
    That is also how a parked workspace gets mistaken for a lost session and
    "restored" by hand behind park's back.

    Never automatic — like everything else here, it runs when asked.
    """
    dry = "--dry-run" in argv
    with Spinner("checking what the parked workspaces still show…"):
        spaces = {w["id"]: w for w in all_workspaces()}
        todo = [(e, spaces[e["workspace_id"]]) for e in read_ledger()
                if e.get("workspace_id") in spaces]
    if not todo:
        print("  nothing parked in an open workspace\n")
        return

    marks = typed = skipped = 0
    for e, w in todo:
        line = prompt_line(w["id"])
        if dry:
            state = ("prefill present" if line and line.endswith(PREFILL)
                     else "would retype prefill" if bare_prompt(line)
                     else "prompt busy — pill/colour only")
            print(f"  would repaint  {w['ref']:<13} "
                  f"{(e.get('title') or '')[:34]:<36} {state}")
            marks += 1
            continue
        ok = cmux_do("set-status", PILL_KEY,
                     f"Parked · {human(e.get('freed_bytes') or 0)} freed",
                     "--icon", "snowflake", "--color", "#5AC8FA",
                     "--priority", "90", "--workspace", w["id"])
        ok &= cmux_do("workspace-action", "--action", "set-color",
                      "--color", PARKED_COLOR, "--workspace", w["id"])
        marks += bool(ok)
        if line and line.endswith(PREFILL):
            continue                       # already there, leave it alone
        if not bare_prompt(line):
            # Something is typed there, or the screen would not read. Either
            # way it is not ours to append to.
            skipped += 1
            print(f"  prompt busy    {w['ref']:<13} "
                  f"{(e.get('title') or '')[:34]:<36} left the line alone")
            continue
        typed += send_text(PREFILL, w["id"])
    if dry:
        print(f"\n  {marks} workspace(s) would be repainted\n")
        return
    print(f"\n  repainted {marks}/{len(todo)}, retyped {typed} prefill(s)"
          + (f", left {skipped} prompt(s) alone" if skipped else "") + "\n")


# --- Interactive picker ------------------------------------------------------
def focus_workspace(row, ws_by_ref):
    """Jump to a workspace without leaving the picker."""
    ws = ws_by_ref.get(row["ref"]) or row
    if ws.get("window_id"):
        cmux_do("focus-window", "--window", ws["window_id"])
    cmux_do("select-workspace", "--workspace", row["id"])


HELP_LINE = ("↑↓/jk move   enter freeze/unfreeze   a whole window   "
             "f focus   r refresh   q quit")

# DECSET 1004: the terminal reports every focus change as CSI I / CSI O. Probed
# against cmux — it fires on all three ways the tab leaves the screen (another
# workspace in the window, another cmux window, another app entirely), which is
# exactly the signal needed to stop scanning for nobody.
FOCUS_ON, FOCUS_OFF = "\033[?1004h", "\033[?1004l"


def focus_reporting(on):
    """Ask the terminal for focus events (and always turn them back off).

    Left enabled after exit, the shell that inherits the tty gets `[I`/`[O`
    typed into its prompt on every window switch, so the disable has to run on
    every exit path, crash included.
    """
    try:
        sys.stdout.write(FOCUS_ON if on else FOCUS_OFF)
        sys.stdout.flush()
    except OSError:                 # a closed tty is not worth dying over
        pass


def focus_change(stdscr, k, tick_ms):
    """True/False when a key is a focus report, None when it is anything else.

    ncurses hands these over one of two ways. When the terminfo entry knows
    focus reporting it swallows the sequence and returns a named key — that is
    what cmux does (TERM=xterm-ghostty, kxIN/kxOUT), so parsing the raw bytes
    alone silently never fires. Otherwise the sequence arrives as-is, and its
    leading ESC would read as the quit key, so it has to be claimed here.
    """
    if k > 255:
        try:
            name = curses.keyname(k)
        except ValueError:
            return None
        return {b"kxIN": True, b"kxOUT": False}.get(name)
    if k != 27:
        return None
    stdscr.timeout(0)       # the rest of the sequence is already buffered
    try:
        rest = "".join(chr(c) for c in (stdscr.getch(), stdscr.getch())
                       if c != -1)
    finally:
        stdscr.timeout(tick_ms)
    return {"[I": True, "[O": False}.get(rest)


def _put(win, y, x, text, attr=0):
    """Write one line, truncated by CHARACTERS.

    curses' addnstr counts its limit in bytes, so passing a column count
    corrupts every line whose title holds multibyte characters — the garbage
    starts right after the accented word and runs to end of line.
    """
    h, w = win.getmaxyx()
    if y >= h or x >= w:
        return
    try:
        win.addstr(y, x, text[:max(0, w - x - 1)], attr)
    except curses.error:  # bottom-right cell always raises
        pass


def _confirm(stdscr, picked, C):
    """Modal y/N gate. Only a literal 'y' proceeds; anything else cancels."""
    to_park = [r for r in picked if not r["parked"]]
    to_unpark = [r for r in picked if r["parked"]]
    freed = sum(r["bytes"] for r in to_park)
    dirty = sum(1 for r in to_park if r["dirty"])

    body = []
    if to_park:
        body.append(f"park {len(to_park)} workspace(s), freeing {human(freed)}")
        for r in to_park[:8]:
            body.append(f"   ❄ {r['ref']:<13} {r['title'][:34]}")
        if len(to_park) > 8:
            body.append(f"   … and {len(to_park) - 8} more")
    if to_unpark:
        body.append(f"unpark {len(to_unpark)} workspace(s)")
        for r in to_unpark[:8]:
            body.append(f"   ▶ {r['ref']:<13} {r['title'][:34]}")
    if dirty:
        body.append(f"{dirty} have uncommitted changes (git is not touched)")
    body.append("")
    body.append("dev servers and test browsers stop and are NOT restarted")
    body.append("")
    body.append("press  y  to apply       any other key cancels")

    h, w = stdscr.getmaxyx()
    bh, bw = min(len(body) + 4, h), min(max(len(line) for line in body) + 6, w)
    top, left = max(0, (h - bh) // 2), max(0, (w - bw) // 2)
    win = curses.newwin(bh, bw, top, left)
    win.erase()
    win.box()
    _put(win, 0, 2, " confirm ", curses.A_BOLD | C(4))
    for i, line in enumerate(body):
        if i + 2 >= bh:
            break
        attr = curses.A_BOLD if line.startswith("press") else 0
        _put(win, i + 2, 3, line, attr)
    win.refresh()
    k = win.getch()
    return k == ord("y")


def _picker(stdscr, rows, ws_by_ref, reload):
    """Cursor + enter toggles the row under it: live freezes, parked thaws.

    The work runs on a worker thread so the list stays responsive and the row
    can show its own in-flight state; a row already in flight ignores further
    presses.
    """
    curses.curs_set(0)
    stdscr.keypad(True)
    stdscr.timeout(TICK_BUSY_MS)  # animate the in-flight spinner
    focus_reporting(True)
    use_color = curses.has_colors()
    if use_color:
        curses.start_color()
        curses.use_default_colors()
        curses.init_pair(1, curses.COLOR_CYAN, -1)     # parked
        curses.init_pair(2, curses.COLOR_RED, -1)      # busy / failed
        curses.init_pair(3, curses.COLOR_YELLOW, -1)   # in flight
        curses.init_pair(4, curses.COLOR_YELLOW, -1)   # window header
        curses.init_pair(5, curses.COLOR_WHITE, -1)

    def C(n):
        return curses.color_pair(n) if use_color else 0

    def layout(src):
        """The picker's whole derived view: lines, peak RAM, selectable rows.

        Returned together because a refresh rebuilds all three. Carrying either
        of the other two over would draw bars against a stale maximum, or let
        the cursor sit on a row that has since gone busy.
        """
        out = []
        for win, group in group_by_window(src):
            out.append({"kind": "header", "win": win, "rows": group})
            for r in group:
                out.append({"kind": "row", "row": r, "win": win})
        return (out, max((r["bytes"] for r in src), default=1),
                [i for i, item in enumerate(out)
                 if item["kind"] == "row" and not item["row"]["busy"]])

    lines, peak, selectable = layout(rows)
    if not selectable:
        return ("quit", None)
    cur, top = selectable[0], 0
    jobs, lock = {}, threading.Lock()   # ref -> {"verb","done","ok","msg"}
    pending, want_reload, stop = [None], [False], threading.Event()
    onscreen = [True]   # flipped by the terminal's focus reports

    def refresher():
        """Re-scan in the background so the list tracks reality on its own.

        The scan is ~1.5 s of socket round-trips, so it cannot run on the draw
        thread. Results are staged and only swapped in when nothing is in
        flight — worker threads mutate the very row dicts on screen, and
        replacing them mid-kill would strand those mutations.

        Off screen it does not scan at all: nobody is reading the list, and the
        picker has no notifications to miss. Coming back re-scans immediately,
        so what you look at is never the state you left behind.
        """
        while not stop.wait(1.0):
            due = time.time() - refresher.last >= REFRESH_SECONDS
            if not want_reload[0] and not (onscreen[0] and due):
                continue
            want_reload[0] = False
            refresher.last = time.time()
            try:
                fresh = reload()
            except Exception:       # a transient socket failure must not kill it
                continue
            with lock:
                pending[0] = fresh
    refresher.last = time.time()
    threading.Thread(target=refresher, daemon=True).start()

    def move(delta):
        nonlocal cur
        pos = selectable.index(cur) if cur in selectable else 0
        cur = selectable[max(0, min(len(selectable) - 1, pos + delta))]

    def worker(row):
        ref = row["ref"]
        ws = ws_by_ref.get(ref)
        try:
            if row["parked"]:
                res = unpark_one(ws)
            else:
                # attribute() needs EVERY workspace: longest-prefix matching
                # is what stops /repo claiming a nested worktree's processes.
                res = park_one(ws, attribute(list(ws_by_ref.values())),
                               ps_table())
        except (Exception, SystemExit) as ex:   # never kill or wedge the UI
            res = {"ok": False, "msg": str(ex)[:60] or "failed"}
        with lock:
            jobs[ref].update(done=True, ok=res["ok"], msg=res.get("msg", ""))
            if res["ok"]:
                row["parked"] = not row["parked"]
                if row["parked"]:
                    row["bytes"] = res.get("freed", row["bytes"])
                    row["state"] = "parked just now"
                else:
                    row["state"] = "resuming"

    def toggle(row):
        with lock:
            j = jobs.get(row["ref"])
            if j and not j["done"]:
                return  # already in flight
            jobs[row["ref"]] = {"verb": "unfreezing" if row["parked"]
                                else "freezing", "done": False,
                                "ok": None, "msg": ""}
        threading.Thread(target=worker, args=(row,), daemon=True).start()

    tick = 0
    while True:
        tick += 1
        stdscr.erase()
        h, w = stdscr.getmaxyx()
        body = h - 4
        if cur < top:
            top = cur
        elif cur >= top + body:
            top = cur - body + 1

        with lock:
            inflight = [r for r, j in jobs.items() if not j["done"]]
            fresh = pending[0] if not inflight else None
            if fresh:
                pending[0] = None
        if fresh:
            # Keep the cursor on the same workspace across a refresh; a list
            # that jumps under you while you are aiming at a row is worse than
            # no refresh at all.
            here = lines[cur]["row"]["ref"] if lines[cur]["kind"] == "row" else None
            spaces_new, rows = fresh
            ws_by_ref.clear()
            ws_by_ref.update({x["ref"]: x for x in spaces_new})
            lines, peak, selectable = layout(rows)
            if not selectable:
                return ("quit", None)
            cur = next((i for i in selectable
                        if lines[i]["row"]["ref"] == here), selectable[0])
        # lines holds the very same row dicts the worker thread mutates, so
        # the totals can come straight off `rows`.
        parked_n = sum(1 for r in rows if r["parked"])
        free_b = sum(r["bytes"] for r in rows
                     if not r["parked"] and not r["busy"])
        head = (f" park — {parked_n} parked   {human(free_b)} parkable"
                + (f"   {len(inflight)} in flight" if inflight else ""))
        _put(stdscr, 0, 0, head.ljust(w - 1), curses.A_BOLD | C(5))

        for vi in range(body):
            li = top + vi
            if li >= len(lines):
                break
            item, y = lines[li], vi + 2
            if item["kind"] == "header":
                free = sum(r["bytes"] for r in item["rows"]
                           if not r["parked"] and not r["busy"])
                _put(stdscr, y, 0,
                     f" {item['win']}   {len(item['rows'])} ws   "
                     f"{human(free)} parkable".ljust(w - 1),
                     curses.A_BOLD | C(4))
                continue
            r = item["row"]
            with lock:
                job = dict(jobs.get(r["ref"]) or {})

            if job and not job.get("done"):
                mark = Spinner.FRAMES[tick % len(Spinner.FRAMES)]
                tail, attr = job["verb"] + "…", C(3)
            elif job and job.get("ok") is False:
                mark, tail, attr = "✗", job.get("msg", "failed")[:24], C(2)
            elif r["conflict"]:
                # Enter still unparks it, which is exactly right: that path
                # clears the stale entry instead of resuming anything.
                mark, tail, attr = "⚠", "parked, but live", C(2)
            elif r["busy"]:
                mark, tail, attr = "●", r["state"][:24], C(2)
            elif r["parked"]:
                mark, tail, attr = "❄", r["state"][:24], C(1)
            else:
                mark, tail, attr = "○", r["state"][:24], 0

            txt = (f" {mark} {r['ref']:<13} {r['title'][:30]:<31}"
                   f" {bar(r['bytes'], peak, 8, plain=True)} {human(r['bytes']):>8}"
                   f"  {tail:<25}{flags_of(r)}")
            if li == cur:
                attr |= curses.A_REVERSE
            _put(stdscr, y, 0, txt.ljust(w - 1), attr)

        _put(stdscr, h - 1, 0, HELP_LINE.ljust(w - 1), curses.A_DIM)
        stdscr.refresh()

        tick_ms = (TICK_BUSY_MS if inflight
                   else TICK_IDLE_MS if onscreen[0] else TICK_HIDDEN_MS)
        stdscr.timeout(tick_ms)
        try:
            k = stdscr.getch()
        except KeyboardInterrupt:
            k = ord("q")
        if k == -1:
            continue  # timeout: just redraw
        seen = focus_change(stdscr, k, tick_ms)
        if seen is not None:
            onscreen[0] = seen
            # Coming back is the one moment the list has to be true, but a
            # flurry of tab switches must not queue up scans behind itself.
            if seen and time.time() - refresher.last >= FOCUS_REFRESH_GAP:
                want_reload[0] = True
            continue
        if k in (ord("q"), 27):
            with lock:
                busy = [r for r, j in jobs.items() if not j["done"]]
            if busy:
                continue  # never exit mid-kill
            return ("quit", None)
        if k in (ord("f"), ord("F")):
            # Focus but STAY OPEN — you usually want to glance at a workspace
            # and come straight back to the list.
            focus_workspace(lines[cur]["row"], ws_by_ref)
            continue
        if k in (ord("r"), ord("R")):
            want_reload[0] = True
            continue
        if k in (curses.KEY_DOWN, ord("j")):
            move(1)
        elif k in (curses.KEY_UP, ord("k")):
            move(-1)
        elif k == curses.KEY_NPAGE:
            move(body)
        elif k == curses.KEY_PPAGE:
            move(-body)
        elif k in (curses.KEY_ENTER, 10, 13):
            row = lines[cur]["row"]
            if not row["busy"]:
                toggle(row)
        elif k == ord("a"):
            win = lines[cur]["win"]
            group = [item["row"] for item in lines if item["kind"] == "row"
                     and item["win"] == win and not item["row"]["busy"]]
            with lock:
                snapshot = {r["ref"]: r["parked"] for r in group}
            live = [r for r in group if not snapshot[r["ref"]]]
            # Whole window is bulk and destructive, so it still confirms.
            target = live or group
            if target and _confirm(stdscr, target, C):
                for r in target:
                    # A worker may have finished while the modal was up; only
                    # act on rows still in the state the user agreed to.
                    with lock:
                        if r["parked"] != snapshot[r["ref"]]:
                            continue
                    toggle(r)


def cmd_pick(argv):
    with Spinner("scanning workspaces…"):
        # Enter kills things here too, so the picker holds itself to the same
        # rule as `park park`: no parking from a map with a window missing.
        spaces = workspaces_for_park()
        rows = collect(spaces)
    # An optional substring narrows the list — with 40 workspaces, scrolling
    # to the three you care about is the slow part.
    terms = [a.lower() for a in argv if not a.startswith("--")]
    if terms:
        rows = [r for r in rows
                if any(t in r["title"].lower() or t in r["ref"] for t in terms)]
        if not rows:
            die(f"nothing matches {' '.join(terms)}")
    if not rows:
        print("  nothing to show\n")
        return
    if not sys.stdin.isatty() or not sys.stdout.isatty():
        die("interactive picker needs a terminal — use `park ls` instead")
    # curses renders non-ASCII as garbage unless the locale is initialised.
    locale.setlocale(locale.LC_ALL, "")

    ws_by_ref = {w["ref"]: w for w in spaces}
    def reload():
        """Re-scan for the picker's background refresh, same filter as above.

        A window that will not enumerate raises, which the refresher already
        treats as "keep what is on screen": swapping in a partial map would
        leave Enter parking from it, and there is nobody to ask mid-curses.
        """
        missing = []
        sp = all_workspaces(missing)
        if missing:
            raise RuntimeError("partial workspace list")
        fresh = collect(sp)
        if terms:
            fresh = [r for r in fresh
                     if any(t in r["title"].lower() or t in r["ref"]
                            for t in terms)]
        return sp, fresh

    try:
        curses.wrapper(_picker, rows, ws_by_ref, reload)
    finally:
        # The picker turns focus reports on; they have to go off even if it
        # died, or the shell that gets the tty back has `[I`/`[O` typed into
        # its prompt every time the window changes.
        focus_reporting(False)
    print()


USAGE = """park — free RAM from idle cmux workspaces without closing them

  park                         interactive picker (enter toggles a row)
  park pick <filter>           the same picker, pre-filtered by title
  park ls                      what is parked / what is live and parkable
  park .                       park the workspace you are in
  park park <target>...        park workspace(s). --dry-run, overrides below
  park park --idle 3d          park everything idle that long (asks first)
  park park --all              park everything parkable (asks first)
  park unpark <target>...      resume a parked workspace
  park show <target>           dump the ledger entry
  park forget <target>         drop a stale ledger entry without resuming
  park doctor                  verify every parked entry is still restorable
  park repaint                 put back the pill, colour and prefill a cmux
                               restart wiped (--dry-run)
  park rekey                   re-point entries after cmux regenerated its
                               workspace uuids (--dry-run). Run BEFORE rebuild
  park rebuild                 recreate workspaces cmux lost (--dry-run)

targets:  workspace:12 | <uuid> | <title substring> | window:2 | .

--close-tab  after a clean park, focus the agent tab and close the tab park is
             running in. For the ⌥⇧P action, which has to open one.

overrides: --force        waive the CPU sample (corroboration only)
           --kill-anyway  waive the draft guard and the in-flight verdict too;
                          asks for confirmation, needs a terminal. Never
                          together with --all or --idle

exit code: 0 when every target reached the state you asked for (an already
parked workspace counts), 1 when any was refused. `park doctor` exits 1 when
any entry needs attention.

Never parks a workspace whose turn is in flight, and never parks the session
park itself is running in. Parking stops the claude session, its dev servers
and any test browsers; unparking restores ONLY the claude session — start dev
servers yourself.
"""


KNOWN_FLAGS = {
    "ls": ("--json",), "list": ("--json",),
    "park": ("--dry-run", "--force", "--kill-anyway", "--idle", "--all",
             "--close-tab"),
    "pick": (), "unpark": (), "resume": (), "show": (),
    "forget": (), "doctor": (), "rebuild": ("--dry-run", "--closed"),
    "rekey": ("--dry-run",), "repaint": ("--dry-run",),
}


def main():
    if not shutil.which("cmux"):
        die("cmux CLI not found on PATH")
    argv = sys.argv[1:]
    if argv and argv[0] in ("-h", "--help", "help"):
        print(USAGE)
        return
    if not argv:  # bare `park` opens the picker
        return cmd_pick([])
    cmd, rest = argv[0], argv[1:]
    if any(a in ("-h", "--help") for a in rest):
        print(USAGE)
        return
    # `park .` is `park park .`. Parking the workspace you are in is the one
    # target worth a shortcut, and `.` can never be mistaken for a verb. Bare
    # targets in general stay unsupported on purpose: `park doctorr` must not
    # silently kill whatever happens to match the typo.
    if cmd == ".":
        cmd, rest = "park", ["."] + rest
    table = {"ls": cmd_ls, "list": cmd_ls, "park": cmd_park, "pick": cmd_pick,
             "unpark": cmd_unpark, "resume": cmd_unpark, "show": cmd_show,
             "forget": cmd_forget, "doctor": cmd_doctor, "rebuild": cmd_rebuild,
             "rekey": cmd_rekey, "repaint": cmd_repaint}
    if cmd not in table:
        die(f"unknown command '{cmd}'\n\n{USAGE}")
    # Unrecognised flags used to be filtered out silently alongside the real
    # ones, so `park park ws:12 --dry-rnu` dropped the typo and actually parked.
    unknown = [a for a in rest
               if a.startswith("--") and a.split("=")[0]
               not in KNOWN_FLAGS.get(cmd, ())]
    if unknown:
        die(f"unknown option {unknown[0]!r} for `park {cmd}`\n\n{USAGE}")
    # Commands report whether every target reached the state that was asked
    # for. `park .` bound to a keyboard shortcut does not care, but anything
    # scripted — a health check calling `park doctor`, a `park . && …` — has no
    # other way to find out, and a tool that always exits 0 reads as "fine".
    sys.exit(table[cmd](rest) or 0)


if __name__ == "__main__":
    main()
