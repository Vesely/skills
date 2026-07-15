// Session state + event-log persistence.
// State lives under <cwd>/.screencast/<name>/ so multiple recordings coexist
// and each `screencast <action>` invocation (a separate process) can append.
import fs from "node:fs";
import path from "node:path";

export function rootDir(cwd = process.cwd()) {
  return path.join(cwd, ".screencast");
}

export function sessionDir(name, cwd = process.cwd()) {
  return path.join(rootDir(cwd), name);
}

const activePtr = (cwd) => path.join(rootDir(cwd), "active");

export function setActive(name, cwd = process.cwd()) {
  fs.mkdirSync(rootDir(cwd), { recursive: true });
  fs.writeFileSync(activePtr(cwd), name, "utf8");
}

export function getActive(cwd = process.cwd()) {
  try {
    return fs.readFileSync(activePtr(cwd), "utf8").trim() || null;
  } catch {
    return null;
  }
}

export function initState(name, state, cwd = process.cwd()) {
  const dir = sessionDir(name, cwd);
  fs.mkdirSync(dir, { recursive: true });
  fs.writeFileSync(path.join(dir, "state.json"), JSON.stringify(state, null, 2));
  fs.writeFileSync(path.join(dir, "events.jsonl"), "");
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
  fs.appendFileSync(file, JSON.stringify(event) + "\n");
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
