// Shared config, math and small helpers for the screencast skill.
import { spawnSync } from "node:child_process";

// ---------------------------------------------------------------------------
// Tunable configuration. Everything cosmetic lives here so it is easy to tweak.
// ---------------------------------------------------------------------------
export const CONFIG = {
  // Capture
  viewport: { w: 1280, h: 720 }, // browser viewport set before recording
  captureScale: 2, // deviceScaleFactor for recording — 2 = retina supersampling
  // (source captured at viewport*scale, then downsampled: crisp text, no upscale blur)
  flashColor: [0, 255, 136], // sync-flash colour injected at record start (rgb)
  srcFps: 30, // rate the source WebM is decoded/indexed at

  // Output
  fps: 30, // output frame rate (set 60 via SCREENCAST_FPS for silkier motion)
  out: { w: 1920, h: 1080 }, // final canvas size
  videoArea: 0.88, // video occupies at most this fraction of the output box
  cornerRadius: 20, // rounded corners on the video card (output px)

  // Background gradient (two stops, top-left -> bottom-right) + accent glows
  gradient: ["#0b1220", "#223046"],
  glow: [
    { x: 0.24, y: 0.1, r: 0.85, color: "rgba(90,130,255,0.10)" },
    { x: 0.82, y: 0.95, r: 0.8, color: "rgba(150,110,255,0.07)" },
  ],

  // Two-layer shadow behind the video card
  shadowTight: { blur: 26, offsetY: 10, alpha: 0.35 },
  shadowAmbient: { blur: 90, offsetY: 44, alpha: 0.3 },

  // Zoom / pan (element-fit: target element fills ~zoomTargetFrac of the frame)
  zoomTargetFrac: 0.42,
  zoomMin: 1.2,
  zoomMax: 2.1,
  zoomInTime: 0.55, // ease-in when moving to a new focus
  zoomOutTime: 1.05, // slower ease-out (feels deliberate)
  zoomOutTail: 0.8, // seconds after last action before easing back to 1x

  // Cursor
  cursorScale: 1.5,
  cursorMin: 0.3, // min seconds for a cursor move
  cursorMax: 0.85, // max seconds for a long cursor move
  cursorDwell: 0.14, // arrive at the target this long before the click
  trailLength: 0.24, // seconds of cursor history kept as a fading trail

  // Click ripple + cursor pop
  rippleDur: 0.55,
  rippleRadius: 46, // max ripple radius in page px (before output scaling)
  popDur: 0.26, // cursor squeeze duration on click

  // Keystroke overlay
  chipDur: 1.4, // seconds a key chip stays on screen
  chipFade: 0.22,

  // Chapter lower-third
  chapterDur: 2.4,
  chapterFade: 0.4,

  // Element highlight + notes
  highlightPad: 8, // page px padding around a highlighted element box
  spotlightAlpha: 0.5, // darkening of the area outside a spotlight
  effectFade: 0.25, // fade in/out for highlights and notes
  noteMaxWidth: 340, // output px, before wrapping
  noteGap: 70, // output px between the anchor and the note pill

  // Intro / outro (added around the content, never eats content)
  introDur: 0.55,
  outroDur: 0.55,

  // Idle trimming (idle spans freeze on the last frame, then hard-cut)
  keepPre: 0.45, // keep this many seconds before each action
  keepPost: 1.1, // keep this many seconds after each action
  idleKeep: 0.5, // collapse idle gaps down to this many seconds
};

// ---------------------------------------------------------------------------
// Math
// ---------------------------------------------------------------------------
export const clamp = (v, lo, hi) => Math.max(lo, Math.min(hi, v));
export const clamp01 = (v) => clamp(v, 0, 1);
export const lerp = (a, b, t) => a + (b - a) * t;

// Smooth, cinematic easing (zero velocity at both ends).
export const smootherstep = (t) => {
  t = clamp01(t);
  return t * t * t * (t * (t * 6 - 15) + 10);
};
export const easeInOut = (t) => {
  t = clamp01(t);
  return t < 0.5 ? 4 * t * t * t : 1 - Math.pow(-2 * t + 2, 3) / 2;
};
export const easeOutCubic = (t) => 1 - Math.pow(1 - clamp01(t), 3);
export const easeOutQuad = (t) => 1 - (1 - clamp01(t)) * (1 - clamp01(t));

// ---------------------------------------------------------------------------
// Process helpers
// ---------------------------------------------------------------------------
// Run a command, return { code, stdout, stderr }. Never throws.
export function run(cmd, args, opts = {}) {
  const r = spawnSync(cmd, args, {
    encoding: "utf8",
    maxBuffer: 64 * 1024 * 1024,
    ...opts,
  });
  return {
    code: r.status ?? 1,
    stdout: r.stdout || "",
    stderr: r.stderr || "",
    error: r.error,
  };
}

export function log(msg) {
  process.stderr.write(`\x1b[2m[screencast]\x1b[0m ${msg}\n`);
}
