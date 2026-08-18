---
name: ssh-gui
description: >-
  Drive the graphical desktop of a remote macOS machine over plain ssh, with no VNC, no screen sharing
  and no agent installed on the far side. Gives you clicks, drags, keystrokes, text entry, menu
  navigation, window geometry and screenshots through cliclick, screencapture and the accessibility
  API, with a coordinate model that actually lines up on Retina displays and a preflight that tells
  you which of the three macOS permissions is missing before you waste a click. Use this whenever the
  task is to operate the GUI of a Mac you reach by ssh: a headless Mac mini or Mac Studio, a build or
  CI Mac, a second machine on the desk, a Mac in a rack or a colo. Trigger on "control the GUI over
  ssh", "click something on my mini", "automate the remote Mac desktop", "screenshot the other Mac",
  "drive an app on the headless Mac", "cliclick over ssh", "no VNC available". Not for controlling a
  virtual machine's guest OS (drive the guest from inside instead) and not for web pages (use a
  browser automation tool).
---

# ssh-gui

Operate a remote macOS desktop over ssh. Everything runs through tools already on the machine
(`cliclick`, `screencapture`, `osascript`, `sips`), so nothing has to be installed on the far side
except cliclick itself.

`bin/ssh-gui` wraps the whole thing. Read the model below before using it, because almost every
failure in this area is a coordinate-space or a permission problem, not a syntax problem.

## Hard rules

- **That desktop may have a human at it.** You are not driving a sandbox, you are moving the real
  cursor on a real screen. Check `idle` before you start. Restore the cursor with `cliclick -r` when
  you are done. If someone is actively using the machine, say so and stop.
- **Never type a password, PIN, recovery code or card number** through `type` or `cliclick t:`. Those
  keystrokes go into whatever is frontmost, they are visible on screen, and you cannot verify the
  target. Ask the person to enter it themselves.
- **If the screen is locked, stop.** Unlocking requires the password. Report it and wait.
- **Bound every Apple Event.** Sending one to an app without an Automation grant blocks for the full
  Apple Event timeout, 120 seconds by default, before failing with `-1712`. Some callers set no
  timeout at all and block indefinitely. Always wrap in `perl -e 'alarm N; exec @ARGV'` or `gtimeout`.
- **Verify after acting, not before.** A synthetic click that lands nowhere produces no error. The
  only proof is that the screen changed.
- Prefer the accessibility API over pixel coordinates. Coordinates are the fallback, not the default.

## The coordinate model

This is the single largest source of "the click landed in the wrong place".

| | space | typical 4K Retina Mac |
|---|---|---|
| `cliclick` input | **logical points** | 1920 x 1080 |
| accessibility API (position, size) | **logical points** | 1920 x 1080 |
| `screencapture` output file | **native pixels** | 3840 x 2160 |
| `screencapture -R x,y,w,h` argument | **logical points** | region given in points |

So a raw screenshot is twice the coordinate space you click in. Measure a button at (1500, 900) on
the raw image, click (1500, 900), and you hit something 750 points up and to the left.

**Rule: downscale every screenshot to logical size before you measure anything on it.** `ssh-gui shot`
does this automatically and prints the backing scale it used. Then image coordinates equal click
coordinates, one to one.

Do not hardcode the factor as 2. Fractionally scaled displays exist. The helper measures it by
capturing a 100 x 100 point region and reading the resulting pixel width.

Multiple displays share one coordinate plane. Negative absolute coordinates (a display arranged to
the left) need the `=` prefix in cliclick: `c:100,=-200`.

## Start every session with preflight

```bash
ssh-gui HOST preflight
```

Prints console user, lock state, screensaver, seconds since last human input, display sleep setting,
cliclick path, logical geometry, and a live probe of all three permissions. One round trip. If
anything there is wrong, no amount of clicking will work.

## The three permissions, and how each one fails

macOS gates this behind three separate grants, and they fail in three different ways. Knowing which
symptom maps to which grant saves an hour.

| Grant | Needed for | Symptom when missing |
|---|---|---|
| **Accessibility** | `cliclick` posting mouse and key events | events vanish silently, exit code 0, nothing moves |
| **Screen Recording** | `screencapture` | you get the wallpaper and cursor only, windows are missing |
| **Automation / Apple Events** | `osascript` talking to an app | blocks up to 120 s, then `-1712` |

They are granted to the *binary that spawns your shell*, which for ssh is
`/usr/libexec/sshd-keygen-wrapper`, not to `cliclick` or to Terminal. Add it under
System Settings, Privacy & Security. The file is hidden, so open the picker and use
Cmd+Shift+G to type the path.

Automation is granted per target app, and the consent dialog appears on the remote screen where
nobody is watching, which is exactly why the call blocks. Two consequences:

- **Prefer `System Events` as the target.** It is usually the one app already granted, and it can
  reach every other app's UI through the accessibility tree anyway.
- If you must talk to an app directly and it blocks, someone has to look at that screen once and
  approve the dialog. It is a one-time grant.

*Not verified by this skill: the exact steps to add sshd-keygen-wrapper on a machine where it has
never been granted. On the machine this was developed against, all three grants already existed.*

## Efficiency: one round trip per intent

An ssh round trip is roughly 200 ms, or 150 ms multiplexed. That cost dominates everything else, so
the difference between a smooth session and a crawling one is how many calls you make.

- **Batch cliclick.** `cliclick -f -` reads a whole command script from stdin and runs it in one
  invocation, `w:` waits included. Twelve actions in one call, not twelve calls.
  ```bash
  ssh-gui HOST do m:400,300 w:150 c:400,300 w:400 t:"invoice" kp:return
  ```
- **Multiplex the connection.** The helper opens a ControlMaster socket and keeps it for 10 minutes.
  Watch the path length: a ControlPath lives in a `sockaddr_un` and the whole path must stay under
  104 bytes, so keep it in `/tmp`, never in a deep scratch directory.
- **Do not screenshot to think.** See the verification ladder below.
- Use `-w <ms>` for a uniform delay after every event instead of scattering `w:` commands.

## Prefer the accessibility tree over pixels

Coordinates rot the moment a window moves. The accessibility API gives you positions that are
correct by construction, and it can click controls directly.

```bash
ssh-gui HOST apps                     # processes that have windows
ssh-gui HOST win "Preview"            # front window bounds: "x y w h", logical points
ssh-gui HOST focus "Preview"          # bring to front
ssh-gui HOST menu Preview File "Export as PDF…"
```

Menu navigation through AX is deterministic and needs no coordinates at all. Note that menu bar
items must be qualified by process: `menu bar 1 of process "Preview"`, never a bare `menu bar 1`.

Composing `win` with a region capture gives you a clean shot of exactly one window:

```bash
ssh-gui HOST shot -R "$(ssh-gui HOST win Preview | tr ' ' ',')" window.png
```

Deeper element lookup, when you need a control's centre point:

```bash
ssh-gui HOST ax 'tell application "System Events" to tell process "Preview"
  set b to button "Done" of window 1
  set p to position of b
  set s to size of b
  return ((item 1 of p) + (item 1 of s) / 2 as text) & "," & ((item 2 of p) + (item 2 of s) / 2 as text)
end tell'
```

Then click that point, or better, `click` the element through AX and skip the mouse entirely.

**Electron and Chromium apps are the exception.** Their accessibility tree is off until a client
sets `AXManualAccessibility` on its AX connection, and `osascript` cannot do it (it has its own TCC
identity and is not AX-trusted for that). Those apps need a small native AX client, or fall back to
coordinates.

## Verification ladder

Check the cheapest thing that can distinguish success from failure.

1. **A pixel.** `ssh-gui HOST color 640 400` returns three bytes. Enough to tell whether a dialog
   opened, a toggle flipped, a row highlighted. This is the workhorse.
2. **AX state.** `ssh-gui HOST ax '...'` to read a value, a window title, whether a sheet exists.
   Text, not an image, and unambiguous.
3. **A region.** `ssh-gui HOST shot -R x,y,w,h`. Small, fast, and you already know where to look.
4. **The whole screen.** Only when you are lost and need to re-orient.

## Text and keys

- `cliclick t:text` types into the frontmost app and handles unicode fine. Activate the target first
  with `focus`, and confirm focus landed before typing anything that matters.
- `kp:` presses one named key (`return`, `tab`, `esc`, `space`, `delete`, `fwd-delete`, `home`, `end`,
  `page-up`, `page-down`, arrows, `f1`..`f16`, numpad, media and brightness keys).
- Modifiers are held and released explicitly: `kd:cmd t:s ku:cmd` is Cmd+S. Always release what you
  press, a stuck modifier poisons every later event.
- For long or awkward text, put it on the remote clipboard instead of typing it:
  ```bash
  printf '%s' "$text" | ssh HOST pbcopy
  ssh-gui HOST do kd:cmd t:v ku:cmd
  ```
  Faster, and immune to keyboard-layout differences.

## Traps

Verified on a real machine, in the order they will bite you.

- **`screencapture` silently refuses any destination whose basename starts with a dot, and still
  exits 0.** `screencapture -x -t png /tmp/.shot.png` writes nothing and reports success. Use
  dot-free names and test the file, never the exit status.
- **A blocked Apple Event costs 120 seconds, not forever, and then returns `-1712`.** Easy to
  mistake for a hang. Bound it.
- **`HIDIdleTime` is reset by your own synthetic events too.** Read it before you start driving; once
  you are clicking, it only tells you how long ago *you* clicked.
- **Screen sharing tools sitting on the remote machine can hold focus and swallow synthetic events.**
  If clicks reach the screen but a dialog ignores Return, check whether a remote-control app is
  frontmost. Symptom: a file picker that visibly has focus but does not respond.
- **A click on an inactive window only activates it.** The first click raises, the second acts. Use
  `focus` first and save yourself the guesswork.
- **Hovering opens nothing.** Hovering highlights an already-open submenu but does not open a
  top-level menu. Click to open, then move.
- **Full screen apps hide the menu bar**, which removes the AX menu path and any coordinates that
  depended on it.
- **Do not trust a click you did not verify.** There is no error channel for a click that lands on
  empty space.

## Helper reference

`bin/ssh-gui HOST <command>`, or set `SSH_GUI_HOST` and drop the first argument.

| Command | Does |
|---|---|
| `preflight` | one-call health and permission report |
| `shot [out.png]` | full screen, downscaled to logical points |
| `shot -R x,y,w,h [out.png]` | region, given in logical points |
| `do <cliclick cmds...>` | batch in one round trip, also reads stdin |
| `click X Y` | move, settle, click |
| `type "text"` | type into the frontmost app |
| `color X Y` | RGB at a point |
| `idle` | seconds since last human input |
| `ax '<applescript>'` | bounded AppleScript, System Events preferred |
| `win <app>` | front window bounds, `x y w h` |
| `apps` | visible application processes |
| `menu <app> <menu> <item>` | click a menu item through AX |
| `focus <app>` | bring an app to the front |
| `close` | drop the multiplexed connection |

Tunables: `SSH_GUI_WAIT` (ms after each event, default 40), `SSH_GUI_AX_TIMEOUT` (seconds, default 15).

## Setting up a fresh host

1. `ssh HOST 'command -v cliclick || brew install cliclick'`
2. Grant Accessibility, Screen Recording and Automation to `/usr/libexec/sshd-keygen-wrapper`, once,
   at the machine or through an existing screen sharing session.
3. Stop the display from sleeping and the screen from locking, otherwise the desktop disappears
   between sessions: `sudo pmset -a displaysleep 0 sleep 0`, and turn off "Require password after
   screen saver begins".
4. `ssh-gui HOST preflight` and confirm every line.

Nothing else is installed on the remote machine, and nothing runs there between your calls.
