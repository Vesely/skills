---
name: pr-handoff
description: >-
  Builds the PR around annotated browser screenshots, with a short GIF when the changed behaviour
  unfolds over time, then writes the shortest text that makes those visuals legible: a scannable,
  ADHD-shaped description of captions and one-line bullets instead of a wall of prose. Reviews the
  branch diff against the default branch, captures every affected user-facing surface with the
  agent-browser CLI, marks the changed elements in red, stitches a collage with ImageMagick, hosts
  it through a configured uploader (or leaves it local for drag-and-drop), embeds it in the PR body,
  and adds data-model notes when the schema changes. Use whenever the user wants to write a PR
  description, document branch changes for a reviewer, prepare a handoff, or says things like
  "write PR description", "prep the PR", "PR handoff", "document my changes", "screenshot my PR",
  or "generate PR notes". Also trigger when the user just says "PR" while finishing or shipping.
---

# PR Handoff

For any PR that touches the UI, **the visuals are the deliverable and the text is their caption**. A reviewer grasps the change in seconds from an annotated screenshot; no amount of prose does that. Two rules follow, and the rest of this file implements them:

1. **Capture before you write.** Annotated stills of every changed surface, plus a short recording when the changed behaviour only exists over time (§2i). Get them into the PR body yourself through one of the three routes in §2h — never as a follow-up comment. When none of those routes is available, §2h option 3 is the correct ending, not a failure.
2. **Write short.** Captions and one-line bullets, shaped for a reader with ADHD who is about to review code. §3 sets the budget.

Scope: **GitHub + `gh`**. Other forges are out of scope.

## Requirements

| Tool | Needed for | Checked |
|---|---|---|
| `git`, `gh` (authenticated), `curl` | diff, PR create/edit, reachability, attachment upload | up front |
| `agent-browser` | every screenshot and screencast | only on UI PRs |
| ImageMagick (`magick` or `convert`) | stitching the collage | only for 2+ shots |
| `ffmpeg` | webm → MP4 or GIF | only for screencasts |
| `gifski` | smaller, sharper GIFs | optional |
| [`share-file`](https://github.com/Vesely/skills/tree/main/share-file) | hosting an image that must also be readable off GitHub (§2h option 2) | optional |

**Up-front check** — cheap, and a docs-only PR should never trigger a browser install:

```bash
for bin in git gh curl; do command -v "$bin" >/dev/null 2>&1 || echo "missing: $bin"; done
gh auth status >/dev/null 2>&1 || echo "gh is not authenticated — the user must run: gh auth login"
```

**UI check** — run this only once §1 confirms the diff touches UI:

```bash
command -v agent-browser >/dev/null 2>&1 || echo "missing: agent-browser"
command -v npm >/dev/null 2>&1 || echo "missing: npm (needed to install agent-browser)"
if command -v magick >/dev/null 2>&1; then IM=magick; MONTAGE="magick montage"
elif command -v convert >/dev/null 2>&1; then IM=convert; MONTAGE=montage
else echo "missing: imagemagick"; fi
```

`$IM` and `$MONTAGE` are used throughout §2f. ImageMagick 7 provides `magick`; ImageMagick 6 — which is what `apt-get install imagemagick` still gives you on Debian and Ubuntu — provides `convert` and a standalone `montage` instead. Checking for either is what keeps this skill working on Linux.

Installing what is missing — tell the user the command before you run it:

```bash
npm i -g agent-browser && agent-browser install    # add --with-deps on Linux for browser system libs
brew install gh imagemagick ffmpeg gifski          # macOS
sudo apt-get install -y imagemagick ffmpeg         # Debian/Ubuntu — ASK before any sudo
sudo dnf install -y ImageMagick ffmpeg             # Fedora
```

Rules:

- Announce before installing. Never run a `sudo` install without an explicit yes.
- `gh` is not in older Ubuntu/Debian archives; it may need GitHub's own apt source. Say so rather than looping on a failing install.
- No package manager, or the user declines? **Degrade, don't stop**: without ImageMagick, embed the individual screenshots one `![]()` per line — every changed surface still gets shown. Without ffmpeg, skip the screencast.
- Missing `agent-browser` on a UI PR is the one thing worth pausing for. Offer the `npm i -g` line and wait.

**Before running any `agent-browser` command**, load its usage guide — the CLI serves docs matching its own version, so the syntax never goes stale:

```bash
agent-browser skills get core
```

If the `/agent-browser` skill is installed, invoke that instead. The commands below are the shape of the flow, not a substitute for the guide.

## 0. Project specifics live in the project, not here

This skill is project-agnostic on purpose. It does not know your dev-server port, your routes, or your login. Resolve those in this order:

1. The project's `CLAUDE.md`, `AGENTS.md`, `README`, or `CONTRIBUTING`
2. `package.json` scripts, `Procfile`, `docker-compose.yml` port mappings, `.env` `PORT`
3. Ask the user

When you had to ask, offer to record the answer in the project's `CLAUDE.md` so the next run doesn't ask again:

> "Want me to add a line to CLAUDE.md — `dev server: <command> on :<port>, log in via the agent-browser vault entry '<name>'` — so this is automatic next time?"

**Credentials.** Never grep `.env` for a password and never put one in a shell command — it lands in shell history and in the transcript. agent-browser has a vault; **the user runs this in their own terminal**, because it waits for a typed password:

```bash
# USER RUNS THIS, not the agent — it reads the password from a TTY
agent-browser auth save myapp-local --url http://localhost:PORT/login \
  --username dev@example.com --password-stdin
```

The agent then only ever calls:

```bash
agent-browser auth login myapp-local
```

If no vault entry exists, ask the user to create one. Never invent credentials, and never satisfy `--password-stdin` by piping in a secret you read from a file.

**Data sensitivity.** Screenshots of a real admin or dashboard capture whatever is on screen — customer names, invoice totals, e-mail addresses, tokens in a debug bar. Prefer a seeded or demo account. If the shots do contain real data, that fact must reach the user **before** anything leaves the machine, not when you present the finished PR — see the gate in §2h.

## 1. Read the diff

Resolve the base branch. Do this with explicit checks — a `git ... | sed ...` pipeline returns *sed's* exit status, so chaining fallbacks with `||` silently yields an empty base, and an empty base makes the diff empty and the whole run conclude "no UI changes":

```bash
BASE="$(gh repo view --json defaultBranchRef -q .defaultBranchRef.name 2>/dev/null)"
if [ -z "$BASE" ] && git symbolic-ref -q refs/remotes/origin/HEAD >/dev/null 2>&1; then
  BASE="$(git symbolic-ref --short refs/remotes/origin/HEAD)"; BASE="${BASE#origin/}"
fi
[ -z "$BASE" ] && BASE=main
git rev-parse --verify -q "$BASE" >/dev/null || git rev-parse --verify -q "origin/$BASE" >/dev/null \
  || { echo "no base branch resolved — ask the user which branch this PR targets"; }
echo "base: $BASE"
```

Test each step, don't chain them with `||`. `git rev-parse --abbrev-ref origin/HEAD` prints the literal string `HEAD` when `origin/HEAD` is unset rather than failing, and `git symbolic-ref … | sed …` returns *sed's* exit status — either one hands you a base that turns `git diff "$BASE"...HEAD` into an empty diff, and the run then concludes "no UI changes" and skips every screenshot.

Check for uncommitted work — it will not appear in `git diff "$BASE"...HEAD`:

```bash
git status --short
```

If there is any, ask whether the PR covers it. To include it, diff the working tree directly — `git diff HEAD` (tracked, staged and unstaged) — do **not** stash first; stashing removes the very changes you are trying to read.

Read the whole diff. Always:

```bash
git diff "$BASE"...HEAD
git log "$BASE"..HEAD --oneline
```

Only when that is genuinely too large for one pass, start from `git diff --stat "$BASE"...HEAD` and then read every hunk area it lists — per-path reads are a way to get through a big diff, not a licence to sample it. Cross-cutting UI changes are exactly what a partial read misses.

From the diff, answer two questions:

- **Does this touch user-facing UI?** Templates, components, admin screens, public pages, e-mails — anything a person looks at. → step 2.
- **Does this change the schema or core data models?** Migrations, model definitions, `schema.prisma`, `.sql` schema files, serializers, API response shapes. → step 4.

No UI? Skip to step 3.

## 2. Screenshots

### 2a. Reach the app

Resolve the dev-server URL per §0, then confirm it responds before opening a browser:

```bash
curl -sS -o /dev/null -w '%{http_code}\n' --max-time 5 "$APP_URL"
```

Unreachable: offer the start command you found in §0. Do not auto-start a long-running server without asking. If it cannot be started, note that in the PR description and skip to step 3.

### 2b. Workspace

```bash
BRANCH="$(git branch --show-current)"
[ -z "$BRANCH" ] && BRANCH="detached-$(git rev-parse --short HEAD)"
SLUGBRANCH="$(printf '%s' "$BRANCH" | tr '/#%' '-')"
SHOTS="$(mktemp -d "${TMPDIR:-/tmp}/pr-handoff-${SLUGBRANCH}-XXXXXX")"
PANELS="$SHOTS/panels"; mkdir -p "$PANELS"
echo "$SHOTS"
```

`mktemp -d` per run — never `rm -rf` a path built from a variable that can be empty.

**Shell variables do not survive between tool calls.** Each command you run is a fresh shell, so `$SHOTS`, `$PANELS`, `$BRANCH`, `$IM` and `$URL` are gone by the next call. Echo the values once (above) and then use the literal paths, or re-derive them at the top of each block. A silently-empty `$SHOTS` writes screenshots to `/01-….png`.

Pin the viewport once so every panel is the same width:

```bash
agent-browser set viewport 1440 900 2      # 2 = retina, sharper text in the collage
```

### 2c. Map every affected surface

Re-read the diff and list every URL where the change is visible:

- The changed screen itself — list view, detail view, edit form, modal
- Any screen that *displays* changed data, even when the change was server-side
- Both ends of a feature that spans surfaces (a setting in admin, its effect on the public page)

For each, plan the states worth capturing: default/empty, populated with realistic data, and the edge cases the diff implies (long text, missing value, error state).

Decide the screencast here too, not at the end. Record when the **changed** behaviour unfolds over time or across states and stills would hide the transition between them: a wizard, a changed animation or transition, a streaming/progressive state, a drag, materially changed hover or click behaviour. Navigating to a surface and logging in are setup, not the change — they do not earn a GIF on their own. Plan the recording now so it happens in the same browser session instead of reopening one later.

### 2d. Capture each surface — annotate first, then shoot

The order matters: a screenshot taken before the markup is injected is an unannotated screenshot.

```bash
agent-browser open "$APP_URL/some/route"
agent-browser wait --load networkidle
# 1. clear any markers left from the previous shot (see 2e)
# 2. inject this shot's markers (see 2e)
agent-browser screenshot "$SHOTS/01-orders-list-default.png"
```

Name pattern: `<NN>-<surface>-<state>.png` — zero-padded, so the collage orders itself.

Always wait for async content before capturing: streamed responses, lazy sections, live previews. A spinner in a PR screenshot reads as a broken feature. Use `--full` for full scroll height when the change extends below the fold.

**Shoot the result, not the trigger.** Build the shot list from the claim in the PR title: for each claim, name the visible evidence of the broken state and of the fixed state before you capture anything. An export-date fix needs the exported date on screen, a parsing-status fix needs the status. The dialog that starts the export and the list the document sits in prove neither. Where the claimed result has no surface in the app, capture the generated artifact itself — the XML, the file, the API response — and say in `Technical notes` which claim the screenshots do not cover. An adjacent screen is not a substitute. Measured on a PR whose two shots were the export dialog and the document list: a reviewer shown only the images could not tell what had changed at all.

**Label the state inside the panel, before the shot.** Inject `BEFORE · broken` and `AFTER · fixed` into the page (tagged `data-prh-marker`, so §2e clears it again), and where two files, accounts or runs appear, the sample id beside it. Captions live in the body, and a reviewer reading the image alone never sees them — a panel only the caption can identify is unidentified. Measured: a before/after pair of totals where neither panel said which was which read as two unrelated results.

**Both directions, both boundaries.** A fix that works in two directions gets a panel for each; a rule that separates valid input from invalid gets one example of each with its resulting status; a responsive fix gets the narrowest supported viewport and a value long enough to have broken it before. Two views of the same happy path are one case, not coverage.

### 2e. Annotation

Mark up the DOM by selector — never pixel coordinates. Pipe the script via heredoc so quoting survives. Tag every marker so it can be removed again:

```bash
cat <<'EOF' | agent-browser eval --stdin
const el = document.querySelector('[data-testid="order-total"]');
el.style.outline = '3px solid red';
el.style.outlineOffset = '4px';
el.dataset.prhOutlined = '1';
EOF
```

For a new section that resists outlining, inject a positioned arrow:

```bash
cat <<'EOF' | agent-browser eval --stdin
const el = document.querySelector('.new-section');
const r = el.getBoundingClientRect();
const arrow = document.createElement('div');
arrow.dataset.prhMarker = '1';
arrow.style.cssText = 'position:fixed;left:' + (r.left - 44) + 'px;top:' +
  (r.top + r.height / 2 - 12) + 'px;z-index:99999;font-size:24px;color:red;pointer-events:none';
arrow.textContent = '▶';
document.body.appendChild(arrow);
EOF
```

Clear them before the next shot on the same page, or markers accumulate across states:

```bash
cat <<'EOF' | agent-browser eval --stdin
document.querySelectorAll('[data-prh-marker]').forEach(el => el.remove());
document.querySelectorAll('[data-prh-outlined]').forEach(el => {
  el.style.outline = ''; el.style.outlineOffset = ''; delete el.dataset.prhOutlined;
});
EOF
```

Rules:

- All annotations red — reviewers learn that red means changed.
- Annotate every shot of a *changed* surface. A context shot of surrounding UI needs none.
- Never cover the thing you are pointing at.
- **Before/after collages** may use two colours (red = old/broken, green = new/fixed) instead of red-only. Apply it to **every** panel consistently — a stray red box in an "after" panel inverts the meaning. This is the single most common mistake here; re-check it in §2g.

### 2f. Crop and stitch

Panels that go into the collage live in `$PANELS`; derived files never land back in the source directory, so a second run cannot stitch its own output.

**Crop to the evidence, not to the component.** What stays: the changed value or control, whatever is needed to read it, and any conflicting value the reviewer has to resolve. What goes: unrelated rows, repeated list items, empty upload zones, document previews that prove nothing. A panel spending more than half its area on content unrelated to its own claim gets cropped again or split in two. Across seven PRs measured on their visuals alone, this was the most common complaint about otherwise correct captures.

Copy each shot into `$PANELS`, cropping the ones that need it — geometry is per-surface, so pick it per file rather than applying one rectangle to everything:

```bash
cp "$SHOTS"/[0-9][0-9]-*.png "$PANELS"/                                   # keep full-frame panels
"$IM" "$SHOTS/02-orders-list-filtered.png" -crop 600x440+500+350 +repage \
  "$PANELS/02-orders-list-filtered.png"                                   # tighten just this one
```

Then stitch. Guard the glob — an empty `$PANELS` makes bash pass the literal pattern to ImageMagick and makes zsh abort the command:

```bash
shopt -s nullglob 2>/dev/null || setopt null_glob 2>/dev/null
panels=("$PANELS"/*.png); COUNT=${#panels[@]}
[ "$COUNT" -eq 0 ] && { echo "no panels — nothing to stitch"; exit 1; }

if [ "$COUNT" -le 2 ]; then
  "$IM" "${panels[@]}" +smush 40 -bordercolor 'rgb(40,40,40)' -border 40 "$SHOTS/collage.png"
else
  COLS=$(( COUNT <= 6 ? 2 : 3 ))
  ROWS=$(( (COUNT + COLS - 1) / COLS ))          # round up, so no panel is dropped
  $MONTAGE "${panels[@]}" -tile "${COLS}x${ROWS}" -geometry +20+20 \
    -background 'rgb(40,40,40)' -bordercolor 'rgb(40,40,40)' -border 20 "$SHOTS/collage.png"
fi
"$IM" identify "$SHOTS/collage.png"
```

**Keep the collage legible.** GitHub renders a PR image at roughly 900px wide. A 1440px viewport at DPR 2 is a 2880px panel, so four of those smushed side by side is ~11,600px — a 13× downscale that turns every label into mush. Two rules follow: use the grid from three panels up (the code above does), and keep each panel at least ~600px wide *in the final image*. If both can't hold, make two collages rather than one unreadable one, and cap the final width:

```bash
"$IM" "$SHOTS/collage.png" -resize '1800x>' "$SHOTS/collage.png"
```

`montage` printing `unable to read font` is harmless — the machine has no default font configured, the collage still renders; confirm with `identify` rather than chasing it. One screenshot: skip the collage entirely. No ImageMagick: embed the individual images, one `![]()` per line, so no surface goes unshown.

### 2g. Review the collage, then fix it

Generating the collage is not the last step. **Judging it and correcting it is.** Open the final PNG with the Read tool and critique it as the reviewer will:

- **No blank or broken panels** — every capture rendered real content; nothing white, cut off, or mid-spinner.
- **Annotations land on target** — each box tightly frames the exact element. Nothing floating in whitespace beside it, nothing overshooting into unrelated content. (A box one line too low, framing empty space instead of the value, is the classic failure.)
- **Colour semantics consistent** — every before marker red, every after marker green, no inverted panel.
- **Nothing important obscured**, and no marker left over from a previous state.
- **Text is readable at the size GitHub will render it.**
- **Panel order matches the state plan** from §2c, so the captions written in §3d can follow it.
- **The cover test** — hide the body text and look at the collage alone: does it say what changed, and what was broken before? That is the bar a reviewer actually applies. Measured on seven PRs, six needed the prose; the one that passed was a plain annotated before/after pair.
- **State and sample are readable from the image itself** — `BEFORE`/`AFTER`, and which sample produced which panel wherever more than one appears.
- **The result is on screen**, not only the control that triggers it.
- **No unexplained contradiction** — an old value sitting beside the fixed one, an identifier that differs where the change claims a merge. Show which run produced which, or name the open question in `Technical notes`. Cropping the mismatch away is the failure, not the fix.

If anything fails: adjust the geometry, re-run, Read it again. **Loop until every item passes.** Do not publish a collage you would not want a reviewer to see as-is — a visibly-off annotation makes the whole PR look careless and costs a round-trip with the user.

### 2h. Host the image

**The invariant, which the three options below cannot override.** The image may leave this machine by exactly the three routes in this section and by no other. Everything else is out of bounds regardless of how the run is going: image hosts (catbox, imgur, litterbox, tmpfiles, 0x0.st and every sibling), gists, release assets, a bucket you pick, a `curl` you compose to a host of your own choosing, committing the file to the PR branch or to an assets branch, or `git add -f` past a `.gitignore`. Not embedding an image is an acceptable outcome; publishing one somewhere the user did not choose is not. Option 3 is always available and publishes nothing, so "everything else failed" is never a reason to improvise a fourth route. If the user explicitly asks for a public host, name exactly what becomes public and permanent, and get a yes for that specific upload first.

Route 1 is the default whatever the repo is. Visibility still decides whether route 2 is acceptable at all, because a `share-file` link to a private repo's screenshots is public where the repo is not — so have the answer before you fall back:

```bash
gh repo view --json visibility -q .visibility     # PUBLIC | PRIVATE | INTERNAL
```

**1. GitHub's own attachment endpoint — the default for anything that goes into a GitHub body.**

`gh` has no command for this, but the endpoint behind the web UI's drag-and-drop is callable directly, and it is the one route whose asset **inherits the repo's visibility**: on a private repo the URL 404s for everyone without access. That is what makes it right for the private case, which used to fall straight through to option 3. If the `gh-upload` skill is installed, invoke that instead of hand-rolling the call.

```bash
IMG="$SHOTS/collage.png"     # run this block once per artifact: the collage, then the video from 2i
NAME="collage.png"           # display filename in the body — name what the reader is looking at
MIME="image/png"             # must match NAME's extension, or the endpoint 422s

REPO_ID="$(gh api repos/{owner}/{repo} --jq .id)"   # numeric; the GraphQL node id from
                                                    # `gh repo view --json id` 404s here
RESP="$(curl -s -X POST -H "Authorization: Bearer $(gh auth token)" -H "Accept: application/json" \
  "https://uploads.github.com/user-attachments/assets?name=$NAME&content_type=$MIME&repository_id=$REPO_ID" \
  --data-binary "@$IMG")"
URL="$(printf '%s' "$RESP" | sed -n 's/.*"url":"\([^"]*\)".*/\1/p')"
case "$URL" in https://github.com/user-attachments/*) ;; *) echo "upload failed: $RESP"; URL="" ;; esac
echo "$URL"          # stash as COLLAGE_URL or FLOW_URL — one per artifact, see below
```

What actually goes wrong here:

- **The extension in `name` must match `content_type`.** `name=collage` with no extension 422s every type. Percent-encode the query values too — `image/svg+xml` sent raw arrives as `image/svg xml`, and a space in `name` needs `%20`.
- **Media only.** PNG, JPEG, GIF, WebP, SVG, MP4, WebM and MOV upload; PDF, text, zip and `application/octet-stream` 422. A non-media artifact belongs on option 2's host, linked rather than embedded.
- **A 404 on the POST is one of two things** — a non-numeric `repository_id`, or a token without push access on the repo. Neither is worth retrying.
- **Verifying the URL needs the header too.** A bare `curl` of a private repo's asset 404s by design and always will, so check it with `-H "Authorization: Bearer $(gh auth token)"` or you will read your own good upload as a failure.
- **Embed the `github.com/user-attachments/…` URL, never the S3 URL it redirects to.** The redirect target is signed and expires in five minutes.
- **There is no delete endpoint.** Every upload is permanent, which is where §0's real-data caveat bites hardest: look at the image before you send it.

**2. An uploader that was already installed and configured before this run.** Route 1 covers the PR body; reach for this one when the image also has to be readable *outside* GitHub — pasted into an e-mail, a Slack thread, a message to a client — or when route 1 is closed because the token has no push access. `PR_HANDOFF_UPLOAD_CMD` if the user set one, otherwise the `share-file` skill if they have it:

```bash
IMG="$SHOTS/collage.png"     # run this block once per artifact: the collage, then the GIF from 2i

UPLOADER="$PR_HANDOFF_UPLOAD_CMD"
if [ -z "$UPLOADER" ]; then                                   # fall back to share-file
  for c in "$(command -v share-file 2>/dev/null)" \
           "$HOME/.claude/skills/share-file/share-file.sh" \
           "$HOME/.agents/skills/share-file/share-file.sh"; do
    [ -n "$c" ] && [ -x "$c" ] && { UPLOADER="$c"; break; }
  done
fi

if [ -n "$UPLOADER" ]; then
  URL="$(sh -c "$UPLOADER \"\$1\"" _ "$IMG")" || URL=""
  case "$URL" in https://*) ;; *) URL="" ;; esac              # anything not a URL is a failure
fi
echo "$URL"          # stash as COLLAGE_URL or FLOW_URL — one per artifact, see below
```

Contract: the uploader takes one file path and prints exactly one `https://` URL on stdout, nothing else, non-zero on failure. Flags are fine — it runs through `sh -c`, so `mytool upload --ttl 90d` works. [`share-file`](https://github.com/Vesely/skills/tree/main/share-file) meets this contract exactly and is the recommended default: it uploads to the user's *own* Cloudflare R2 bucket with a 90-day expiry, so the link is theirs to revoke and cleans itself up.

**Neither one may be created during the run.** The variable must already be set in the environment you inherited, and `share-file` must already be installed *and* set up. You never export the variable, suggest a value for it, write the script it points at, install `share-file`, or run its `setup` — a route you construct yourself is your consent, not the user's, and that is the fourth route the invariant forbids. Missing both is a normal outcome that leads to option 3.

**One upload per artifact, one variable each.** The collage and the GIF are two separate runs of this block. Keep the results apart — `COLLAGE_URL` for the stills, `FLOW_URL` for the GIF — and echo both before you write the body. Reusing `$URL` for the second upload is how a body ends up embedding the same image twice, or the collage under the flow caption.

Two limits to keep in mind:

- **Unlisted is not private.** A `share-file` URL is public to anyone holding it, just unguessable and expiring. That is far better than a permanent anonymous host, but it is not a private destination.
- **Consent to the mechanism is not consent to the content.** When §0's real-data caveat applies — the shots show live customer data — get an explicit yes for *these images* before uploading, even though the uploader is configured.

**3. Otherwise — keep it local and hand the upload to the user.** This is the correct outcome, not a failure. Write the Screenshots section with the captions already in place, so nothing is lost when the user drops the file in:

```markdown
## Screenshots

<!-- drag /absolute/path/to/collage.png into this box in the GitHub web UI -->

1. **Order list, default** — unchanged baseline for comparison
2. **Order list, filtered** — new date inputs outlined in red

<!-- drag /absolute/path/to/flow.gif into this box -->

3. **Export flow** — filter → export → download
```

One placeholder per artifact, captions per §3d. Print each absolute path and one line: *"Open the PR in the browser and drag this file where the comment is — GitHub hosts it on its own CDN, which is the one route that works for private repos too."*

Once the URLs are set, hold them for step 3 and apply it with the rest of the body in one `gh pr edit <N> --body-file <file>` or `gh pr create --body-file <file>`. `--body-file` **replaces the entire description**, so on an existing PR read the current body first and merge your section into it — a reviewer's checklist or a linked issue must not disappear because you were asked for a description. Don't post the collage as a standalone `gh pr comment`.

### 2i. Screencast

A still cannot show behaviour over time, so temporal changes get a GIF **as well as** the stills: a multi-step flow or wizard, a changed animation or transition, a progressive/streaming state, a drag, an interaction whose *point* is what happens after the click.

The test: **if annotated stills cannot show the changed behaviour without a paragraph of prose explaining it, record the GIF.** That paragraph is what the recording exists to delete. What fails the test needs no video — a restyled component, a new static section, a copy edit, or a dialog that merely opens on click, all of which read fine as before/after frames.

**MP4 when the file stays on GitHub, GIF when it leaves.** GitHub mounts a player only for video on its own CDN, which is exactly where route 1 puts it — so with that route the recording ships as an MP4, embedded as a **bare URL alone on its own line**, because `![]()` around a video renders nothing at all. On route 2 the file sits on an external host, where an MP4 degrades to a bare link and only a GIF still plays; produce the GIF then. Route 3's drag-drop lands on GitHub's CDN, so either works there.

With a session already open on the starting page:

```bash
agent-browser record start "$SHOTS/flow.webm"
# ... drive one pass of the flow with the same open/click/fill commands used above ...
agent-browser record stop

# route 1 — H.264 in a yuv420p pixel format, which is what plays everywhere
ffmpeg -i "$SHOTS/flow.webm" -c:v libx264 -pix_fmt yuv420p "$SHOTS/flow.mp4"

# route 2 — two-pass palette; a single-pass filter chain produces visibly dithered output
ffmpeg -i "$SHOTS/flow.webm" -vf \
  "fps=12,scale=900:-1:flags=lanczos,split[a][b];[a]palettegen[p];[b][p]paletteuse" \
  -loop 0 "$SHOTS/flow.gif"
```

Record only **one** pass of the flow itself; `-loop 0` makes the GIF repeat it forever, and GitHub's player loops the MP4. Keep a GIF under ~5 MB — check it, and drop to `fps=10` or `scale=720:-1` if it is over. The MP4 of the same recording lands far smaller, so the cap rarely binds there:

```bash
du -h "$SHOTS/flow.gif" "$SHOTS/flow.mp4" 2>/dev/null
```

Verify the recording with the Read tool, then run §2h again with `IMG` pointing at it and keep the result in `FLOW_URL` — a second artifact, not a replacement for the collage. Embed it in the `## Screenshots` section below the stills with its own one-line caption: `![…](URL)` for a GIF, the bare URL on its own line for an MP4.

## 3. Write the PR text

Write it after the collage and the GIF exist, not before.

### 3a. Budget

Counts of things, not a word total you cannot verify while writing:

| Part | Default |
|---|---|
| Title | one line, ≤70 chars |
| Summary | one sentence; a second only if it earns its place |
| Content sections | 3 maximum — `Screenshots` and the conditional `Data model docs` don't count against it |
| Bullets per section | 5 maximum, one line each |
| Panel captions | one per panel, one line |

That lands around 150 words of body on a UI PR and 250 on a backend-only PR, captions and image markup excluded. Those numbers are the target the counts produce, not a gate to squeeze under.

**What the budget never cuts.** Operational and migration risk, rollout or feature-flag behaviour, backward compatibility, security implications, known regressions, testing gaps. Those live in `Technical notes` and stay there however long they run — a PR whose longest section is its risk notes is correctly written. Trim narration, never review-critical facts.

Everything else: over budget means cut, not reformat.

### 3b. Shape

Title — conventional-commit style; `feat`, `fix`, `refactor`, `chore`, `docs`, scope in parentheses:

```
feat(orders): add date range filter to the order list and CSV export
```

Body — one sentence of orientation, then the pictures, then the short prose:

```markdown
Order lists could not be narrowed by date, so month-end reconciliation meant exporting everything.

## Screenshots

![Order list with the new date range filter](COLLAGE_URL)

1. **Order list, default** — unchanged baseline for comparison
2. **Order list, filtered** — new date inputs outlined in red

## Filtering
- Admins can filter the order list by date range
- Empty result shows a new empty state instead of a blank table

## Technical notes
- Filters on `created_at`; defaults to the last 30 days
```

That single leading sentence is not decoration. GitHub reuses the body in places that render no images at all — e-mail notifications, the API, and squash/merge commit messages — and a body opening with `![...](https://…)` tells those readers nothing. One sentence, then the visuals dominate everything below.

Give the image real alt text — `![Billing settings, invoice list and plan-change dialog](URL)`, not `![Collage](URL)`. It is what a reviewer on a broken connection, on mobile data, or after the host expiry sees.

Architectural and dependency decisions go under `Technical notes`, never mixed into feature bullets. On a backend-only PR there is no `## Screenshots` section and the summary may run to two sentences, because nothing else orients the reviewer.

### 3c. Shaped for a reader with ADHD

A PR-body adaptation of the `i-have-adhd` style. Its interactive rules — restate state each turn, give time estimates, end on a next action — do not apply to a PR description. These do:

**Cut**

- Preamble. Banned openers: "This PR", "This change introduces", "In this pull request", "As part of", "In order to". Start with the thing itself.
- Recaps and closers. Nothing restating the bullets above it, no "Let me know if…".
- Empty hedging — "should now", "hopefully", "various improvements". Real uncertainty is different; it stays, named.
- Idiom. "Falls back to the cached list" beats "gracefully degrades".

**Shape**

- One line, one fact. A bullet carrying two independent facts is two bullets — or one bullet and a cut.
- Concrete over abstract: names, paths, numbers. "Filters by `created_at`, defaults to the last 30 days" beats "improved filtering capabilities".
- Cap every list at 5. Past five, split into what matters for review and what is incidental, then drop the incidental.

**Keep**

- What a panel cannot show: why, the trade-off, what this replaces, permissions, defaults, accessibility and responsive behaviour.
- Limitations, stated flat: what is untested, what was only verified by hand, what the reviewer should check locally. "Not tested on Safari" is worth more than a paragraph of confidence.

### 3d. Captions do the explaining

**Captions are mandatory**, whether the image is embedded or still waiting to be dragged in. A collage without captions makes the reviewer guess what each panel proves. Mirror the state plan from §2c, one line per panel, in panel order, and give each artifact its own block:

```markdown
## Screenshots

![Order list, filtered and empty states](COLLAGE_URL)

1. **Order list, default** — unchanged baseline for comparison
2. **Order list, filtered** — new date inputs outlined in red
3. **Empty result** — new empty state instead of a blank table

![Export flow, four steps](FLOW_URL)

4. **Export flow** — filter → export → download
```

If a host expires, say so in this section so the reviewer knows the embed is impermanent — `share-file`'s 90-day default included.

### 3e. Trim pass before publishing

Read the body back once and delete:

1. The first sentence, if it announces the PR ("This PR adds…") instead of naming the problem or the outcome.
2. Any sentence re-describing what a panel already shows.
3. Any bullet naming a file or function without saying what changed for the user.
4. Empty hedges and idioms.
5. The last sentence, if it recaps or offers.

Then three checks:

- **Captions match panels** in order and description. §2g fixed the panel order; the captions are written here, so this is the first point at which they can be compared.
- **Each artifact appears once, under its own caption.** `COLLAGE_URL` and `FLOW_URL` are two different URLs — a body embedding one of them twice is the §2h variable bug, not a caption bug.
- **Skim test:** reading only the summary sentence, the captions and the headers, does the reviewer know what changed and where to look in the diff? If a *visible* change still needs a paragraph to be identifiable, fix the annotation or the caption (§2e, §3d) rather than adding prose. Facts no screenshot could carry — risk, architecture, compatibility — are supposed to be text. Leave them.

## 4. Data model documentation (conditional)

Only when the diff touches migrations, model definitions, `schema.prisma`, `.sql` schema files, or core serializers:

```
## Data model docs — suggested updates
- [Table/model]: added `field_name` (type, nullable/required, what it stores)
- [Table/model]: renamed `old_name` → `new_name`
- External API docs: response now includes `new_field`
```

Flag destructive changes explicitly:

```
**Operational risk:** [drops column X / adds NOT NULL to a populated table / needs a backfill]
```

One line per field, no prose wrapped around it. No schema change: omit the section entirely. Do not mention migrations in passing just to acknowledge them.

## 5. Final output

What you tell the user follows the same shape as what you wrote into the PR: the link or the file path first, prose after — and no recap of the steps you just ran.

1. **The PR URL**, or the title + body in one code block if the PR does not exist yet
2. **What the user still has to do**, if anything — usually "drag `<abs path>` into the PR body", one line per artifact (§2h option 3). If there is nothing, say the visuals are live in the body.
3. **Anything skipped and why**, one line each — dev server unreachable, no ImageMagick, real customer data in the shots, screencast dropped because ffmpeg is missing

Nothing else. Do not paste the description back when it is already published, do not list the surfaces you captured — the collage shows them.

Then clean up. `$SHOTS` holds full-resolution screenshots of the app, which may show real customer data:

```bash
rm -rf "$SHOTS"          # only after the user has what they need from it
```

Keep it if the user still has to drag the file into GitHub (§2h option 3) — tell them where it is and that it is theirs to delete.
