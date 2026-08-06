// Regressions for the zoom/trim timeline, argument handling and session state.
// Run with: npm test
//
// Assertions here are deliberately exact. A loose assertion ("still zoomed",
// "roughly there") passes against the very bugs these cover, so each test states
// the number it expects and where that number comes from.
import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";

import { buildTimeline } from "../lib/timeline.mjs";
import { CONFIG } from "../lib/util.mjs";
import { splitPrivateArgs, effectDur } from "../lib/args.mjs";
import * as state from "../lib/state.mjs";

const T0 = 1_000_000;
const box = (x, y, w = 120, h = 40) => ({ x, y, width: w, height: h });
const centerOf = (b) => ({ x: b.x + b.width / 2, y: b.y + b.height / 2 });

// The flash sits at video time 0, so event time == wall offset in seconds.
const timeline = (duration, events) =>
  buildTimeline(
    { viewport: { w: 1280, h: 720 }, record: { startWall: T0, flashWall: T0 }, fps: 30 },
    events,
    { duration, videoW: 1280, videoH: 720 },
    0,
  );

const click = (sec, b) => ({ t: T0 + sec * 1000, type: "click", target: "@e", box: b });
const highlight = (sec, dur, b) => ({ t: T0 + sec * 1000, type: "highlight", dur, box: b });

const near = (a, b, eps = 1e-6) => Math.abs(a - b) < eps;

// --- zoom rhythm ---------------------------------------------------------

test("camera punches in, returns exactly to 1x, punches in again", () => {
  const tl = timeline(12, [click(1, box(100, 100)), click(6, box(900, 600))]);
  assert.ok(tl.zoomAt(1).z > 1.5, "zoomed in for the first click");
  // Exact 1.0, not "close to 1": a timeline that merely eases toward a lower
  // zoom, or parks at the previous focus, fails here.
  const rest = tl.zoomAt(4);
  assert.ok(near(rest.z, 1), `expected exactly 1x between actions, got ${rest.z}`);
  assert.ok(near(rest.cx, 640) && near(rest.cy, 360), "pulled back to the frame centre");
  assert.ok(tl.zoomAt(6).z > 1.5, "zoomed in again for the second click");
});

test("rapid actions never return to 1x between them", () => {
  // 1s apart, far under the ~2.85s an out-and-back needs at default timings.
  const tl = timeline(12, [click(1, box(100, 100)), click(2, box(140, 120)), click(3, box(180, 140))]);
  for (let t = 1; t <= 3; t += 0.1) {
    assert.ok(tl.zoomAt(t).z > 1.01, `camera dropped to 1x at ${t.toFixed(1)}s — that is the strobe`);
  }
});

test("the pull-back appears exactly at the documented gap, and not one step below it", () => {
  // A rest needs zoomHold + zoomOutTime + zoomInTime + zoomRestMin between two
  // actions — 2.85s at the defaults, the number SKILL.md quotes. The comparison
  // runs in integer milliseconds, so the boundary itself must be reachable.
  const gap = CONFIG.zoomHold + CONFIG.zoomOutTime + CONFIG.zoomInTime + CONFIG.zoomRestMin;
  assert.ok(near(gap, 2.85), `defaults changed: the documented 2.85s gap is now ${gap}`);
  const restVt = 1 + CONFIG.zoomHold + CONFIG.zoomOutTime;

  const exactly = timeline(12, [click(1, box(100, 100)), click(1 + gap, box(900, 600))]);
  assert.ok(near(exactly.zoomAt(restVt).z, 1), "at exactly the boundary the camera does pull back");

  const justUnder = timeline(12, [click(1, box(100, 100)), click(1 + gap - 0.01, box(900, 600))]);
  assert.ok(justUnder.zoomAt(restVt).z > 1.01, "10ms under the boundary it stays pushed in");
});

test("an effect keeps the camera perfectly still until it ends", () => {
  const b = box(400, 300);
  const c = centerOf(b);
  const tl = timeline(12, [highlight(1, 2.5, b)]);
  // Frozen on the element for the whole 1.0-3.5s effect: identical values, not
  // just "still zoomed". Drifting toward the pull-back early fails this.
  const ref = tl.zoomAt(1.0);
  assert.ok(near(ref.cx, c.x) && near(ref.cy, c.y), "framed on the highlighted element");
  for (const t of [1.5, 2.0, 2.5, 3.0, 3.49]) {
    const z = tl.zoomAt(t);
    assert.ok(near(z.cx, ref.cx) && near(z.cy, ref.cy) && near(z.z, ref.z), `camera moved at ${t}s, before the effect ended`);
  }
  // zoomOutTime after the effect ends it must be all the way back.
  assert.ok(near(tl.zoomAt(3.5 + CONFIG.zoomOutTime).z, 1), "back to exactly 1x once the effect is over");
});

test("a later action overrides an unfinished effect, arriving on time and without a cut", () => {
  // Highlight runs 1.0-3.5s, but a click lands at 3.0s. The camera must be on
  // the click when it fires; the hold has to yield rather than hard-cut.
  const target = box(900, 600, 60, 20);
  const tl = timeline(12, [highlight(1, 2.5, box(400, 300)), click(3, target)]);
  const at = (t) => tl.zoomAt(t).cx;

  assert.ok(near(at(3.0), centerOf(target).x), "arrived at the click target exactly when it fires");
  // Movement must have started before 3.0 — an implementation that holds until
  // holdUntil and then jumps would sit at 460 right up to the click.
  assert.ok(at(2.7) > 460 + 1, "the pan has begun before the click, so there is no jump cut");
  // ...and it must be gradual.
  const xs = [2.5, 2.6, 2.7, 2.8, 2.9, 3.0].map(at);
  for (let i = 1; i < xs.length; i++) {
    assert.ok(xs[i] >= xs[i - 1] - 1e-6, "camera travels monotonically toward the target");
    assert.ok(xs[i] - xs[i - 1] < 300, "no single-frame jump");
  }
});

test("focus points sharing an instant keep the longest hold", () => {
  const b = box(400, 300);
  // A click and a 2.5s highlight at the same moment. If the collapse kept the
  // click (holdUntil 0) the camera would rest at 1.0 + zoomHold + zoomOutTime
  // = 2.75s; keeping the longest hold pushes that to 3.5 + zoomOutTime.
  const tl = timeline(12, [highlight(1, 2.5, b), click(1, b)]);
  assert.ok(tl.zoomAt(2.8).z > 1.01, "still framed past the click-only rest time — the longer hold won");
  assert.ok(near(tl.zoomAt(3.5 + CONFIG.zoomOutTime).z, 1), "and it does end after the effect");
});

test("an effect near the end of a take is not cut short by the closing pull-back", () => {
  // Recording ends at 4.0s; the effect runs 1.0-3.5s, so the proper rest (4.4s)
  // does not fit. The tail must not start easing out at 3.3s instead.
  const tl = timeline(4.0, [highlight(1, 2.5, box(400, 300))]);
  const ref = tl.zoomAt(1.5).z;
  for (const t of [3.0, 3.3, 3.49]) {
    assert.ok(near(tl.zoomAt(t).z, ref), `camera began pulling back at ${t}s, before the effect ended`);
  }
});

// --- idle trim -----------------------------------------------------------

test("output never runs past the end of the recording", () => {
  // An action at 1.0s puts its rest at 2.75s, whose keep interval would reach
  // 3.25s — past this 2.8s source.
  const tl = timeline(2.8, [click(1, box(100, 100, 80, 30))]);
  assert.ok(tl.totalOut <= 2.8 + 1e-9, `output ${tl.totalOut} longer than the 2.8s source`);
  // The decisive one: every output frame must map to a frame that exists.
  for (let o = 0; o <= tl.totalOut; o += 0.05) {
    assert.ok(tl.remapInverse(o) <= 2.8 + 1e-9, `output ${o.toFixed(2)}s maps past the end of the source`);
  }
});

// --- argument handling ---------------------------------------------------

test("--private is consumed for typing commands only", () => {
  const typed = splitPrivateArgs("type", ["@e1", "--private", "secret"]);
  assert.equal(typed.priv, true);
  assert.deepEqual(typed.passArgs, ["@e1", "secret"], "agent-browser never sees our flag");
  assert.deepEqual(typed.logArgs, ["@e1", "secret"]);

  // `click` has no text to redact, so the token is somebody else's argument.
  const clicked = splitPrivateArgs("click", ["@e1", "--private"]);
  assert.equal(clicked.priv, false);
  assert.deepEqual(clicked.passArgs, ["@e1", "--private"], "passed through untouched");
});

test("a `--` separator protects literal values and survives to agent-browser", () => {
  const t = splitPrivateArgs("type", ["@e1", "--", "--private"]);
  assert.equal(t.priv, false, "after -- it is a value, not our flag");
  assert.deepEqual(t.passArgs, ["@e1", "--", "--private"], "separator forwarded, or --json would be re-read as an option");
  assert.deepEqual(t.logArgs, ["@e1", "--private"], "the log records the value, not the separator");

  const both = splitPrivateArgs("type", ["@e1", "--private", "--", "--json"]);
  assert.equal(both.priv, true, "a flag before -- still counts");
  assert.deepEqual(both.passArgs, ["@e1", "--", "--json"]);
  assert.deepEqual(both.logArgs, ["@e1", "--json"]);
});

test("a session option is never appended after the `--` separator", async () => {
  // Appended at the end it would land after `--` and be typed into the page
  // instead of selecting a session.
  process.env.SCREENCAST_SESSION = "demo";
  const { withSession } = await import(`../lib/agentbrowser.mjs?session-test=${Date.now()}`);
  try {
    const out = withSession(["type", "@e1", "--", "--json"]);
    assert.deepEqual(out, ["type", "@e1", "--session", "demo", "--", "--json"]);
    // Without a separator the option still goes at the end, where two-word
    // subcommands like `get box` expect it.
    assert.deepEqual(withSession(["get", "box", "@e1", "--json"]), ["get", "box", "@e1", "--json", "--session", "demo"]);
  } finally {
    delete process.env.SCREENCAST_SESSION;
  }
});

test("effect durations reject everything that is not a positive finite number", () => {
  assert.equal(effectDur(undefined, 2.5), 2.5, "absent falls back");
  assert.equal(effectDur("", 2.5), 2.5);
  assert.equal(effectDur("3", 2.5), 3);
  for (const bad of ["0", "-3", "abc", "Infinity", "-Infinity", "NaN"]) {
    assert.equal(effectDur(bad, 2.5), null, `rejected ${bad}`);
  }
});

// --- session state -------------------------------------------------------

function inTempCwd(fn) {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "screencast-test-"));
  try {
    fn(dir);
  } finally {
    fs.rmSync(dir, { recursive: true, force: true });
  }
}

test("stop retires the active take but render can still find it", () => {
  inTempCwd((cwd) => {
    state.initState("demo", { name: "demo" }, cwd);
    assert.equal(state.getActive(cwd), "demo");
    state.clearActive(cwd);
    assert.equal(state.getActive(cwd), null, "nothing left to append to");
    assert.equal(state.getLast(cwd), "demo", "render with no name still resolves");
    // Clearing twice is not an error; the pointer is simply gone.
    state.clearActive(cwd);
    assert.equal(state.getLast(cwd), "demo");
  });
});

test("a take name cannot escape the session directory", () => {
  for (const bad of ["../project", "a/b", "..", ".", "", "-lead", "a\\b", "x/../../y"]) {
    assert.throws(() => state.assertSafeName(bad), /invalid recording name/, `rejected ${JSON.stringify(bad)}`);
  }
  for (const good of ["demo", "my-demo_2", "v1.2"]) {
    assert.equal(state.assertSafeName(good), good);
  }
});

test("every session path stays under .screencast", () => {
  inTempCwd((cwd) => {
    const root = path.join(cwd, ".screencast");
    assert.throws(() => state.paths("../escape", cwd), /invalid recording name/);
    const p = state.paths("demo", cwd);
    assert.ok(p.srcFrames.startsWith(root + path.sep), "frame directory (which render rm -rf's) stays contained");
    assert.ok(p.video.startsWith(root + path.sep));
  });
});
