#!/usr/bin/env python3
"""Tests for the decisions park makes before it kills anything.

Scope is deliberate: the functions that choose WHO dies, whether a session is
busy, and how it comes back. Those are pure, and they are where a mistake costs
the user a conversation. Everything that needs a live cmux socket is left to
`park doctor` and the pty harnesses.

    python3 test_park.py            # or: python3 -m unittest discover
"""
import json
import os
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import park  # noqa: E402


def proc(pid, cmd, ppid=1, rss=0, surface=None):
    return {"pid": pid, "cmd": cmd, "ppid": ppid, "rss": rss,
            "surface": surface}


class TestWhoGetsKilled(unittest.TestCase):
    """`runs_binary` and friends. Over-matching here loses unsaved work."""

    def test_dev_binary_only_in_command_position(self):
        self.assertEqual(park.kill_kind("node .bin/vite"), "dev-server")
        self.assertEqual(park.kill_kind("node /x/node_modules/nuxi/bin/nuxi.mjs"),
                         "dev-server")
        self.assertEqual(park.kill_kind("npm run dev"), "dev-server")

    def test_name_as_argument_is_not_a_dev_server(self):
        for cmd in ("rg webpack src/",
                    "vim vite.config.ts",
                    "git commit -m 'npm run dev broke'",
                    "tail -f /var/log/vite.log"):
            self.assertIsNone(park.kill_kind(cmd), cmd)

    def test_name_as_path_segment_is_not_a_dev_server(self):
        self.assertIsNone(
            park.kill_kind("node /app/node_modules/vite/dist/esbuild"))

    def test_launcher_value_flag_swallows_its_argument(self):
        # `npx --package vite prettier` runs prettier, not vite.
        self.assertIsNone(park.kill_kind("npx --package vite prettier ."))

    def test_python_dash_m_is_read_through(self):
        self.assertEqual(park.kill_kind("python3 -m uvicorn app:api"),
                         "dev-server")

    def test_test_browsers(self):
        self.assertEqual(park.kill_kind("/x/Chrome for Testing/chrome --port"),
                         "test-browser")
        self.assertEqual(park.kill_kind("node /x/.bin/agent-browser"),
                         "test-browser")

    def test_wrappers_are_read_through_to_the_real_program(self):
        # `ps` renders argv unquoted, so a commit message is just more tokens.
        # Stopping at the wrapper missed NEVER_KILL and then matched `npm run
        # dev` INSIDE the message — a git commit classified as a dev server,
        # killed with the editor holding the message.
        for cmd in ("env git commit -m npm run dev broke",
                    "env FOO=1 git commit -m npm run dev broke",
                    "nice -n 10 vim vite.config.ts npm run dev",
                    "sudo git rebase -i npm run dev",
                    "nohup git commit -m npm run dev"):
            self.assertIsNone(park.kill_kind(cmd), cmd)

    def test_a_wrapped_dev_server_is_still_a_dev_server(self):
        for cmd in ("env vite", "stdbuf -oL npm run dev", "nohup next dev"):
            self.assertEqual(park.kill_kind(cmd), "dev-server", cmd)

    def test_is_claude_matches_the_program_not_the_path(self):
        self.assertTrue(park.is_claude("claude --resume abc"))
        self.assertTrue(park.is_claude("/opt/homebrew/bin/claude"))
        for cmd in ("vim /tmp/claude", "tail -f /var/log/claude",
                    "grep claude ~/.zshrc"):
            self.assertFalse(park.is_claude(cmd), cmd)


class TestClassify(unittest.TestCase):
    def test_subagent_claude_is_not_a_root_session(self):
        procs = [proc(100, "claude --resume a"), proc(200, "claude -p sub", 100)]
        table = {100: {"ppid": 1, "rss": 0, "cmd": "claude"},
                 200: {"ppid": 100, "rss": 0, "cmd": "claude"}}
        claude, dev, browser = park.classify(procs, table)
        self.assertEqual([p["pid"] for p in claude], [100])

    def test_grandchild_claude_is_not_a_root_session(self):
        procs = [proc(100, "claude --resume a"), proc(300, "claude -p sub", 200)]
        table = {100: {"ppid": 1, "rss": 0, "cmd": "claude"},
                 200: {"ppid": 100, "rss": 0, "cmd": "sh"},
                 300: {"ppid": 200, "rss": 0, "cmd": "claude"}}
        claude, _, _ = park.classify(procs, table)
        self.assertEqual([p["pid"] for p in claude], [100])

    def test_two_unrelated_sessions_both_count(self):
        procs = [proc(100, "claude --resume a"), proc(400, "claude --resume b")]
        table = {100: {"ppid": 1, "rss": 0, "cmd": "claude"},
                 400: {"ppid": 1, "rss": 0, "cmd": "claude"}}
        claude, _, _ = park.classify(procs, table)
        self.assertEqual(sorted(p["pid"] for p in claude), [100, 400])

    def test_cycle_in_the_process_table_does_not_hang(self):
        procs = [proc(100, "claude a"), proc(200, "claude b", 100)]
        table = {100: {"ppid": 200, "rss": 0, "cmd": "claude"},
                 200: {"ppid": 100, "rss": 0, "cmd": "claude"}}
        park.classify(procs, table)      # must terminate


class TestBusyVerdict(unittest.TestCase):
    """The gate Rule #1 rests on."""

    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)

    def transcript(self, age_seconds):
        p = Path(self.dir.name) / f"t{age_seconds}.jsonl"
        p.write_text("{}\n")
        when = time.time() - age_seconds
        os.utime(p, (when, when))
        return {"transcript": str(p)}

    def test_busy_pill_with_a_live_transcript_refuses(self):
        stale, why = park.busy_verdict("Running", [self.transcript(5)])
        self.assertFalse(stale)
        self.assertIn("turn in flight", why)

    def test_busy_pill_gone_quiet_is_treated_as_stale(self):
        stale, why = park.busy_verdict(
            "Running", [self.transcript(park.STALE_PILL_SECONDS + 60)])
        self.assertTrue(stale)
        self.assertIsNone(why)

    def test_no_pill_but_a_live_transcript_still_refuses(self):
        # A session blocked on a slow tool call has no pill and near-zero CPU;
        # the transcript is the only signal left.
        stale, why = park.busy_verdict("", [self.transcript(3)])
        self.assertIn("recent transcript", why)

    def test_no_pill_and_a_quiet_transcript_parks(self):
        stale, why = park.busy_verdict("", [self.transcript(3600)])
        self.assertIsNone(why)

    def test_the_busiest_tab_decides_for_the_whole_workspace(self):
        sessions = [self.transcript(3600), self.transcript(2)]
        _, why = park.busy_verdict("", sessions)
        self.assertIsNotNone(why)

    def test_a_missing_transcript_does_not_read_as_busy(self):
        _, why = park.busy_verdict("", [{"transcript": "/nope/gone.jsonl"}])
        self.assertIsNone(why)

    def test_every_busy_state_is_honoured(self):
        for state in park.BUSY_STATES:
            _, why = park.busy_verdict(state.title(), [self.transcript(5)])
            self.assertIsNotNone(why, state)


class TestResumeCommand(unittest.TestCase):
    SID = "0a1b2c3d-4e5f-6071-8293-a4b5c6d7e8f9"

    def test_session_id_is_read_from_both_spellings(self):
        self.assertEqual(park.argv_session_id(f"claude --resume {self.SID}"),
                         self.SID)
        self.assertEqual(park.argv_session_id(f"claude --session-id {self.SID}"),
                         self.SID)
        self.assertEqual(park.argv_session_id(f"claude --resume='{self.SID}'"),
                         self.SID)

    def test_uppercase_session_id_is_still_seen(self):
        # SESSION_ID_RE accepts A-F, so a lowercase-only scan here made an
        # uppercase id invisible to unpark's already-running guard — and two
        # processes on one transcript corrupt it.
        up = self.SID.upper()
        self.assertEqual(park.argv_session_id(f"claude --resume {up}"), up)

    def test_no_session_id(self):
        self.assertIsNone(park.argv_session_id("claude --model opus"))

    def test_flags_survive_the_round_trip(self):
        cmd = park.command_from_argv(
            f"claude --resume {self.SID} --dangerously-skip-permissions "
            "--model opus", self.SID, "/tmp/x")
        self.assertIn("--dangerously-skip-permissions", cmd)
        self.assertIn("--model opus", cmd)

    def test_flag_values_from_argv_cannot_inject(self):
        # argv belongs to the process; the result is handed to /bin/sh.
        cmd = park.command_from_argv(
            "claude --model ;curl|sh", self.SID, "/tmp/x")
        self.assertNotIn("--model ;curl|sh", cmd)
        self.assertIn("';curl|sh'", cmd)

    def test_cwd_with_spaces_is_quoted(self):
        cmd = park.command_from_argv("claude", self.SID, "/tmp/my repo")
        self.assertIn("'/tmp/my repo'", cmd)

    def test_flags_that_swallow_spaces_are_dropped(self):
        # ps joins argv with spaces, so --settings JSON cannot be split back.
        cmd = park.command_from_argv(
            'claude --settings {"a": 1} --verbose', self.SID, "/tmp/x")
        self.assertNotIn("--settings", cmd)
        self.assertIn("--verbose", cmd)


class TestWithShim(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        self.shim = Path(self.dir.name) / "claude-shim"
        self.shim.write_text("#!/bin/sh\n")
        self.shim.chmod(0o755)
        old = os.environ.get("CMUX_CLAUDE_WRAPPER_SHIM")
        os.environ["CMUX_CLAUDE_WRAPPER_SHIM"] = str(self.shim)
        self.addCleanup(lambda: os.environ.__setitem__(
            "CMUX_CLAUDE_WRAPPER_SHIM", old) if old
            else os.environ.pop("CMUX_CLAUDE_WRAPPER_SHIM", None))

    def test_only_the_command_position_is_rewritten(self):
        out = park.with_shim("cd /home/me/projects/claude && claude --resume x")
        self.assertIn("cd /home/me/projects/claude &&", out)
        self.assertIn(str(self.shim), out)

    def test_no_shim_leaves_the_command_alone(self):
        os.environ.pop("CMUX_CLAUDE_WRAPPER_SHIM")
        self.assertEqual(park.with_shim("cd /x && claude -r y"),
                         "cd /x && claude -r y")


class TestLedgerPath(unittest.TestCase):
    def test_traversal_is_refused(self):
        for bad in ("../settings", "/etc/passwd", "a/b", ""):
            with self.assertRaises(SystemExit, msg=bad):
                park.ledger_path(bad)

    def test_a_normal_id_is_accepted(self):
        self.assertEqual(park.ledger_path("ws-12.ab_C").name, "ws-12.ab_C.json")


class TestLedgerClaim(unittest.TestCase):
    """The claim lock is the "already parked" guard; a leaked one wedges it."""

    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        self.real = park.LEDGER
        park.LEDGER = Path(self.dir.name)
        self.addCleanup(lambda: setattr(park, "LEDGER", self.real))

    def test_a_claim_creates_the_entry_and_removes_the_lock(self):
        p = park.ledger_path("ws-one")
        self.assertTrue(park.write_entry(p, {"a": 1}, claim=True))
        self.assertTrue(p.exists())
        self.assertFalse(p.with_suffix(".json.lock").exists())

    def test_a_second_claim_loses(self):
        p = park.ledger_path("ws-one")
        park.write_entry(p, {"a": 1}, claim=True)
        self.assertFalse(park.write_entry(p, {"a": 2}, claim=True))

    def test_a_live_lock_blocks(self):
        p = park.ledger_path("ws-one")
        p.with_suffix(".json.lock").write_text("")
        self.assertFalse(park.write_entry(p, {"a": 1}, claim=True))

    def test_a_lock_left_by_a_killed_park_is_reclaimed(self):
        # Without this the workspace is wedged for good: every park reads
        # "already parked" while no entry exists, so unpark and forget both
        # answer "not parked".
        p = park.ledger_path("ws-one")
        lock = p.with_suffix(".json.lock")
        lock.write_text("")
        old = time.time() - park.LOCK_STALE_SECONDS - 60
        os.utime(lock, (old, old))
        self.assertTrue(park.write_entry(p, {"a": 1}, claim=True))
        self.assertTrue(p.exists())

    def test_entries_are_not_world_readable(self):
        # They record cwds, branches and the user's last prompt.
        p = park.ledger_path("ws-one")
        park.write_entry(p, {"a": 1}, claim=True)
        self.assertEqual(p.stat().st_mode & 0o077, 0)


class TestOpLock(unittest.TestCase):
    """Claiming the entry is not enough: park publishes it BEFORE it kills."""

    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        self.real = park.LEDGER
        park.LEDGER = Path(self.dir.name)
        self.addCleanup(lambda: setattr(park, "LEDGER", self.real))

    def test_a_second_operation_on_the_same_workspace_is_refused(self):
        first = park.acquire_op_lock("ws-one")
        self.assertIsNotNone(first)
        self.assertIsNone(park.acquire_op_lock("ws-one"))
        park.release_op_lock(first)
        self.assertIsNotNone(park.acquire_op_lock("ws-one"))

    def test_another_workspace_is_not_blocked(self):
        park.acquire_op_lock("ws-one")
        self.assertIsNotNone(park.acquire_op_lock("ws-two"))

    def test_a_lock_whose_owner_is_gone_is_reclaimed(self):
        p = park.op_lock_path("ws-one")
        p.write_text("999999")            # a pid that cannot be running
        self.assertIsNotNone(park.acquire_op_lock("ws-one"))

    def test_an_ancient_lock_is_reclaimed(self):
        p = park.op_lock_path("ws-one")
        p.write_text(str(os.getpid()))
        old = time.time() - park.OP_LOCK_STALE_SECONDS - 60
        os.utime(p, (old, old))
        self.assertIsNotNone(park.acquire_op_lock("ws-one"))

    def test_the_lock_is_not_mistaken_for_a_ledger_entry(self):
        park.acquire_op_lock("ws-one")
        self.assertEqual(park.read_ledger(), [])


class TestRestoreVisualState(unittest.TestCase):
    def setUp(self):
        self.real = park.cmux_do
        self.addCleanup(lambda: setattr(park, "cmux_do", self.real))

    def test_silence_when_everything_went_back(self):
        park.cmux_do = lambda *a: True
        self.assertIsNone(park.restore_visual_state("ws", {"prev_color": "Red"}))

    def test_a_failure_names_the_colour_the_entry_is_about_to_take_away(self):
        park.cmux_do = lambda *a: False
        note = park.restore_visual_state("ws", {"prev_color": "Red"})
        self.assertIn("Red", note)


class TestRebuildHoldsBackWhatRekeyCouldPlace(unittest.TestCase):
    """After a cmux reset `rebuild` would build a duplicate of every survivor."""

    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        self.real = {k: getattr(park, k) for k in
                     ("LEDGER", "all_workspaces", "cmux_do")}
        park.LEDGER = Path(self.dir.name)
        self.made = []
        park.cmux_do = lambda *a: self.made.append(a) or True
        self.addCleanup(self.restore)

    def restore(self):
        for k, v in self.real.items():
            setattr(park, k, v)

    def entry(self, title, ws_id):
        park.write_entry(park.ledger_path(ws_id),
                         {"workspace_id": ws_id, "title": title,
                          "cwd": self.dir.name, "sessions": []})

    def run_rebuild(self):
        import io, contextlib
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            park.cmd_rebuild([])
        return out.getvalue()

    def test_an_entry_whose_title_is_live_under_a_new_uuid_is_held(self):
        self.entry("api-worker", "OLD-UUID")
        park.all_workspaces = lambda: [
            {"id": "NEW-UUID", "ref": "workspace:1", "title": "api-worker",
             "current_directory": self.dir.name, "window_id": "w"}]
        out = self.run_rebuild()
        self.assertIn("park rekey", out)
        self.assertEqual(self.made, [], "it created a duplicate workspace")

    def test_a_genuinely_lost_entry_is_still_rebuilt(self):
        self.entry("gone-for-good", "OLD-UUID")
        park.all_workspaces = lambda: [
            {"id": "NEW-UUID", "ref": "workspace:1", "title": "something else",
             "current_directory": self.dir.name, "window_id": "w"}]
        out = self.run_rebuild()
        self.assertNotIn("park rekey", out)
        self.assertTrue(any("new-workspace" in a for a in self.made))


class TestUnparkKeepsWhatItOwes(unittest.TestCase):
    """The ledger holds the ONLY copy of a session id and its resume command.

    Deleting it is only ever right once every tab it names is actually back.
    """

    WS = {"id": "ws-one", "ref": "workspace:1", "title": "demo"}

    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        self.tmp = Path(self.dir.name)
        self.real = {k: getattr(park, k) for k in
                     ("LEDGER", "prompt_line", "cmux_do", "send_text",
                      "wait_for_sessions", "git_info", "restore_visual_state")}
        park.LEDGER = self.tmp / "ledger"
        park.prompt_line = lambda ws, s=None: "~/x ❯ "
        park.cmux_do = lambda *a: True
        park.send_text = lambda *a, **k: True
        park.git_info = lambda cwd: {}
        park.restore_visual_state = lambda ws, e: True
        self.confirm = True
        park.wait_for_sessions = lambda ids, **k: (
            {str(i).lower() for i in ids} if self.confirm else set())
        self.addCleanup(self.restore)

    def restore(self):
        for k, v in self.real.items():
            setattr(park, k, v)

    def entry(self, n):
        """A parked entry for `n` tabs of a REBUILT workspace (no surfaces)."""
        sessions = []
        for i in range(n):
            t = self.tmp / f"s{i}.jsonl"
            t.write_text("{}")
            sessions.append({"session_id": f"0000000{i}-1111-2222-3333-"
                                           "444444444444",
                             "transcript": str(t), "cwd": str(self.tmp),
                             "resume_command": f"cd x && claude --resume s{i}",
                             "surface": ""})
        e = {"workspace_id": "ws-one", "workspace_ref": "workspace:1",
             "title": "demo", "cwd": str(self.tmp), "sessions": sessions,
             "git": {}, "killed": []}
        park.write_entry(park.ledger_path("ws-one"), e)
        return e

    def test_a_single_confirmed_tab_clears_the_entry(self):
        self.entry(1)
        res = park.unpark_one(self.WS, live_ids=set())
        self.assertTrue(res["ok"], res["msg"])
        self.assertFalse(park.ledger_path("ws-one").exists())

    def test_the_tab_that_needs_a_new_pane_stays_in_the_ledger(self):
        # A rebuilt workspace has one surface, so only the first session can be
        # resumed. The rest used to be mentioned in a note and then deleted.
        self.entry(2)
        res = park.unpark_one(self.WS, live_ids=set())
        left = park.read_entry(park.ledger_path("ws-one"))
        self.assertIsNotNone(left, "the entry was deleted")
        self.assertEqual(len(left["sessions"]), 1)
        self.assertIn("still parked", res["msg"])
        self.assertTrue(any("new agent tab" in n for n in res["notes"]))

    def test_a_tab_that_never_came_up_stays_in_the_ledger(self):
        self.confirm = False
        self.entry(1)
        res = park.unpark_one(self.WS, live_ids=set())
        left = park.read_entry(park.ledger_path("ws-one"))
        self.assertIsNotNone(left, "the entry was deleted")
        self.assertEqual(len(left["sessions"]), 1)
        self.assertTrue(any("no process appeared" in n for n in res["notes"]))

    def test_a_prompt_with_something_typed_stops_the_resume(self):
        park.prompt_line = lambda ws, s=None: "~/x ❯ git rebase --cont"
        self.entry(1)
        res = park.unpark_one(self.WS, live_ids=set())
        self.assertFalse(res["ok"])
        self.assertTrue(park.ledger_path("ws-one").exists())

    def test_an_already_running_session_is_recognised_whatever_its_case(self):
        e = self.entry(1)
        sid = e["sessions"][0]["session_id"]
        res = park.unpark_one(self.WS, live_ids={sid.upper().lower()})
        self.assertIn("already running", res["msg"])
        self.assertFalse(park.ledger_path("ws-one").exists())


class TestRekeyMatch(unittest.TestCase):
    """A wrong re-key is silent and lands on a workspace the user is using."""

    SPACES = [
        {"id": "A", "ref": "workspace:1", "title": "api-fix",
         "current_directory": "/r/api"},
        {"id": "B", "ref": "workspace:2", "title": "web-fix",
         "current_directory": "/r/web"},
        {"id": "C", "ref": "workspace:3", "title": "twin",
         "current_directory": "/r/one"},
        {"id": "D", "ref": "workspace:4", "title": "twin",
         "current_directory": "/r/two"},
    ]

    def entry(self, cwd, title):
        return {"cwd": cwd, "title": title}

    def test_an_exact_match_wins(self):
        w, note, why = park.rekey_match(self.entry("/r/api", "api-fix"),
                                        self.SPACES, set())
        self.assertEqual(w["id"], "A")
        self.assertIsNone(note)
        self.assertIsNone(why)

    def test_a_worktree_under_the_recorded_root_still_matches(self):
        # The normal case, not the odd one: park records the worktree, cmux
        # records the repo root. 19 of 44 real entries looked like this.
        w, note, why = park.rekey_match(
            self.entry("/r/api/.claude/worktrees/x", "api-fix"),
            self.SPACES, set())
        self.assertEqual(w["id"], "A")
        self.assertIsNone(note)

    def test_a_disagreeing_cwd_matches_but_is_reported(self):
        # cmux's per-panel cwd is scrambled by a reset; the ledger's is ours.
        w, note, why = park.rekey_match(
            self.entry("/somewhere/else", "api-fix"), self.SPACES, set())
        self.assertEqual(w["id"], "A")
        self.assertIn("/r/api", note)

    def test_a_repeated_title_refuses_rather_than_guessing(self):
        w, note, why = park.rekey_match(self.entry("/r/one", "twin"),
                                        self.SPACES, set())
        self.assertIsNone(w)
        self.assertIn("share this title", why)

    def test_an_unavailable_workspace_is_never_adopted(self):
        # Already claimed by another entry, or running a claude session.
        w, note, why = park.rekey_match(self.entry("/r/api", "api-fix"),
                                        self.SPACES, {"A"})
        self.assertIsNone(w)

    def test_freeing_one_twin_makes_the_other_unambiguous(self):
        w, note, why = park.rekey_match(self.entry("/r/two", "twin"),
                                        self.SPACES, {"C"})
        self.assertEqual(w["id"], "D")

    def test_an_entry_with_no_title_is_refused(self):
        w, note, why = park.rekey_match(self.entry("/r/api", ""),
                                        self.SPACES, set())
        self.assertIsNone(w)
        self.assertIn("no title", why)


class TestClosedWorkspaces(unittest.TestCase):
    """Telling "you closed it" apart from "cmux lost it".

    Without this park told the user to `rebuild` a workspace they had shut on
    purpose, and resurrected it.
    """

    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        self.base = Path(self.dir.name)

    def write(self, records, name="closed-item-history-com.cmuxterm.app.json"):
        (self.base / name).write_text(json.dumps({"records": records}))

    def record(self, ws_id, closed_at):
        # cmux nests the payload one level down under "_0".
        return {"closedAt": closed_at, "id": "r",
                "entry": {"workspace": {"_0": {"workspaceId": ws_id,
                                               "snapshot": {}}}}}

    def test_a_closed_workspace_is_found_with_a_unix_timestamp(self):
        # Core Data epoch: 0 there is 2001-01-01, not 1970-01-01.
        self.write([self.record("WS-1", 0)])
        got = park.closed_workspaces(self.base)
        self.assertEqual(got, {"WS-1": park.APPLE_EPOCH})
        self.assertEqual(
            datetime.fromtimestamp(got["WS-1"], timezone.utc).year, 2001)

    def test_the_latest_close_wins(self):
        self.write([self.record("WS-1", 100), self.record("WS-1", 900),
                    self.record("WS-1", 500)])
        self.assertEqual(park.closed_workspaces(self.base)["WS-1"],
                         900 + park.APPLE_EPOCH)

    def test_panels_and_windows_are_not_workspaces(self):
        self.write([{"closedAt": 1, "entry": {"panel": {"_0": {"id": "P"}}}},
                    {"closedAt": 2, "entry": {"window": {"_0": {"id": "W"}}}}])
        self.assertEqual(park.closed_workspaces(self.base), {})

    def test_junk_records_are_skipped_not_fatal(self):
        self.write([{"closedAt": "yesterday",
                     "entry": {"workspace": {"_0": {"workspaceId": "WS-1"}}}},
                    {"entry": {"workspace": {"_0": {"workspaceId": "WS-2"}}}},
                    self.record("WS-3", 7)])
        self.assertEqual(list(park.closed_workspaces(self.base)), ["WS-3"])

    def test_an_unreadable_history_is_not_an_error(self):
        (self.base / "closed-item-history-x.json").write_text("{not json")
        self.assertEqual(park.closed_workspaces(self.base), {})

    def test_no_history_at_all_is_not_an_error(self):
        self.assertEqual(park.closed_workspaces(self.base), {})

    def test_several_history_files_are_merged(self):
        self.write([self.record("WS-1", 1)], "closed-item-history-a.json")
        self.write([self.record("WS-2", 2)], "closed-item-history-b.json")
        self.assertEqual(sorted(park.closed_workspaces(self.base)),
                         ["WS-1", "WS-2"])


class TestLiveSessionIds(unittest.TestCase):
    """The set that stops two processes appending to one transcript."""

    SID = "0a1b2c3d-4e5f-6071-8293-a4b5c6d7e8f9"
    OTHER = "11111111-2222-3333-4444-555555555555"

    def setUp(self):
        self.real_sid_of, self.real_cwd = park.session_id_of, park.proc_cwd
        park.proc_cwd = lambda pid: "/r/x"
        self.addCleanup(self.restore)

    def restore(self):
        park.session_id_of, park.proc_cwd = self.real_sid_of, self.real_cwd

    def table(self, *cmds):
        return {100 + i: {"ppid": 1, "rss": 0, "cmd": c}
                for i, c in enumerate(cmds)}

    def test_an_id_in_argv_is_used_directly(self):
        park.session_id_of = lambda pid, cwd=None: (None, None, None)
        got = park.live_session_ids(self.table(f"claude --resume {self.SID}"))
        self.assertEqual(got, {self.SID})

    def test_a_bare_resume_is_resolved_off_its_transcript(self):
        # cmux 0.64 restores agents as plain `claude --resume`, supplying the
        # id out of band. argv alone returns nothing and the guard goes blind.
        park.session_id_of = lambda pid, cwd=None: (self.OTHER, "/t.jsonl",
                                                    "lsof")
        got = park.live_session_ids(
            self.table("claude --dangerously-skip-permissions --resume"))
        self.assertEqual(got, {self.OTHER})

    def test_non_claude_processes_are_not_resolved(self):
        park.session_id_of = lambda pid, cwd=None: (self.OTHER, None, None)
        got = park.live_session_ids(
            self.table("vim /tmp/claude", "rg claude .", "node server.js"))
        self.assertEqual(got, set())

    def test_a_session_that_cannot_be_resolved_is_simply_absent(self):
        park.session_id_of = lambda pid, cwd=None: (None, None, None)
        got = park.live_session_ids(self.table("claude --resume"))
        self.assertEqual(got, set())

    def test_both_forms_together(self):
        park.session_id_of = lambda pid, cwd=None: (self.OTHER, None, "scan")
        got = park.live_session_ids(
            self.table(f"claude --resume {self.SID}", "claude --resume"))
        self.assertEqual(got, {self.SID, self.OTHER})


class TestBarePrompt(unittest.TestCase):
    """Guards `repaint` before it types into someone's shell."""

    def test_a_bare_prompt_is_safe_to_type_into(self):
        for line in ("❯", "~/Sites/x on main ❯", "$", "~/Sites/x % ",
                     "davidvesely@mac ~ % ", "➜  "):
            self.assertTrue(park.bare_prompt(line), line)

    def test_a_prompt_with_something_typed_is_not(self):
        for line in ("❯ git status", "❯ park unpark .", "$ rm -rf /"):
            self.assertFalse(park.bare_prompt(line), line)

    def test_a_half_typed_command_ending_in_a_glyph_is_not(self):
        # The naive "last character is a prompt glyph" test called all of these
        # bare, and repaint would then append its prefill to the user's line.
        for line in ("echo $", "grep # notes.md", "cat file >", "foo ➜  bar #"):
            self.assertFalse(park.bare_prompt(line), line)

    def test_an_unreadable_screen_is_not_bare(self):
        # prompt_line returns None when the surface cannot be read; typing
        # blind there is exactly what the guard exists to stop.
        self.assertFalse(park.bare_prompt(None))
        self.assertFalse(park.bare_prompt(""))


class TestProcessLiveness(unittest.TestCase):
    """Real processes: the zombie case is why this cannot be faked."""

    def spawn(self):
        p = subprocess.Popen([sys.executable, "-c", "import time;time.sleep(30)"])
        self.addCleanup(self.reap, p)
        return p

    def reap(self, p):
        if p.poll() is None:
            p.kill()
        p.wait()

    def test_a_live_process_is_running(self):
        p = self.spawn()
        self.assertEqual([x["pid"] for x in park.still_running([proc(p.pid, "x")])],
                         [p.pid])

    def test_a_zombie_is_not_running(self):
        # kill(pid, 0) succeeds for a zombie, which is exactly the trap: park
        # kills children before parents, so unreaped corpses read as survivors
        # and used to trigger the rollback that deletes the ledger.
        p = self.spawn()
        p.send_signal(signal.SIGKILL)
        for _ in range(100):                    # wait for it to become a corpse
            if p.poll() is None and os.path.exists(f"/proc/{p.pid}") is False:
                pass
            out = subprocess.run(["ps", "-o", "state=", "-p", str(p.pid)],
                                 capture_output=True, text=True).stdout.strip()
            if out.startswith("Z"):
                break
            time.sleep(0.02)
        else:
            p.wait()
            self.skipTest("the corpse was reaped before it could be observed")
        self.assertEqual(park.still_running([proc(p.pid, "x")]), [])

    def test_an_absent_pid_is_not_running(self):
        self.assertEqual(park.still_running([proc(999999, "gone")]), [])

    def test_wait_gone_returns_as_soon_as_they_die(self):
        p = self.spawn()
        p.send_signal(signal.SIGKILL)
        started = time.time()
        left = park.wait_gone([proc(p.pid, "x")], timeout=5.0)
        self.assertEqual(left, [])
        self.assertLess(time.time() - started, 2.0)   # not the full budget

    def test_wait_gone_gives_up_and_reports_the_survivor(self):
        p = self.spawn()
        left = park.wait_gone([proc(p.pid, "x")], timeout=0.4)
        self.assertEqual([x["pid"] for x in left], [p.pid])


class TestProcessIdentity(unittest.TestCase):
    """What stops park from SIGKILLing a tree it never measured."""

    def spawn(self):
        p = subprocess.Popen([sys.executable, "-c", "import time;time.sleep(30)"])
        self.addCleanup(lambda: (p.kill(), p.wait()))
        return p

    def test_etime_parses_every_shape_ps_emits(self):
        self.assertEqual(park.etime_seconds("12:34"), 754)
        self.assertEqual(park.etime_seconds("01:02:03"), 3723)
        self.assertEqual(park.etime_seconds("2-03:04:05"), 183845)
        self.assertIsNone(park.etime_seconds("what"))

    def test_ps_table_carries_a_start_time(self):
        p = self.spawn()
        row = park.ps_table()[p.pid]
        self.assertIsNotNone(row["start"])
        self.assertLess(abs(row["start"] - time.time()), 30)

    def test_the_same_process_matches(self):
        p = self.spawn()
        row = park.ps_table()[p.pid]
        self.assertTrue(park.pid_matches(
            {"pid": p.pid, "cmd": row["cmd"], "start": row["start"]}))

    def test_a_recycled_pid_running_the_same_command_does_not(self):
        # cmux 0.64 starts every agent as the same command line, so the
        # command alone cannot tell two sessions apart — only the start time.
        p = self.spawn()
        row = park.ps_table()[p.pid]
        self.assertFalse(park.pid_matches(
            {"pid": p.pid, "cmd": row["cmd"], "start": row["start"] - 600}))

    def test_a_snapshot_without_a_start_time_still_matches_on_command(self):
        p = self.spawn()
        row = park.ps_table()[p.pid]
        self.assertTrue(park.pid_matches({"pid": p.pid, "cmd": row["cmd"]}))

    def test_tree_pids_reaches_the_descendants_the_kill_would(self):
        table = {10: {"ppid": 1, "rss": 0, "cmd": "claude"},
                 11: {"ppid": 10, "rss": 0, "cmd": "node mcp"},
                 12: {"ppid": 11, "rss": 0, "cmd": "npm test"},
                 20: {"ppid": 1, "rss": 0, "cmd": "unrelated"}}
        self.assertEqual(park.tree_pids([proc(10, "claude")], table),
                         {10, 11, 12})


class TestSelfPids(unittest.TestCase):
    def test_our_own_ancestry_is_in_the_chain(self):
        chain = park.self_pids()
        self.assertIn(os.getpid(), chain)
        self.assertIn(os.getppid(), chain)

    def test_a_cycle_in_the_table_does_not_hang(self):
        me = os.getpid()
        park.self_pids({me: {"ppid": me}})


class TestPromptGuards(unittest.TestCase):
    """The two reads that stand between park and something the user typed."""

    BOX = "─" * 40

    def screen(self, lines):
        return lambda ws, surface=None: lines

    def test_a_fenced_draft_is_found(self):
        park.read_screen = self.screen([self.BOX, "> half a thought"])
        self.addCleanup(self.restore)
        self.assertEqual(park.unsent_input("ws"), "half a thought")

    def test_an_empty_input_box_is_not_a_draft(self):
        park.read_screen = self.screen([self.BOX, ">"])
        self.addCleanup(self.restore)
        self.assertEqual(park.unsent_input("ws"), "")

    def test_a_shell_prompt_is_not_a_draft(self):
        park.read_screen = self.screen(["~/Sites/foo ❯ ls -la"])
        self.addCleanup(self.restore)
        self.assertEqual(park.unsent_input("ws"), "")

    def test_an_unreadable_screen_is_not_no_draft(self):
        park.read_screen = lambda ws, surface=None: None
        self.addCleanup(self.restore)
        self.assertIsNone(park.unsent_input("ws"))

    def test_draft_guard_refuses_a_draft_in_any_tab(self):
        park.read_screen = self.screen([self.BOX, "> wait"])
        self.addCleanup(self.restore)
        why = park.draft_guard("ws", [proc(1, "claude", surface="s1"),
                                      proc(2, "claude", surface="s2")])
        self.assertIn("unsent text", why)

    def test_draft_guard_refuses_a_screen_it_cannot_read(self):
        park.read_screen = lambda ws, surface=None: None
        self.addCleanup(self.restore)
        self.assertIn("cannot read",
                      park.draft_guard("ws", [proc(1, "claude")]))

    def test_draft_guard_passes_a_clean_prompt(self):
        park.read_screen = self.screen(["~/Sites/foo ❯ "])
        self.addCleanup(self.restore)
        self.assertIsNone(park.draft_guard("ws", [proc(1, "claude")]))

    def restore(self):
        import importlib
        importlib.reload(park)


class TestClearPrefill(unittest.TestCase):
    def setUp(self):
        self.sent = []
        self.real_do, self.real_line = park.cmux_do, park.prompt_line
        park.cmux_do = lambda *a: self.sent.append(a) or True
        self.addCleanup(self.restore)

    def restore(self):
        park.cmux_do, park.prompt_line = self.real_do, self.real_line

    def test_our_own_prefill_is_cleared(self):
        park.prompt_line = lambda ws, s=None: f"~/x ❯ {park.PREFILL}"
        self.assertTrue(park.clear_prefill("ws", [{"surface": "s1"}]))
        self.assertEqual(len(self.sent), 1)
        self.assertIn("ctrl+u", self.sent[0])

    def test_a_line_the_user_typed_into_is_left_alone(self):
        park.prompt_line = lambda ws, s=None: f"~/x ❯ {park.PREFILL}rm -rf"
        self.assertTrue(park.clear_prefill("ws", [{"surface": "s1"}]))
        self.assertEqual(self.sent, [])

    def test_an_unrelated_line_is_left_alone(self):
        park.prompt_line = lambda ws, s=None: "~/x ❯ git status"
        park.clear_prefill("ws", [{"surface": "s1"}])
        self.assertEqual(self.sent, [])

    def test_an_unreadable_prompt_reports_failure(self):
        park.prompt_line = lambda ws, s=None: None
        self.assertFalse(park.clear_prefill("ws", [{"surface": "s1"}]))
        self.assertEqual(self.sent, [])


class TestPreparePrompt(unittest.TestCase):
    """The check that stands between unpark and a line the user is typing."""

    def setUp(self):
        self.sent = []
        self.real_do, self.real_line = park.cmux_do, park.prompt_line
        park.cmux_do = lambda *a: self.sent.append(a) or True
        self.addCleanup(self.restore)

    def restore(self):
        park.cmux_do, park.prompt_line = self.real_do, self.real_line

    def lines(self, *seq):
        """Successive prompt_line answers — clearing changes what is there."""
        it = iter(seq)
        last = [None]

        def read(ws, s=None):
            try:
                last[0] = next(it)
            except StopIteration:
                pass
            return last[0]
        park.prompt_line = read

    def test_our_prefill_is_cleared_and_the_line_is_then_bare(self):
        self.lines(f"~/x ❯ {park.PREFILL}", "~/x ❯ ")
        ok, why = park.prepare_prompt("ws", "s1")
        self.assertTrue(ok, why)
        self.assertIn("ctrl+u", self.sent[0])

    def test_a_bare_prompt_needs_no_clearing(self):
        self.lines("~/x ❯ ")
        self.assertEqual(park.prepare_prompt("ws"), (True, None))
        self.assertEqual(self.sent, [])

    def test_a_half_typed_command_is_refused(self):
        # The prefill is gone (a cmux restart wipes the buffer) and the user
        # started typing. The old check only looked for the prefill, said
        # "nothing of mine here" and appended the resume command + enter.
        self.lines("~/x ❯ git status")
        ok, why = park.prepare_prompt("ws")
        self.assertFalse(ok)
        self.assertIn("typed at the prompt", why)
        self.assertEqual(self.sent, [])

    def test_text_typed_after_our_prefill_survives_the_clear(self):
        # ctrl+u wipes the whole line, so what is left after clearing has to be
        # looked at again rather than assumed empty.
        self.lines(f"~/x ❯ {park.PREFILL}", "~/x ❯ rm -rf")
        ok, why = park.prepare_prompt("ws")
        self.assertFalse(ok)
        self.assertIn("typed at the prompt", why)

    def test_an_unreadable_prompt_is_refused(self):
        self.lines(None)
        ok, why = park.prepare_prompt("ws")
        self.assertFalse(ok)
        self.assertIn("cannot read", why)

    def test_a_failed_clear_is_refused(self):
        park.cmux_do = lambda *a: False
        self.lines(f"~/x ❯ {park.PREFILL}")
        ok, why = park.prepare_prompt("ws")
        self.assertFalse(ok)
        self.assertIn("would not clear", why)


class TestWaitForSessions(unittest.TestCase):
    """`cmux send` succeeding is not a session starting."""

    def test_a_live_session_is_confirmed(self):
        real = park.ps_table
        sid = "11111111-2222-3333-4444-555555555555"
        park.ps_table = lambda: {7: {"ppid": 1, "rss": 0, "start": 0,
                                     "cmd": f"claude --resume {sid}"}}
        self.addCleanup(lambda: setattr(park, "ps_table", real))
        self.assertEqual(park.wait_for_sessions([sid], timeout=0.1), {sid})

    def test_a_session_that_never_starts_is_not(self):
        real = park.ps_table
        park.ps_table = lambda: {}
        self.addCleanup(lambda: setattr(park, "ps_table", real))
        started = time.time()
        self.assertEqual(
            park.wait_for_sessions(["11111111-2222-3333-4444-555555555555"],
                                   timeout=0.3, step=0.1), set())
        self.assertLess(time.time() - started, 2.0)

    def test_case_does_not_hide_a_running_session(self):
        real = park.ps_table
        sid = "AAAAAAAA-2222-3333-4444-555555555555"
        park.ps_table = lambda: {7: {"ppid": 1, "rss": 0, "start": 0,
                                     "cmd": f"claude --resume {sid}"}}
        self.addCleanup(lambda: setattr(park, "ps_table", real))
        self.assertEqual(park.wait_for_sessions([sid.lower()], timeout=0.1),
                         {sid.lower()})


class TestFormatting(unittest.TestCase):
    def test_ago_reads_both_timestamp_dialects(self):
        # Ours is +00:00, cmux's ends in Z, and 3.9 rejects the Z form.
        now = datetime.now(timezone.utc)
        self.assertEqual(park.ago((now - timedelta(minutes=5)).isoformat()),
                         "5m ago")
        z = (now - timedelta(hours=3)).isoformat().replace("+00:00", "Z")
        self.assertEqual(park.ago(z), "3h ago")
        self.assertEqual(park.ago((now - timedelta(days=2)).isoformat()),
                         "2d ago")

    def test_ago_survives_junk(self):
        for bad in (None, "", "yesterday", 17):
            self.assertEqual(park.ago(bad), "?")

    def test_human(self):
        self.assertEqual(park.human(500 * 1024 * 1024), "500 MB")
        self.assertEqual(park.human(2 * 1024 ** 3), "2.0 GB")

    def test_bar_never_hides_a_nonzero_workspace(self):
        self.assertEqual(park.bar(0, 100, width=10, plain=True), "-" * 10)
        self.assertTrue(park.bar(1, 10 ** 9, width=10, plain=True).startswith("="))
        self.assertEqual(park.bar(100, 100, width=10, plain=True), "=" * 10)

    def test_bar_with_no_peak(self):
        self.assertEqual(park.bar(5, 0, width=4), "    ")


if __name__ == "__main__":
    unittest.main(verbosity=2)
