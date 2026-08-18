---
name: pr-handoff
description: >-
  Generates annotated browser screenshots of every UI change as the primary PR deliverable — plus an
  optional GIF screencast for multi-step or animated flows — then writes a concise PR title and
  description ready to paste into GitHub, and optional data-model documentation notes. Reviews the
  current branch diff against the default branch, captures every affected user-facing surface with
  the agent-browser CLI, marks the changed elements in red, stitches the shots into a collage with
  ImageMagick, hosts it through a configured uploader (or leaves it local for drag-and-drop), and
  embeds it in the PR body with per-panel captions. Use whenever the user wants to write a PR
  description, document branch changes for a reviewer, create a PR writeup, prepare a handoff, or
  says things like "write PR description", "prep the PR", "PR handoff", "document my changes",
  "screenshot my PR", or "generate PR notes". Also trigger when the user just says "PR" in the
  context of finishing or shipping work.
---

# PR Handoff

For any PR that touches the UI, **screenshots are the primary deliverable**. A reviewer grasps the change in seconds from an annotated screenshot — no amount of prose does that. Capture them before writing the description, and get them into the PR body yourself through one of the three routes in §2h — never as a follow-up comment. When none of those routes is available, §2h option 3 is the correct ending, not a failure.

Scope: **GitHub + `gh`**. Other forges are out of scope.

## Requirements

| Tool | Needed for | Checked |
|---|---|---|
| `git`, `gh` (authenticated), `curl` | diff, PR create/edit, reachability | up front |
| `agent-browser` | every screenshot and screencast | only on UI PRs |
| ImageMagick (`magick` or `convert`) | stitching the collage | only for 2+ shots |
| `ffmpeg` | webm → GIF | only for screencasts |
| `gifski` | smaller, sharper GIFs | optional |
| [`share-file`](https://github.com/Vesely/skills/tree/main/share-file) | hosting the image so GitHub can render it (§2h option 1) | optional, recommended |

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
- **Captions still match the panels** in order and description.

If anything fails: adjust the geometry, re-run, Read it again. **Loop until every item passes.** Do not publish a collage you would not want a reviewer to see as-is — a visibly-off annotation makes the whole PR look careless and costs a round-trip with the user.

### 2h. Host the image

**The invariant, which the three options below cannot override.** The image may leave this machine by exactly the three routes in this section and by no other. Everything else is out of bounds regardless of how the run is going: image hosts (catbox, imgur, litterbox, tmpfiles, 0x0.st and every sibling), gists, release assets, a bucket you pick, a `curl` you compose, committing the file to the PR branch, or `git add -f` past a `.gitignore`. Not embedding an image is an acceptable outcome; publishing one somewhere the user did not choose is not. Option 3 is always available and publishes nothing, so "everything else failed" is never a reason to improvise a fourth route. If the user explicitly asks for a public host, name exactly what becomes public and permanent, and get a yes for that specific upload first.

Pick the destination by what the repo is:

```bash
gh repo view --json visibility -q .visibility     # PUBLIC | PRIVATE | INTERNAL
```

**1. An uploader that was already installed and configured before this run.** `PR_HANDOFF_UPLOAD_CMD` if the user set one, otherwise the `share-file` skill if they have it:

```bash
IMG="$SHOTS/collage.png"     # or the single screenshot, or the GIF from 2i

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
```

Contract: the uploader takes one file path and prints exactly one `https://` URL on stdout, nothing else, non-zero on failure. Flags are fine — it runs through `sh -c`, so `mytool upload --ttl 90d` works. [`share-file`](https://github.com/Vesely/skills/tree/main/share-file) meets this contract exactly and is the recommended default: it uploads to the user's *own* Cloudflare R2 bucket with a 90-day expiry, so the link is theirs to revoke and cleans itself up.

**Neither one may be created during the run.** The variable must already be set in the environment you inherited, and `share-file` must already be installed *and* set up. You never export the variable, suggest a value for it, write the script it points at, install `share-file`, or run its `setup` — a route you construct yourself is your consent, not the user's, and that is the fourth route the invariant forbids. Missing both is a normal outcome that leads to option 2 or 3.

Two limits to keep in mind:

- **Unlisted is not private.** A `share-file` URL is public to anyone holding it, just unguessable and expiring. That is far better than a permanent anonymous host, but it is not a private destination.
- **Consent to the mechanism is not consent to the content.** When §0's real-data caveat applies — the shots show live customer data — get an explicit yes for *these images* before uploading, even though the uploader is configured.

Note the expiry in the description (§3) whenever the host is time-limited, `share-file`'s 90-day default included.

**2. Public repo, no uploader — an orphan assets branch (ask first).** Runs entirely in a throwaway worktree, so the user's working tree, branch and uncommitted changes are never touched. One `&&` chain, so a failure anywhere leaves `$URL` empty and drops you to option 3 instead of embedding a dead link:

```bash
git worktree prune                                  # clear worktrees left by a crashed run
WT="$(mktemp -d)"; URL=""
SLUG="$(gh repo view --json nameWithOwner -q .nameWithOwner)"
ASSET="pr/$SLUGBRANCH/$(basename "$IMG")"

if git ls-remote --exit-code --heads origin pr-assets >/dev/null 2>&1; then
  git fetch -q origin pr-assets && git worktree add -q --detach "$WT" origin/pr-assets
else
  git worktree add -q --detach "$WT" \
    && git -C "$WT" checkout -q --orphan pr-assets-staging \
    && git -C "$WT" rm -rq --cached .
fi \
  && mkdir -p "$WT/$(dirname "$ASSET")" && cp "$IMG" "$WT/$ASSET" \
  && git -C "$WT" add "$ASSET" \
  && git -C "$WT" commit -q --allow-empty -m "chore: PR assets for $BRANCH" \
  && git -C "$WT" push -q origin HEAD:pr-assets \
  && URL="https://raw.githubusercontent.com/$SLUG/pr-assets/$ASSET"

git worktree remove --force "$WT" 2>/dev/null; git branch -qD pr-assets-staging 2>/dev/null
[ -n "$URL" ] || echo "assets branch failed — use option 3"
```

Ask before doing this: it writes the image into the repository permanently, and git history is much harder to walk back than a deleted file. **Never on a private or internal repo** — GitHub's image proxy fetches without credentials, so a private `raw.githubusercontent.com` URL renders as a broken image for every reviewer.

**3. Otherwise — keep it local and hand the upload to the user.** This is the correct outcome, not a failure. Write the Screenshots section with the captions already in place, so nothing is lost when the user drops the file in:

```markdown
## Screenshots

<!-- drag /absolute/path/to/collage.png into this box in the GitHub web UI -->

1. **Order list, default** — unchanged baseline for comparison
2. **Order list, filtered** — new date inputs outlined in red
```

Print the absolute path and one line: *"Open the PR in the browser and drag this file where the comment is — GitHub hosts it on its own CDN, which is the one route that works for private repos too."*

Once `$URL` is set, hold it for step 3 and apply it with the rest of the body in one `gh pr edit <N> --body-file <file>` or `gh pr create --body-file <file>`. `--body-file` **replaces the entire description**, so on an existing PR read the current body first and merge your section into it — a reviewer's checklist or a linked issue must not disappear because you were asked for a description. Don't post the collage as a standalone `gh pr comment`.

### 2i. Screencast (only for flows)

A still cannot show behaviour over time. Record **only** when the change is temporal: a multi-step flow or wizard, an animation, a progressive/streaming state, a drag or hover interaction. A static visual change needs no video.

**Produce a GIF, not an MP4.** GitHub plays inline video only for files on its own CDN (web-UI drag-drop, which `gh` cannot do); an external MP4 degrades to a bare link. A GIF embeds with `![]()` exactly like the collage and takes the same three routes in §2h.

With a session already open on the starting page:

```bash
agent-browser record start "$SHOTS/flow.webm"
# ... drive one pass of the flow with the same open/click/fill commands used above ...
agent-browser record stop

# two-pass palette — a single-pass filter chain produces visibly dithered output
ffmpeg -i "$SHOTS/flow.webm" -vf \
  "fps=12,scale=900:-1:flags=lanczos,split[a][b];[a]palettegen[p];[b][p]paletteuse" \
  -loop 0 "$SHOTS/flow.gif"
```

`-loop 0` means the finished GIF loops forever, which is what you want; record only **one** pass of the flow itself. Keep the file under ~5 MB — check it, and drop to `fps=10` or `scale=720:-1` if it is over:

```bash
du -h "$SHOTS/flow.gif"
```

Verify the GIF with the Read tool, host it through §2h (as `$IMG`), and embed it in the `## Screenshots` section alongside the stills with a one-line caption. It supplements the annotated stills; it does not replace them.

## 3. Write the PR description

**Title** — one line, conventional-commit style, ≤70 characters:

```
feat(orders): add date range filter to the order list and CSV export
```

`feat`, `fix`, `refactor`, `chore`, `docs`, with a scope in parentheses.

**Body:**

```
Two or three sentences on what this PR does and why — the problem solved,
not the list of files changed.

## Screenshots
<!-- UI PRs only: collage (+ flow GIF from 2i) and one caption per panel -->

## [Header 1 — the main change]
- outcome-focused bullet ("Admins can filter the order list by date range")
- not implementation-focused ("Added date_from to the queryset")

## [Header 2 — second area, if any]

## [Technical notes — decisions, libraries, infrastructure, if any]
```

Guidelines:

- Three headers maximum. Merge small items rather than splitting into four.
- Architectural and dependency decisions go under "Technical notes", not mixed into feature bullets.
- The `## Screenshots` section sits right after the summary — the first thing a reviewer sees.

**Captions are mandatory**, whether the image is embedded or still waiting to be dragged in. A collage with no captions makes the reviewer guess what each panel proves. Mirror the state plan from §2c:

```markdown
## Screenshots

![Collage](URL)

1. **Order list, default** — unchanged baseline for comparison
2. **Order list, filtered** — new date inputs outlined in red
3. **Empty result** — new empty state instead of a blank table
```

If the image is hosted somewhere that expires, say so in that section so the reviewer knows the embed is impermanent.

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

No schema change: omit the section entirely. Do not mention migrations in passing just to acknowledge them.

## 5. Final output

Present:

1. **PR title** — pasted, or already applied via `gh pr create`
2. **Screenshots** — the hosted URL now embedded in the body, or the local path plus the one-line drag-drop instruction
3. **PR description** — in a code block if the PR does not exist yet, otherwise confirmation that it is live
4. **Data model notes**, if any
5. **Anything skipped and why** — dev server unreachable, no ImageMagick, real customer data in the shots

Then clean up. `$SHOTS` holds full-resolution screenshots of the app, which may show real customer data:

```bash
rm -rf "$SHOTS"          # only after the user has what they need from it
```

Keep it if the user still has to drag the file into GitHub (§2h option 3) — tell them where it is and that it is theirs to delete.
