#!/usr/bin/env bun
import { spawnSync } from "node:child_process";

const API_BASE = "https://api.atlascloud.ai/api/v1";
const CATALOG_URL = `${API_BASE}/models`;
const MODEL = "google/gemini-2.5-flash-tts";
const DEFAULT_VOICE = "Charon";
const DEFAULT_OUTPUT = "/tmp/atlas-say.wav";
const MAX_POLLS = 8;

type FetchLike = typeof fetch;
type Sleep = (milliseconds: number) => Promise<void>;

function unwrap(body: any): any {
  return body?.data ?? body;
}

async function jsonRequest(fetcher: FetchLike, url: string, init?: RequestInit): Promise<any> {
  const response = await fetcher(url, init);
  if (!response.ok) throw new Error(`request failed with HTTP ${response.status}`);
  const body = await response.json();
  if (body?.code !== undefined && !["0", "200"].includes(String(body.code))) {
    throw new Error(`Atlas API returned code ${body.code}`);
  }
  return body;
}

export async function validateAtlasContract(fetcher: FetchLike = fetch): Promise<{ schema: any; price?: string }> {
  const catalogBody = await jsonRequest(fetcher, CATALOG_URL);
  const models = unwrap(catalogBody);
  if (!Array.isArray(models)) throw new Error("Atlas model catalog returned an unexpected shape");

  const model = models.find((item: any) => item?.model === MODEL && item?.display_console === true);
  if (!model?.schema) throw new Error(`${MODEL} is not available in the Atlas console catalog`);

  const schema = await jsonRequest(fetcher, model.schema);
  const input = schema?.components?.schemas?.Input;
  const route = schema?.paths?.["/api/v1/model/generateAudio"]?.post;
  const predictionRoute = schema?.paths?.["/api/v1/model/prediction/{request_id}"]?.get;
  if (!route || !predictionRoute || !input?.properties?.text || !input?.properties?.voice) {
    throw new Error("Atlas TTS schema does not match the expected generateAudio contract");
  }
  if (!input.properties.model?.enum?.includes(MODEL)) {
    throw new Error(`Atlas TTS schema does not declare ${MODEL}`);
  }
  return { schema, price: model?.price?.actual?.base_price };
}

export async function generateAtlasSpeech(
  text: string,
  voice: string,
  apiKey: string,
  options: { fetcher?: FetchLike; sleep?: Sleep; maxPolls?: number } = {},
): Promise<{ outputUrl: string; predictionId: string; price?: string }> {
  const fetcher = options.fetcher ?? fetch;
  const sleep = options.sleep ?? ((milliseconds) => Bun.sleep(milliseconds));
  const maxPolls = options.maxPolls ?? MAX_POLLS;
  const { schema, price } = await validateAtlasContract(fetcher);
  const voices = schema.components.schemas.Input.properties.voice.enum ?? [];
  if (!voices.includes(voice)) throw new Error(`voice ${voice} is not supported by the live Atlas schema`);

  const submitted = unwrap(await jsonRequest(fetcher, `${API_BASE}/model/generateAudio`, {
    method: "POST",
    headers: { Authorization: `Bearer ${apiKey}`, "Content-Type": "application/json" },
    body: JSON.stringify({ model: MODEL, text, voice }),
  }));
  const predictionId = submitted?.id;
  if (!predictionId) throw new Error("Atlas generation response did not include a prediction id");

  for (let attempt = 0; attempt < maxPolls; attempt += 1) {
    if (attempt > 0) await sleep(Math.min(1_000 * 2 ** (attempt - 1), 8_000));
    let prediction: any;
    try {
      prediction = unwrap(await jsonRequest(fetcher, `${API_BASE}/model/prediction/${encodeURIComponent(predictionId)}`, {
        headers: { Authorization: `Bearer ${apiKey}` },
      }));
    } catch (error) {
      if (attempt === maxPolls - 1) throw error;
      continue;
    }
    if (["completed", "succeeded"].includes(prediction?.status)) {
      const outputUrl = prediction?.outputs?.[0];
      if (!outputUrl) throw new Error("completed Atlas prediction did not include an audio URL");
      return { outputUrl, predictionId, price };
    }
    if (prediction?.status === "failed") throw new Error("Atlas TTS prediction failed");
  }
  throw new Error(`Atlas TTS prediction did not finish after ${maxPolls} checks`);
}

async function downloadAudio(fetcher: FetchLike, url: string, outputPath: string): Promise<void> {
  if (new URL(url).protocol !== "https:") throw new Error("Atlas audio URL must use HTTPS");
  const response = await fetcher(url);
  if (!response.ok) throw new Error(`audio download failed with HTTP ${response.status}`);
  await Bun.write(outputPath, await response.arrayBuffer());
}

function playAudio(outputPath: string): void {
  const nowPlaying = "/opt/homebrew/bin/nowplaying-cli";
  const status = spawnSync(nowPlaying, ["get", "playbackRate"], { encoding: "utf8" });
  const ducked = status.status === 0 && parseFloat((status.stdout || "").trim()) > 0;
  if (ducked) spawnSync(nowPlaying, ["pause"]);
  spawnSync("afplay", [outputPath], { stdio: "ignore" });
  if (ducked) spawnSync(nowPlaying, ["play"]);
}

export async function runCli(args = process.argv.slice(2)): Promise<number> {
  const noPlay = args.includes("--no-play");
  const confirmed = args.includes("--yes");
  const outputIndex = args.indexOf("-o");
  const outputPath = outputIndex >= 0 ? args[outputIndex + 1] : DEFAULT_OUTPUT;
  const positional = args.filter((arg, index) =>
    !["--no-play", "--yes"].includes(arg) && !(outputIndex >= 0 && (index === outputIndex || index === outputIndex + 1))
  );
  const text = positional[0];
  const voice = positional[1] || DEFAULT_VOICE;
  if (!text || !outputPath) {
    console.error("usage: bun atlas-say.ts <text> [voice] [--yes] [--no-play] [-o out.wav]");
    return 1;
  }

  const apiKey = process.env.ATLASCLOUD_API_KEY;
  if (!apiKey) {
    console.error("ATLASCLOUD_API_KEY is required for the Atlas provider");
    return 1;
  }

  if (!confirmed) {
    const { schema, price } = await validateAtlasContract();
    const voices = schema.components.schemas.Input.properties.voice.enum ?? [];
    if (!voices.includes(voice)) throw new Error(`voice ${voice} is not supported by the live Atlas schema`);
    console.log(`PLAN model=${MODEL} voice=${voice} current_base_price=${price ?? "unknown"}; rerun with --yes to submit once`);
    return 0;
  }

  const result = await generateAtlasSpeech(text, voice, apiKey);
  await downloadAudio(fetch, result.outputUrl, outputPath);
  console.log(`OK ${voice} ${outputPath} | prediction=${result.predictionId}`);
  if (!noPlay) playAudio(outputPath);
  return 0;
}

if (import.meta.main) {
  try {
    process.exitCode = await runCli();
  } catch (error) {
    console.error("ERR", error instanceof Error ? error.message : "unexpected Atlas TTS failure");
    process.exitCode = 1;
  }
}
