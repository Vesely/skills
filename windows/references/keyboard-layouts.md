# Non-US guest keyboard layout

Only applies when the target's `guest_keyboard` is not `us`. The worked examples below are
a Czech (QWERTZ) guest; the shape of the problem is identical for any non-US layout, only
the affected characters differ.

**The cause:** the browser and noVNC send **US scancodes**. Windows interprets them through
the *guest's* layout, so a physical key position produces a different character than the
one you asked for. Nothing is broken; the translation is simply happening twice.

## Symptoms

| You send | You get (Czech guest) | Why |
|---|---|---|
| `type "12345"` | `+ěščř` | the digit row is unshifted diacritics |
| `type "type"` | `tzpe` | Y and Z are swapped |
| `press Digit1` | nothing | a US scancode does not survive the mapping |
| `press Numpad1` | nothing | NumLock state |

## The one-time fix that removes all of this

Switch the guest's **system layout to EN-US** (Settings → Time & Language → Language →
English (United States) → Set as default), then set `"guest_keyboard": "us"`. `type` and
`press Digit*` work normally afterwards.

It needs a human step in the Windows GUI once, and it saves fighting the layout on every
later action. Recommend it to the user the first time a layout problem costs real time.

The other clean escape is an **in-guest channel**: `SendKeys` from inside Windows takes
Unicode and ignores the layout entirely, so paths, digits and accented text all go through
in one call. See `guest-channel.md`.

## Working around it from outside

| Input | Method | Example |
|---|---|---|
| A digit | `press Shift+Digit{N}` (Czech puts digits on Shift) | `press "Shift+Digit1"` → `1` |
| A digit string | loop over `Shift+Digit*` | helper below |
| Letters with no Y/Z | `type` works | `type "notepad"` ✓ |
| Words containing Y/Z | one `press "Key{X}"` per character | `KeyA`, `KeyN`, `KeyO` are identical in both layouts |
| Capitals | `press "Shift+Key{X}"`, not `type "A"` | `press "Shift+KeyA"` |
| Tab/Enter/Escape/arrows | `press` works normally | `press Tab` |
| Punctuation (`/ - = . , : ;`) | do not trust `type`; send the key that carries it | table below |
| Clear a Win32 edit field | `End` → `Shift+Home` → `Delete` (not `Ctrl+A`, which some Win32 fields ignore) | — |
| Select an existing value | triple-click does not work on Win32 edit boxes over noVNC — click, then `Home` → `Shift+End` | — |

```bash
# Send a digit string via Shift+Digit*, independent of NumLock and Windows settings
type_digits() {
  local s="$1" i d
  for ((i=0; i<${#s}; i++)); do
    d="${s:$i:1}"
    agent-browser --session "$SESSION" press "Shift+Digit$d" >/dev/null
  done
}
```

**A modifier that does not survive the trip** can often be sent decomposed with pauses:

```bash
agent-browser --session "$SESSION" keydown "Alt"; sleep 0.4
agent-browser --session "$SESSION" press  "KeyS"; sleep 0.4
agent-browser --session "$SESSION" keyup  "Alt"
```

## Paths through `vncdo` on a non-US guest

A Windows path is the worst case — it needs exactly the three characters the layout moves.
On a Czech guest `Z:\shared\file.xml` arrives as `YŮ¨shared¨file.xml`. Send each problem
character as the key that carries it:

| want | send | why |
|---|---|---|
| `Z` | `vncdo key shift-y` | Y and Z swapped on QWERTZ |
| `:` | `vncdo key shift-.` | colon sits on the period key |
| `\` | `vncdo key ctrl-alt-q` | `\` is AltGr+Q, and AltGr on Windows = Ctrl+Alt |
| digits | `vncdo key shift-1` … `shift-0` | digits are under Shift |

**Send the character, not its name.** `vncdotool` 1.3.0 has neither `period` nor `digitN`
in its `KEYMAP`; `key shift-period` dies with `TypeError: ord() expected a character`, and
an unknown name can hang the connection to timeout while sending nothing. In a helper that
discards stderr, both fail completely silently.

**Better than typing a path at all:** put it on the clipboard and paste it — see
*Clipboard* in `shared-folder.md`, including the two ways that silently pastes the wrong
thing. Best of all, send it from an in-guest channel.

The rest — letters without Y/Z, `.`, `-` inside a name — goes in a single `type`. **Name
the files you create without hyphens and without Y/Z** and half the problem disappears.

## Modal dialogs

While a modal is open, keys go to it and not to the field behind it, even when focus
appears to be elsewhere. Close the modal (`Enter`/`Escape`) before typing. If it seems to
ignore the keyboard entirely, it probably lacks focus — see `input.md`.
