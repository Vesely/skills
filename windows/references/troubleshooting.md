# Troubleshooting

Symptom → likely cause → what to do. Most of these read as "the VM is frozen" and none of
them are; **reach for a restart last, not first.**

## The picture

| Symptom | Cause | Fix |
|---|---|---|
| `The console requires a GL context` | Display is `virtio-ramfb-gl` | stop the VM, set it to `virtio-ramfb` (Step 1) |
| Black window, nothing shown | the VM is not running | start it (Step 2) |
| noVNC logo / Connect button in the screenshot | the canvas disconnected | `goto` the bridge URL and reconnect (Step 4) |
| Image cropped, or every coordinate offset | viewport ≠ guest resolution | re-measure and resize (Step 4) |
| The image is not the state you expect | websockify points at another target | kill it by pid and restart with the right `$BRIDGE_TARGET` (Step 3) |
| `vncdo capture` is black or hangs | a noVNC client is holding the head | release it — `input.md`, *One VNC client at a time* |
| First `vncdo capture` looks stale | known first-frame behaviour | `move X Y pause 2 capture`; tell by the guest's clock |
| Every `vncdo` call hangs silently | an orphaned `vncdo` process holds the connection | `pgrep -fl "vncdo -s"`, `kill -9 <pid>` |
| `Socket operation on non-socket` from `vncdo` | the hostname resolved to IPv6 | address the IPv4 literal; put it in `vnc_host` |
| Whole desktop uniformly grey, clock ticking | nothing is repainting | force a repaint from inside the guest — `input.md` |
| Guest dialogs hang for many minutes | the shared folder died | `shared-folder.md`, *When it dies* |
| A paste inserts the wrong or an old string | SPICE clipboard lag or staleness | `shared-folder.md`, *Clipboard* |

## Input

| Symptom | Cause | Fix |
|---|---|---|
| Nothing at all reaches the guest, framebuffer still updating, a tooltip stuck on screen | a mouse button was left down | send a bare `mouse up` — `input.md` |
| A click does nothing while the image is clearly updating | the pointer does not reach the guest | expected on some setups; **do not reconnect**. Re-probe, then use `vncdo` or an in-guest channel |
| The keyboard does not land | the canvas has no focus | click the canvas once for focus; use `Ctrl+Esc` instead of `Meta` |
| A dialog ignores `esc`/`enter`/clicks | it does not have focus | `alt-tab`, then `esc`/`enter` — one `alt-tab` per stuck dialog |
| Typed text comes out as different characters | US scancodes through a non-US guest layout | `keyboard-layouts.md` |
| `key shift-x` sends a plain `x` | modifier and character arrive too close together | insert pauses — `input.md` |
| A `vncdo key <name>` sends nothing and then times out | the name is not in `vncdotool`'s `KEYMAP` | send the literal character instead |
| A button click only activates the window | Win32: an inactive window consumes the first click | click the title bar, pause, then the control |
| A UAC prompt appeared and nothing responds | the secure desktop | stop and tell the user — `input.md` |
| Coordinates are consistently off by a factor | framebuffer pixels vs logical desktop points | `input.md`, *Coordinates* |
| A recipe that worked yesterday clicks next to everything | the guest resolution or window geometry changed | re-measure; a reboot can change the resolution |

## Startup and processes

| Symptom | Cause | Fix |
|---|---|---|
| `utmctl` hangs and returns nothing | the target is remote and lacks Automation (TCC) approval | expected — do not wait out the 120 s. Use `start_method: cliclick`, or have someone approve the prompt once |
| `utmctl list` is empty after editing the plist | bad argument format | `AdditionalArguments` must be an array of **plain strings** (`-vnc`, then `127.0.0.1:0`), never dictionaries with an `argString` key. Restore from `.bak-*` and redo it |
| `Address already in use` on 5900 | on macOS, Screen Sharing holds 5900 | use display `:1` (port 5901) and set `vnc_port` |
| No qemu process found, but the VM is clearly running | UTM launches QEMU under a helper | match the launcher process, not `qemu-<arch>` — check what `ps` actually shows on your UTM version before relying on a pattern |
| A session burns two cores while idle | a zombie session: the websocket died and the canvas retries forever | the `ESTABLISHED` check on the fast path catches it — reconnect or close |

## Before you restart anything

Restarting UTM costs minutes and destroys state for any other agent using that VM. Work
through this first:

1. **Is it really the VM?** A screenshot of the *host's* screen is not evidence — a UTM
   window can render a frozen frame that is hours old while the VNC head is live. The
   guest's own clock in a fresh capture is the only reliable read.
2. **Is the VNC server alive?** `nc -w 5 127.0.0.1 $VNCPORT | head -c 12 | od -c` — an
   `RFB 003.008` banner means QEMU is fine and the problem is on your side of the socket.
3. **Is someone else holding the head?** `lsof -nP -iTCP:$VNCPORT | grep -c ESTABLISHED`.
4. **Is it just a stuck button or a lost focus?** A bare `mouse up`, then `alt-tab`.
5. **Is it only the repaint?** Force one from inside the guest.
6. **Is it only the share?** Restart the guest's WebDAV service.

Only then consider restarting UTM — and check the lock first, because someone
else may be mid-task inside that guest.
