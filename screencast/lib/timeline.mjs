// Builds the effect timeline from the recorded event log:
//  - converts wall-clock events to video-time (anchored on the sync flash)
//  - derives element-fit zoom/pan keyframes, the cursor path, ripples, key
//    chips, chapters, highlights and notes
//  - computes the idle-trim remap (idle spans freeze on the last frame, then cut)
import { CONFIG, clamp, lerp, smootherstep, easeInOut } from "./util.mjs";

function prettyKey(key) {
  return String(key)
    .split("+")
    .map((k) => {
      const m = {
        Control: "Ctrl", Meta: "⌘", Alt: "⌥", Shift: "⇧",
        Enter: "Enter", Escape: "Esc", ArrowUp: "↑", ArrowDown: "↓",
        ArrowLeft: "←", ArrowRight: "→", Backspace: "⌫", Tab: "Tab", " ": "Space",
      };
      if (m[k]) return m[k];
      return k.length === 1 ? k.toUpperCase() : k;
    })
    .join(" ");
}

// Zoom factor that makes a (padded) element fill ~zoomTargetFrac of the frame,
// fitting in both axes, clamped to a sane range. Works in viewport space.
function fitZoom(box) {
  if (!box || !(box.width > 0) || !(box.height > 0)) return 1.5;
  const padW = box.width + 2 * CONFIG.highlightPad;
  const padH = box.height + 2 * CONFIG.highlightPad;
  const zW = (CONFIG.zoomTargetFrac * CONFIG.viewport.w) / padW;
  const zH = (CONFIG.zoomTargetFrac * CONFIG.viewport.h) / padH;
  return clamp(Math.min(zW, zH), CONFIG.zoomMin, CONFIG.zoomMax);
}

function boxCenter(box) {
  return { x: box.x + box.width / 2, y: box.y + box.height / 2 };
}

// Resolve a note's anchor point + side (which edge the label sits off).
function resolveNote(e) {
  const vp = CONFIG.viewport;
  let side = e.side && e.side !== "auto" ? e.side : null;
  let box = e.box;
  const ref = box ? boxCenter(box) : e.at;
  if (!side) {
    const room = box
      ? { top: box.y, bottom: vp.h - (box.y + box.height), left: box.x, right: vp.w - (box.x + box.width) }
      : { top: ref.y, bottom: vp.h - ref.y, left: ref.x, right: vp.w - ref.x };
    side = Object.entries(room).sort((a, b) => b[1] - a[1])[0][0];
  }
  let anchor;
  if (box) {
    if (side === "top") anchor = { x: box.x + box.width / 2, y: box.y };
    else if (side === "bottom") anchor = { x: box.x + box.width / 2, y: box.y + box.height };
    else if (side === "left") anchor = { x: box.x, y: box.y + box.height / 2 };
    else anchor = { x: box.x + box.width, y: box.y + box.height / 2 };
  } else {
    anchor = ref;
  }
  return { side, anchor };
}

function mergeIntervals(intervals) {
  const sorted = intervals.filter((iv) => iv[1] > iv[0]).sort((a, b) => a[0] - b[0]);
  const out = [];
  for (const iv of sorted) {
    const last = out[out.length - 1];
    if (last && iv[0] <= last[1]) last[1] = Math.max(last[1], iv[1]);
    else out.push([...iv]);
  }
  return out;
}

// Keep activity spans full; collapse idle gaps, which FREEZE on their first
// frame (then hard-cut) rather than fast-forwarding the page.
function buildTrim(keepIntervals, duration) {
  const keeps = mergeIntervals(keepIntervals);
  const segments = [];
  let cursor = 0;
  const pushIdle = (a, b) => {
    if (b - a <= 1e-3) return;
    segments.push({ srcStart: a, srcEnd: b, idle: true });
  };
  for (const [ks, ke] of keeps) {
    if (ks > cursor) pushIdle(cursor, ks);
    segments.push({ srcStart: ks, srcEnd: ke, idle: false });
    cursor = ke;
  }
  if (cursor < duration) pushIdle(cursor, duration);
  if (segments.length === 0) segments.push({ srcStart: 0, srcEnd: duration, idle: false });

  // Drop leading/trailing idle entirely (page-load, settle and post-roll dead
  // time from `record start` reloading the page); keep interior idle capped.
  const firstReal = segments.findIndex((s) => !s.idle);
  const lastReal = firstReal === -1 ? -1 : segments.length - 1 - segments.slice().reverse().findIndex((s) => !s.idle);
  let outAt = 0;
  for (let i = 0; i < segments.length; i++) {
    const s = segments[i];
    const srcLen = s.srcEnd - s.srcStart;
    const edgeIdle = s.idle && firstReal !== -1 && (i < firstReal || i > lastReal);
    s.outLen = edgeIdle ? 0 : s.idle ? Math.min(srcLen, CONFIG.idleKeep) : srcLen;
    s.outStart = outAt;
    s.outEnd = outAt + s.outLen;
    outAt = s.outEnd;
  }
  const totalOut = outAt;

  const remapInverse = (outputT) => {
    for (const s of segments) {
      if (outputT >= s.outStart && outputT <= s.outEnd) {
        if (s.idle) return s.srcStart; // freeze
        const f = s.outLen > 0 ? (outputT - s.outStart) / s.outLen : 0;
        return lerp(s.srcStart, s.srcEnd, f);
      }
    }
    return duration;
  };
  const remapForward = (srcT) => {
    for (const s of segments) {
      if (srcT >= s.srcStart && srcT <= s.srcEnd) {
        if (s.idle) return s.outStart;
        const f = s.srcEnd > s.srcStart ? (srcT - s.srcStart) / (s.srcEnd - s.srcStart) : 0;
        return lerp(s.outStart, s.outEnd, f);
      }
    }
    return totalOut;
  };
  const firstRealSeg = segments.find((s) => !s.idle);
  const contentStartVt = firstRealSeg ? firstRealSeg.srcStart : 0;
  return { totalOut, remapInverse, remapForward, contentStartVt };
}

// Interpolate a keyframe track that holds, then eases to the next keyframe.
// durationFn(a,b) sets the transition length; arriveEarly lands on the target
// that many seconds before its timestamp (cursor dwell before a click).
function makeTrack(keyframes, { durationFn, easer, fields, arriveEarly = 0 }) {
  const kf = keyframes.slice().sort((a, b) => a.vt - b.vt);
  return (vt) => {
    if (kf.length === 0) return null;
    if (vt <= kf[0].vt) return kf[0];
    if (vt >= kf[kf.length - 1].vt) return kf[kf.length - 1];
    let a = kf[0], b = kf[kf.length - 1];
    for (let i = 0; i < kf.length - 1; i++) {
      if (vt >= kf[i].vt && vt <= kf[i + 1].vt) { a = kf[i]; b = kf[i + 1]; break; }
    }
    const arrive = b.vt - arriveEarly;
    const dur = durationFn(a, b);
    const transStart = Math.max(a.vt, arrive - dur);
    if (vt <= transStart) return a;
    if (vt >= arrive) return b;
    const s = easer((vt - transStart) / (arrive - transStart));
    const out = {};
    for (const f of fields) out[f] = lerp(a[f], b[f], s);
    return out;
  };
}

export function buildTimeline(state, events, meta, flashVideoTime) {
  const { duration, videoW, videoH } = meta;
  const dpr = Math.max(1, Math.round(videoW / state.viewport.w)) || 1;

  const { flashWall, startWall } = state.record;
  const toVt = (wall) => {
    const v = flashVideoTime != null
      ? flashVideoTime + (wall - flashWall) / 1000
      : (wall - startWall) / 1000;
    return clamp(v, 0, duration);
  };

  const clicks = [];
  const cursorWaypoints = [];
  const keys = [];
  const chapters = [];
  const effects = [];
  const focusPoints = []; // drives zoom: {vt, cx, cy, z}
  const center = { x: state.viewport.w / 2, y: state.viewport.h / 2 };

  for (const e of events) {
    const vt = toVt(e.t);
    if (e.type === "click") {
      if (e.box) {
        const c = boxCenter(e.box);
        clicks.push({ vt, x: c.x, y: c.y });
        cursorWaypoints.push({ vt, x: c.x, y: c.y });
        focusPoints.push({ vt, cx: c.x, cy: c.y, z: fitZoom(e.box) });
      } else if (typeof e.x === "number") {
        clicks.push({ vt, x: e.x, y: e.y });
        cursorWaypoints.push({ vt, x: e.x, y: e.y });
        focusPoints.push({ vt, cx: e.x, cy: e.y, z: 1.55 });
      }
    } else if (e.type === "move" || e.type === "hover") {
      if (e.box) { const c = boxCenter(e.box); cursorWaypoints.push({ vt, x: c.x, y: c.y }); }
      else if (typeof e.x === "number") cursorWaypoints.push({ vt, x: e.x, y: e.y });
    } else if (e.type === "keys") {
      if (e.box) { const c = boxCenter(e.box); cursorWaypoints.push({ vt, x: c.x, y: c.y }); }
      else if (typeof e.x === "number") cursorWaypoints.push({ vt, x: e.x, y: e.y });
      keys.push({ vt, label: e.text });
    } else if (e.type === "key") {
      keys.push({ vt, label: prettyKey(e.key) });
    } else if (e.type === "chapter") {
      chapters.push({ vt, title: e.title });
    } else if (e.type === "highlight") {
      if (!e.box) continue;
      const dur = e.dur || 2.5;
      effects.push({ type: "highlight", vt, dur, box: e.box, mode: e.mode || "spotlight" });
      if (e.zoom !== false) {
        const c = boxCenter(e.box);
        focusPoints.push({ vt, cx: c.x, cy: c.y, z: fitZoom(e.box) });
      }
    } else if (e.type === "note") {
      const dur = e.dur || 3;
      const { side, anchor } = resolveNote(e);
      effects.push({ type: "note", vt, dur, text: e.text, box: e.box, anchor, side });
      if (e.zoom && e.box) {
        const c = boxCenter(e.box);
        focusPoints.push({ vt, cx: c.x, cy: c.y, z: fitZoom(e.box) });
      }
    }
  }

  // --- Zoom / pan keyframes (unified across clicks + zoom-driving effects) ---
  focusPoints.sort((a, b) => a.vt - b.vt);
  const zoomKf = [{ vt: 0, cx: center.x, cy: center.y, z: 1 }, ...focusPoints];
  const lastAction = Math.max(0, ...clicks.map((c) => c.vt), ...keys.map((k) => k.vt), ...effects.map((e) => e.vt + e.dur));
  const lastFocus = focusPoints.length ? focusPoints[focusPoints.length - 1] : { cx: center.x, cy: center.y };
  zoomKf.push({ vt: Math.min(duration, lastAction + CONFIG.zoomOutTail), cx: lastFocus.cx, cy: lastFocus.cy, z: 1 });
  const zoomAt = makeTrack(zoomKf, {
    durationFn: (a, b) => (b.z >= a.z ? CONFIG.zoomInTime : CONFIG.zoomOutTime),
    easer: smootherstep,
    fields: ["cx", "cy", "z"],
  });

  // --- Cursor path (distance-aware speed, arrives just before the click) ---
  const cursorKf = [{ vt: 0, x: center.x, y: center.y }, ...cursorWaypoints.sort((a, b) => a.vt - b.vt)];
  const cursorAt = makeTrack(cursorKf, {
    durationFn: (a, b) => clamp(CONFIG.cursorMin, CONFIG.cursorMax, 0.25 + Math.hypot(b.x - a.x, b.y - a.y) / 1400),
    easer: easeInOut,
    fields: ["x", "y"],
    arriveEarly: CONFIG.cursorDwell,
  });

  // --- Idle trim (keep intervals around every activity) ---
  const keepIntervals = [];
  for (const e of [...clicks, ...keys, ...chapters, ...cursorWaypoints]) {
    keepIntervals.push([e.vt - CONFIG.keepPre, e.vt + CONFIG.keepPost]);
  }
  for (const e of effects) keepIntervals.push([e.vt - CONFIG.keepPre, e.vt + e.dur + 0.4]);
  keepIntervals.push([Math.max(0, lastAction - 0.1), Math.min(duration, lastAction + CONFIG.zoomOutTail + 0.4)]);
  const trim = buildTrim(keepIntervals, duration);

  return { dpr, videoW, videoH, duration, clicks, keys, chapters, effects, zoomAt, cursorAt, ...trim };
}
