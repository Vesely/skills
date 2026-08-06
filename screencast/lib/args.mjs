// Pure argument helpers, kept out of bin/ so they can be tested without running
// the CLI (which dispatches and exits on import).

// Commands whose text ends up in the event log and the keycast overlay, and for
// which --private therefore means something.
export const TYPING = ["type", "fill", "keyboard"];

// Split a passthrough invocation into what agent-browser should run and what the
// event log should record.
//
// --private is ours and must never reach agent-browser. Everything after a `--`
// separator is a literal value, so a flag-looking string can still be typed. The
// separator is forwarded downstream — swallowing it would let a literal such as
// `--json` be re-read as an option — but it is not part of the logged value.
export function splitPrivateArgs(cmd, args) {
  const applies = TYPING.includes(cmd);
  const sep = args.indexOf("--");
  const head = sep === -1 ? args : args.slice(0, sep);
  const literal = sep === -1 ? [] : args.slice(sep + 1);
  const priv = applies && head.includes("--private");
  const cleanHead = priv ? head.filter((a) => a !== "--private") : head;
  return {
    priv,
    passArgs: sep === -1 ? cleanHead : [...cleanHead, "--", ...literal],
    logArgs: [...cleanHead, ...literal],
  };
}

// An effect duration drives both a real `wait` and a timeline span. Zero,
// negative and non-finite values sail through `Number(x) || fallback` and then
// produce a nonsensical hold, so validate rather than coerce. Returns null when
// the caller supplied something unusable.
export function effectDur(raw, fallback) {
  if (raw === undefined || raw === "") return fallback;
  const n = Number(raw);
  if (!Number.isFinite(n) || n <= 0) return null;
  return n;
}
