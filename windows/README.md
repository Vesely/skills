# `windows` — drive a UTM Windows VM from Claude Code

A Claude Code skill. `/windows open Notepad` starts a Windows VM in UTM, bridges its VNC
port to noVNC, and drives the guest from a headless browser session. The VM can be on this
Mac or on another one over SSH.

It is **not** a general remote-desktop tool. It is a set of instructions an agent follows,
built out of eight months of finding out which parts of this stack lie to you.

## Install

Clone it into your skills directory (it is a plain skill, not a plugin):

```bash
git clone <this repo> ~/.claude/skills/windows
cp ~/.claude/skills/windows/config.example.json ~/.claude/skills/windows/config.json
$EDITOR ~/.claude/skills/windows/config.json      # vm_uuid + bundle, that is all
```

Get the UUID with `/Applications/UTM.app/Contents/MacOS/utmctl list`. Everything else has
a default; `references/config.md` has the full list.

## Requirements

| | |
|---|---|
| macOS + [UTM](https://mac.getutm.app) 4.x | with a Windows VM already installed. The skill reads and can rewrite the VM's `config.plist`, whose layout is UTM's private business — check what your version has before letting it write |
| [`agent-browser`](https://github.com/anthropics/agent-browser) | drives the noVNC canvas |
| [noVNC](https://github.com/novnc/noVNC) + [websockify](https://github.com/novnc/websockify) | `git clone` and `pipx install websockify` |
| [`vncdotool`](https://pypi.org/project/vncdotool/) | `pipx install vncdotool` — needed for pointer input |
| `cliclick` | only for a headless VM host where `utmctl` over SSH cannot get Automation approval |

The skill's Preflight checks all of these and tells you what is missing.

## Layout

```
SKILL.md                     what the agent reads first
references/config.md         every config key
references/input.md          how input reaches the guest, and how it fails
references/troubleshooting.md symptom → cause → fix
references/keyboard-layouts.md non-US guest layouts
references/shared-folder.md  UTM's WebDAV share and its failure modes
references/guest-channel.md  building an in-guest agent (optional)
references/recipes.md        recipe format and trust model
config.example.json          copy to config.json
examples/recipes/            one reference recipe
```

`config.json`, `recipes/` and `notes/` are gitignored. They hold your machine's addresses
and, in the case of recipes, whatever you typed in the guest while working — client names,
paths, occasionally credentials.

## Two things to know before you use it

**The `allowed-tools` list is broad.** It includes `ssh:*`, `scp:*`, `osascript:*` and
`curl:*`, because the skill has to reach another machine, drive UTM's GUI and poll an HTTP
bridge. Read the frontmatter before you install it.

Note what that list actually is: `allowed-tools` **pre-approves** those commands so they do
not prompt. It is not a sandbox and it does not stop the skill using anything else — that
would just prompt instead. Trimming it buys you prompts, not containment. If you want a
real boundary, use Claude Code's permission settings.

**A recipe is executable code.** A `{"cmd": "shell"}` step runs arbitrary bash on your host
with those permissions. Never run a recipe file you did not write. `recipes/` ships empty
for exactly this reason.

## Known gaps

- **Guest-side helpers are documented, not shipped.** `host_prep` recipes and the in-guest
  click fallback need something running inside Windows. `references/guest-channel.md`
  describes the pattern and every trap in it, but you build it for your own guest —
  shipping a working RCE-into-a-VM channel is not something this repo should do for you.
- **Tested end to end on one setup** (Apple Silicon, UTM 4, Windows 11 ARM, a Czech guest
  layout, both local and over SSH to a second Mac). Rules that came from a single
  observation are tagged `[verify once]` in the text; the rest follow from how the
  components work.

## Contributing back

If a `[verify once]` rule turns out differently on your hardware, that is the most useful
thing you can report — the whole design assumes these answers vary.
