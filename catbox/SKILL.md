---
name: catbox
description: Upload files to catbox.moe for free, anonymous hosting with direct links. Use when the user wants to upload an image, video, or any file to catbox, host a file online, get a direct link to a file, or mentions "catbox", "catbox.moe", "upload to catbox", "host file", or wants a permanent direct URL for a file.
---

# catbox

Upload files to [catbox.moe](https://catbox.moe/) — a free, anonymous file hosting service. No account or CLI tool required; uploads use a simple curl API.

- **Max file size:** 200 MB
- **No authentication** needed
- **Direct links** to hosted files (e.g. `https://files.catbox.moe/abc123.png`)
- **Permanent** — uploaded files do not expire

## File upload

Upload a local file:

```bash
curl -F "reqtype=fileupload" -F "fileToUpload=@<FILE>" https://catbox.moe/user/api.php
```

Examples:

```bash
# Upload an image
curl -F "reqtype=fileupload" -F "fileToUpload=@screenshot.png" https://catbox.moe/user/api.php

# Upload a video
curl -F "reqtype=fileupload" -F "fileToUpload=@demo.mp4" https://catbox.moe/user/api.php
```

The response body is the direct URL to the file, e.g. `https://files.catbox.moe/abc123.png`.

## URL upload

Re-host a file from another URL (no local download needed):

```bash
curl -F "reqtype=urlupload" -F "url=https://example.com/image.png" https://catbox.moe/user/api.php
```

## Silent mode

Add `-s` for scripting — suppresses progress output, response is just the URL:

```bash
curl -s -F "reqtype=fileupload" -F "fileToUpload=@photo.jpg" https://catbox.moe/user/api.php
```

## Output

After upload, present the direct `https://files.catbox.moe/...` URL to the user. Note that catbox links are permanent and publicly accessible.
