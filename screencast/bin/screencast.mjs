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
import path from "node:path";
import { fileURLToPath } from "node:url";
import { CONFIG, run, log } from "../lib/util.mjs";
import * as ab from "../lib/agentbrowser.mjs";
import * as state from "../lib/state.mjs";

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

async function ensureDeps() {
  try {
    await import("@napi-rs/canvas");
    return;
  } catch {
    log("installing @napi-rs/canvas (first run)…");
    const r = run("npm", ["install", "--prefix", SKILL_ROOT, "--no-audit", "--no-fund", "@napi-rs/canvas"], {
      stdio: "inherit",
    });
    if (r.code !== 0) throw new Error("failed to install @napi-rs/canvas");
  }
}

function doStart(args) {
  const name = args[0];
  const url = args[1];
  if (!name) return fail("start needs a <name>: screencast start demo [url]");

  const p = state.paths(name);
  require_mkdir(p.dir);

  ab.setViewport(CONFIG.viewport.w, CONFIG.viewport.h, CONFIG.captureScale);
  const rec = ab.recordStart(p.video, url);
  if (rec.code !== 0) return fail("agent-browser record start failed:\n" + rec.stderr);
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

function doPassthrough(cmd, args) {
  const active = state.getActive();
  const loggable = active && LOGGABLE.has(cmd);

  // Resolve the target box BEFORE the action (the element may change after).
  let box = null;
  if (loggable && args[0] && !["press", "keyboard"].includes(cmd)) {
    box = ab.getBox(args[0]);
  }

  const t = Date.now(); // stamp at dispatch, so the effect lines up with the click
  const code = ab.passthrough([cmd, ...args]);
  if (!loggable || code !== 0) return process.exit(code);

  let ev = null;
  if (cmd === "click" || cmd === "dblclick" || cmd === "check" || cmd === "uncheck" || cmd === "select") {
    ev = { t, type: "click", target: args[0] };
  } else if (cmd === "hover") {
    ev = { t, type: "move", target: args[0] };
  } else if (cmd === "type" || cmd === "fill") {
    ev = { t, type: "keys", text: args.slice(1).join(" "), target: args[0] };
  } else if (cmd === "press") {
    ev = { t, type: "key", key: args[0] };
  } else if (cmd === "keyboard") {
    ev = { t, type: "keys", text: args.slice(1).join(" ") };
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

function doHighlight(args) {
  const active = state.getActive();
  if (!active) return fail("no active recording");
  const { pos, flags } = parseArgs(args);
  const sel = pos[0];
  if (!sel) return fail("highlight needs a selector: screencast highlight @e5 [dur] [--mode spotlight|ring] [--no-zoom]");
  const box = ab.getBox(sel);
  if (!box) return fail(`could not resolve element box for ${sel}`);
  const dur = Number(pos[1]) || 2.5;
  const ev = { t: Date.now(), type: "highlight", box, dur, mode: flags.mode === "ring" ? "ring" : "spotlight" };
  if (flags["no-zoom"]) ev.zoom = false;
  state.appendEvent(active, ev);
  ab.passthrough(["wait", String(Math.round(dur * 1000))]); // hold the element on screen
  log(`highlight ${sel} (${ev.mode}, ${dur}s)`);
}

function doNote(args) {
  const active = state.getActive();
  if (!active) return fail("no active recording");
  const { pos, flags } = parseArgs(args);
  const text = pos[0];
  if (!text) return fail('note needs text: screencast note "Click here" @e5 [dur] [--side auto] [--zoom]');
  const ev = { t: Date.now(), type: "note", text, dur: 3, side: flags.side || "auto" };
  // remaining positionals: a selector and/or a duration
  for (const x of pos.slice(1)) {
    if (!isNaN(Number(x))) ev.dur = Number(x);
    else ev.box = ab.getBox(x);
  }
  if (flags.at) {
    const [x, y] = String(flags.at).split(",").map(Number);
    if (!isNaN(x) && !isNaN(y)) ev.at = { x, y };
  }
  if (flags.zoom) ev.zoom = true;
  if (!ev.box && !ev.at) return fail("note needs a target: a selector or --at x,y");
  state.appendEvent(active, ev);
  ab.passthrough(["wait", String(Math.round(ev.dur * 1000))]);
  log(`note "${text.slice(0, 40)}" (${ev.dur}s)`);
}

async function doStop() {
  const active = state.getActive();
  if (!active) return fail("no active recording to stop");
  ab.recordStop();
  log(`stopped "${active}", rendering…`);
  await ensureDeps();
  const { render } = await import("../lib/render.mjs");
  const out = await render(active);
  process.stdout.write(`\n${out}\n`);
}

async function doRender(args) {
  const name = args[0] || state.getActive();
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
  run("mkdir", ["-p", dir]);
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
