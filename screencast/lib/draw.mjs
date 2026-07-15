// Canvas drawing primitives for the compositor. All text is drawn here (the
// local ffmpeg has no drawtext), so overlays are rendered per frame in canvas.
import { createCanvas } from "@napi-rs/canvas";
import { CONFIG, clamp01, easeOutCubic } from "./util.mjs";

const CHIP_BG = "rgba(17,23,36,0.92)";
const CHIP_BORDER = "rgba(255,255,255,0.16)";
const CHIP_TEXT = "#f4f7ff";
const ACCENT = "130,190,255";

export function roundRectPath(ctx, x, y, w, h, r) {
  r = Math.min(r, w / 2, h / 2);
  ctx.beginPath();
  ctx.moveTo(x + r, y);
  ctx.arcTo(x + w, y, x + w, y + h, r);
  ctx.arcTo(x + w, y + h, x, y + h, r);
  ctx.arcTo(x, y + h, x, y, r);
  ctx.arcTo(x, y, x + w, y, r);
  ctx.closePath();
}

// Build the static backdrop once: gradient, accent glows and the baked card
// shadow. Reused every frame via drawImage (huge per-frame saving).
export function buildStaticBg(W, H, rect) {
  const c = createCanvas(W, H);
  const ctx = c.getContext("2d");
  const g = ctx.createLinearGradient(0, 0, W, H);
  g.addColorStop(0, CONFIG.gradient[0]);
  g.addColorStop(1, CONFIG.gradient[1]);
  ctx.fillStyle = g;
  ctx.fillRect(0, 0, W, H);
  for (const gl of CONFIG.glow) {
    const rad = ctx.createRadialGradient(gl.x * W, gl.y * H, 0, gl.x * W, gl.y * H, gl.r * H);
    rad.addColorStop(0, gl.color);
    rad.addColorStop(1, "rgba(0,0,0,0)");
    ctx.fillStyle = rad;
    ctx.fillRect(0, 0, W, H);
  }
  for (const sh of [CONFIG.shadowAmbient, CONFIG.shadowTight]) {
    ctx.save();
    ctx.shadowColor = `rgba(0,0,0,${sh.alpha})`;
    ctx.shadowBlur = sh.blur;
    ctx.shadowOffsetY = sh.offsetY;
    ctx.fillStyle = "#0b1220";
    roundRectPath(ctx, rect.x, rect.y, rect.w, rect.h, CONFIG.cornerRadius);
    ctx.fill();
    ctx.restore();
  }
  return c;
}

// Draw the (zoomed/panned) page into the rounded card + hairline border.
export function drawCardContent(ctx, img, rect, focusSrc, scale) {
  ctx.save();
  roundRectPath(ctx, rect.x, rect.y, rect.w, rect.h, CONFIG.cornerRadius);
  ctx.clip();
  ctx.translate(rect.x + rect.w / 2, rect.y + rect.h / 2);
  ctx.scale(scale, scale);
  ctx.translate(-focusSrc.x, -focusSrc.y);
  ctx.drawImage(img, 0, 0);
  ctx.restore();

  ctx.save();
  ctx.strokeStyle = "rgba(255,255,255,0.08)";
  ctx.lineWidth = 1.5;
  roundRectPath(ctx, rect.x + 0.75, rect.y + 0.75, rect.w - 1.5, rect.h - 1.5, CONFIG.cornerRadius);
  ctx.stroke();
  ctx.restore();
}

export function clipCard(ctx, rect) {
  roundRectPath(ctx, rect.x, rect.y, rect.w, rect.h, CONFIG.cornerRadius);
  ctx.clip();
}

export function drawTrail(ctx, points) {
  if (points.length < 2) return;
  ctx.save();
  ctx.lineCap = "round";
  ctx.lineJoin = "round";
  for (let i = 1; i < points.length; i++) {
    const a = points[i - 1], b = points[i];
    const t = i / points.length;
    if (Math.hypot(b.x - a.x, b.y - a.y) > 90) continue;
    ctx.strokeStyle = `rgba(150,195,255,${0.14 * t})`;
    ctx.lineWidth = 6 * t;
    ctx.beginPath();
    ctx.moveTo(a.x, a.y);
    ctx.lineTo(b.x, b.y);
    ctx.stroke();
  }
  ctx.restore();
}

export function drawCursor(ctx, x, y, scale) {
  const pts = [
    [0, 0], [0, 18], [4.8, 13.6], [8, 20.8], [11, 19.4], [7.8, 12.4], [14, 12.2],
  ];
  ctx.save();
  ctx.translate(x, y);
  ctx.scale(scale, scale);
  ctx.shadowColor = "rgba(0,0,0,0.45)";
  ctx.shadowBlur = 6;
  ctx.shadowOffsetY = 2;
  ctx.beginPath();
  ctx.moveTo(pts[0][0], pts[0][1]);
  for (const p of pts.slice(1)) ctx.lineTo(p[0], p[1]);
  ctx.closePath();
  ctx.fillStyle = "#ffffff";
  ctx.fill();
  ctx.shadowColor = "transparent";
  ctx.lineWidth = 1.4;
  ctx.strokeStyle = "rgba(20,20,25,0.9)";
  ctx.stroke();
  ctx.restore();
}

export function drawRipple(ctx, x, y, progress, scaleFactor) {
  const p = clamp01(progress);
  const r = CONFIG.rippleRadius * scaleFactor * easeOutCubic(p);
  const alpha = (1 - p) * (1 - p) * 0.5;
  ctx.save();
  ctx.beginPath();
  ctx.arc(x, y, r, 0, Math.PI * 2);
  ctx.strokeStyle = `rgba(${ACCENT},${alpha})`;
  ctx.lineWidth = 3.5;
  ctx.stroke();
  ctx.restore();
}

// Spotlight: dim the card, punch a hole over the element (via a scratch layer
// so we don't depend on even-odd), then stroke a glowing outline.
export function drawSpotlight(ctx, scratch, rect, hole, alpha) {
  const sctx = scratch.getContext("2d");
  sctx.clearRect(0, 0, scratch.width, scratch.height);
  sctx.save();
  roundRectPath(sctx, rect.x, rect.y, rect.w, rect.h, CONFIG.cornerRadius);
  sctx.clip();
  sctx.fillStyle = `rgba(4,8,16,${CONFIG.spotlightAlpha * alpha})`;
  sctx.fillRect(rect.x, rect.y, rect.w, rect.h);
  sctx.globalCompositeOperation = "destination-out";
  roundRectPath(sctx, hole.x, hole.y, hole.w, hole.h, 10);
  sctx.fill();
  sctx.restore();
  ctx.drawImage(scratch, 0, 0);
  drawOutline(ctx, rect, hole, alpha, 0);
}

// Ring highlight: glowing outline + one entrance pulse.
export function drawRing(ctx, rect, hole, alpha, pulse) {
  drawOutline(ctx, rect, hole, alpha, pulse);
}

function drawOutline(ctx, rect, hole, alpha, pulse) {
  ctx.save();
  clipCard(ctx, rect);
  ctx.shadowColor = `rgba(${ACCENT},${0.9 * alpha})`;
  ctx.shadowBlur = 18;
  ctx.strokeStyle = `rgba(${ACCENT},${0.95 * alpha})`;
  ctx.lineWidth = 2.5;
  roundRectPath(ctx, hole.x, hole.y, hole.w, hole.h, 10);
  ctx.stroke();
  if (pulse > 0 && pulse < 1) {
    const grow = 8 * pulse;
    ctx.shadowColor = "transparent";
    ctx.strokeStyle = `rgba(${ACCENT},${(1 - pulse) * (1 - pulse) * 0.8})`;
    ctx.lineWidth = 2;
    roundRectPath(ctx, hole.x - grow, hole.y - grow, hole.w + 2 * grow, hole.h + 2 * grow, 10 + grow);
    ctx.stroke();
  }
  ctx.restore();
}

function wrapText(ctx, text, maxWidth) {
  const words = text.split(/\s+/);
  const lines = [];
  let line = "";
  for (const w of words) {
    const test = line ? line + " " + w : w;
    if (ctx.measureText(test).width > maxWidth && line) { lines.push(line); line = w; }
    else line = test;
  }
  if (line) lines.push(line);
  return lines;
}

// Note callout: a pill (chip visual) on `side` of the anchor, a curved
// connector and an anchor dot. `alpha` fades it; `slide` (0..1) slides it in.
export function drawNote(ctx, rect, anchor, side, text, alpha, slide) {
  ctx.save();
  ctx.globalAlpha = alpha;
  ctx.font = "600 28px -apple-system, 'Helvetica Neue', Arial, sans-serif";
  const lines = wrapText(ctx, text, CONFIG.noteMaxWidth - 44);
  const lineH = 36;
  const padX = 22, padY = 16;
  const tw = Math.max(...lines.map((l) => ctx.measureText(l).width));
  const w = tw + padX * 2;
  const h = lines.length * lineH + padY * 2 - (lineH - 28);

  const gap = CONFIG.noteGap;
  const slideOff = (1 - slide) * 10;
  let x, y;
  if (side === "top") { x = anchor.x - w / 2; y = anchor.y - gap - h + slideOff; }
  else if (side === "bottom") { x = anchor.x - w / 2; y = anchor.y + gap - slideOff; }
  else if (side === "left") { x = anchor.x - gap - w + slideOff; y = anchor.y - h / 2; }
  else { x = anchor.x + gap - slideOff; y = anchor.y - h / 2; }
  x = Math.max(rect.x + 12, Math.min(x, rect.x + rect.w - w - 12));
  y = Math.max(rect.y + 12, Math.min(y, rect.y + rect.h - h - 12));

  // connector: from the pill edge nearest the anchor to the anchor, curved
  const from = { x: clampN(anchor.x, x, x + w), y: clampN(anchor.y, y, y + h) };
  const mx = (from.x + anchor.x) / 2, my = (from.y + anchor.y) / 2;
  ctx.strokeStyle = `rgba(255,255,255,${0.45 * alpha})`;
  ctx.lineWidth = 1.5;
  ctx.beginPath();
  ctx.moveTo(from.x, from.y);
  ctx.quadraticCurveTo(mx, my - 10, anchor.x, anchor.y);
  ctx.stroke();
  ctx.beginPath();
  ctx.arc(anchor.x, anchor.y, 5, 0, Math.PI * 2);
  ctx.fillStyle = `rgba(${ACCENT},${0.95 * alpha})`;
  ctx.fill();

  // pill
  ctx.shadowColor = "rgba(0,0,0,0.4)";
  ctx.shadowBlur = 18;
  ctx.shadowOffsetY = 6;
  roundRectPath(ctx, x, y, w, h, 14);
  ctx.fillStyle = CHIP_BG;
  ctx.fill();
  ctx.shadowColor = "transparent";
  ctx.lineWidth = 1.5;
  ctx.strokeStyle = CHIP_BORDER;
  roundRectPath(ctx, x, y, w, h, 14);
  ctx.stroke();
  ctx.fillStyle = CHIP_TEXT;
  ctx.textBaseline = "middle";
  lines.forEach((l, i) => ctx.fillText(l, x + padX, y + padY + lineH / 2 + i * lineH - 2));
  ctx.restore();
}

const clampN = (v, lo, hi) => Math.max(lo, Math.min(hi, v));

export function drawKeyChip(ctx, W, H, label, alpha) {
  if (!label) return;
  const text = label.length > 40 ? label.slice(0, 39) + "…" : label;
  ctx.save();
  ctx.globalAlpha = alpha;
  ctx.font = "600 34px -apple-system, 'Helvetica Neue', Arial, sans-serif";
  const tw = ctx.measureText(text).width;
  const padX = 26, w = tw + padX * 2, h = 58;
  const x = (W - w) / 2, y = H - 118;
  ctx.shadowColor = "rgba(0,0,0,0.4)";
  ctx.shadowBlur = 18;
  ctx.shadowOffsetY = 6;
  roundRectPath(ctx, x, y, w, h, 14);
  ctx.fillStyle = CHIP_BG;
  ctx.fill();
  ctx.shadowColor = "transparent";
  ctx.lineWidth = 1.5;
  ctx.strokeStyle = CHIP_BORDER;
  roundRectPath(ctx, x, y, w, h, 14);
  ctx.stroke();
  ctx.fillStyle = CHIP_TEXT;
  ctx.textBaseline = "middle";
  ctx.fillText(text, x + padX, y + h / 2 + 1);
  ctx.restore();
}

export function drawChapter(ctx, W, H, title, alpha) {
  if (!title) return;
  ctx.save();
  ctx.globalAlpha = alpha;
  ctx.font = "600 30px -apple-system, 'Helvetica Neue', Arial, sans-serif";
  const tw = ctx.measureText(title).width;
  const padL = 22, padR = 26, dot = 10;
  const w = padL + dot + 14 + tw + padR, h = 52;
  const x = 64, y = 56;
  ctx.shadowColor = "rgba(0,0,0,0.4)";
  ctx.shadowBlur = 18;
  ctx.shadowOffsetY = 6;
  roundRectPath(ctx, x, y, w, h, 12);
  ctx.fillStyle = "rgba(17,23,36,0.9)";
  ctx.fill();
  ctx.shadowColor = "transparent";
  ctx.beginPath();
  ctx.arc(x + padL + dot / 2, y + h / 2, dot / 2, 0, Math.PI * 2);
  ctx.fillStyle = "#48d597";
  ctx.fill();
  ctx.fillStyle = CHIP_TEXT;
  ctx.textBaseline = "middle";
  ctx.fillText(title, x + padL + dot + 14, y + h / 2 + 1);
  ctx.restore();
}
