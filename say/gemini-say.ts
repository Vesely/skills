#!/usr/bin/env bun
// Gemini TTS (Vertex AI) say-helper. Self-contained: mints a service-account
// OAuth token via crypto (no npm deps), synthesizes Czech speech, plays via afplay.
// Creds: point GEMINI_SAY_ENV at a file containing GOOGLE_VERTEX_PROJECT,
// GOOGLE_CLIENT_EMAIL and GOOGLE_PRIVATE_KEY (a Vertex service account).
// Defaults to ~/.config/gemini-say.env. No secrets are stored in this file.
// Usage: bun gemini-say.ts "text to speak" [voiceName] [--no-play] [-o out.wav]
import { createSign } from "node:crypto";
import { readFileSync } from "node:fs";
import { spawnSync } from "node:child_process";

const ENV_PATH = process.env.GEMINI_SAY_ENV || `${process.env.HOME}/.config/gemini-say.env`;
const LOCATION = "us-central1"; // global returns 500 for the TTS preview model
const MODEL = "gemini-2.5-flash-preview-tts";
const DEFAULT_VOICE = "Charon";

function readEnv(path: string): Record<string, string> {
  const out: Record<string, string> = {};
  for (const line of readFileSync(path, "utf8").split("\n")) {
    const m = line.match(/^([A-Z0-9_]+)=(.*)$/);
    if (!m) continue;
    let v = m[2];
    if (v.startsWith('"') && v.endsWith('"')) v = v.slice(1, -1).replace(/\\n/g, "\n");
    out[m[1]] = v;
  }
  return out;
}

function b64url(b: Buffer | string): string {
  return Buffer.from(b).toString("base64").replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
}

async function getToken(clientEmail: string, privateKey: string): Promise<string> {
  const now = Math.floor(Date.now() / 1000);
  const header = b64url(JSON.stringify({ alg: "RS256", typ: "JWT" }));
  const claim = b64url(JSON.stringify({
    iss: clientEmail,
    scope: "https://www.googleapis.com/auth/cloud-platform",
    aud: "https://oauth2.googleapis.com/token",
    iat: now, exp: now + 3600,
  }));
  const sig = b64url(createSign("RSA-SHA256").update(`${header}.${claim}`).sign(privateKey));
  const jwt = `${header}.${claim}.${sig}`;
  const r = await fetch("https://oauth2.googleapis.com/token", {
    method: "POST",
    headers: { "Content-Type": "application/x-www-form-urlencoded" },
    body: `grant_type=urn:ietf:params:oauth:grant-type:jwt-bearer&assertion=${jwt}`,
  });
  const j: any = await r.json();
  if (!j.access_token) throw new Error("token: " + JSON.stringify(j).slice(0, 300));
  return j.access_token;
}

const args = process.argv.slice(2);
const noPlay = args.includes("--no-play");
const oIdx = args.indexOf("-o");
const outPath = oIdx >= 0 ? args[oIdx + 1] : "/tmp/gemini-say.wav";
const positional = args.filter((a, i) => a !== "--no-play" && !(oIdx >= 0 && (i === oIdx || i === oIdx + 1)));
const text = positional[0];
const voice = positional[1] || DEFAULT_VOICE;
if (!text) { console.error("usage: bun gemini-say.ts <text> [voice] [--no-play] [-o out.wav]"); process.exit(1); }

const env = readEnv(ENV_PATH);
const project = env.GOOGLE_VERTEX_PROJECT;
const token = await getToken(env.GOOGLE_CLIENT_EMAIL, env.GOOGLE_PRIVATE_KEY);
const url = `https://${LOCATION}-aiplatform.googleapis.com/v1/projects/${project}/locations/${LOCATION}/publishers/google/models/${MODEL}:generateContent`;
const r = await fetch(url, {
  method: "POST",
  headers: { Authorization: `Bearer ${token}`, "Content-Type": "application/json" },
  body: JSON.stringify({
    contents: [{ role: "user", parts: [{ text }] }],
    generationConfig: { responseModalities: ["AUDIO"], speechConfig: { voiceConfig: { prebuiltVoiceConfig: { voiceName: voice } } } },
  }),
});
if (!r.ok) { console.error("ERR", r.status, (await r.text()).slice(0, 500)); process.exit(1); }
const j: any = await r.json();
const part = j.candidates?.[0]?.content?.parts?.find((p: any) => p.inlineData);
if (!part) { console.error("NOAUDIO", JSON.stringify(j).slice(0, 400)); process.exit(1); }
const rate = parseInt((part.inlineData.mimeType || "").match(/rate=(\d+)/)?.[1] || "24000", 10);
const pcm = Buffer.from(part.inlineData.data, "base64");
const ch = 1, bps = 16, blockAlign = (ch * bps) / 8, byteRate = rate * blockAlign;
const h = Buffer.alloc(44);
h.write("RIFF", 0); h.writeUInt32LE(36 + pcm.length, 4); h.write("WAVE", 8); h.write("fmt ", 12);
h.writeUInt32LE(16, 16); h.writeUInt16LE(1, 20); h.writeUInt16LE(ch, 22); h.writeUInt32LE(rate, 24);
h.writeUInt32LE(byteRate, 28); h.writeUInt16LE(blockAlign, 32); h.writeUInt16LE(bps, 34); h.write("data", 36); h.writeUInt32LE(pcm.length, 40);
await Bun.write(outPath, Buffer.concat([h, pcm]));

const u = j.usageMetadata || {};
const inTok = u.promptTokenCount || 0;
const outTok = u.candidatesTokenCount || u.totalTokenCount - inTok || 0;
const cost = (inTok / 1e6) * 0.5 + (outTok / 1e6) * 10;
console.log(`OK ${voice} ${outPath} | in=${inTok} out=${outTok} tok | ~$${cost.toFixed(5)} (~${(cost * 23).toFixed(3)} Kč)`);
if (!noPlay) {
  // Duck other audio (Spotify / Music / browser / YouTube) for the duration of
  // playback, like Wispr does for dictation, so the voice isn't a mishmash with
  // background media. nowplaying-cli drives the system "now playing" client
  // whatever app it is; only resume what we actually paused. Missing tool or
  // nothing playing => no-op (spawnSync reports ENOENT via .error, not a throw).
  const NOWPLAYING = "/opt/homebrew/bin/nowplaying-cli";
  let ducked = false;
  try {
    const r = spawnSync(NOWPLAYING, ["get", "playbackRate"], { encoding: "utf8" });
    if (r.status === 0 && parseFloat((r.stdout || "").trim()) > 0) {
      spawnSync(NOWPLAYING, ["pause"]);
      ducked = true;
    }
  } catch {}
  spawnSync("afplay", [outPath], { stdio: "ignore" });
  if (ducked) { try { spawnSync(NOWPLAYING, ["play"]); } catch {} }
}
