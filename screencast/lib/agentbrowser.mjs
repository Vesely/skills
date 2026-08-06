// Thin wrapper around the `agent-browser` CLI.
import { run } from "./util.mjs";

const BIN = process.env.SCREENCAST_AB_BIN || "agent-browser";
// Optional dedicated session so the recording is isolated from other work.
const SESSION = process.env.SCREENCAST_SESSION || "";

function baseArgs() {
  return SESSION ? ["--session", SESSION] : [];
}

// Our own options are appended, except that they must land *before* any `--`
// separator the caller passed: everything after it is literal input, so a
// trailing `--session` would be typed into the page instead of selecting a
// session. Subcommands can be two words (`get box`), so nothing is inserted at
// the front.
export function withSession(args) {
  const base = baseArgs();
  if (!base.length) return args;
  const sep = args.indexOf("--");
  return sep === -1 ? [...args, ...base] : [...args.slice(0, sep), ...base, ...args.slice(sep)];
}

// Run an agent-browser subcommand, inheriting stdio so the agent sees output
// (snapshots, refs, errors). Returns the exit code.
export function passthrough(args) {
  const r = run(BIN, withSession(args), { stdio: "inherit" });
  return r.code;
}

// Run an agent-browser subcommand and capture its output (for internal use).
export function capture(args) {
  return run(BIN, withSession(args));
}

// Resolve the bounding box (viewport CSS px) of a selector or @ref.
// Returns { x, y, width, height } (top-left) or null if unavailable.
export function getBox(selector) {
  const r = capture(["get", "box", selector, "--json"]);
  if (r.code !== 0) return null;
  try {
    const parsed = JSON.parse(r.stdout.trim());
    const b = parsed.data || parsed;
    if (b && typeof b.x === "number" && typeof b.width === "number") return b;
  } catch {
    /* fall through */
  }
  return null;
}

// Read an attribute off a selector or @ref.
// Tri-state on purpose: callers must tell "the element has no such attribute"
// (ok, value null) apart from "the question could not be answered" (not ok), so
// a failed lookup can fail closed instead of reading as a negative answer.
export function getAttr(selector, name) {
  const r = capture(["get", "attr", selector, name, "--json"]);
  if (r.code !== 0) return { ok: false, value: null };
  try {
    const parsed = JSON.parse(r.stdout.trim());
    const v = parsed.data ?? parsed;
    return { ok: true, value: typeof v === "string" ? v : null };
  } catch {
    return { ok: false, value: null };
  }
}

// Center point of a selector's box, or null.
export function centerOf(selector) {
  const b = getBox(selector);
  if (!b) return null;
  return { x: b.x + b.width / 2, y: b.y + b.height / 2 };
}

// Inject a full-viewport colour flash used to align the event log with the
// video timeline. Returns the wall-clock time (ms) the flash was injected.
export function injectFlash([r, g, b]) {
  const js =
    "(()=>{try{var d=document.createElement('div');" +
    "d.setAttribute('data-sc-flash','1');" +
    "d.style.cssText='position:fixed;left:0;top:0;width:100vw;height:100vh;" +
    `z-index:2147483647;background:rgb(${r},${g},${b});pointer-events:none;margin:0';` +
    "(document.body||document.documentElement).appendChild(d);" +
    "setTimeout(function(){try{d.remove()}catch(e){}},220);}catch(e){}})()";
  const t = Date.now();
  capture(["eval", js]);
  return t;
}

export function setViewport(w, h, scale) {
  const args = ["set", "viewport", String(w), String(h)];
  if (scale && scale > 1) args.push(String(scale)); // deviceScaleFactor (retina capture)
  return capture(args);
}

export function recordStart(path, url) {
  const args = ["record", "start", path];
  if (url) args.push(url);
  return capture(args);
}

export function recordStop() {
  return capture(["record", "stop"]);
}
