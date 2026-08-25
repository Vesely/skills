---
name: windows
description: Run a UTM Windows VM and control it via agent-browser over noVNC
allowed-tools:
  - Bash(/Applications/UTM.app/Contents/MacOS/utmctl:*)
  - Bash(agent-browser:*)
  - Bash(websockify:*)
  - Bash(~/.local/bin/websockify:*)
  - Bash(pipx:*)
  - Bash(/usr/libexec/PlistBuddy:*)
  - Bash(vncdo:*)
  - Bash(ssh:*)
  - Bash(scp:*)
  - Bash(curl:*)
  - Bash(nc:*)
  - Bash(netstat:*)
  - Bash(lsof:*)
  - Bash(pgrep:*)
  - Bash(kill:*)
  - Bash(osascript:*)
  - Bash(sips:*)
  - Bash(screencapture:*)
  - Bash(cliclick:*)
  - Bash(killall:*)
  - Bash(git:*)
  - Bash(grep:*)
  - Bash(head:*)
  - Bash(od:*)
  - Bash(mv:*)
  - Bash(ps:*)
  - Bash(mktemp:*)
  - Bash(timeout:*)
  - Bash(gtimeout:*)
  - Bash(open:*)
  - Bash(cp:*)
  - Bash(ls:*)
  - Bash(cat:*)
  - Bash(mkdir:*)
  - Bash(rmdir:*)
  - Bash(rm:*)
  - Bash(date:*)
  - Bash(stat:*)
  - Bash(test:*)
  - Bash(which:*)
  - Bash(sleep:*)
  - Bash(python3:*)
  - Read
  - Write
  - Edit
  - AskUserQuestion
when_to_use: |
  Use ONLY when the user explicitly invokes `/windows` (with optional action description).
  Examples: `/windows`, `/windows open Notepad`, `/windows close` (tear down the browser
  session), `/windows stop` (shut the VM down properly), `/windows <action> on <target>`
  to pick a non-default VM from config.json.
  Do NOT auto-invoke from general phrasing about Windows or UTM — wait for the slash command.
argument-hint: "[action | close | stop] [target]"
arguments:
  - action
---

# Windows VM (UTM + noVNC + agent-browser)

Start a UTM Windows VM, bring up a noVNC bridge, and drive the guest from a browser
session. A fast path skips setup when everything is already running; recipes cache
sequences that worked.

## Inputs

- `$action`: (optional) what to do, e.g. "open Notepad". Special values:
  - `close` = tear down the browser session only (leave the VM running).
  - `stop` / `shutdown` = shut Windows down properly from the inside, then quit UTM.
- The action may also name a target from `config.json`, or one of its `aliases`.

## References — read the relevant one *before* you need it

| File | Read it when |
|---|---|
| `references/config.md` | writing or extending `config.json`, or a key is missing |
| `references/input.md` | **before your first click or keystroke on a target**, and whenever input stops working |
| `references/troubleshooting.md` | anything looks frozen, black, stale or off by a factor |
| `references/keyboard-layouts.md` | `guest_keyboard` is not `us`, or typed text comes out wrong |
| `references/shared-folder.md` | moving files in or out, or a guest dialog hangs |
| `references/guest-channel.md` | noVNC and `vncdo` are both insufficient, or you need real work done inside the guest |
| `references/recipes.md` | saving, loading or writing a recipe |

## Configuration

**Everything machine-specific lives in `config.json` in this skill's directory.** No
hostname, UUID, port or personal path appears in this file, so the skill can be shared
as-is; each user brings their own config. Standard install locations (UTM's app bundle and
container) do appear, and the ones that genuinely vary — `novnc_path`, `websockify` — are
config keys.

**If `config.json` is missing, or a key you need is absent — HALT.** Print the setup block
below and stop. Never fall back to `config.example.json`, and never guess a value: a wrong
UUID starts someone else's VM, and a wrong `ssh_host` connects to a machine that is not
yours.

> Copy `config.example.json` to `config.json` and fill in `vm_uuid` and `bundle`.
> Get the UUID with `/Applications/UTM.app/Contents/MacOS/utmctl list`.

Minimum config — two fields, everything else defaults:

```json
{ "vm_uuid": "XXXXXXXX-XXXX-XXXX-XXXX-XXXXXXXXXXXX", "bundle": "Windows.utm" }
```

For several VMs, target selection, and the full key table, see `references/config.md`.

### Loading it

```bash
# SKILL_DIR = the directory you loaded this SKILL.md from. This file is not an executed
# script, so there is no $0 to derive it from — substitute the literal path (it is
# usually ~/.claude/skills/windows, often a symlink to a checkout elsewhere).
SKILL_DIR=<directory this SKILL.md was loaded from>
CFG="$SKILL_DIR/config.json"

TARGET=<chosen target key>          # $action alias match → target key → default_target
SSH_HOST=<ssh_host or empty>
VNCHOST=<vnc_host>
VNCPORT=<vnc_port>                  # port ON THE VM HOST
TUNNEL_PORT=<tunnel_local_port or empty>
VMDIR=<bundle>
VMUUID=<vm_uuid>
BRIDGE_PORT=<bridge_port>
SESSION=<session_name>

# What websockify and vncdo connect to on THIS Mac:
if [[ -n "$TUNNEL_PORT" ]]; then BRIDGE_TARGET="localhost:$TUNNEL_PORT"
else                             BRIDGE_TARGET="$VNCHOST:$VNCPORT"; fi

# Run a command on whichever machine hosts the VM.
# It takes ONE string and runs it through a shell, so redirects, pipes and || work
# the same locally and remotely. Quote every call site accordingly.
run() {
  if [[ -n "$SSH_HOST" ]]; then ssh "$SSH_HOST" "$1"
  else                          bash -c "$1"; fi
}

PLIST=~/Library/Containers/com.utmapp.UTM/Data/Documents/$VMDIR/config.plist

# Scratch for this run. Fixed /tmp names collide with another session of the same user,
# and screenshots here are full captures of someone's desktop.
RUNDIR=$(umask 077; mktemp -d "/tmp/windows-skill.XXXXXX")
```

Put every screenshot, log and marker under `$RUNDIR` and delete it when you finish. The
one deliberate exception is the readiness marker below, which has to outlive the run.

**Validate every value before it reaches a shell command.** `vm_uuid` must match the UUID
shape; `vnc_port`, `tunnel_local_port` and `bridge_port` must be integers in range; and
`ssh_host`, `bundle`, `vnc_host`, `novnc_path`, `websockify`, `session_name`,
`shared_folder`, the target names and their `aliases` must contain no whitespace, quotes,
`;`, `|`, `&`, `$`, newlines or backticks — every one of them is substituted into a command
line, several of them unquoted. You may not be the person who wrote that file.

**`run` must be a function, not a variable.** In zsh an unquoted variable is **not**
word-split — `SSHP="ssh host"; $SSHP ls` fails with `command not found: ssh host`. Add
`2>/dev/null` and the command vanishes without a trace, looking like it succeeded.

**And it must go through a shell on both branches.** A `run() { "$@"; }` local branch
execs its arguments directly, so `run 'pgrep -x UTM >/dev/null || open -a UTM'` looks for
a program with that entire sentence as its name — which fails on the local target only,
while the remote target works. Use one string plus `bash -c`, as above.

**Anything you want expanded on the far side must be escaped**: `\$(date …)` inside a
double-quoted `run` argument, or the host's own value is substituted before it is sent.

`$PLIST` expands **locally**, which is right only if the remote user has the same home
path. If not, build it on the far side or keep `~/Library/…` in single quotes.

**The bridge and the browser session always run on this Mac**, whatever the target is.
Only websockify's upstream address changes.

## Hard rules

Rules marked **[universal]** follow from how UTM/QEMU/noVNC/Win32 work. Rules marked
**[verify once]** were observed on a specific setup and may differ on yours — check them
the first time you use a target and record the answer in that target's `notes`.

### Never run two copies of the same VM at once **[universal]**

Two QEMU processes on the **same disk image** corrupt it outright. Two *copies* of one
image are less dramatic but still bad: they share a Windows machine SID and often a
`vm_uuid`, so they collide on the network and on anything licence- or identity-bound, and
afterwards you cannot tell which copy holds the real data. Either way, run one.

```bash
pgrep -f qemu >/dev/null && echo "A VM IS RUNNING LOCALLY"
# every DISTINCT ssh_host across all targets, not just the one you are about to start
for h in $(<every distinct non-null ssh_host in config.json>); do
  ssh -o ConnectTimeout=5 "$h" 'pgrep -f qemu >/dev/null' 2>/dev/null \
    && echo "A VM IS RUNNING ON $h"
done
```

If one is up and the user asked for another, **stop and ask**. This is the one place in
this skill where asking is mandatory.

### The VM is shared. Claim it atomically before you touch it **[universal]**

GUI automation is exclusive to the foreground window: two sessions at once switch each
other's windows, clicks land in the wrong place, and both lose their work — or worse, save
something in the wrong place.

Claim with an operation that cannot interleave. `mkdir` fails if the directory exists, so
it is a lock; reading a file and then writing it is not.

```bash
# On the VM HOST's own filesystem, not on the shared folder — the share is the least
# reliable thing here, and a lock you cannot read is worse than no lock.
LOCK=/tmp/vm-owner-$VMUUID.lock
if run "mkdir '$LOCK' 2>/dev/null"; then
  run "echo '<session-name> '\$(date +%FT%T) > '$LOCK/held-by'"    # we hold it
else
  run "cat '$LOCK/held-by' 2>/dev/null"                             # someone else does
fi
```

Everyone driving that VM goes through its host, so a lock there is seen by every session,
including ones on other machines. Key it by `$VMUUID` so two different VMs on one host do
not block each other.

- **Refresh `held-by` as you work** (its mtime is the liveness signal). Release it when
  you are done — including when you abort or hit an error — but **only if it is still
  yours**; between your last refresh and now someone may legitimately have taken over:
  ```bash
  run "grep -q '<session-name>' '$LOCK/held-by' 2>/dev/null && rm -rf '$LOCK'"
  ```
- **When it is taken, do not start anything** — not even "just one screenshot", which
  still switches the foreground window. Do not wait blindly either:
  1. **Ask the user** who holds it and whether to wait — always available, always correct.
  2. If your harness can address other agent sessions by name and the owner string looks
     like a session name, ask that session directly. An optimisation, not a requirement.

  Short wait (~10 min) → wait and retry. Long or no answer → tell the user and let them
  decide.
- **A stale lock is a judgement call, not a timer.** An old `held-by` with no other
  activity is probably a crashed session — but a long-running import looks identical.
  Confirm the guest is idle (two screenshots 60 s apart, unchanged) *and* say what you are
  doing before you break someone's lock. Never break one on a timer alone.
- **Before releasing, clean up inside the guest.** Close the applications and dialogs you
  opened, and leave the desktop as you found it. Anything you did not open, leave alone.

### Never send `mouse down` without an immediate `mouse up` **[universal]**

`mouse down` and `mouse up` are separate CLI processes. If anything happens between them,
the guest is left holding a button — and the whole input path can wedge: the framebuffer
keeps updating, but **no input arrives at all, mouse or keyboard, including Escape**.
Restarting the session or websockify does not clear it; a bare `mouse up` does.

**Do not click in the guest through noVNC.** Use `vncdo` or an in-guest channel for that.
Exactly two noVNC pointer uses remain allowed, both emitted as one uninterrupted unit with
nothing in between:

- `mouse move` alone — a hover, for the tooltip probe. No button involved.
- `mouse move` → `down` → `up` **once**, to give the browser canvas focus so keystrokes
  reach noVNC. That is a focus tap, not a click in the guest, and it is the only place the
  sequence appears.

Full reasoning and the recovery procedure are in `references/input.md`.

### Only one VNC client at a time **[verify once]**

Treat the VNC head as exclusive unless a probe proves otherwise on your setup. While noVNC
holds it, `vncdo capture` comes back black or hangs — which looks exactly like a dead VM.
**Never run `vncdo` while the browser session is connected**: release the session and the
bridge first, confirm the upstream socket is gone, then reconnect afterwards. Procedure in
`references/input.md`.

### Probe the input channel; never trust a cached answer **[verify once]**

Which channel reaches the guest is **not stable**. Observed over months on one VM: the
mouse worked, died, worked, worked only via `vncdo`, died again after a restart — with no
configuration change. On the same day two applications in the same guest disagreed about
whether the keyboard or the pointer was the working one.

So `input_preference` in `config.json` is the order to **try**, never a verdict. Probe at
the start of a session that will do more than take a screenshot (~20 s), and re-probe
whenever a step silently does nothing, after any restart, and when the foreground
application changes. If nothing is verified, **stop and say so** — do not "try a click".
The probe is in `references/input.md`.

### Bound everything that talks to the VM **[universal]**

Every `vncdo`, `ssh`, `nc`, share and capture call gets an explicit timeout. Un-bounded,
they do not fail — they hang for tens of minutes and look like a dead guest. In
particular, never probe a network share with a bare `Test-Path`; see
`references/shared-folder.md`.

### Kill by pid, never by pattern **[universal]**

`pkill -f websockify` and friends also kill other sessions' bridges, other agents' work and
other people's processes. Resolve the pid first (`lsof -t`, `pgrep -f`), look at what you
found, then kill that pid.

**One deliberate exception: `killall UTM`.** UTM is a single application instance owning
every VM on that host, so there is no per-VM process to target — and an `osascript` quit
fails silently over SSH. It is still blunt: it takes down *every* VM on that machine, so
check the other targets' locks on that host first, and never reach for it while another
session holds one.

### The shared folder is the most fragile link **[universal for UTM's WebDAV sharing]**

When it dies, **every guest dialog that touches it hangs for many minutes**, and anything
in the guest polling a file there dies with it. Check it is alive before a long series of
steps. Recovery order and the safe liveness test: `references/shared-folder.md`.

### A dialog that "ignores the keyboard" usually just lacks focus **[universal]**

Send `alt-tab` first, then `esc`/`enter` — one `alt-tab` per stuck dialog. Verified on a
pair of windows that had resisted `esc`, `tab`+`enter` and clicking, and which two sessions
independently concluded were unreachable by keyboard. They were reachable; the keys were
going somewhere else.

### VNC has no authentication here **[universal]**

`vnc_display_arg` must keep its `127.0.0.1` prefix. Reach the port from another machine
through the SSH tunnel this skill sets up — never by binding QEMU to `0.0.0.0`.

## Fast path (try first, ~0.3 s)

**Never call `eval` on the fast path.** Not for cost, but because `session list` plus a port
check answers faster, and `eval` needs a live connected canvas — exactly what you are still
verifying.

```bash
# 1. ports listening — VNC on the target, bridge always local
nc -z -w1 ${BRIDGE_TARGET%:*} ${BRIDGE_TARGET##*:} >/dev/null 2>&1 \
  && lsof -nP -iTCP:"$BRIDGE_PORT" -sTCP:LISTEN -t >/dev/null || exit 1
# 2. session exists
agent-browser session list 2>/dev/null | grep -qE "^[[:space:]]*$SESSION\$" || exit 1
# 3. the browser is really attached — without this a zombie session passes:
#    window still open, websocket long dead
lsof -nP -iTCP:"$BRIDGE_PORT" -sTCP:ESTABLISHED -t >/dev/null 2>&1 || exit 1
# 4. marker from the last successful setup, TTL 30 min AND the same target
M=/tmp/windows-skill-ready-$SESSION
[[ -f $M ]] && [[ $(($(date +%s) - $(stat -f %m $M))) -lt 1800 ]] \
  && [[ "$(cat $M)" == "$TARGET" ]] || exit 1
echo "ALL_READY"
```

`ALL_READY` → jump to **Step 5**. Otherwise walk 1–4, and on success
`echo "$TARGET" > /tmp/windows-skill-ready-$SESSION`.

**Why the `ESTABLISHED` check.** A session whose websocket dies keeps running and looks
alive: `session list` shows it, the bridge port listens. Measured once: such a session held
**two cores for 8 hours**, because a disconnected noVNC canvas retries forever. The socket
is the only reliable evidence — though it is *necessary, not sufficient* (sockets exist
during "Connecting…" too), so the sanity screenshot confirms the handshake completed.

**The marker carries the target on purpose.** If it only had to exist, switching targets
would sail through and you would be talking to the old bridge and the still-running VM
behind it.

**Sanity verify before the first action** (not on the fast path): one screenshot,
`agent-browser --session "$SESSION" screenshot "$RUNDIR/_vnc.png"`. If it is dominated by a dark
background with the noVNC logo, reconnect (Step 4).

## Steps

### 1. Preflight (only if the fast path failed)

Local tools, in parallel: `which agent-browser`; `<websockify> --help` (else
`pipx install websockify`); `ls <novnc_path>/vnc.html` (else
`git clone --depth 1 https://github.com/novnc/noVNC.git <novnc_path>`); `which vncdo`
(`pipx install vncdotool`); `which cliclick` only for `start_method: cliclick`.

VM configuration, on the target. Read the plist directly rather than through `utmctl`:

```bash
run "/usr/libexec/PlistBuddy -c 'Print :QEMU:AdditionalArguments' '$PLIST'"
run "/usr/libexec/PlistBuddy -c 'Print :Display:0:Hardware' '$PLIST'"
```

Expected: a **non-GL** display, and the VNC argument matching `vnc_display_arg`. A `-gl`
display makes QEMU refuse the VNC console (`The console requires a GL context`). On the
setup this was written against the working value was `virtio-ramfb`; the right value is
whatever your UTM build offers without `-gl`, so read the current one before changing it.
If they match, continue. If not:

1. If the VM is running, **human checkpoint**: shut Windows down from the inside over VNC.
   Poll until the qemu process is gone. Never `--force`.
2. Quit UTM — over SSH `run "killall UTM"` (an osascript quit fails silently over SSH);
   locally `osascript -e 'tell application "UTM" to quit'`. Verify with `run "pgrep -x UTM"`.
3. Back the plist up: `run "cp '$PLIST' '$PLIST.bak-$(date +%Y%m%d-%H%M%S)'"`.
4. Write the arguments. `Add` fails if the entry already exists and `Set` fails if it does
   not, so **read first, pick the right verb, and check each result before the next** — a
   half-written `AdditionalArguments` leaves the VM unable to boot:
   ```bash
   run "/usr/libexec/PlistBuddy -c 'Add :QEMU:AdditionalArguments:0 string -vnc' '$PLIST'"
   run "/usr/libexec/PlistBuddy -c 'Add :QEMU:AdditionalArguments:1 string <vnc_display_arg>' '$PLIST'"
   run "/usr/libexec/PlistBuddy -c 'Set :Display:0:Hardware <non-GL display>' '$PLIST'"
   ```
   If anything fails midway, restore the `.bak-*` you just made and start over.
5. `run "open -a UTM"`, then Step 2.

### 2. VM start

**First confirm no other copy of this VM is running.** Then, by `start_method`:

**`utmctl`** — the normal path, locally and over SSH where Automation is approved:

```bash
run 'pgrep -x UTM >/dev/null || open -a UTM'
run "timeout 20 /Applications/UTM.app/Contents/MacOS/utmctl start '$VMUUID'"
```

Always address the VM by `$VMUUID`, never by name. **Bound the call**: without Automation
approval `utmctl` blocks for 120 s before returning `-1712`, so give it an explicit limit
and treat a timeout as "this target needs `start_method: cliclick`", not as something to
retry. (`timeout` is GNU coreutils — `gtimeout` from `brew install coreutils`, or use
`ssh -o ConnectTimeout` plus a server-side bound.)

**`cliclick`** — for a Mac nobody is sitting at, where `utmctl` over SSH hangs. Apple
Events need Automation (TCC) approval, and with no one there to click that prompt the call
blocks for 120 s and returns `-1712`. Drive UTM's GUI instead. This needs that Mac to have
a **logged-in graphical session** and to have granted Accessibility and Screen Recording —
it is a workaround for an unattended machine, not for a truly headless one:

```bash
run 'pgrep -x UTM >/dev/null || open -a UTM'
run "screencapture -x -t png $RUNDIR/s.png"       # find the play button
HOST_LOGICAL_W=${HOST_LOGICAL_RESOLUTION%%x*}    # "1920x1080" -> 1920; empty if unset
[[ -n "$HOST_LOGICAL_W" ]] && run "sips -Z $HOST_LOGICAL_W $RUNDIR/s.png"
run 'cliclick m:<x>,<y> w:300 c:<x>,<y>'          # cliclick_play_xy from config.json
```

Coordinates are **logical points**. A scaled panel reports physical pixels in a screenshot
but takes clicks in logical points; skip the downscale and every coordinate is off by the
scale factor. If someone can approve the Automation prompt once, this detour disappears.

**Enlarge the VM window on a remote target, but do NOT full-screen it.** True full screen
hides the UTM menu bar that drives the VM and covers the rest of that machine's screen.
This has no effect on the resolution you see over VNC — the guest decides that.

Poll **on the VM host**: `run "netstat -an" | grep "\.$VNCPORT.*LISTEN"`, 300 ms step, 60 s
over a network, 40 s locally. `$VNCPORT` is the port on that machine, never the tunnel port.

**If `tunnel_local_port` is set, open the tunnel now, before the bridge:**

```bash
lsof -nP -iTCP:"$TUNNEL_PORT" -sTCP:LISTEN -t >/dev/null 2>&1 \
  || ssh -fN -L "$TUNNEL_PORT:127.0.0.1:$VNCPORT" "$SSH_HOST"
```

### 3. Bridge

The bridge always runs **on this Mac**, on `$BRIDGE_PORT`; only its upstream changes. If
`lsof -i:$BRIDGE_PORT` is empty:

```bash
<websockify> --web <novnc_path> 127.0.0.1:"$BRIDGE_PORT" "$BRIDGE_TARGET" \
  >"$RUNDIR/novnc.log" 2>&1 &
```

**The `127.0.0.1:` prefix is not optional.** Without it websockify binds every interface,
and noVNC has no authentication — anyone who can reach this Mac gets full view *and*
control of that Windows desktop. Same reasoning as `vnc_display_arg`.

Poll `curl -s -o /dev/null -w "%{http_code}" http://localhost:$BRIDGE_PORT/vnc.html` until
`200` (100 ms step, 5 s timeout).

**When the target changes, close the browser session *and* stop websockify** — the upstream
is fixed at launch and cannot be switched. Close the session **first**: one left open
against a dead bridge is exactly the two-core zombie described above. Resolve websockify's
pid (`lsof -nP -iTCP:"$BRIDGE_PORT" -sTCP:LISTEN -t`) and kill that, not a pattern. Kill a
stale tunnel the same way, then rebuild both.

### 4. Browser session (idempotent)

- **No `$SESSION`** → create it. `open` navigates, so it is two commands:
  ```bash
  agent-browser --session "$SESSION" open "http://localhost:$BRIDGE_PORT/vnc.html?host=localhost&port=$BRIDGE_PORT&autoconnect=true&quality=4"
  agent-browser --session "$SESSION" set viewport <width> <height>   # TWO args, not "1920x1080"
  ```
- **It exists** → verify with a screenshot (no `eval`). Showing the noVNC logo → `goto`
  the bridge URL to reconnect.

**The guest's resolution is set inside the guest and cannot be changed from outside.**
`resize=remote` is pointless — the server refuses and logs `Server did not accept the
resize request`.

Set the viewport to **exactly the guest resolution**, or every coordinate is wrong:
smaller → noVNC scales down and the taskbar is cut off; larger → the canvas is centred and
every coordinate is offset by half the difference; equal → 1:1 at 0,0.

```bash
agent-browser --session "$SESSION" eval "(() => { const c=document.querySelector('canvas'); const r=c.getBoundingClientRect(); return c.width+'x'+c.height+' @ '+Math.round(r.left)+','+Math.round(r.top); })()"
```

You want `<guest_resolution> @ 0,0`. Different → update `guest_resolution` and resize.
**Re-measure after any guest reboot**; a reboot can change the resolution and silently
invalidate every stored coordinate. (`agent-browser` takes a *script* whose value is the
last expression; a wrapped IIFE works in every variant, so always write it that way.)

**After a `goto`, do not blind-`sleep`** — poll with screenshots every 300 ms and continue
as soon as the dominant colour is no longer the dark noVNC background. Timeout 8 s.

On success: `echo "$TARGET" > /tmp/windows-skill-ready-$SESSION`.

### 5. Perform the action

**Special `$action` values:**
- `close` → `agent-browser close --session "$SESSION"` and stop. **Never `--all`.**
- `stop` / `shutdown` → shut the VM and UTM down per Cleanup.
- empty → report "pipeline ready" and stop.

Otherwise: look for a recipe, run it if it matches, investigate and save one if not — see
`references/recipes.md`.

**Pick the channel before you act, and do not mix two of them in one pass.** Before the
first click or keystroke on this target, run the input probe (`references/input.md`).

- **Keyboard-only work** (Start menu, typing, `Alt+F4`, `Alt+Tab`, dialogs): stay on noVNC.
  Screenshots and keystrokes share one connection and cost nothing extra.
- **Anything needing a pointer**: noVNC keeps the VNC head, so `vncdo` cannot have it.
  Group the pointer work together, then: release the session and the bridge → confirm the
  upstream socket is free → one bounded `vncdo` call containing move, pause, click and
  capture → reconnect (Steps 3–4) when the pointer work is finished. Procedure and pitfalls
  in `references/input.md`.
- **Real work inside the guest** (files, queries, anything scriptable): prefer an in-guest
  channel over clicking at all — `references/guest-channel.md`.
- **No channel verified**: stop and say so. Do not "just try a click".

**Verify after every coordinate-sensitive or destructive step**, with a screenshot and a
statement of what you expect to see. A click that landed 40 px away and a click that did
not arrive look identical until you look.

## Cleanup

**Clean up inside the VM first, then deal with the session.** Close what you opened and
release the lock, even when you leave the browser session running.

**Default: leave the browser session running.** Measured: a connected idle session costs
~10 % of one core and ~270 MB, and websockify adds nothing. Tearing it down and setting it
up again costs more than it saves. Close it (**never `--all`**) only when the user says
`/windows close`, "done with Windows", or the action itself is `close`.

That only holds for a session that is genuinely connected — a disconnected one costs two
cores, and the `ESTABLISHED` check catches it next time.

`agent-browser session list` lists every live session. **Never close or touch sessions that
are not yours.** `$SESSION` on the noVNC URL → reuse; `$SESSION` on a different URL → leave
it and open `<name>2`; anything else → leave alone.

### Shutting the VM down

Different rule from the browser session: the VM holds its full RAM allocation the whole
time it runs, so shut it down once the work is done.

**Ask first unless you can show the guest is idle.** A shutdown is only "reversible" if
nothing is in flight. *Idle* means all of: the lock is yours; two screenshots 60 s apart are
identical; no window shows a progress indicator or an unsaved-changes marker; and you opened
everything that is open. Anything less — in particular an application you did not start,
which may hold a person's unsaved work — means **ask**. If someone else holds the lock, do
not shut down at all.

**Proper shutdown, in this order:**

1. Shut Windows down **from the inside**, via the keyboard. `Alt+F4` on the desktop opens
   the "Shut down Windows" dialog. **Read the selected action in the screenshot before you
   press Enter** — which one is preselected depends on policy and on what the machine did
   last, and Restart or Sign out look almost identical at a glance.
   ```bash
   agent-browser --session "$SESSION" press "Alt+F4"   # screenshot to see what opened
   agent-browser --session "$SESSION" press "Enter"    # only once you see the dialog
   ```
   `Alt+F4` closes the **focused window** first, so close applications first (`Alt+Tab` →
   `Alt+F4`) or they block the shutdown. With an in-guest channel, `Stop-Computer -Force`
   is the other correct path. Neither `utmctl stop` nor closing the UTM window is a proper
   shutdown — both return before the guest is down and leave NTFS unclean.
2. Wait for the qemu process to disappear (90 s timeout). Check what your UTM version
   actually names it — it may run QEMU under a helper process rather than as `qemu-<arch>`.
3. Close the browser session and websockify (by pid), delete `/tmp/windows-skill-ready-$SESSION` and `$RUNDIR`.
4. Quit UTM — over SSH `run "killall UTM"`; locally
   `osascript -e 'tell application "UTM" to quit'`.

## Notes

- Everything machine-specific is in `config.json`; this file stays free of hostnames,
  UUIDs, ports and personal paths so it can be shared.
- `config.json`, `recipes/` and `notes/` are ignored in a fresh clone. If a checkout
  already tracked them before the ignore rules existed, they are still tracked — verify
  with `git ls-files` before pushing anywhere.
- Screenshots under `/tmp` are full-desktop captures of someone's working machine. Delete
  what you no longer need, and look at one before attaching it anywhere.
- Plist location: `~/Library/Containers/com.utmapp.UTM/Data/Documents/<bundle>/config.plist`.
- Exposing a VNC port across a private network (e.g. `tailscale serve --bg --tcp <port>
  tcp://127.0.0.1:<port>`) persists across reboots and needs no re-setup. It also hands
  **unauthenticated** view-and-control of that desktop to everything on the tailnet — the
  SSH tunnel this skill sets up gives you the same reach without that. Prefer the tunnel;
  reach for `serve` only knowing what it opens.
