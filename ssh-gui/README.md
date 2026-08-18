# ssh-gui

Drive the graphical desktop of a remote macOS machine over plain ssh. No VNC, no screen sharing, no
agent running on the far side. Clicks, drags, keystrokes, menus, window geometry and screenshots
through `cliclick`, `screencapture` and the accessibility API, with a coordinate model that lines up
correctly on Retina displays and a preflight that names which of the three macOS permissions is
missing before you waste a click.

Built for headless Macs: a Mac mini in a cupboard, a build machine, a second Mac on the desk.

## Install

```
npx skills@latest add Vesely/skills/ssh-gui
```

## Requires

- ssh access to a macOS host, with a logged-in graphical session
- `cliclick` on that host (`brew install cliclick`)
- Accessibility, Screen Recording and Automation granted to `/usr/libexec/sshd-keygen-wrapper`

`SKILL.md` covers the coordinate model, the three permissions and their distinct failure modes, how
to keep a session fast, and the traps worth knowing before the first click.
