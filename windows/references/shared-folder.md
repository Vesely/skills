# Shared folder (host ↔ guest)

Set `shared_folder` in `config.json` to the host path. With it `null`, `host_prep` recipes
and AHK detection do not work and files must move another way (`scp` to the VM host plus a
guest-side fetch, or the clipboard).

**It is the most fragile link in the whole setup, and when it dies it takes the guest's
file dialogs with it.** Check it is alive before a long series of steps.

**If an action needs the shared folder and the active target has none, do not switch
targets on your own.** Another target is a different machine with different — often
older — data, and silently doing the work there produces a result that looks right and is
not. Ask the user whether to switch or to wire the folder up on this target.

## How it actually works

- UTM serves it as **WebDAV over SPICE** (`DirectoryShareMode = WebDAV` in the plist), not
  VirtFS. In the guest it appears as a mapped network drive.
- Hence the cache: **wait 25–30 s after writing** before the guest sees new content, and
  the same the other way. Do not chain a write and its trigger back to back.
- **The mapped drive may point at the PARENT of the folder you selected.** Observed:
  selecting `…/windows/shared` surfaced `…/windows` in the guest, so a file written to
  `shared/foo.xml` appeared as `<drive>:\shared\foo.xml`, not `<drive>:\foo.xml`. Check
  once and write the real guest-side path into the target's `notes`.
- The share path is **not** in `config.plist` — it is a security-scoped bookmark in
  `com.utmapp.UTM.plist`. It survives a UTM restart, but not migrating the VM to another
  machine, where it has to be picked again in the GUI.
- **Setting it up is a manual step the agent cannot do**: with the VM running, UTM menu
  → Virtual Machine → Shared Folder → Browse… → pick the directory. Driving that file
  picker with synthetic clicks does not work — another process holds focus and it ignores
  both clicks and Return.

## When it dies

Symptoms, any one of which is enough:

- The guest reports it cannot reach `\\localhost@<port>\DavWWWRoot` — **in the guest's own
  display language**, so match on the path, not on the sentence. Record whatever string
  your guest produces in `notes`.
- The drive root does not answer at all (a directory listing returns nothing within 15 s).
- **Every dialog that touches the folder hangs — up to ~20 minutes**, or indefinitely if
  a file dialog remembers the share as its last-used location. Anything in the guest
  polling a file there dies with it.

**Never probe it with a bare `Test-Path <drive>:\`.** On a dead share that call hangs
forever and takes your in-guest channel with it. Always wrap it — and **clean the job up
afterwards**, or the timed-out call stays hung in the background holding the same resource:

```powershell
$j = Start-Job { (Get-ChildItem "Z:\" -EA SilentlyContinue).Name -join "," }
if (Wait-Job $j -Timeout 20) { "OK: " + (Receive-Job $j) } else { "SHARE NOT RESPONDING" }
Stop-Job $j -EA SilentlyContinue; Remove-Job $j -Force -EA SilentlyContinue
```

## Recovery, cheapest first

1. **Restart the WebDAV service inside the guest.** This is usually enough and touches
   nothing else:
   ```powershell
   Restart-Service spice-webdavd -Force; Start-Sleep -Seconds 5
   ```
   Then re-run the guarded listing above. Note the drive is provided by that service, not
   by a `net use` mapping — deleting the mapping does nothing.
2. **Restart UTM** — only if step 1 does not bring it back, or if the mouse is also dead
   inside the user session. Restarting the *guest* does **not** fix it: verified once that
   after a guest reboot the drive stayed unmapped with both SPICE services running, and
   restarting those services from `services.msc` changed nothing. The cycle that worked
   was: shut the guest down from the inside → quit UTM → reopen UTM → start the VM. The
   clipboard came back with it, and the share bookmark survived.
3. Expect the input channel to have changed after either restart — re-probe (`input.md`).

## Clipboard

The SPICE clipboard is the fastest way to get an awkward string (a path, a serial number)
into the guest without fighting the keyboard layout: put it on the host clipboard, then
send `Ctrl+V` in the guest.

Two caveats, both of which look like the paste "not working":

- **Allow a few seconds** after setting the host clipboard. Pasting immediately pastes the
  *previous* contents, which reads as the command having run twice.
- **It can silently paste content that is much older.** Observed once pasting a value put
  there an hour earlier, while the host's own `pbpaste` returned the correct string — so
  the loss is in the SPICE transfer, not on the host. When it matters, set the clipboard
  **from inside the guest** (`Set-Clipboard -Value '…'; Get-Clipboard`) and paste after
  that.

A clipboard round trip is also the cheapest liveness test for the SPICE channel as a
whole — but by the same token a *stale* paste is not proof the channel is dead. Prefer the
guarded directory listing above when the answer matters.
