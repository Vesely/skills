---
name: ai-gateway
description: Generate text and images from the CLI via the Vercel AI Gateway (one key, hundreds of models).
allowed-tools:
  - Bash(ai-gateway:*)
  - Bash(npm install -g @vesely/ai-gateway-cli)
  - Bash(npm list -g @vesely/ai-gateway-cli)
  - Bash(which ai-gateway)
  - Read
when_to_use: |
  Use when the user (or your own task) needs to generate text or images via an AI model and prefers a quick CLI call over writing SDK code.
  Trigger phrases: "generate an image of...", "make an image with AI", "ask an LLM to...", "use ai-gateway to...", "draft text with AI", "summarize via CLI", "use a Vercel AI Gateway model".
  Examples: "Generate a hero image of a snow leopard and save it as hero.png", "Use Nano Banana to make a logo", "Pipe this README into an LLM and get a summary".
  Skip when the user wants to integrate AI into source code (use the AI SDK directly), or when they need streaming UI / tool-use / multi-turn chat.
argument-hint: "<text|image> <prompt> [-m model] [-o file] [-n count]"
---

# ai-gateway CLI

A thin wrapper around the `ai-gateway` CLI (https://vercel.com/ai-gateway) for one-shot text and image generation. Use it whenever a single CLI call beats writing SDK code.

## Defaults

- Text model: `xai/grok-4.1-fast-non-reasoning` (cheap + capable)
- Image model: `bfl/flux-2-flex`
- Override per-call with `-m <model-id>`. Browse with `ai-gateway models --type image|language`.

## Notable models

- Image-only: `bfl/flux-2-pro`, `bfl/flux-pro-1.1`, `openai/gpt-image-2`, `google/imagen-4.0-generate-001`, `xai/grok-imagine-image`.
- Multimodal LLMs (auto-routed through chat completions): `google/gemini-2.5-flash-image` (Nano Banana), `google/gemini-3.1-flash-image-preview` (Nano Banana 2), `google/gemini-3-pro-image`.
- Text quality: `anthropic/claude-opus-4.6`, `openai/gpt-5.4`, `xai/grok-4.3`.

## Steps

### 1. Verify the CLI is installed

Run `which ai-gateway`. If missing, install: `npm install -g @vesely/ai-gateway-cli`.

**Success criteria**: `which ai-gateway` returns a path.

### 2. Verify the API key is reachable

The CLI looks for the key in this order: `--key` flag → `AI_GATEWAY_API_KEY` env → `~/.config/ai-gateway-cli/config.json`. If `AI_GATEWAY_API_KEY` is unset AND the config file is missing/empty, ask the user for it once: tell them to either `export AI_GATEWAY_API_KEY=...` or run `ai-gateway config set key <value>`. Get a key at https://vercel.com/ai-gateway.

**Success criteria**: `ai-gateway config` shows a key (masked) OR `$AI_GATEWAY_API_KEY` is set.

### 3. Run the generation

**Text** (streamed to stdout):

```bash
ai-gateway "<prompt>"                       # default model
ai-gateway -m anthropic/claude-opus-4.6 "<prompt>"
ai-gateway --json "<prompt>"                # full JSON response (.text, .usage)
cat file.md | ai-gateway "<prompt>"         # piped stdin is prepended as context
```

**Image** (saves to disk, prints path):

```bash
ai-gateway image "<prompt>"                                    # ./ai-image-<timestamp>.png
ai-gateway image -o output.png "<prompt>"                      # custom path
ai-gateway image -n 4 "<prompt>"                               # 4 images, auto-suffixed
ai-gateway image -m bfl/flux-2-pro -o cover.png "<prompt>"     # specific image-only model
ai-gateway image -m google/gemini-2.5-flash-image "<prompt>"   # Nano Banana (auto-routed via chat completions)
```

**Success criteria**:
- Text: streamed output ends with a newline, exit 0.
- Image: stdout contains `Saved: <absolute path>` and the file exists on disk.

### 4. Report the result back

For text: relay the model output to the user (it's already on stdout).
For image: report the absolute path(s) printed by the CLI. Do not re-encode or open the file unless asked.

**Success criteria**: User has the answer/file path.

## Rules

- Never hardcode an API key in scripts. Resolution is env > config; agents should not read or write `~/.config/ai-gateway-cli/config.json` directly.
- For multi-image batches with multimodal LLMs (Nano Banana etc.), the CLI loops `n` times against `/v1/chat/completions` since chat has no native batch — be patient with `-n 4`.
- If the model id is unknown, run `ai-gateway models --search <substring>` to discover it instead of guessing.
- Don't pass `--json` to the image command if the user wants a human-readable result; it suppresses the friendly "Saved: ..." lines.
- The default text model is non-reasoning + fast; for harder reasoning tasks pick `xai/grok-4.1-fast-reasoning`, `anthropic/claude-opus-4.6`, or `openai/gpt-5.4` via `-m`.

## Troubleshooting

- `Unauthorized (401)` → key is wrong/expired. Reset with `ai-gateway config set key <value>`.
- `Not found (404). Unknown model?` → run `ai-gateway models --search <hint>`.
- `Model "<id>" does not support image generation` → the chosen model isn't an image-only model and lacks the `image-generation` tag. Pick from `ai-gateway models --type image` or use a multimodal LLM listed above.
