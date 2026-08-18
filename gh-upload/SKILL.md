---
name: gh-upload
description: Upload an image, GIF or video into a GitHub PR or issue body and get back a github.com/user-attachments URL. `gh` has no native command for this — this is the same endpoint the web UI's drag-and-drop uses, so the asset inherits the repo's visibility instead of sitting on a public host. Use when embedding a screenshot, before/after collage, screencast or UI proof into a PR description, an issue, or a review comment. Triggers on "put this screenshot in the PR", "attach this to the issue", "embed this video in the PR description", "upload proof to GitHub", "nahraj to do PR".
allowed-tools:
  - Bash(gh:*)
  - Bash(curl:*)
  - Bash(ffmpeg:*)
  - Read
argument-hint: "[file ...]"
---

# gh-upload

`gh` cannot attach files. `POST https://uploads.github.com/user-attachments/assets` can — it is the endpoint behind drag-and-drop in the web UI. No browser, no computer use.

Assets **inherit repo visibility**: upload against a private repo and the URL 404s for anyone without access. That is the reason to prefer this over an external host for anything going into a GitHub body.

## 1. Get the numeric repo id

```bash
REPO_ID=$(gh api repos/{owner}/{repo} --jq .id)   # e.g. 169221790
```

It must be the **numeric** id. `gh repo view --json id` returns a GraphQL node id (`MDEwOlJlcG9zaXRvcnkx…`) — that 404s.

## 2. Upload

```bash
curl -s "https://uploads.github.com/user-attachments/assets?name=$NAME&content_type=$MIME&repository_id=$REPO_ID" \
  -X POST \
  -H "Authorization: Bearer $(gh auth token)" \
  -H "Accept: application/json" \
  --data-binary "@$FILE"
# 201 → {"url":"https://github.com/user-attachments/assets/<uuid>"}
```

`$NAME` is the display filename shown in the body; it does not have to equal `$FILE`. Use it to say what the reader is looking at — `login-error-before.png`, not `Screenshot 2026-08-18 at 14.13.12.png`.

## 3. Embed

| Kind | Markdown |
|---|---|
| Image / GIF | `![caption](URL)` |
| **Video** | the **bare URL, alone on its own line** |
| Several surfaces | one `###` heading + one image per surface |

`![](URL)` around a video renders nothing — GitHub only mounts the player for a bare URL.

Hand the finished markdown back, or write it: `gh pr edit <n> --body-file body.md`.

## Accepted types

Verified against the live endpoint:

| Accepted (201) | Rejected (422) |
|---|---|
| `image/png` `image/jpeg` `image/gif` `image/webp` `image/svg+xml` | `application/pdf` |
| `video/mp4` `video/webm` `video/quicktime` | `text/plain` `text/markdown` |
| | `application/zip` `application/json` `application/octet-stream` |

**Media only.** For a PDF, log, zip or any non-media artifact the endpoint always 422s — host it elsewhere (`share-file`) and link it, and note in the body that that link is public.

`video/mp4` and `video/webm` are the two GitHub reliably plays. Transcode anything else — including the `.webm` a Playwright/agent-browser recording produces, if broad playback matters:

```bash
ffmpeg -i in.webm -c:v libx264 -pix_fmt yuv420p out.mp4
```

## Gotchas

- **`name`'s extension must match `content_type`.** `name=shot` with no extension 422s every single type; `shot.png` + `image/png` passes. The 422 body names the mismatch — read it instead of guessing.
- **Percent-encode the query values.** `image/svg+xml` sent raw arrives as `image/svg xml` → 422; send `image%2Fsvg%2Bxml`. Spaces in `name` → `%20`.
- **Bytes are not sniffed.** A text file named `.png` and declared `image/png` uploads happily, then renders broken. The extension/mime pair is the only check — getting the real file right is on you.
- **The URL can 404 for a minute after upload.** Propagation is not instant — a check that runs immediately after the 201 is not evidence the upload failed. Re-check before you conclude anything.
- **Keep the `github.com/user-attachments/…` form.** It 302s to a signed S3 URL with `X-Amz-Expires=300`; embed the short one and the link keeps working, embed the redirect target and it dies in five minutes.
- **404** = wrong `repository_id`, or the token has no push access to that repo. `gh auth token` must carry `repo` scope.
- **No delete endpoint.** Every upload is permanent. Look at the image before sending it — screenshots carry whatever was on screen: tokens in a devtools panel, customer names, staging data.
- **Never commit proof assets to a product branch**, and do not create a `.github/pr-assets` directory. Living off-repo is the point.
