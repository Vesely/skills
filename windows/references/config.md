# `config.json` — full reference

`SKILL.md` covers the two-field minimum and how to load it. This page is the complete key
list and the multi-target shape.

**If `config.json` is missing, or a key you need is absent — HALT** and print the setup
block. Never fall back to `config.example.json` and never guess: a wrong UUID starts
someone else's VM, and a wrong `ssh_host` connects to a machine that is not yours.

## Shapes

Single VM — the whole file:

```json
{
  "vm_uuid": "XXXXXXXX-XXXX-XXXX-XXXX-XXXXXXXXXXXX",
  "bundle": "Windows.utm"
}
```

More than one VM — only then introduce `targets`:

```json
{
  "default_target": "local",
  "bridge_port": 6080,
  "targets": {
    "local":  { "vm_uuid": "…", "bundle": "Windows.utm" },
    "remote": { "vm_uuid": "…", "bundle": "Windows.utm",
                "ssh_host": "<host>", "vnc_port": 5901, "tunnel_local_port": 5902,
                "start_method": "cliclick", "cliclick_play_xy": [736, 266],
                "input_preference": ["guest", "novnc", "vncdo"],
                "aliases": ["on the box", "remote"] }
  }
}
```

**Loader rule:** if `targets` exists, use it; otherwise treat the top level as the single
target. Both shapes accept the same per-target keys.

**Validate before you interpolate.** These values end up inside shell commands. Before
using them, check that `vm_uuid` looks like a UUID, that ports are integers in range, and
that `ssh_host` and `bundle` contain no whitespace, quotes, `;`, `|`, `$` or backticks. A
config file is not automatically trusted input — you may not be the person who wrote it.

## Per-target keys

| Key | Default | Notes |
|---|---|---|
| `vm_uuid` | — **required** | From `utmctl list`. Address the VM by UUID, never by name: several bundles can share a name, and renaming a bundle does not change `Information:Name`. |
| `bundle` | — **required** | `.utm` bundle directory name; used to locate `config.plist`. |
| `ssh_host` | `null` | `null` = the VM is on this Mac. A string = run VM-side commands over `ssh <host>`. |
| `vnc_host` | `localhost` | Where **websockify** connects. For a remote VM this is `localhost` when tunnelled, or the ssh host directly. If a hostname makes `vncdo` fail with a socket error, put the IPv4 literal here. |
| `vnc_port` | `5900` | The port **on the VM host**. Must match the `-vnc` display index in the VM's QEMU args (`:0` = 5900, `:1` = 5901). |
| `tunnel_local_port` | `null` | Only when the VNC port is not reachable directly from this Mac. Set it and the skill opens `ssh -fN -L <tunnel_local_port>:127.0.0.1:<vnc_port> <ssh_host>` **before Step 3**, then points websockify and `vncdo` at `localhost:<tunnel_local_port>`. Leave `null` when `vnc_host` is reachable as-is. |
| `vnc_display_arg` | `127.0.0.1:0` | What Preflight expects in `QEMU:AdditionalArguments`. **Keep the `127.0.0.1` prefix** — QEMU's VNC has no authentication here, so it must never listen on `0.0.0.0`; reach it across machines through the SSH tunnel above. Add `,lossy=on` only for a VM reached over a network — on loopback the compression just burns CPU. |
| `start_method` | `utmctl` | `utmctl` or `cliclick`. See SKILL.md Step 2. |
| `cliclick_play_xy` | `null` | `[x, y]` of the VM's play button in the UTM window, in **logical** points. Only for `start_method: cliclick`. |
| `host_logical_resolution` | `null` | e.g. `"1920x1080"`. The VM host's **logical** screen size when its panel is scaled (a 3840×2160 display running a 1920×1080 UI). Downscale screenshots to this before measuring `cliclick_play_xy`, or the coordinates will be off by the scale factor. Only for `start_method: cliclick`. |
| `input_preference` | `["novnc", "vncdo", "guest"]` | The order in which to **try** input channels — a hint, never a verdict. Which one actually works changes between sessions, between reboots and between guest applications, so the probe in `input.md` decides. Drop a channel from the list only when it is genuinely not installed on this target. |
| `guest_keyboard` | `us` | `us` or a layout code (`cs`, `de`, …). Anything other than `us` activates `keyboard-layouts.md`. |
| `guest_resolution` | `null` = **probe it** | The canvas `eval` in Step 4 measures it. Set the viewport to exactly this. Cache it here, and re-measure after any guest reboot — a reboot can change it and silently invalidate every stored coordinate. |
| `shared_folder` | `null` | Host path shared into the guest, or `null` if not set up. |
| `aliases` | `[]` | Words in `$action` that select this target, e.g. `["locally", "here"]`. |
| `notes` | `""` | Free text shown to the agent when this target is selected. The place for this target's answers: the guest-side path of the shared folder, the exact wording of its WebDAV error, the filenames your job channel uses. |

## Global keys

| Key | Default |
|---|---|
| `default_target` | first key in `targets` |
| `bridge_port` | `6080` |
| `session_name` | `novnc` |
| `novnc_path` | `~/Tools/noVNC` |
| `websockify` | `~/.local/bin/websockify` |

## What does *not* belong here

Anything that is an observation rather than a setting. Whether the mouse landed this
morning, what the framebuffer measured last time, which application was in the foreground
— all of that expires, and a stale copy in `config.json` is worse than no copy, because it
reads as authority. Keep observations in the session, and write only durable facts here.

## Older config files

Early versions of this skill stored `"mouse"` and `"input"` as single verdicts
(`noVNC` / `vncdo` / `none`). Read them as the first entry of `input_preference` and
nothing more — they were exactly the cached-truth mistake the probe exists to avoid.
Replace them when you next edit the file.
