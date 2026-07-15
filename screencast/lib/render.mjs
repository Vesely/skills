// Render pipeline: raw.webm + events.jsonl -> polished <name>.mp4
//   probe -> extract frames -> detect sync flash -> build timeline ->
//   composite every output frame in canvas -> stream to ffmpeg (with chapters)
import fs from "node:fs";
import path from "node:path";
import { spawn } from "node:child_process";
import { createCanvas, loadImage } from "@napi-rs/canvas";
import { CONFIG, clamp, clamp01, easeOutCubic, easeOutQuad, run, log } from "./util.mjs";
import { readState, paths } from "./state.mjs";
import { buildTimeline } from "./timeline.mjs";
import * as draw from "./draw.mjs";

function probe(video) {
  const r = run("ffprobe", ["-v", "error", "-select_streams", "v:0", "-show_entries", "stream=width,height", "-of", "json", video]);
  const s = JSON.parse(r.stdout).streams[0];
  return { videoW: s.width, videoH: s.height };
}

function extractFrames(video, dir, fps) {
  fs.rmSync(dir, { recursive: true, force: true });
  fs.mkdirSync(dir, { recursive: true });
  const r = run("ffmpeg", ["-y", "-i", video, "-vf", `fps=${fps}`, "-qscale:v", "2", path.join(dir, "%06d.jpg")]);
  if (r.code !== 0) throw new Error("ffmpeg frame extraction failed:\n" + r.stderr);
  return fs.readdirSync(dir).filter((f) => f.endsWith(".jpg")).sort();
}

async function detectFlash(dir, frames, fps, color) {
  const scan = Math.min(frames.length, Math.ceil(fps * 1.6));
  const probe = createCanvas(16, 16);
  const pctx = probe.getContext("2d");
  const [fr, , fb] = color;
  for (let i = 0; i < scan; i++) {
    const img = await loadImage(path.join(dir, frames[i]));
    pctx.clearRect(0, 0, 16, 16);
    pctx.drawImage(img, img.width / 2 - 8, img.height / 2 - 8, 16, 16, 0, 0, 16, 16);
    const d = pctx.getImageData(0, 0, 16, 16).data;
    let r = 0, g = 0, b = 0, n = 0;
    for (let p = 0; p < d.length; p += 4) { r += d[p]; g += d[p + 1]; b += d[p + 2]; n++; }
    r /= n; g /= n; b /= n;
    if (g > 165 && g > r + 45 && g > b + 30 && Math.abs(r - fr) < 90 && Math.abs(b - fb) < 90) return i / fps;
  }
  return null;
}

// Find the first source frame (from startVt) that actually has page content,
// skipping a leading near-uniform-white blank/spinner frame (the app's reload
// "loading" state that `record start` always produces). Capped so a genuinely
// pale screen is never over-trimmed.
async function firstContentVt(dir, frames, fps, startVt, capSec) {
  const probe = createCanvas(32, 32);
  const pctx = probe.getContext("2d");
  const start = clamp(Math.round(startVt * fps), 0, frames.length - 1);
  const end = Math.min(frames.length - 1, start + Math.round(capSec * fps));
  for (let i = start; i <= end; i++) {
    const img = await loadImage(path.join(dir, frames[i]));
    pctx.clearRect(0, 0, 32, 32);
    pctx.drawImage(img, 0, 0, img.width, img.height, 0, 0, 32, 32);
    const d = pctx.getImageData(0, 0, 32, 32).data;
    let sum = 0, sum2 = 0, n = 0;
    for (let p = 0; p < d.length; p += 4) {
      const l = (d[p] + d[p + 1] + d[p + 2]) / 3;
      sum += l; sum2 += l * l; n++;
    }
    const mean = sum / n, sd = Math.sqrt(Math.max(0, sum2 / n - mean * mean));
    if (!(mean > 244 && sd < 16)) return i / fps; // has real content
  }
  return startVt;
}

function makeFrameLoader(dir, frames) {
  const cache = new Map();
  return async (idx) => {
    idx = clamp(idx, 0, frames.length - 1);
    if (cache.has(idx)) return cache.get(idx);
    const img = await loadImage(path.join(dir, frames[idx]));
    cache.set(idx, img);
    if (cache.size > 6) cache.delete(cache.keys().next().value);
    return img;
  };
}

function writeChapters(chapters, remapForward, totalOut, introOffset, file) {
  if (!chapters.length) return false;
  const ms = (s) => Math.round((introOffset + s) * 1000);
  const sorted = chapters.map((c) => ({ start: remapForward(c.vt), title: c.title })).sort((a, b) => a.start - b.start);
  let out = ";FFMETADATA1\n";
  for (let i = 0; i < sorted.length; i++) {
    const start = ms(sorted[i].start);
    const end = i + 1 < sorted.length ? ms(sorted[i + 1].start) : ms(totalOut);
    const title = sorted[i].title.replace(/([=;#\\\n])/g, "\\$1");
    out += `[CHAPTER]\nTIMEBASE=1/1000\nSTART=${start}\nEND=${Math.max(end, start + 1)}\ntitle=${title}\n`;
  }
  fs.writeFileSync(file, out);
  return true;
}

export async function render(name, cwd = process.cwd()) {
  const { state, events } = readState(name, cwd);
  const p = paths(name, cwd);
  const srcFps = state.fps || CONFIG.srcFps;
  const outFps = Number(process.env.SCREENCAST_FPS) || CONFIG.fps;

  if (!fs.existsSync(p.video)) throw new Error(`recording not found: ${p.video}`);

  log("probing video…");
  const { videoW, videoH } = probe(p.video);
  log("extracting frames…");
  const frames = extractFrames(p.video, p.srcFrames, srcFps);
  if (!frames.length) throw new Error("no frames extracted from recording");
  const duration = frames.length / srcFps;

  log("detecting sync flash…");
  const flashVt = await detectFlash(p.srcFrames, frames, srcFps, state.record.flashColor);
  log(flashVt != null ? `flash at ${flashVt.toFixed(2)}s` : "no flash found (wall-clock fallback)");

  const tl = buildTimeline(state, events, { duration, videoW, videoH }, flashVt);
  const { dpr } = tl;

  // Video card placement.
  const OW = CONFIG.out.w, OH = CONFIG.out.h;
  const baseScale = Math.min((OW * CONFIG.videoArea) / videoW, (OH * CONFIG.videoArea) / videoH);
  const rect = { w: videoW * baseScale, h: videoH * baseScale, x: 0, y: 0 };
  rect.x = (OW - rect.w) / 2;
  rect.y = (OH - rect.h) / 2;

  const introOffset = CONFIG.introDur;
  const hasChapters = writeChapters(tl.chapters, tl.remapForward, tl.totalOut, introOffset, p.chapters);

  // ffmpeg encoder fed raw RGBA on stdin.
  const enc = ["-y", "-f", "rawvideo", "-pixel_format", "rgba", "-video_size", `${OW}x${OH}`, "-framerate", String(outFps), "-i", "-"];
  if (hasChapters) enc.push("-i", p.chapters, "-map", "0:v", "-map_metadata", "1");
  enc.push("-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "18", "-preset", "medium", "-movflags", "+faststart", p.output);
  const ff = spawn("ffmpeg", enc, { stdio: ["pipe", "ignore", "pipe"] });
  let ffErr = "";
  ff.stderr.on("data", (d) => (ffErr += d));
  const ffDone = new Promise((res, rej) => ff.on("close", (c) => (c === 0 ? res() : rej(new Error("ffmpeg encode failed:\n" + ffErr.slice(-2000))))));

  const canvas = createCanvas(OW, OH);
  const ctx = canvas.getContext("2d");
  const scratch = createCanvas(OW, OH); // reused for the spotlight punch
  const bg = draw.buildStaticBg(OW, OH, rect);
  const loadFrame = makeFrameLoader(p.srcFrames, frames);

  const totalFrames = Math.max(1, Math.ceil((introOffset + tl.totalOut + CONFIG.outroDur) * outFps));
  const trailSteps = Math.round(CONFIG.trailLength * outFps);
  // Skip a leading blank/spinner frame so the intro fades into real content.
  // Scan from the first real segment's source start (not remapInverse(0), which
  // resolves to the dropped-idle source 0 and would catch the sync flash).
  const srcFloor = await firstContentVt(p.srcFrames, frames, srcFps, tl.contentStartVt, 1.5);
  log(`compositing ${totalFrames} frames (${tl.totalOut.toFixed(1)}s content, source ${duration.toFixed(1)}s, ${outFps}fps)…`);

  for (let j = 0; j < totalFrames; j++) {
    const T = j / outFps;
    let contentT, reveal;
    if (T < introOffset) { contentT = 0; reveal = easeOutCubic(T / introOffset); }
    else if (T <= introOffset + tl.totalOut) { contentT = T - introOffset; reveal = 1; }
    else { contentT = tl.totalOut; reveal = 1 - easeOutCubic((T - introOffset - tl.totalOut) / CONFIG.outroDur); }

    const srcVt = Math.max(tl.remapInverse(contentT), srcFloor);
    const img = await loadFrame(Math.round(srcVt * srcFps));

    const zoom = tl.zoomAt(srcVt) || { cx: state.viewport.w / 2, cy: state.viewport.h / 2, z: 1 };
    const scale = baseScale * zoom.z;
    const scaleFactor = scale * dpr;

    // Clamp focus so the page always covers the card (no background gutter).
    const focusSrc = { x: zoom.cx * dpr, y: zoom.cy * dpr };
    const halfW = rect.w / (2 * scale), halfH = rect.h / (2 * scale);
    focusSrc.x = 2 * halfW >= videoW ? videoW / 2 : clamp(focusSrc.x, halfW, videoW - halfW);
    focusSrc.y = 2 * halfH >= videoH ? videoH / 2 : clamp(focusSrc.y, halfH, videoH - halfH);

    const pageToCanvas = (px, py) => ({
      x: rect.x + rect.w / 2 + scale * (px * dpr - focusSrc.x),
      y: rect.y + rect.h / 2 + scale * (py * dpr - focusSrc.y),
    });
    const holeFor = (box) => {
      const tl2 = pageToCanvas(box.x, box.y);
      const br = pageToCanvas(box.x + box.width, box.y + box.height);
      const pad = CONFIG.highlightPad * scaleFactor;
      return { x: tl2.x - pad, y: tl2.y - pad, w: br.x - tl2.x + 2 * pad, h: br.y - tl2.y + 2 * pad };
    };

    ctx.drawImage(bg, 0, 0);
    draw.drawCardContent(ctx, img, rect, focusSrc, scale);

    // highlights (under the cursor)
    for (const e of tl.effects) {
      if (e.type !== "highlight") continue;
      const dt = srcVt - e.vt;
      if (dt < 0 || dt > e.dur) continue;
      const a = Math.min(clamp01(dt / CONFIG.effectFade), clamp01((e.dur - dt) / CONFIG.effectFade));
      const hole = holeFor(e.box);
      if (e.mode === "ring") draw.drawRing(ctx, rect, hole, a, clamp01(dt / 0.5));
      else draw.drawSpotlight(ctx, scratch, rect, hole, a);
    }

    // cursor + trail + ripple (clipped to the card)
    const cur = tl.cursorAt(srcVt);
    if (cur) {
      ctx.save();
      draw.clipCard(ctx, rect);
      const trail = [];
      for (let k = trailSteps; k >= 0; k--) {
        const c = tl.cursorAt(srcVt - k / outFps);
        if (c) trail.push(pageToCanvas(c.x, c.y));
      }
      draw.drawTrail(ctx, trail);
      let pop = 1;
      for (const c of tl.clicks) {
        const dt = srcVt - c.vt;
        if (dt >= 0 && dt <= CONFIG.rippleDur) {
          const rp = pageToCanvas(c.x, c.y);
          draw.drawRipple(ctx, rp.x, rp.y, dt / CONFIG.rippleDur, scaleFactor);
        }
        if (dt >= 0 && dt <= CONFIG.popDur) {
          const q = dt / CONFIG.popDur;
          pop = q < 0.4 ? 1 - 0.15 * easeOutQuad(q / 0.4) : 0.85 + 0.15 * easeOutCubic((q - 0.4) / 0.6);
        }
      }
      const cc = pageToCanvas(cur.x, cur.y);
      draw.drawCursor(ctx, cc.x, cc.y, CONFIG.cursorScale * pop);
      ctx.restore();
    }

    // notes (callouts, drawn above the cursor, connector may cross the edge)
    for (const e of tl.effects) {
      if (e.type !== "note") continue;
      const dt = srcVt - e.vt;
      if (dt < 0 || dt > e.dur) continue;
      const a = Math.min(clamp01(dt / CONFIG.effectFade), clamp01((e.dur - dt) / CONFIG.effectFade));
      const anchor = pageToCanvas(e.anchor.x, e.anchor.y);
      draw.drawNote(ctx, rect, anchor, e.side, e.text, a, clamp01(dt / CONFIG.effectFade));
    }

    // key chip
    let chip = null;
    for (const k of tl.keys) { const dt = srcVt - k.vt; if (dt >= 0 && dt <= CONFIG.chipDur) chip = { label: k.label, dt }; }
    if (chip) {
      const a = Math.min(clamp01(chip.dt / CONFIG.chipFade), clamp01((CONFIG.chipDur - chip.dt) / CONFIG.chipFade));
      draw.drawKeyChip(ctx, OW, OH, chip.label, a);
    }

    // chapter lower-third
    let chap = null;
    for (const c of tl.chapters) { const dt = srcVt - c.vt; if (dt >= 0 && dt <= CONFIG.chapterDur) chap = { title: c.title, dt }; }
    if (chap) {
      const a = Math.min(clamp01(chap.dt / CONFIG.chapterFade), clamp01((CONFIG.chapterDur - chap.dt) / CONFIG.chapterFade));
      draw.drawChapter(ctx, OW, OH, chap.title, a);
    }

    // intro / outro fade to the backdrop
    if (reveal < 1) {
      ctx.save();
      ctx.globalAlpha = 1 - reveal;
      ctx.fillStyle = CONFIG.gradient[0];
      ctx.fillRect(0, 0, OW, OH);
      ctx.restore();
    }

    const buf = Buffer.from(ctx.getImageData(0, 0, OW, OH).data.buffer);
    if (!ff.stdin.write(buf)) await new Promise((res) => ff.stdin.once("drain", res));
    if (j % 60 === 0) log(`  frame ${j}/${totalFrames}`);
  }

  ff.stdin.end();
  await ffDone;
  if (!process.env.SCREENCAST_KEEP) fs.rmSync(p.srcFrames, { recursive: true, force: true });
  log(`done -> ${p.output}`);
  return p.output;
}
