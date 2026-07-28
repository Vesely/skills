---
name: share-file
description: Upload a local file to private R2 temp storage and get back a public direct URL that auto-expires. Use when you need to host a screenshot, screencast, GIF, PDF, log or any artifact so it can be embedded in a PR description, pasted into Slack/Linear, or shared as a preview link — anything you would previously have sent to catbox, 0x0.st or an image host. Triggers on "upload this", "share this file", "host this screenshot", "get me a link for", "put this in the PR", "temp storage", "shareable link", "nahraj tohle", "sdílený odkaz". Default retention 90 days, customizable per upload.
allowed-tools:
  - Bash(share-file:*)
  - Bash(./share-file.sh:*)
  - Bash(wrangler r2:*)
  - Read
---

# share-file

Uploads a file to the private Cloudflare R2 bucket `storage` and prints a public
direct URL. Replaces catbox.moe.

- **Free** at normal volume (R2 free tier: 10 GB stored, unlimited egress)
- **Auto-expiring** — 90 days by default, so temp files clean themselves up
- **Direct links** with correct `Content-Type`, so images and GIFs render inline

## Usage

```bash
share-file <file> [--expire 7d|30d|90d|365d|keep] [--name <slug>]
```

Prints the public URL on stdout and nothing else, so it is safe to capture:

```bash
URL="$(share-file ./screenshot.png)"
```

Examples:

```bash
share-file ./screenshot.png                      # 90-day default
share-file ./demo.gif --expire 30d               # shorter-lived preview
share-file ./architecture.pdf --expire keep      # never expires
share-file ./out.gif --name login-flow           # control the URL slug
```

## Choosing an expiry

| Use case | Flag |
|---|---|
| Throwaway preview, one reviewer | `--expire 7d` |
| Screenshot for a PR that will merge soon | `--expire 30d` |
| **Default — PR assets, shared previews** | *(omit)* → `90d` |
| Docs or a link you'll reference for a while | `--expire 365d` |
| Permanent asset | `--expire keep` |

Pick a shorter window when the link is obviously disposable. Never use `keep`
unless the user asks for a permanent link — this is temp storage.

## Embedding the result

Return the bare URL to the user. When the file is going into a PR description or
a markdown comment, hand back a ready-to-paste snippet:

```markdown
![login flow](https://<public-base>/90d/2026-07/login-flow-a1b2c3d4.gif)
```

**GIFs, PNGs and JPEGs render inline in GitHub PRs.** MP4 does not — GitHub only
plays video uploaded to its own CDN, so an external `.mp4` URL degrades to a
plain link. If the user wants an inline video in a PR, convert to GIF first
(the `screencast` skill already does this) or post the MP4 as a labelled link.

## How expiry actually works

R2 lifecycle rules are scoped **per prefix, not per object** — there is no
per-object TTL. So the script routes each upload into a TTL-named prefix
(`90d/2026-07/name-abc123.png`) and each prefix carries a matching lifecycle
rule on the bucket. Deletion happens within ~24h of the deadline.

This means: **the prefix is the expiry.** Never hand-write a key into a
different prefix than the retention you want, and don't move objects between
prefixes expecting the clock to change.

## Setup

Nothing account-specific is baked into this skill — it works on any Cloudflare
account. Two one-time steps:

```bash
npm install -g wrangler && wrangler login
share-file setup
```

`setup` creates the bucket, adds the four lifecycle rules, and enables public
access. It is idempotent, so re-running it is harmless. Add `--bucket <name>` to
use something other than `storage`.

R2 must be enabled on the Cloudflare account first (dashboard → R2). Cloudflare
requires a payment method on file to enable it, even though normal
screenshot-sharing volume sits inside the free tier: 10 GB stored, unlimited
egress, 1M writes and 10M reads per month.

The public host is **discovered at runtime** from the bucket and cached in
`~/.cache/share-file/`, so a copy of this skill on another machine or account
resolves to that account's own bucket. Override either value if needed:

```bash
R2_PUBLIC_BASE="https://cdn.example.com" R2_BUCKET="scratch" share-file ./x.png
```

### Custom domain (optional)

Public delivery defaults to Cloudflare's `r2.dev` subdomain, which is
rate-limited, uncached, and documented as development-only. That is fine when
links are consumed by a handful of people — GitHub's camo proxy fetches an
embedded image once and serves its own copy to every viewer.

To use your own hostname the domain must be a **zone in the same Cloudflare
account**. Full nameserver hosting works; so does a partial (CNAME) setup, but
that is Business plan only. Once the zone is present:

```bash
wrangler r2 bucket domain add storage --domain files.example.com
export R2_PUBLIC_BASE="https://files.example.com"   # or clear the cache
```

Existing object keys are unaffected — only the host changes.

## Failure modes

- **`wrangler` not authenticated** → run `wrangler login`.
- **URL 404s right after upload** → custom domain not attached to the bucket, or
  DNS still propagating. Verify with `wrangler r2 object get storage/<key> --remote`.
- **Browser downloads instead of rendering** → wrong `Content-Type`. The script
  maps common extensions explicitly; add to the `case` block if a format is missing.
