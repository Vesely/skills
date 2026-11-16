# Getting input into the guest

Read this the first time you use a target, and again whenever something that worked
yesterday stops working. **Which channel delivers input is not a stable property of your
setup** — see *It flips* below.

## The four channels

| Channel | Delivers | Needs | Notes |
|---|---|---|---|
| **noVNC** via `agent-browser` | screenshots always; keyboard usually; mouse sometimes | the bridge (Step 3) | the only one this skill sets up for you |
| **`vncdo`** over the VNC port | mouse and keyboard | `pipx install vncdotool`, and the VNC socket **free** | best mouse path when noVNC's mouse does not land |
| **In-guest agent** | everything, in the guest's own terms | something you install inside Windows | immune to keyboard layout; see `guest-channel.md` |
| **SSH into the guest** | everything | an SSH server in Windows | lands in session 0, see below |

## The probe: which one works *today* (~20 s)

Run it at the start of a session that will do more than take a screenshot. Do not skip it
because `config.json` says something — that field records what was true last time.

```bash
# 1. keyboard?  Ctrl+Esc should open the Start menu.
agent-browser --session "$SESSION" press "Control+Escape"
agent-browser --session "$SESSION" screenshot "$RUNDIR/p1.png"    # Start menu visible?
agent-browser --session "$SESSION" press "Escape"

# 2. mouse?  hover a taskbar icon and look for a tooltip. A hover only — no button is
#    pressed, so this is not the click that SKILL.md forbids over noVNC.
agent-browser --session "$SESSION" mouse move <x> <y>
agent-browser --session "$SESSION" screenshot "$RUNDIR/p2.png"    # tooltip visible?
```

- Start menu opened → keyboard works over noVNC.
- Tooltip appeared → mouse works over noVNC.
- Neither → the bridge is a **screenshot channel only**. Do not spend an hour concluding
  the keyboard is broken; it may never have been connected. Go to `vncdo` or an in-guest
  channel, and record `"input": "none"` as a *hint* for next time.

> **The mouse probe lies on a local target when a physical cursor sits over the UTM
> window.** A local UTM window forwards the real mouse into the guest, so a tooltip
> appears whether or not VNC input works. Move the physical cursor away first. On a
> headless remote host this cannot happen.

## It flips

Observed over eight months on one long-lived VM: mouse worked, then died, then worked,
then only through `vncdo`, then died again after a VM restart — with no configuration
change in between. On the same day, in the same guest, **two applications disagreed**: in
one, in-guest `SendKeys` typed fine while in-guest synthetic clicks did nothing; in the
other, exactly the reverse.

Consequences for how you work:

- **Treat `mouse` / `input` in `config.json` as last-known, never as truth.** They are
  there to tell you what to try *first*, not to skip the probe.
- **When a step silently does nothing, re-probe before you debug the application.** The
  cheapest test is 10 seconds; assuming the channel is fine costs hours.
- **A restart of UTM or of the guest can change the answer.** Re-probe after either.

## Never leave a mouse button down

**[universal, and the single most damaging mistake in this skill]**

`mouse down` and `mouse up` are separate CLI invocations. If anything fails between them —
a non-zero exit, a timeout, you deciding to do something else — the guest is left holding
a button. Once that happens the guest's whole input state can wedge: the framebuffer keeps
updating so it looks alive, but **no further input arrives at all, mouse or keyboard,
including Escape**, and the last hover tooltip stays painted on screen.

Restarting the browser session does not clear it. Restarting websockify does not clear it.
What cleared it was a **bare `mouse up` with no preceding `mouse down`**:

```bash
agent-browser --session "$SESSION" mouse up
```

So: emit `down` and `up` as one unit, never branch between them, and when input has gone
dead for no reason, send a lone `mouse up` before you conclude anything else.

## One VNC client at a time

**Treat the VNC head as exclusive unless a probe on your setup proves otherwise.**
Observed consistently here: while noVNC holds it, `vncdo capture` returns a **black frame**
or hangs, and a websockify worker left over from a dead session keeps holding it — which
looks exactly like a dead VM.

**So do not run noVNC and `vncdo` at the same time.** Hand the head over explicitly:

```bash
# 1. release the browser  (never --all: other agents own the other sessions)
agent-browser close --session "$SESSION"
# 2. stop OUR websockify by pid, not by pattern
for pid in $(lsof -nP -iTCP:"$BRIDGE_PORT" -sTCP:LISTEN -t); do kill "$pid"; done
# 3. confirm the upstream socket is really gone before continuing
run "lsof -nP -iTCP:$VNCPORT | grep -c ESTABLISHED"     # want 0
```

Kill by pid throughout. A broad `pkill -f websockify` also kills bridges belonging to
other sessions and other people's work.

Reconnect noVNC (Step 3 + Step 4) when you are done with `vncdo`.

Diagnose before assuming the guest is dead — one line each:

```bash
run "lsof -nP -iTCP:$VNCPORT | grep -c ESTABLISHED"   # 1 = someone holds the head
run "nc -w 5 127.0.0.1 $VNCPORT | head -c 12 | od -c" # "RFB 003.008" = server is healthy
```

If the RFB handshake answers, QEMU is fine and the fix is to release the client — not to
restart UTM.

## `vncdo` in practice

```bash
# only when the port is not reachable directly
ssh -fN -L "$TUNNEL_PORT:127.0.0.1:$VNCPORT" "$SSH_HOST"
vncdo -s "127.0.0.1::$TUNNEL_PORT" move 1535 971 click 1
```

Five traps, each of which reads as "the VM is frozen":

1. **The first `capture` after connecting can return a stale framebuffer.** Tell by the
   guest's clock, not by the window contents. Force a redraw first:
   `vncdo -s … move 3000 1900 pause 2 capture out.png`.
2. **A killed background shell leaves the `vncdo` process alive holding the connection**,
   and every later `vncdo` then hangs silently. Measured once at 1 h 07 min. Recovery:
   `pgrep -fl "vncdo -s"` then `kill -9 <pid>`. Never run two `vncdo` calls concurrently,
   and keep long `pause` chains out of calls that might get backgrounded.
3. **Modifiers need explicit pauses.** `key shift-d` sends a plain `d`; the modifier and
   the character arrive too close together for Windows to pair them.
   ```bash
   vncdo -s … keydown shift pause 0.4 key c pause 0.3 key y pause 0.3 keyup shift
   ```
4. **A key name outside `vncdotool`'s `KEYMAP` hangs the connection to timeout and sends
   nothing.** `period`, `digit1`, `bracketright` are not in it. Send the literal character
   (`type "."`) instead of a name. In 1.3.0 some names also die with
   `TypeError: ord() expected a character` — in a helper that discards stderr this fails
   completely silently. On one setup `Return`, `Delete`, `Home` and `End` hung too; if
   they do on yours, navigate by menu instead of by shortcut.
5. **A hostname that resolves to IPv6 can break it**: `CRITICAL … Socket operation on non-socket`,
   while `nc -z host port` succeeds. Address the IPv4 literal instead. It alternates with
   whatever the resolver returns, so on the first such error switch to the IP rather than
   investigating the VNC head.

Over a slow link raise `--timeout` well above the default; a large framebuffer can take
tens of seconds to pull.

`vncdo` has **no `paste`** — the clipboard does not go this way. It has `type`, `typefile`,
`key`, `move`, `click`, `capture`, `rcapture`.

## SSH into the guest

If Windows runs an SSH server, `ssh <vm-host> 'ssh <guest> "…"'` bypasses VNC entirely and
noVNC stays useful for screenshots. Two traps:

- **Quoting is mangled across two SSH hops.** Send PowerShell as `-EncodedCommand` with a
  UTF-16LE base64 payload, or write the script to a file and transfer it.
- **An SSH session lands in session 0**, while the interactive desktop is session 1. A
  process started from SSH opens its window on an invisible desktop. To put a window on
  the visible desktop, register a scheduled task with an `Interactive` logon principal,
  start it, then unregister it.

## Coordinates: two systems, easily mixed up

When the guest runs at a display scale other than 100 %, there are two coordinate spaces
and they differ by the scale factor:

- the **VNC framebuffer** in physical pixels — what `vncdo` and noVNC screenshots use;
- the **logical desktop** — what Win32 APIs inside the guest use.

A guest at 200 % scale reports a 1920×1010 desktop while the framebuffer is 3840×2020.
Mixing the two is the fastest way to click next to everything, and it looks exactly like
"the mouse does not reach the guest".

Two related traps:

- **An in-guest PowerShell screenshot silently captures only the top-left quadrant.**
  `Screen.PrimaryScreen.Bounds` returns logical size but `Graphics.CopyFromScreen` copies
  physical pixels, and PowerShell is not per-monitor DPI aware by default. The image has a
  plausible size and looks real; three quarters of the screen are simply missing. Take
  screenshots with `vncdo capture` or through noVNC, or make the agent DPI aware first
  (`SetProcessDpiAwarenessContext(-4)` before anything else).
- **A guest reboot can change the resolution**, invalidating every pixel coordinate you
  cached. Re-measure after a restart rather than trusting a saved recipe.

Always derive the framebuffer size from the actual PNG you just captured, never from a
number written down earlier.

## Clicking things that resist

Win32 behaviours worth knowing before you blame the channel:

- **A click into an inactive window only activates it** — the button underneath is not
  pressed. Click the title bar first, pause, then click the control.
- **A main menu opens on click, a submenu opens on hover.** Move onto the parent item,
  pause ~500 ms, then click the child.
- **Never call `SetForegroundWindow` while a modal is up.** It raises the main window
  above the modal, and the next click lands underneath it.
- **A dialog that "ignores the keyboard" usually just lacks focus.** Send `alt-tab`, then
  `esc`/`enter`. Verified on a pair of stuck windows that had resisted `esc`, `tab`+`enter`
  and clicking, and which two sessions independently concluded were unreachable.
- **Old Delphi/Win32 edit boxes** may ignore `Ctrl+A` and `Ctrl+V`, and triple-click does
  not select their contents over VNC. Use `Home` → `Shift+End`, or go through the
  control's Browse button into a standard Windows dialog, which behaves normally.

## Whole desktop grey, clock still ticking

Not frozen — nothing is repainting. Restarting Explorer or the VM is the wrong move. Force
a repaint from inside the guest:

```powershell
# RDW_INVALIDATE|RDW_ERASE|RDW_ALLCHILDREN|RDW_UPDATENOW|RDW_FRAME
[Rdw]::RedrawWindow([IntPtr]::Zero, [IntPtr]::Zero, [IntPtr]::Zero, 0x585)
```

Observed to come back within a second. `vncdo move … pause 2 capture` does **not** fix this
— that one only cures the stale first frame.

## Where no channel reaches: UAC, the lock screen, Ctrl+Alt+Del

Windows draws UAC prompts on the **secure desktop**, which ordinary synthetic input cannot
touch — not `SendKeys`, not an in-guest agent, and often not VNC either. The sign-in and
lock screens behave similarly: on one guest the keyboard could not activate the sign-in
button and only a real VNC pointer event would do it, while `Ctrl+Alt+Del` went through
from `vncdo` when nothing else did.

**When an action can raise a UAC prompt, stop and tell the user** rather than retrying into
a screen you cannot see the state of. Prefer doing the work in a way that does not elevate.
If a target regularly needs it, disable the prompt inside that guest as a one-time manual
step, or accept a human checkpoint at that spot.

A related diagnostic value: if the mouse works on the lock screen but not inside the user
session, the SPICE guest agent is the broken part — see `shared-folder.md`, *When it dies*.
