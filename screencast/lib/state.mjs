// Session state + event-log persistence.
// State lives under <cwd>/.screencast/<name>/ so multiple recordings coexist
// and each `screencast <action>` invocation (a separate process) can append.
import fs from "node:fs";
import path from "node:path";

export function rootDir(cwd = process.cwd()) {
  return path.join(cwd, ".screencast");
}

// A take name becomes a directory under .screencast/ and an .mp4 in cwd, and the
// renderer rm -rf's the frame directory. `path.join` happily normalises "../x"
// out of the session root, so an unchecked name turns a render into a recursive
// delete somewhere else on disk. Keep it to a single plain path segment.
const SAFE_NAME = /^[A-Za-z0-9][A-Za-z0-9._-]*$/;

export function assertSafeName(name) {
  if (typeof name !== "string" || !SAFE_NAME.test(name) || name === "." || name === "..") {
    throw new Error(
      `invalid recording name ${JSON.stringify(name)} — use letters, digits, dot, dash or underscore ` +
        `(no slashes, must start with a letter or digit)`,
    );
  }
  return name;
}

export function sessionDir(name, cwd = process.cwd()) {
  return path.join(rootDir(cwd), assertSafeName(name));
}

const activePtr = (cwd) => path.join(rootDir(cwd), "active");
const lastPtr = (cwd) => path.join(rootDir(cwd), "last");

// The event log can hold typed text, so keep the whole tree owner-only rather
// than inheriting a permissive umask on a shared machine.
const DIR_MODE = 0o700;
const FILE_MODE = 0o600;

export function setActive(name, cwd = process.cwd()) {
  fs.mkdirSync(rootDir(cwd), { recursive: true, mode: DIR_MODE });
  fs.writeFileSync(activePtr(cwd), name, { encoding: "utf8", mode: FILE_MODE });
}

export function getActive(cwd = process.cwd()) {
  try {
    return fs.readFileSync(activePtr(cwd), "utf8").trim() || null;
  } catch {
    return null;
  }
}

// `stop` ends the take, so the active pointer has to go with it — otherwise
// later wrapper commands keep appending events to a finished recording. The
// name moves to `last` so `render` with no argument still finds it.
export function clearActive(cwd = process.cwd()) {
  const name = getActive(cwd);
  if (name) fs.writeFileSync(lastPtr(cwd), name, { encoding: "utf8", mode: FILE_MODE });
  try {
    fs.unlinkSync(activePtr(cwd));
  } catch (e) {
    // Already gone is fine; anything else (permissions, read-only volume) would
    // leave the take active and silently keep collecting events.
    if (e.code !== "ENOENT") throw e;
  }
}

export function getLast(cwd = process.cwd()) {
  try {
    return fs.readFileSync(lastPtr(cwd), "utf8").trim() || null;
  } catch {
    return null;
  }
}

export function initState(name, state, cwd = process.cwd()) {
  const dir = sessionDir(name, cwd);
  fs.mkdirSync(dir, { recursive: true, mode: DIR_MODE });
  fs.writeFileSync(path.join(dir, "state.json"), JSON.stringify(state, null, 2), { mode: FILE_MODE });
  fs.writeFileSync(path.join(dir, "events.jsonl"), "", { mode: FILE_MODE });
  setActive(name, cwd);
}

export function readState(name, cwd = process.cwd()) {
  const dir = sessionDir(name, cwd);
  const state = JSON.parse(fs.readFileSync(path.join(dir, "state.json"), "utf8"));
  const raw = fs.readFileSync(path.join(dir, "events.jsonl"), "utf8");
  const events = raw
    .split("\n")
    .map((l) => l.trim())
    .filter(Boolean)
    .map((l) => JSON.parse(l));
  return { state, events, dir };
}

export function appendEvent(name, event, cwd = process.cwd()) {
  const file = path.join(sessionDir(name, cwd), "events.jsonl");
  fs.appendFileSync(file, JSON.stringify(event) + "\n", { mode: FILE_MODE });
}

export function paths(name, cwd = process.cwd()) {
  const dir = sessionDir(name, cwd);
  return {
    dir,
    video: path.join(dir, "raw.webm"),
    srcFrames: path.join(dir, "src"),
    chapters: path.join(dir, "chapters.ffmeta"),
    output: path.join(cwd, `${name}.mp4`),
  };
}
