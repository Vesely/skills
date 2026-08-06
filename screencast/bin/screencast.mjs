#!/usr/bin/env node
// screencast — wrap an agent-browser session and turn it into a polished
// product-demo video (auto-zoom, cursor, keystrokes, chapters), fully local.
//
// Usage:
//   screencast start <name> [url]     Set viewport, start recording, drop a sync flash
//   screencast <agent-browser cmd…>   Passthrough to agent-browser + log the action
//   screencast chapter "<title>"      Mark a chapter at the current moment
//   screencast stop                   Stop recording and render <name>.mp4
//   screencast render [name]          Re-render from an existing recording
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { CONFIG, run, log } from "../lib/util.mjs";
import * as ab from "../lib/agentbrowser.mjs";
import * as state from "../lib/state.mjs";
import { splitPrivateArgs, effectDur } from "../lib/args.mjs";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const SKILL_ROOT = path.resolve(__dirname, "..");

const LOGGABLE = new Set([
  "click", "dblclick", "type", "fill", "press",
  "keyboard", "hover", "check", "uncheck", "select",
]);

function usage() {
  process.stdout.write(
    `screencast — polished demo videos from an agent-browser session\n\n` +
      `  screencast start <name> [url]     start recording\n` +
      `  screencast <cmd …>                run an agent-browser command (logged)\n` +
      `  screencast chapter "<title>"      add a chapter marker\n` +
      `  screencast highlight @ref [dur]   spotlight/ring an element  [--mode ring] [--no-zoom]\n` +
      `  screencast note "text" @ref [dur] callout an element/point  [--at x,y] [--side auto] [--zoom]\n` +
      `  screencast stop                   stop + render <name>.mp4\n` +
      `  screencast render [name]          re-render an existing take\n`,
  );
}

const CANVAS = "@napi-rs/canvas";

async function ensureDeps() {
  try {
    await import(CANVAS);
    return;
  } catch {
    // Install the version package.json declares, not whatever is newest.
    // `npm install <name>` resolves to the newest match *and rewrites the range
    // it found*, which both dirties a checked-out skill and silently moves the
    // renderer onto an untested build; `--no-save` plus an explicit spec keeps
    // the declared version the only source of truth.
    const pkg = JSON.parse(fs.readFileSync(path.join(SKILL_ROOT, "package.json"), "utf8"));
    const spec = pkg.dependencies?.[CANVAS];
    if (!spec) throw new Error(`package.json no longer declares ${CANVAS}`);
    log(`installing ${CANVAS}@${spec} (first run)…`);
    const r = run("npm", ["install", "--prefix", SKILL_ROOT, "--no-audit", "--no-fund", "--no-save", `${CANVAS}@${spec}`], {
      stdio: "inherit",
    });
    if (r.code !== 0) throw new Error(`failed to install ${CANVAS}@${spec}`);
  }
}

function doStart(args) {
  const name = args[0];
  const url = args[1];
  if (!name) return fail("start needs a <name>: screencast start demo [url]");

  const p = state.paths(name);
  require_mkdir(p.dir);

  // A silently failed viewport leaves the capture at some other geometry while
  // the timeline still assumes CONFIG.viewport, which misplaces every zoom.
  const vp = ab.setViewport(CONFIG.viewport.w, CONFIG.viewport.h, CONFIG.captureScale);
  if (vp.code !== 0) {
    return fail("agent-browser set viewport failed:\n" + (vp.error?.message || vp.stderr));
  }
  const rec = ab.recordStart(p.video, url);
  if (rec.code !== 0) return fail("agent-browser record start failed:\n" + (rec.error?.message || rec.stderr));
  const startWall = Date.now();
  const flashWall = ab.injectFlash(CONFIG.flashColor);

  state.initState(name, {
    name,
    viewport: { ...CONFIG.viewport },
    fps: CONFIG.fps,
    record: { startWall, flashWall, flashColor: CONFIG.flashColor },
  });

  log(`recording "${name}" -> ${p.video}`);
  process.stdout.write(
    `Recording started. Drive the demo with:\n` +
      `  screencast chapter "Step title"\n` +
      `  screencast click @e3 / screencast type @e5 "text" / screencast press Enter\n` +
      `Then: screencast stop\n`,
  );
}

function doChapter(args) {
  const active = state.getActive();
  if (!active) return fail("no active recording (run: screencast start <name>)");
  const title = args.join(" ").trim();
  if (!title) return fail('chapter needs a title: screencast chapter "Open dashboard"');
  state.appendEvent(active, { t: Date.now(), type: "chapter", title });
  log(`chapter: ${title}`);
}

const SECRET_MASK = "••••••••";

// Typed text is written to events.jsonl and burned into the keycast overlay, so
// a secret typed during a recording ends up in the shipped MP4. Redact when the
// caller says so, or when the field itself declares it is a password.
//
// A lookup that cannot be answered (agent-browser gone, stale ref, malformed
// output) must not read as "not a password" — that is exactly the case where a
// secret would leak. Fail closed and say so, rather than guessing.
function isSecretInput(cmd, target, priv) {
  if (priv) return true;
  if (!target || !["type", "fill"].includes(cmd)) return false;
  const attr = ab.getAttr(target, "type");
  if (!attr.ok) {
    log(`could not read the type of ${target} — redacting this value; pass --private to silence this`);
    return true;
  }
  return (attr.value || "").toLowerCase() === "password";
}

function doPassthrough(cmd, args) {
  const active = state.getActive();
  const loggable = active && LOGGABLE.has(cmd);

  const { priv, passArgs, logArgs } = splitPrivateArgs(cmd, args);

  // Resolve the target box BEFORE the action (the element may change after).
  let box = null;
  if (loggable && logArgs[0] && !["press", "keyboard"].includes(cmd)) {
    box = ab.getBox(logArgs[0]);
  }
  const secret = loggable && isSecretInput(cmd, logArgs[0], priv);

  const t = Date.now(); // stamp at dispatch, so the effect lines up with the click
  const code = ab.passthrough([cmd, ...passArgs]);
  if (!loggable || code !== 0) return process.exit(code);

  let ev = null;
  if (cmd === "click" || cmd === "dblclick" || cmd === "check" || cmd === "uncheck" || cmd === "select") {
    ev = { t, type: "click", target: logArgs[0] };
  } else if (cmd === "hover") {
    ev = { t, type: "move", target: logArgs[0] };
  } else if (cmd === "type" || cmd === "fill") {
    ev = { t, type: "keys", text: secret ? SECRET_MASK : logArgs.slice(1).join(" "), target: logArgs[0], redacted: secret || undefined };
  } else if (cmd === "press") {
    ev = { t, type: "key", key: logArgs[0] };
  } else if (cmd === "keyboard") {
    ev = { t, type: "keys", text: secret ? SECRET_MASK : logArgs.slice(1).join(" "), redacted: secret || undefined };
  }
  if (ev && box) ev.box = box;
  if (ev) state.appendEvent(active, ev);
  process.exit(code);
}

// Split argv into positionals and flags (--k v, --k=v, --flag).
function parseArgs(args) {
  const pos = [];
  const flags = {};
  for (let i = 0; i < args.length; i++) {
    const a = args[i];
    if (a.startsWith("--")) {
      const eq = a.indexOf("=");
      if (eq !== -1) { flags[a.slice(2, eq)] = a.slice(eq + 1); }
      else if (i + 1 < args.length && !args[i + 1].startsWith("--")) { flags[a.slice(2)] = args[++i]; }
      else { flags[a.slice(2)] = true; }
    } else pos.push(a);
  }
  return { pos, flags };
}

// The event is only committed once the hold actually happened: an effect logged
// at full duration that never held leaves the timeline pointing at a moment the
// recording does not contain.
function holdFor(active, ev, label) {
  const r = ab.passthrough(["wait", String(Math.round(ev.dur * 1000))]);
  if (r !== 0) return fail(`could not hold the page for ${ev.dur}s — ${label} not recorded`);
  state.appendEvent(active, ev);
}

function doHighlight(args) {
  const active = state.getActive();
  if (!active) return fail("no active recording");
  const { pos, flags } = parseArgs(args);
  const sel = pos[0];
  if (!sel) return fail("highlight needs a selector: screencast highlight @e5 [dur] [--mode spotlight|ring] [--no-zoom]");
  const box = ab.getBox(sel);
  if (!box) return fail(`could not resolve element box for ${sel}`);
  const dur = effectDur(pos[1], 2.5);
  if (dur === null) return fail(`highlight duration must be a positive number of seconds, got ${pos[1]}`);
  const ev = { t: Date.now(), type: "highlight", box, dur, mode: flags.mode === "ring" ? "ring" : "spotlight" };
  if (flags["no-zoom"]) ev.zoom = false;
  holdFor(active, ev, "highlight");
  log(`highlight ${sel} (${ev.mode}, ${dur}s)`);
}

function doNote(args) {
  const active = state.getActive();
  if (!active) return fail("no active recording");
  const { pos, flags } = parseArgs(args);
  const text = (pos[0] || "").trim();
  if (!text) return fail('note needs text: screencast note "Click here" @e5 [dur] [--side auto] [--zoom]');
  const ev = { t: Date.now(), type: "note", text, dur: 3, side: flags.side || "auto" };
  // remaining positionals: a selector and/or a duration
  for (const x of pos.slice(1)) {
    if (!isNaN(Number(x))) {
      const d = effectDur(x, 3);
      if (d === null) return fail(`note duration must be a positive number of seconds, got ${x}`);
      ev.dur = d;
    } else ev.box = ab.getBox(x);
  }
  if (flags.at) {
    // "x,y" exactly: `,0` parses to 0,0 via Number("") and would silently anchor
    // the callout in the corner instead of telling the caller it was malformed.
    const parts = String(flags.at).split(",");
    const [x, y] = parts.map((v) => (v.trim() === "" ? NaN : Number(v)));
    if (parts.length !== 2 || !Number.isFinite(x) || !Number.isFinite(y)) {
      return fail(`--at needs "x,y" in viewport pixels, got ${JSON.stringify(String(flags.at))}`);
    }
    ev.at = { x, y };
  }
  if (flags.zoom) ev.zoom = true;
  if (!ev.box && !ev.at) return fail("note needs a target: a selector or --at x,y");
  holdFor(active, ev, "note");
  log(`note "${text.slice(0, 40)}" (${ev.dur}s)`);
}

async function doStop() {
  const active = state.getActive();
  if (!active) return fail("no active recording to stop");
  const stopped = ab.recordStop();
  if (stopped.code !== 0) {
    return fail("agent-browser record stop failed:\n" + (stopped.error?.message || stopped.stderr));
  }
  // The take is over the moment the recorder stops: retire the active pointer
  // before rendering, so a render failure cannot leave later commands appending
  // events to a finished recording.
  state.clearActive();
  log(`stopped "${active}", rendering…`);
  await ensureDeps();
  const { render } = await import("../lib/render.mjs");
  const out = await render(active);
  process.stdout.write(`\n${out}\n`);
}

async function doRender(args) {
  const name = args[0] || state.getActive() || state.getLast();
  if (!name) return fail("render needs a <name>");
  await ensureDeps();
  const { render } = await import("../lib/render.mjs");
  const out = await render(name);
  process.stdout.write(`\n${out}\n`);
}

// helpers ------------------------------------------------------------------
function fail(msg) {
  process.stderr.write(`\x1b[31m[screencast] ${msg}\x1b[0m\n`);
  process.exit(1);
}
function require_mkdir(dir) {
  fs.mkdirSync(dir, { recursive: true, mode: 0o700 }); // may hold typed text
}

// main ---------------------------------------------------------------------
const [cmd, ...args] = process.argv.slice(2);
try {
  if (!cmd || cmd === "help" || cmd === "-h" || cmd === "--help") {
    usage();
  } else if (cmd === "start") {
    doStart(args);
  } else if (cmd === "chapter") {
    doChapter(args);
  } else if (cmd === "highlight") {
    doHighlight(args);
  } else if (cmd === "note") {
    doNote(args);
  } else if (cmd === "stop") {
    await doStop();
  } else if (cmd === "render") {
    await doRender(args);
  } else {
    doPassthrough(cmd, args);
  }
} catch (e) {
  fail(e && e.stack ? e.stack : String(e));
}
