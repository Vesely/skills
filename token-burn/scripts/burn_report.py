#!/usr/bin/env python3
"""Analyze recent Claude Code sessions and report where tokens were burned.

Scans ~/.claude/projects/<slug>/<session>.jsonl, sums per-message `usage` for
every assistant turn whose timestamp falls inside the window (default: last 5h),
prices it per model (with cache read/write discounts), and renders a compact
report ranking the heaviest sessions and projects, cache efficiency, and
data-driven optimization tips.

Stdlib only. Outputs a plain-text report to stdout; with --out also writes a
Markdown report (for the cmux markdown viewer). With --json, prints the raw data.
"""

import argparse
import json
import os
import re
import sys
from datetime import datetime, timedelta, timezone

# --- Pricing -----------------------------------------------------------------
# USD per 1M tokens, as (input, output). Cache pricing is derived from input:
#   cache read = 0.10x input, cache write 5m = 1.25x input, cache write 1h = 2x.
# Update from Anthropic's pricing page when prices drift:
#   https://platform.claude.com/docs/en/about-claude/pricing
PRICES = {
    "claude-fable-5":        (10.0, 50.0),
    "claude-mythos-5":       (10.0, 50.0),
    "claude-mythos-preview": (10.0, 50.0),
    "claude-opus-4-8":       (5.0, 25.0),
    "claude-opus-4-7":       (5.0, 25.0),
    "claude-opus-4-6":       (5.0, 25.0),
    "claude-opus-4-5":       (5.0, 25.0),
    "claude-opus-4-1":       (15.0, 75.0),
    "claude-opus-4-0":       (15.0, 75.0),
    "claude-sonnet-5":       (3.0, 15.0),
    "claude-sonnet-4-6":     (3.0, 15.0),
    "claude-sonnet-4-5":     (3.0, 15.0),
    "claude-sonnet-4-0":     (3.0, 15.0),
    "claude-haiku-4-5":      (1.0, 5.0),
    "claude-3-5-haiku":      (0.8, 4.0),
    "claude-3-haiku":        (0.25, 1.25),
}
# Family fallbacks for unrecognized but plausible ids (new releases, snapshots).
FAMILY = [
    ("claude-fable", (10.0, 50.0)),
    ("claude-mythos", (10.0, 50.0)),
    ("claude-opus", (5.0, 25.0)),
    ("claude-sonnet", (3.0, 15.0)),
    ("claude-haiku", (1.0, 5.0)),
]
CACHE_READ_MULT = 0.10
CACHE_WRITE_5M_MULT = 1.25
CACHE_WRITE_1H_MULT = 2.0

# Known model ids, longest first — lets dated snapshots (e.g. claude-opus-4-1-20250805)
# match the most specific price rather than falling through to a broad family.
_PRICE_KEYS_BY_LEN = sorted(PRICES, key=len, reverse=True)


def price_for(model):
    """Return (input, output) $/Mtok for a model id, or None if unpriceable."""
    if not model or model == "<synthetic>":
        return None
    if model in PRICES:
        return PRICES[model]
    # Dated snapshots: match the most specific known id first, so e.g. 4.1
    # isn't mispriced by the broad "claude-opus" family fallback.
    for key in _PRICE_KEYS_BY_LEN:
        if model.startswith(key + "-"):
            return PRICES[key]
    for prefix, p in FAMILY:
        if model.startswith(prefix):
            return p
    return None


def model_family(model):
    if not model:
        return "unknown"
    for fam in ("opus", "sonnet", "haiku", "fable", "mythos"):
        if fam in model:
            return fam.capitalize()
    return model


# --- Time --------------------------------------------------------------------
_TS_RE = re.compile(r"\.(\d+)")


def parse_ts(s):
    """Parse an ISO-8601 UTC timestamp (…Z or …+00:00); 3.9-safe."""
    if not s:
        return None
    s = s.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    # Normalize fractional seconds to 6 digits (3.9 fromisoformat is picky).
    m = _TS_RE.search(s)
    if m:
        frac = (m.group(1) + "000000")[:6]
        s = s[: m.start()] + "." + frac + s[m.end():]
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        return None
    if dt.tzinfo is None:  # assume UTC so comparisons with aware datetimes don't raise
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


# --- Formatting --------------------------------------------------------------
def fmt_tok(n):
    n = float(n)
    if n >= 1e9:
        return f"{n / 1e9:.1f}B"
    if n >= 1e6:
        return f"{n / 1e6:.1f}M"
    if n >= 1e3:
        return f"{n / 1e3:.0f}k"
    return f"{int(n)}"


def fmt_usd(x):
    if x >= 100:
        return f"${x:,.0f}"
    if x >= 10:
        return f"${x:.1f}"
    return f"${x:.2f}"


def bar(value, vmax, width=22, fill="█", empty="·"):
    if vmax <= 0:
        return empty * width
    n = int(round(value / vmax * width))
    n = max(0, min(width, n))
    return fill * n + empty * (width - n)


def pct(part, whole):
    return (100.0 * part / whole) if whole else 0.0


# --- Core --------------------------------------------------------------------
def new_acc():
    return {
        "input": 0, "cache_read": 0, "cache_w5m": 0, "cache_w1h": 0,
        "output": 0, "cost": 0.0, "msgs": 0, "side_tok": 0,
    }


def acc_add(a, b):
    for k in ("input", "cache_read", "cache_w5m", "cache_w1h", "output", "cost", "msgs", "side_tok"):
        a[k] += b[k]


def acc_tokens(a):
    return a["input"] + a["cache_read"] + a["cache_w5m"] + a["cache_w1h"] + a["output"]


def project_label(cwd, slug):
    """A short, human label for a project/worktree."""
    if cwd:
        norm = cwd.replace("\\", "/")
        if "/.claude/worktrees/" in norm:
            head, wt = norm.split("/.claude/worktrees/", 1)
            return f"{os.path.basename(head)}/{wt.split('/')[0]}"
        parts = [p for p in norm.split("/") if p]
        if len(parts) >= 2:
            return f"{parts[-2]}/{parts[-1]}" if parts[-1] not in (".",) else parts[-1]
        if parts:
            return parts[-1]
    # Fall back to the directory slug, trimmed of the common home prefix.
    s = slug
    s = re.sub(r"^-(?:Users|home)-[^-]+-", "", s)
    return s


def project_root(cwd, slug):
    """Collapse a worktree to its parent repo, so a project groups all its worktrees."""
    if cwd:
        norm = cwd.replace("\\", "/")
        if "/.claude/worktrees/" in norm:
            head = norm.split("/.claude/worktrees/", 1)[0]
            return os.path.basename(head) or head
        parts = [p for p in norm.split("/") if p]
        if parts:
            return parts[-1]
    s = re.sub(r"^-(?:Users|home)-[^-]+-", "", slug)
    if "--claude-worktrees-" in s:
        s = s.split("--claude-worktrees-", 1)[0]
    return s.split("-")[-1] if s else slug


def why_session(s):
    """One-line, data-driven explanation of why a session burned so much."""
    a = s["acc"]
    tok = acc_tokens(a)
    if tok == 0:
        return ""
    inp_side = a["input"] + a["cache_read"] + a["cache_w5m"] + a["cache_w1h"]
    rsh = pct(a["cache_read"], inp_side)
    wsh = pct(a["cache_w5m"] + a["cache_w1h"], inp_side)
    fsh = pct(a["input"], inp_side)
    osh = pct(a["output"], tok)
    sidesh = pct(a["side_tok"], tok)
    msgs = a["msgs"] or 1
    avg_ctx = a["cache_read"] / msgs / 1000.0  # k tokens of context re-read per turn
    bits = []
    if rsh >= 60:
        bits.append(f"{msgs} turns re-reading a large context (~{avg_ctx:.0f}k tok/turn)")
    if wsh >= 20:
        bits.append(f"{wsh:.0f}% cache writes — context churn")
    if fsh >= 20:
        bits.append(f"{fsh:.0f}% fresh input — big files/pastes")
    if osh >= 15:
        bits.append(f"{fmt_tok(a['output'])} generated output")
    if sidesh >= 35:
        bits.append(f"{sidesh:.0f}% from subagents")
    if not bits:
        bits.append(f"{msgs} turns, {fmt_tok(tok)} tokens")
    return "; ".join(bits[:2])


def analyze(projects_dir, window_start, now, project_filter, cwd_here):
    seen = set()
    sessions = {}   # sessionId -> dict
    unknown_models = {}
    grace = window_start - timedelta(seconds=90)
    grace_epoch = grace.timestamp()

    try:
        entries = list(os.scandir(projects_dir))
    except FileNotFoundError:
        return None

    for ent in entries:
        if not ent.is_dir():
            continue
        slug = ent.name
        if project_filter == "current":
            # Claude Code derives the slug by mapping '/' and '.' in the cwd to '-'.
            here_slug = cwd_here.replace("\\", "/").replace("/", "-").replace(".", "-")
            if slug != here_slug:
                continue
        elif project_filter and project_filter not in ("all", "current"):
            if project_filter.lower() not in slug.lower():
                continue

        try:
            files = [f for f in os.scandir(ent.path) if f.name.endswith(".jsonl")]
        except OSError:
            continue

        for f in files:
            try:
                if f.stat().st_mtime < grace_epoch:
                    continue  # whole file predates the window
            except OSError:
                continue
            _scan_file(f.path, window_start, now, seen, sessions, unknown_models)

    return {"sessions": sessions, "unknown_models": unknown_models}


def _scan_file(path, window_start, now, seen, sessions, unknown_models):
    title = None
    try:
        fh = open(path, "r", encoding="utf-8", errors="replace")
    except OSError:
        return
    with fh:
        for lineno, line in enumerate(fh, 1):
            # Cheap pre-filter: only assistant-usage and title lines matter.
            has_usage = '"usage"' in line
            has_title = '"aiTitle"' in line
            if not has_usage and not has_title:
                continue
            try:
                o = json.loads(line)
            except (ValueError, TypeError):
                continue

            if has_title and o.get("aiTitle"):
                title = o.get("aiTitle")
                continue
            if o.get("type") != "assistant":
                continue
            msg = o.get("message") or {}
            usage = msg.get("usage")
            if not isinstance(usage, dict):
                continue

            ts = parse_ts(o.get("timestamp"))
            if ts is None or ts < window_start or ts > now:
                continue

            key = o.get("requestId") or msg.get("id") or f"{path}:{lineno}"
            if key in seen:
                continue
            seen.add(key)

            inp = int(usage.get("input_tokens") or 0)
            cr = int(usage.get("cache_read_input_tokens") or 0)
            cc = int(usage.get("cache_creation_input_tokens") or 0)
            out = int(usage.get("output_tokens") or 0)
            cobj = usage.get("cache_creation") or {}
            w5 = int(cobj.get("ephemeral_5m_input_tokens") or 0)
            w1 = int(cobj.get("ephemeral_1h_input_tokens") or 0)
            if (w5 + w1) == 0 and cc > 0:
                w5 = cc  # no breakdown -> assume 5m TTL

            model = msg.get("model") or "<unknown>"
            p = price_for(model)
            if p is None:
                cost = 0.0
                if model not in ("<synthetic>",):
                    unknown_models[model] = unknown_models.get(model, 0) + 1
            else:
                pin, pout = p
                cost = (
                    inp * pin
                    + cr * pin * CACHE_READ_MULT
                    + w5 * pin * CACHE_WRITE_5M_MULT
                    + w1 * pin * CACHE_WRITE_1H_MULT
                    + out * pout
                ) / 1e6

            sid = o.get("sessionId") or os.path.splitext(os.path.basename(path))[0]
            s = sessions.get(sid)
            if s is None:
                slug_dir = os.path.basename(os.path.dirname(path))
                s = {
                    "id": sid,
                    "label": project_label(o.get("cwd"), slug_dir),
                    "root": project_root(o.get("cwd"), slug_dir),
                    "cwd": o.get("cwd"),
                    "title": title,
                    "branch": o.get("gitBranch"),
                    "acc": new_acc(),
                    "models": {},
                    "first": ts, "last": ts,
                }
                sessions[sid] = s
            if title and not s["title"]:
                s["title"] = title
            if ts < s["first"]:
                s["first"] = ts
            if ts > s["last"]:
                s["last"] = ts

            a = s["acc"]
            a["input"] += inp
            a["cache_read"] += cr
            a["cache_w5m"] += w5
            a["cache_w1h"] += w1
            a["output"] += out
            a["cost"] += cost
            a["msgs"] += 1
            side = bool(o.get("isSidechain"))
            if side:
                a["side_tok"] += inp + cr + w5 + w1 + out
            fam = model_family(model)
            fa = s["models"].setdefault(fam, new_acc())
            fa["input"] += inp
            fa["cache_read"] += cr
            fa["cache_w5m"] += w5
            fa["cache_w1h"] += w1
            fa["output"] += out
            fa["cost"] += cost
            fa["msgs"] += 1


def build_report(data, hours, now, window_start, project_filter, top):
    sessions = list(data["sessions"].values())
    total = new_acc()
    projects = {}
    models = {}
    proj_sessions = {}  # root -> session count
    for s in sessions:
        acc_add(total, s["acc"])
        pl = s["root"]
        projects.setdefault(pl, new_acc())
        acc_add(projects[pl], s["acc"])
        proj_sessions[pl] = proj_sessions.get(pl, 0) + 1
        for fam, fa in s["models"].items():
            models.setdefault(fam, new_acc())
            acc_add(models[fam], fa)

    sessions.sort(key=lambda s: s["acc"]["cost"], reverse=True)
    proj_list = sorted(projects.items(), key=lambda kv: kv[1]["cost"], reverse=True)
    model_list = sorted(models.items(), key=lambda kv: kv[1]["cost"], reverse=True)

    return {
        "hours": hours,
        "now": now,
        "window_start": window_start,
        "project_filter": project_filter,
        "top": top,
        "total": total,
        "sessions": sessions,
        "projects": proj_list,
        "models": model_list,
        "unknown_models": data["unknown_models"],
        "proj_sessions": proj_sessions,
        "n_sessions": len(sessions),
        "n_projects": len(projects),
    }


def tips(rep):
    """Return a list of (icon, head, body) tips, most impactful first.

    Each tip is scannable: an emoji + a short headline, then a concrete body
    that ends with a `→` next-step the user can actually act on.
    """
    out = []
    total = rep["total"]
    ttok = acc_tokens(total)
    tcost = total["cost"]
    if ttok == 0:
        return out
    sessions = rep["sessions"]

    # 1. Huge context carried per turn — the dominant lever for heavy Claude Code use.
    if sessions:
        s0 = sessions[0]
        m0 = s0["acc"]["msgs"] or 1
        ctxk = s0["acc"]["cache_read"] / m0 / 1000.0
        if ctxk >= 120 or m0 >= 150:
            fam0 = (max(s0["models"].items(), key=lambda kv: kv[1]["cost"])[0]
                    if s0["models"] else "Opus")
            inprice = {"Opus": 5, "Sonnet": 3, "Haiku": 1, "Fable": 10, "Mythos": 10}.get(fam0, 5)
            per_turn = ctxk * 1000 * CACHE_READ_MULT * inprice / 1e6
            out.append((
                "🧠", "History is the biggest lever",
                f"Your top session re-read ~{ctxk:.0f}k tokens every turn across {m0} turns — about "
                f"{fmt_usd(per_turn)}/turn just to carry the conversation, even at cache-read rates. "
                f"That, not a cache miss, is where the money goes. "
                f"→ Run /compact when a thread gets long, or start a fresh session per task.",
            ))

    # 2. Model concentration -> downshift suggestion.
    if rep["models"]:
        fam, fa = rep["models"][0]
        share = pct(fa["cost"], tcost) if tcost else 0
        if fam == "Opus" and share >= 55 and tcost >= 0.5:
            save = fa["cost"] * 0.4
            out.append((
                "💸", f"Opus drove {share:.0f}% of spend",
                f"That's {fmt_usd(fa['cost'])} on the priciest tier. On read-heavy or mechanical work, "
                f"Sonnet (~40% cheaper) or Haiku (~80% cheaper) rarely costs quality. "
                f"→ Pick the lighter model at the start of such a session (mid-session swaps bust the "
                f"cache) — could trim ~{fmt_usd(save)}.",
            ))

    # 3. Single heavy session.
    if sessions:
        s = sessions[0]
        share = pct(s["acc"]["cost"], tcost) if tcost else 0
        if share >= 35 and rep["n_sessions"] > 1:
            name = s["title"] or s["label"]
            out.append((
                "🧵", "One session dominated",
                f"“{name}” alone was {share:.0f}% of all burn ({fmt_usd(s['acc']['cost'])}). "
                f"→ Split mega-threads into task-sized sessions so each context stays small and cheap.",
            ))

    # 4. Cache churn vs reuse.
    inp_side = total["input"] + total["cache_read"] + total["cache_w5m"] + total["cache_w1h"]
    if inp_side > 0:
        read_share = pct(total["cache_read"], inp_side)
        write_share = pct(total["cache_w5m"] + total["cache_w1h"], inp_side)
        if write_share >= 18:
            out.append((
                "♻️", f"Context churn: {write_share:.0f}% cache writes",
                f"Reads were only {read_share:.0f}%. Editing early context, switching models mid-session, or "
                f">5-min idle gaps invalidate the prompt cache and force expensive re-writes. "
                f"→ Keep stable context up top and avoid mid-session model swaps.",
            ))
        elif read_share >= 60:
            out.append((
                "✅", "Caching is working well",
                f"{read_share:.0f}% of input tokens were cache reads (billed at 10%). Keeping sessions warm "
                f"(<5-min gaps) is paying off — nothing to change here.",
            ))

    # 5. Subagent share.
    side = sum(s["acc"]["side_tok"] for s in sessions)
    side_share = pct(side, ttok)
    if side_share >= 30:
        out.append((
            "🤖", f"Subagents were {side_share:.0f}% of tokens",
            f"Fan-out is powerful, but each agent re-reads the context it's handed. "
            f"→ Scope the number of subagents to what the task actually needs.",
        ))

    # 6. Rate-limit pacing (weighted throughput over the window).
    hrs = rep["hours"] or 1
    cost_per_hr = tcost / hrs
    if cost_per_hr >= 3 and rep["n_sessions"] >= 3:
        out.append((
            "🚦", f"Pacing ~{fmt_usd(cost_per_hr)}/h of weighted burn",
            f"Anthropic limits roll over a window, so bunching heavy Opus sessions concentrates usage and "
            f"risks a 429. → Spread heavy work out or batch non-urgent runs to keep headroom.",
        ))

    out = out[:5]

    # Accuracy note — kept past the cap since it explains why totals may read low.
    if rep["unknown_models"]:
        ms = ", ".join(sorted(rep["unknown_models"]))
        out.append((
            "⚠️", "Unpriced model in the mix",
            f"{ms} isn’t in the price table — its tokens are counted but billed at $0, so totals read low. "
            f"→ Add it to PRICES to fix.",
        ))

    return out


# --- Renderers ---------------------------------------------------------------
def scope_line(rep):
    pf = rep["project_filter"]
    scope = "all projects" if pf in (None, "all") else (
        "current project" if pf == "current" else f"project ~{pf}")
    return f"last {rep['hours']:g}h · {scope}"


def render_ascii(rep):
    L = []
    total = rep["total"]
    ttok = acc_tokens(total)
    when = rep["now"].strftime("%Y-%m-%d %H:%M UTC")
    L.append("")
    L.append(f"  TOKEN BURN · {scope_line(rep)}{' ' * max(1, 40 - len(scope_line(rep)))}{when}")
    L.append("  " + "─" * 72)
    if rep["n_sessions"] == 0:
        L.append("  No session activity in this window.")
        L.append("")
        return "\n".join(L)

    fams = [(f, a) for f, a in rep["models"] if a["cost"] > 0][:3]
    msum = " · ".join(
        f"{f} {pct(a['cost'], total['cost']):.0f}%" for f, a in fams
    ) if fams else "—"
    inp_side = total["input"] + total["cache_read"] + total["cache_w5m"] + total["cache_w1h"]
    rsh = pct(total["cache_read"], inp_side)
    wsh = pct(total["cache_w5m"] + total["cache_w1h"], inp_side)
    L.append(f"  TOTAL  {fmt_usd(total['cost'])}  ·  {fmt_tok(ttok)} tok  ·  "
             f"{rep['n_sessions']} sessions / {rep['n_projects']} projects")
    L.append(f"         {msum}        cache: {rsh:.0f}% read · {wsh:.0f}% write")
    L.append("")

    # Top sessions (+ a row summarizing the rest)
    L.append("  TOP SESSIONS                                          cost     tokens")
    shown = rep["sessions"][:rep["top"]]
    mx = shown[0]["acc"]["cost"] or 1
    for i, s in enumerate(shown, 1):
        a = s["acc"]
        name = (s["title"] or s["label"] or s["id"][:8])[:34]
        L.append(f"  {i:>2} {name:<34} {bar(a['cost'], mx, 10)} {fmt_usd(a['cost']):>7}  {fmt_tok(acc_tokens(a)):>7}")
    rest = rep["sessions"][rep["top"]:]
    if rest:
        ra = new_acc()
        for s in rest:
            acc_add(ra, s["acc"])
        label = f"+ {len(rest)} more sessions"
        L.append(f"     {label:<34} {'·' * 10} {fmt_usd(ra['cost']):>7}  {fmt_tok(acc_tokens(ra)):>7}")
    L.append("")

    # Why the biggest sessions burned
    L.append("  WHY THE BIGGEST BURNED")
    for s in shown[:3]:
        name = (s["title"] or s["label"] or s["id"][:8])[:38]
        wrapped = _wrap(f"{name} ({fmt_usd(s['acc']['cost'])}) — {why_session(s)}", 66)
        L.append(f"   • {wrapped[0]}")
        for cont in wrapped[1:]:
            L.append(f"     {cont}")
    L.append("")

    # Top projects (worktrees grouped into their repo)
    if rep["n_projects"] > 1:
        L.append("  TOP PROJECTS  (worktrees grouped)                    cost     tokens")
        pshown = rep["projects"][:rep["top"]]
        mxp = pshown[0][1]["cost"] or 1
        for i, (pl, a) in enumerate(pshown, 1):
            n = rep["proj_sessions"].get(pl, 0)
            tag = f"{pl}  ({n})"[:34]
            L.append(f"  {i:>2} {tag:<34} {bar(a['cost'], mxp, 10)} {fmt_usd(a['cost']):>7}  {fmt_tok(acc_tokens(a)):>7}")
        prest = rep["projects"][rep["top"]:]
        if prest:
            pa = new_acc()
            for _, a in prest:
                acc_add(pa, a)
            label = f"+ {len(prest)} more projects"
            L.append(f"     {label:<34} {'·' * 10} {fmt_usd(pa['cost']):>7}  {fmt_tok(acc_tokens(pa)):>7}")
        L.append("")

    # Cache efficiency
    L.append("  CACHE EFFICIENCY (share of input-side tokens)")
    L.append(f"   read   {rsh:>4.0f}%  {bar(rsh, 100, 24)}  cheap (0.1×)")
    L.append(f"   write  {wsh:>4.0f}%  {bar(wsh, 100, 24)}  pricey (1.25–2×)")
    ush = pct(total["input"], inp_side)
    L.append(f"   fresh  {ush:>4.0f}%  {bar(ush, 100, 24)}  full price")
    L.append("")

    t = tips(rep)
    if t:
        L.append("  💡 TIPS")
        L.append("")
        for icon, head, body in t:
            L.append(f"   {icon}  {head}")
            for cont in _wrap(body, 66):
                L.append(f"      {cont}")
            L.append("")
    return "\n".join(L)


def _wrap(text, width):
    words = text.split()
    lines, cur = [], ""
    for w in words:
        if len(cur) + len(w) + 1 > width and cur:
            lines.append(cur)
            cur = w
        else:
            cur = (cur + " " + w).strip()
    if cur:
        lines.append(cur)
    return lines or [""]


def render_markdown(rep):
    total = rep["total"]
    ttok = acc_tokens(total)
    when = rep["now"].strftime("%Y-%m-%d %H:%M UTC")
    M = []
    M.append(f"# 🔥 Token Burn — {scope_line(rep)}")
    M.append("")
    M.append(f"*Generated {when}*")
    M.append("")
    if rep["n_sessions"] == 0:
        M.append("No session activity in this window.")
        return "\n".join(M) + "\n"

    fams = [(f, a) for f, a in rep["models"] if a["cost"] > 0][:4]
    msum = " · ".join(
        f"**{f}** {pct(a['cost'], total['cost']):.0f}%" for f, a in fams
    ) if fams else "—"
    inp_side = total["input"] + total["cache_read"] + total["cache_w5m"] + total["cache_w1h"]
    rsh = pct(total["cache_read"], inp_side)
    wsh = pct(total["cache_w5m"] + total["cache_w1h"], inp_side)
    M.append(f"## {fmt_usd(total['cost'])} · {fmt_tok(ttok)} tokens · "
             f"{rep['n_sessions']} sessions / {rep['n_projects']} projects")
    M.append("")
    M.append(f"{msum}  \ncache: {rsh:.0f}% read · {wsh:.0f}% write · {pct(total['input'], inp_side):.0f}% fresh")
    M.append("")

    shown = rep["sessions"][:rep["top"]]
    M.append("## 📊 Top sessions by burn")
    M.append("")
    M.append("| # | Session | Project | Cost | Tokens | Model |")
    M.append("|--:|---|---|--:|--:|---|")
    for i, s in enumerate(shown, 1):
        a = s["acc"]
        name = (s["title"] or "—").replace("|", "／")[:48]
        topfam = max(s["models"].items(), key=lambda kv: kv[1]["cost"])[0] if s["models"] else "—"
        M.append(f"| {i} | {name} | `{s['label']}` | {fmt_usd(a['cost'])} | {fmt_tok(acc_tokens(a))} | {topfam} |")
    rest = rep["sessions"][rep["top"]:]
    if rest:
        ra = new_acc()
        for s in rest:
            acc_add(ra, s["acc"])
        M.append(f"| | *+ {len(rest)} more sessions* | | *{fmt_usd(ra['cost'])}* | *{fmt_tok(acc_tokens(ra))}* | |")
    M.append("")

    # Why the biggest sessions burned
    M.append("## 🔍 Why the biggest sessions burned")
    M.append("")
    for s in shown[:5]:
        name = (s["title"] or s["label"] or s["id"][:8]).replace("|", "／")
        M.append(f"- **{name}** ({fmt_usd(s['acc']['cost'])}) — {why_session(s)}")
    M.append("")

    if rep["n_projects"] > 1:
        M.append("## 📁 Top projects by burn")
        M.append("")
        M.append("*Worktrees are grouped under their parent repo.*")
        M.append("")
        M.append("| # | Project | Cost | Tokens | Sessions |")
        M.append("|--:|---|--:|--:|--:|")
        pshown = rep["projects"][:rep["top"]]
        for i, (pl, a) in enumerate(pshown, 1):
            M.append(f"| {i} | `{pl}` | {fmt_usd(a['cost'])} | {fmt_tok(acc_tokens(a))} | {rep['proj_sessions'].get(pl, 0)} |")
        prest = rep["projects"][rep["top"]:]
        if prest:
            pa = new_acc()
            for _, a in prest:
                acc_add(pa, a)
            M.append(f"| | *+ {len(prest)} more projects* | *{fmt_usd(pa['cost'])}* | *{fmt_tok(acc_tokens(pa))}* | |")
        M.append("")

    M.append("## ♻️ Cache efficiency")
    M.append("")
    M.append("Share of input-side tokens. Reads are cheap (0.1× input); writes cost 1.25–2× and signal context churn.")
    M.append("")
    M.append(f"- **Read** {rsh:.0f}% `{bar(rsh, 100, 28)}` — reused context, billed at 10%")
    M.append(f"- **Write** {wsh:.0f}% `{bar(wsh, 100, 28)}` — cache (re)creation")
    M.append(f"- **Fresh** {pct(total['input'], inp_side):.0f}% `{bar(pct(total['input'], inp_side), 100, 28)}` — uncached, full price")
    M.append("")

    t = tips(rep)
    if t:
        M.append("## 💡 Tips to cut burn & avoid rate limits")
        M.append("")
        for icon, head, body in t:
            M.append(f"- {icon} **{head}** — {body}")
        M.append("")
    M.append("---")
    M.append("")
    M.append(f"<sub>Window: {rep['window_start'].strftime('%Y-%m-%d %H:%M')} → {when}. "
             f"Cost is estimated from public per-model pricing with cache discounts; treat as a relative guide.</sub>")
    return "\n".join(M) + "\n"


def report_to_json(rep):
    def acc_json(a):
        return {**{k: a[k] for k in a}, "tokens": acc_tokens(a)}
    return {
        "hours": rep["hours"],
        "generated_utc": rep["now"].isoformat(),
        "window_start_utc": rep["window_start"].isoformat(),
        "project_filter": rep["project_filter"],
        "n_sessions": rep["n_sessions"],
        "n_projects": rep["n_projects"],
        "total": acc_json(rep["total"]),
        "models": [{"family": f, **acc_json(a)} for f, a in rep["models"]],
        "projects": [{"label": p, **acc_json(a)} for p, a in rep["projects"]],
        "sessions": [
            {
                "id": s["id"], "title": s["title"], "label": s["label"], "root": s["root"],
                "branch": s["branch"], "first": s["first"].isoformat(),
                "last": s["last"].isoformat(), **acc_json(s["acc"]),
                "top_model": (max(s["models"].items(), key=lambda kv: kv[1]["cost"])[0]
                              if s["models"] else None),
            }
            for s in rep["sessions"]
        ],
        "unknown_models": rep["unknown_models"],
        "tips": [{"icon": i, "head": h, "body": b} for i, h, b in tips(rep)],
    }


def main(argv=None):
    ap = argparse.ArgumentParser(description="Report where Claude Code tokens were burned.")
    ap.add_argument("--hours", type=float, default=5.0, help="window length in hours (default 5)")
    ap.add_argument("--project", default="all",
                    help="'all' (default), 'current', or a substring to match project slugs")
    ap.add_argument("--top", type=int, default=15, help="rows in each ranking (default 15)")
    ap.add_argument("--projects-dir", default=os.path.expanduser("~/.claude/projects"))
    ap.add_argument("--out", help="write the Markdown report to this path")
    ap.add_argument("--json", action="store_true", help="print computed data as JSON to stdout")
    ap.add_argument("--no-ascii", action="store_true", help="suppress the ASCII report on stdout")
    ap.add_argument("--now", help="override 'now' (ISO-8601 UTC) — for testing")
    ap.add_argument("--cwd", default=os.environ.get("CMUX_AGENT_LAUNCH_CWD") or os.getcwd(),
                    help="working dir used to resolve --project current")
    args = ap.parse_args(argv)
    if args.top < 1:
        ap.error("--top must be >= 1")
    if args.hours <= 0:
        ap.error("--hours must be > 0")

    now = parse_ts(args.now) if args.now else datetime.now(timezone.utc)
    if now is None:
        print("Could not parse --now timestamp.", file=sys.stderr)
        return 2
    window_start = now - timedelta(hours=args.hours)

    data = analyze(args.projects_dir, window_start, now, args.project, args.cwd)
    if data is None:
        print(f"Projects dir not found: {args.projects_dir}", file=sys.stderr)
        return 1

    rep = build_report(data, args.hours, now, window_start, args.project, args.top)

    if args.out:
        try:
            with open(args.out, "w", encoding="utf-8") as fh:
                fh.write(render_markdown(rep))
        except OSError as e:
            print(f"Could not write --out: {e}", file=sys.stderr)

    if args.json:
        print(json.dumps(report_to_json(rep), indent=2))
    elif not args.no_ascii:
        print(render_ascii(rep))

    return 0


if __name__ == "__main__":
    sys.exit(main())
