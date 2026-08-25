# In-guest channel (optional, and the most capable one)

Everything else in this skill pushes input *at* the guest from outside. An in-guest channel
inverts that: a small agent runs inside Windows, takes commands from the host, and reports
back. It is immune to keyboard layout, immune to a dead VNC pointer, and it can do things
no click sequence can — read a file, query a database, enumerate windows.

**Nothing here is shipped with the skill.** You build it once, for your own guest. This
page is the shape and the traps, so you do not rediscover them.

> **Security.** Any such channel is remote code execution into that VM by design. Bind the
> host side to a loopback or tailnet address, never `0.0.0.0` on an untrusted network, and
> require a token. Treat the VM as compromised by anyone who can reach the channel, and
> do not put anything in it you would not put on a public host.

## Two shapes

**Polled file channel** — the guest watches a file on the shared folder; the host writes a
payload and bumps a trigger. Needs no networking, and no bootstrap beyond starting the
watcher. Inherits every shared-folder failure mode, and the cache makes each round trip
tens of seconds.

**HTTP agent** *(better where you can have it)* — the guest long-polls an HTTP endpoint on
the host for the next command and POSTs output and screenshots back. Sub-second round
trips, no shared folder, no cache. The keyboard is then needed exactly once: to type the
bootstrap line that starts the agent. It does not remove the need for idempotency — a
reconnect or a retry can still deliver the same command twice, so every job needs an id the
guest can recognise as already done.

Whichever you build, the guest side wants roughly: move/click/double-click/right-click,
send text (via `SendKeys`), screenshot, list windows, activate a window.

`SendKeys` is not layout-independent in principle — it synthesises keystrokes like anything
else — but in practice it got paths, digits and accented text through unharmed on a non-US
guest where the same strings sent over VNC arrived mangled. Verify it on your guest with a
string containing a digit, a backslash and a colon before you rely on it.

## Traps, all of them paid for

**Starting it**

- **A watcher that starts by reading its trigger file runs the OLD payload immediately.**
  If the last thing you did was shut the machine down, starting the watcher shuts it down
  again. Overwrite the payload with something harmless *before* you start the watcher, and
  leave it harmless when you finish.
- **A stale done-marker makes a recycled job ID look finished instantly** and hands you
  last week's result. Use fresh IDs and read the marker's timestamp, not its existence.
- The bootstrap has to be typed on the guest's keyboard once. Under a non-US layout, send
  literal characters rather than key names (see `keyboard-layouts.md`), and remember that
  pasting a full `powershell -Command "…"` into the Run dialog fails — open a bare shell
  first and paste the command into it.

**Running it**

- **Return an exit status, not just output.** "The command produced text" is not the same
  as "the command succeeded". Have the guest report a status alongside the output, and
  treat a missing status as a failure rather than as success.
- **Give every job a deadline and a way to cancel it.** Without one, a payload that blocks
  leaves you unable to tell a slow job from a dead channel, and the only recovery is
  killing the interpreter from the guest's Task Manager.
- **A payload that produces no output is indistinguishable from a timeout.** A host that
  detects completion by "the output changed" will wait out the full timeout on every click.
  Append something that differs every time — a tick count — to every payload.
- **One hung command hangs the whole channel** if the agent runs commands in a single
  loop. File operations are the usual culprit: downloads, archive extraction, copying to
  the shared drive. Keep those out of the agent, or give it a worker per command.
- **`Add-Type` definitions persist between commands** in a long-lived process, so the
  second run dies with "type already exists". Guard every one:
  ```powershell
  if (-not ([System.Management.Automation.PSTypeName]'MyHelper').Type) { Add-Type … }
  ```
- **Windows PowerShell 5.1 reads a `.ps1` without a BOM as ANSI**, so any non-ASCII string
  in the payload arrives corrupted — and a corrupted string in a query just returns zero
  rows, silently. Write payloads as UTF-8 **with** a BOM, or keep them ASCII-only.
- **Writing output straight onto a network share can fail silently** — the file never
  reaches the host. Write locally in the guest, then copy in a retrying loop.
- **`FindWindow` may return 0 even for an exact ASCII title** that `EnumWindows` can see.
  If a helper built on it stops working, enumerate windows yourself and match on a
  substring.
- **Graphic controls have no window handle.** Toolbar buttons drawn by the application
  (Delphi `TSpeedButton` and similar) are invisible to child-window enumeration and can
  only be reached by coordinates.

**Over the shared folder specifically**

- **Write the payload and bump the trigger at least ~35 s apart.** The guest sees the two
  files through the cache independently, and will otherwise read the new trigger and run
  the *old* payload.
- Wait 45–60 s after a trigger before retrying, and lock against double execution
  — a trigger sent over VNC fails often enough that you will retry, and without a lock the
  work happens twice. Make the lock **atomic**: create a directory, or open the file with a
  create-if-absent flag. `if (Test-Path lock) { exit }` followed by a write is check-then-act
  and races with the retry it is supposed to stop.
- A successful directory listing does not mean the next read will succeed; the host's
  directory cache lies too. When a file matters, verify from a screenshot.

**When it stops answering**

The agent can die quietly and it looks exactly like a dead shared folder: the trigger is
new, the log is silent, the drive is fine. Restart it from the guest without the mouse:
Task Manager (`Ctrl+Shift+Esc`) → Run new task → kill the interpreter → run it again. Make
sure the payload is harmless first, per the first trap above.

## Doing the work directly

Once you have a channel, prefer it over clicking wherever the application allows:

- Query the application's database instead of navigating its GUI — orders of magnitude
  faster and not sensitive to window geometry.
- Read result and log files from disk instead of screenshotting a report window.
- Anything with a command-line or scripting interface should go that way.

The GUI is the channel of last resort, not the default.
