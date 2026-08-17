# -*- coding: utf-8 -*-
import socket
import subprocess
import sys
import unittest

from launcher import server

NETSTAT = """
Aktive Verbindungen

  Proto  Lokale Adresse         Remoteadresse          Status           PID
  TCP    0.0.0.0:135            0.0.0.0:0              ABHÖREN          1832
  TCP    127.0.0.1:8080         0.0.0.0:0              ABHÖREN          19004
  TCP    127.0.0.1:8082         127.0.0.1:51234        HERGESTELLT      31337
  TCP    127.0.0.1:8082         0.0.0.0:0              ABHÖREN          24188
  TCP    127.0.0.1:8090         127.0.0.1:51999        WARTEND          0
  TCP    [::]:445               [::]:0                 ABHÖREN          4
"""

# Real `tasklist /FI "PID eq N" /FO CSV /NH` output from this machine. Note the
# no-match case is German AND exits 0, so neither the wording nor the return code
# can be used to detect it - only the absence of a CSV row can.
TASKLIST_FOUND = '"System","4","Services","0","14.348 K"\n'
TASKLIST_MISSING = ("INFORMATION: Es werden keine Aufgaben mit den angegebenen "
                    "Kriterien ausgeführt.\n")


class TestParseNetstat(unittest.TestCase):
    def test_finds_the_listening_pid(self):
        self.assertEqual(server.parse_netstat(NETSTAT, 8080), 19004)
        self.assertEqual(server.parse_netstat(NETSTAT, 8082), 24188)

    def test_returns_none_for_a_free_port(self):
        self.assertIsNone(server.parse_netstat(NETSTAT, 9999))

    def test_ignores_established_rows(self):
        """8082 has both an ESTABLISHED and a LISTENING row; only the listener
        identifies the owner.

        The fixture deliberately puts the ESTABLISHED row FIRST and gives it a
        different PID. Both details are load-bearing: with the same PID, or with
        the listener first, this test would pass even with the shape check
        deleted, and would prove nothing."""
        self.assertEqual(server.parse_netstat(NETSTAT, 8082), 24188)

    def test_does_not_match_a_port_that_is_a_prefix(self):
        """Port 808 must not match the 8080 row."""
        self.assertIsNone(server.parse_netstat(NETSTAT, 808))

    def test_handles_ipv6_rows(self):
        self.assertEqual(server.parse_netstat(NETSTAT, 445), 4)

    def test_ignores_time_wait_rows(self):
        """A WARTEND row has a real peer address and pid 0; it owns nothing."""
        self.assertIsNone(server.parse_netstat(NETSTAT, 8090))

    def test_does_not_depend_on_the_localised_status_word(self):
        """The same rows with English status words must parse identically."""
        english = (NETSTAT.replace("ABHÖREN", "LISTENING")
                          .replace("HERGESTELLT", "ESTABLISHED")
                          .replace("WARTEND", "TIME_WAIT"))
        self.assertEqual(server.parse_netstat(english, 8082), 24188)
        self.assertIsNone(server.parse_netstat(english, 9999))

    def test_empty_output_is_safe(self):
        self.assertIsNone(server.parse_netstat("", 8080))


class TestParseTasklist(unittest.TestCase):
    def test_extracts_the_image_name(self):
        self.assertEqual(server.parse_tasklist(TASKLIST_FOUND), "System")

    def test_no_such_process_is_empty_not_unknown(self):
        """'The process is gone' and 'we could not ask' are different answers.
        Conflating them would let a caller's safety gate misread one for the
        other. tasklist exits 0 in this case, so only the absent CSV row
        distinguishes it."""
        self.assertEqual(server.parse_tasklist(TASKLIST_MISSING), "")

    def test_empty_output_is_empty(self):
        self.assertEqual(server.parse_tasklist(""), "")

    def test_none_output_is_unknown_not_empty(self):
        """None means the output could never be read - the decode died in
        subprocess's reader thread, where our try/except cannot reach. That is
        'we could not ask', not 'the process is gone'. Returning "" here would
        tell kill()'s guard that a live process had exited."""
        self.assertEqual(server.parse_tasklist(None), "unknown")


class Completed:
    """Minimal stand-in for subprocess.CompletedProcess."""

    def __init__(self, stdout="", returncode=0):
        self.stdout = stdout
        self.stderr = ""
        self.returncode = returncode


class FakeRun:
    """Stands in for subprocess.run: records the exact argv and kwargs of every
    console call and answers by tool name.

    These three functions shell out to tasklist, netstat and taskkill, so this
    is the only way to assert what they actually ask the machine to do without
    running it. `taskkill /IM llama-server.exe` would kill every llama-server on
    the box - the regression this launcher exists to prevent - and it is exactly
    as testable as it is dangerous, but only against a recorded argv."""

    def __init__(self, raises=None, **answers):
        self.calls = []                  # (argv, kwargs) per call, in order
        self.raises = raises
        self.answers = answers           # tasklist=..., netstat=..., taskkill=...

    def __call__(self, argv, **kwargs):
        self.calls.append((argv, kwargs))
        if self.raises is not None:
            raise self.raises
        return self.answers.get(argv[0], Completed())

    def argv(self, tool):
        for argv, _ in self.calls:
            if argv[0] == tool:
                return argv
        raise AssertionError(f"{tool} was never run; ran {self.tools()}")

    def kwargs(self, tool):
        for argv, kwargs in self.calls:
            if argv[0] == tool:
                return kwargs
        raise AssertionError(f"{tool} was never run; ran {self.tools()}")

    def tools(self):
        return [argv[0] for argv, _ in self.calls]


class TestConsoleDecoding(unittest.TestCase):
    """The bug that crashed process_name on EVERY dead pid.

    German tasklist's no-match line carries U+00FC as byte 0x81 in the OEM
    codepage. cp1252 - what text=True picks - has no 0x81, and the decode runs
    in subprocess's READER THREAD: the exception prints to stderr, .stdout comes
    back None, and the try/except around subprocess.run never sees a thing.

    The real failure cannot be provoked from a unit test (it needs the real
    localised tasklist), so the guarantee is asserted where it lives: the
    encoding actually passed to subprocess.run."""

    def test_every_console_tool_decodes_with_the_oem_codepage(self):
        run = FakeRun(netstat=Completed(NETSTAT),
                      tasklist=Completed(TASKLIST_FOUND))
        server.port_owner(8080, run=run)
        server._force_kill(4321, run=run)
        self.assertEqual(sorted(run.tools()), ["netstat", "taskkill", "tasklist"])
        for tool in run.tools():
            self.assertEqual(run.kwargs(tool)["encoding"], server.OEM, tool)
            self.assertEqual(run.kwargs(tool)["errors"], "replace", tool)

    @unittest.skipUnless(sys.platform == "win32", "OEM is a Windows codepage")
    def test_oem_is_the_console_codepage_not_the_ansi_one(self):
        """cp1252 is the ANSI codepage; console tools print in the OEM one."""
        self.assertEqual(server.OEM, "oem")

    def test_every_console_tool_has_a_timeout(self):
        """A console tool that never returns would hang the launcher forever."""
        run = FakeRun(netstat=Completed(NETSTAT),
                      tasklist=Completed(TASKLIST_FOUND))
        server.port_owner(8080, run=run)
        server._force_kill(4321, run=run)
        for tool in run.tools():
            self.assertGreater(run.kwargs(tool)["timeout"], 0, tool)


class TestProcessName(unittest.TestCase):
    """process_name is the guard on the kill path and had no test caller at
    all: its crash took out both port_owner's 'listener exited' branch and
    kill()'s 'already gone' refusal."""

    def name(self, run):
        return server.process_name(4321, run=run)

    def test_asks_tasklist_about_exactly_one_pid(self):
        """The argv is the safety property. A filter on IMAGENAME instead of
        PID would answer about some other llama-server entirely."""
        run = FakeRun(tasklist=Completed(TASKLIST_FOUND))
        self.name(run)
        self.assertEqual(run.argv("tasklist"),
                         ["tasklist", "/FI", "PID eq 4321", "/FO", "CSV", "/NH"])

    def test_returns_the_image_name(self):
        self.assertEqual(self.name(FakeRun(tasklist=Completed(TASKLIST_FOUND))),
                         "System")

    def test_a_process_that_is_gone_is_empty_string(self):
        """Answer two of three. TASKLIST_MISSING is the real German no-match
        line from this machine, and tasklist exits 0 while printing it."""
        self.assertEqual(self.name(FakeRun(tasklist=Completed(TASKLIST_MISSING))),
                         "")

    def test_a_decode_failure_is_unknown_not_empty(self):
        """Answer three. stdout is None exactly as the reader thread leaves it
        when the decode dies. This used to raise AttributeError on every dead
        pid; reporting "" instead would be worse still, because "" means
        'already gone' and would let a caller believe a live process had
        exited."""
        run = FakeRun(tasklist=Completed(None))
        self.assertEqual(self.name(run), "unknown")

    def test_tasklist_that_cannot_be_run_is_unknown(self):
        self.assertEqual(self.name(FakeRun(raises=OSError("no tasklist"))),
                         "unknown")

    def test_tasklist_that_times_out_is_unknown(self):
        boom = subprocess.TimeoutExpired(cmd="tasklist", timeout=10)
        self.assertEqual(self.name(FakeRun(raises=boom)), "unknown")

    def test_tasklist_that_exits_nonzero_is_unknown(self):
        """A non-zero exit with empty stdout is a failed query, not a missing
        process - and "" would be read as 'already gone'."""
        run = FakeRun(tasklist=Completed("", returncode=1))
        self.assertEqual(self.name(run), "unknown")


class TestPortOwner(unittest.TestCase):
    """port_owner had no test caller either, including for the argv that
    decides which process gets force-killed."""

    def test_asks_netstat_for_all_connections_with_pids(self):
        run = FakeRun(netstat=Completed(NETSTAT),
                      tasklist=Completed(TASKLIST_FOUND))
        server.port_owner(8080, run=run)
        self.assertEqual(run.argv("netstat"), ["netstat", "-ano"])

    def test_reports_the_pid_and_the_image_name(self):
        run = FakeRun(netstat=Completed(NETSTAT),
                      tasklist=Completed(TASKLIST_FOUND))
        self.assertEqual(server.port_owner(8080, run=run), (19004, "System"))

    def test_a_free_port_is_none(self):
        run = FakeRun(netstat=Completed(NETSTAT))
        self.assertIsNone(server.port_owner(9999, run=run))

    def test_a_netstat_that_cannot_be_run_is_not_a_free_port(self):
        """'Could not determine' is not evidence the port is unused. Returning
        None here would send the launcher on to start a server on a port
        something else may well be holding."""
        owner = server.port_owner(8080, run=FakeRun(raises=OSError("no netstat")))
        self.assertIsNotNone(owner)
        self.assertEqual(owner, server.UNKNOWN_OWNER)
        self.assertEqual(owner[1], "unknown")

    def test_a_netstat_that_exits_nonzero_is_not_a_free_port(self):
        run = FakeRun(netstat=Completed("", returncode=1))
        self.assertEqual(server.port_owner(8080, run=run), server.UNKNOWN_OWNER)

    def test_a_netstat_whose_output_could_not_be_decoded_is_not_a_free_port(self):
        """netstat is localised too, so it has the same 0x81 exposure."""
        run = FakeRun(netstat=Completed(None))
        self.assertEqual(server.port_owner(8080, run=run), server.UNKNOWN_OWNER)

    def test_a_listener_that_exited_meanwhile_reads_as_free(self):
        """netstat saw it, tasklist says it is gone: the port really is free."""
        run = FakeRun(netstat=Completed(NETSTAT),
                      tasklist=Completed(TASKLIST_MISSING))
        self.assertIsNone(server.port_owner(8080, run=run))

    def test_a_held_port_whose_owner_cannot_be_named_stays_unknown(self):
        """The port IS held; we just cannot say by what. Reporting it free
        would be a lie, and the name kill() refuses on keeps it unkillable."""
        run = FakeRun(netstat=Completed(NETSTAT), tasklist=Completed(None))
        self.assertEqual(server.port_owner(8080, run=run), (19004, "unknown"))


class TestForceKill(unittest.TestCase):
    """The one function that actually terminates a process, previously with no
    test of the command it runs."""

    def test_targets_one_pid_and_never_an_image_name(self):
        """THE regression this project exists to prevent. `taskkill /IM
        llama-server.exe` exits 0 and looks like a success while killing every
        llama-server on the machine - including ones the user started by hand
        and is still using. Only a /PID argv is acceptable."""
        run = FakeRun(taskkill=Completed(""))
        server._force_kill(4321, run=run)
        argv = run.argv("taskkill")
        self.assertEqual(argv, ["taskkill", "/PID", "4321", "/F"])
        self.assertNotIn("/IM", argv)
        self.assertNotIn("llama-server.exe", argv)

    def test_true_only_on_a_zero_exit(self):
        self.assertIs(server._force_kill(4321, run=FakeRun(taskkill=Completed(""))),
                      True)

    def test_false_when_taskkill_refuses(self):
        """Access denied, or the pid was already gone: nothing was killed."""
        run = FakeRun(taskkill=Completed("", returncode=1))
        self.assertIs(server._force_kill(4321, run=run), False)

    def test_false_when_taskkill_cannot_be_run(self):
        self.assertIs(server._force_kill(4321, run=FakeRun(raises=OSError())),
                      False)


class TestKillGuard(unittest.TestCase):
    """kill() force-terminates a real process. port_owner's snapshot can be
    minutes old by the time a user answers a prompt, and Windows recycles PIDs -
    so identity is re-checked immediately before the kill.

    Every test here injects both `name_of` and `force`, so nothing real dies."""

    def kill(self, reported, expect="llama-server.exe"):
        """Returns (result, pids actually passed to the killer)."""
        killed = []
        result = server.kill(4321, expect_name=expect,
                             name_of=lambda pid: reported,
                             force=lambda pid: killed.append(pid) or True)
        return result, killed

    def test_proceeds_when_the_name_matches(self):
        """The positive path. Without this, a regression to 'always refuse'
        would pass every other test in this class while making the launcher
        permanently unable to take a busy port."""
        result, killed = self.kill("llama-server.exe")
        self.assertTrue(result)
        self.assertEqual(killed, [4321])

    def test_match_is_case_insensitive(self):
        result, killed = self.kill("LLAMA-SERVER.EXE")
        self.assertTrue(result)
        self.assertEqual(killed, [4321])

    def test_refuses_when_the_name_no_longer_matches(self):
        result, killed = self.kill("notepad.exe")
        self.assertFalse(result)
        self.assertEqual(killed, [], "must not have called the killer at all")

    def test_refuses_when_the_process_has_vanished(self):
        result, killed = self.kill("")
        self.assertFalse(result)
        self.assertEqual(killed, [])

    def test_refuses_when_the_name_is_unknown(self):
        """'unknown' means tasklist itself failed. Not knowing is not permission."""
        result, killed = self.kill("unknown")
        self.assertFalse(result)
        self.assertEqual(killed, [])

    def test_refuses_a_running_llama_server_when_that_is_not_what_was_expected(self):
        """The mismatch guard runs in BOTH directions. Here the live process is
        a llama-server but the caller expected something else - a comparison
        hard-coded to 'llama-server.exe', or one that only checked `current` for
        truthiness, would kill it anyway."""
        result, killed = self.kill("llama-server.exe", expect="notepad.exe")
        self.assertFalse(result)
        self.assertEqual(killed, [])

    def test_refuses_every_name_that_is_not_the_running_image(self):
        result, killed = self.kill("llama-server.exe", expect="llama-server")
        self.assertFalse(result)
        result, killed = self.kill("llama-server.exe", expect="xllama-server.exe")
        self.assertFalse(result)
        self.assertEqual(killed, [])

    def test_expect_name_is_required_and_keyword_only(self):
        """A default would let a caller silently fall back to unguarded killing."""
        with self.assertRaises(TypeError):
            server.kill(4321)
        with self.assertRaises(TypeError):
            server.kill(4321, "llama-server.exe")     # positional not allowed


class TestKillPortGuard(unittest.TestCase):
    """The name check proves the pid is *a* llama-server, not *the* one that
    held the port. Passing expect_port re-confirms ownership immediately before
    the kill, so a different llama-server that inherited the recycled pid is
    refused rather than killed."""

    def kill(self, owner, expect_port=8080, reported="llama-server.exe"):
        killed = []
        result = server.kill(4321, expect_name="llama-server.exe",
                             expect_port=expect_port,
                             name_of=lambda pid: reported,
                             force=lambda pid: killed.append(pid) or True,
                             owner_of=lambda port: owner)
        return result, killed

    def test_proceeds_when_the_pid_still_owns_the_port(self):
        result, killed = self.kill((4321, "llama-server.exe"))
        self.assertTrue(result)
        self.assertEqual(killed, [4321])

    def test_refuses_a_different_llama_server_on_the_same_pid(self):
        """Name matches, pid matches, but the port is now held by someone else:
        the process we meant to stop is gone and this one is a stranger."""
        result, killed = self.kill((9999, "llama-server.exe"))
        self.assertFalse(result)
        self.assertEqual(killed, [], "must not have called the killer at all")

    def test_refuses_when_netstat_could_not_say(self):
        """Not knowing is not permission, here as everywhere else."""
        result, killed = self.kill(server.UNKNOWN_OWNER)
        self.assertFalse(result)
        self.assertEqual(killed, [])

    def test_refuses_when_the_port_is_already_free(self):
        """Nothing holds it, so there is nothing to take and nothing to kill."""
        result, killed = self.kill(None)
        self.assertFalse(result)
        self.assertEqual(killed, [])

    def test_the_port_check_is_opt_in_and_costs_nothing_when_unused(self):
        """Callers that pass no expect_port must not pay for a netstat - and
        must not have their kill blocked by one that fails."""
        def boom(port):
            raise AssertionError("owner_of must not be consulted")

        killed = []
        result = server.kill(4321, expect_name="llama-server.exe",
                             name_of=lambda pid: "llama-server.exe",
                             force=lambda pid: killed.append(pid) or True,
                             owner_of=boom)
        self.assertTrue(result)
        self.assertEqual(killed, [4321])

    def test_the_name_check_still_applies_with_a_port(self):
        result, killed = self.kill((4321, "notepad.exe"), reported="notepad.exe")
        self.assertFalse(result)
        self.assertEqual(killed, [])


class FakeProc:
    """Stands in for Popen. `dies_after` counts poll() calls before exit."""
    def __init__(self, dies_after=None, returncode=1):
        self.calls = 0
        self.dies_after = dies_after
        self.returncode = returncode

    def poll(self):
        self.calls += 1
        if self.dies_after is not None and self.calls >= self.dies_after:
            return self.returncode
        return None


class TestWaitReady(unittest.TestCase):
    def test_reports_ready_once_the_port_accepts(self):
        opens = iter([False, False, True])
        ok, msg = server.wait_ready("127.0.0.1", 8080, FakeProc(),
                                    timeout=5, tick=lambda: None,
                                    probe=lambda h, p: next(opens),
                                    sleep=lambda s: None)
        # assertIs, not assertTrue: a swapped return of (msg, ok) would make ok a
        # non-empty string, which assertTrue accepts. And the message is checked
        # because callers print it - a wrong tuple order would print "-> True".
        self.assertIs(ok, True)
        self.assertEqual(msg, "http://127.0.0.1:8080")

    def test_tick_is_called_while_waiting(self):
        """Without this, deleting the tick call ships silently - and the user
        watches a frozen screen for the minutes a 20 GB model takes to load,
        with no way to tell it apart from a hang."""
        ticks = []
        opens = iter([False, False, True])
        server.wait_ready("127.0.0.1", 8080, FakeProc(),
                          timeout=5, tick=lambda: ticks.append(1),
                          probe=lambda h, p: next(opens),
                          sleep=lambda s: None)
        self.assertEqual(len(ticks), 2)      # two waits before the third probe

    def test_reports_failure_when_the_process_dies(self):
        ok, msg = server.wait_ready("127.0.0.1", 8080, FakeProc(dies_after=2),
                                    timeout=5, tick=lambda: None,
                                    probe=lambda h, p: False,
                                    sleep=lambda s: None)
        self.assertIs(ok, False)
        self.assertIn("exited", msg)
        self.assertIn("1", msg)              # the child's return code

    def test_a_dead_child_beats_an_open_port(self):
        """The ordering bug. A foreign process already listening on that port is
        the usual REASON llama-server died on startup - so probing before
        checking liveness read the stranger's listener as our success and sent
        the user to someone else's server. The probe here always says open; the
        child is dead; the answer must still be failure."""
        probes = []
        ok, msg = server.wait_ready("127.0.0.1", 8080, FakeProc(dies_after=1),
                                    timeout=5, tick=lambda: None,
                                    probe=lambda h, p: probes.append(1) or True,
                                    sleep=lambda s: None)
        self.assertIs(ok, False)
        self.assertIn("exited", msg)
        self.assertEqual(probes, [], "must not have probed a dead child's port")

    def test_a_child_that_never_started_is_reported_not_probed(self):
        """spawn() returns None when llama-server could not be started. Probing
        then would test a port nothing of ours will ever open."""
        def boom(host, port):
            raise AssertionError("must not probe when there is no child")

        ok, msg = server.wait_ready("127.0.0.1", 8080, None, timeout=5,
                                    probe=boom, sleep=lambda s: None)
        self.assertIs(ok, False)
        self.assertIn("did not start", msg)

    def test_reports_failure_on_timeout(self):
        clock = iter([0, 1, 2, 3, 999])
        ok, msg = server.wait_ready("127.0.0.1", 8080, FakeProc(),
                                    timeout=5, tick=lambda: None,
                                    probe=lambda h, p: False,
                                    sleep=lambda s: None,
                                    clock=lambda: next(clock))
        self.assertIs(ok, False)
        self.assertIn("timed out", msg)


class TestPortOpen(unittest.TestCase):
    """Uses a loopback socket the test binds and closes itself: instant,
    deterministic, no network. A fake here would only test the fake."""

    def free_port(self):
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
        s.close()
        return port

    def test_true_when_something_is_listening(self):
        srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        srv.bind(("127.0.0.1", 0))
        srv.listen(1)
        self.addCleanup(srv.close)
        self.assertTrue(server.port_open("127.0.0.1", srv.getsockname()[1]))

    def test_false_when_nothing_is_listening(self):
        self.assertFalse(server.port_open("127.0.0.1", self.free_port()))

    def test_false_rather_than_raising_on_a_host_it_cannot_resolve(self):
        """An IPv6 literal through an AF_INET socket raises gaierror. This runs
        inside wait_ready's poll loop, where an exception does not mean 'closed'
        - it means the whole wait dies and the user gets a traceback."""
        self.assertIs(server.port_open("::1", 8080), False)

    def test_false_rather_than_raising_on_a_host_of_the_wrong_type(self):
        """A hand-edited config can put anything here; connect_ex raises
        TypeError on a non-string host."""
        self.assertIs(server.port_open(5, 8080), False)

    def test_false_rather_than_raising_on_a_port_of_the_wrong_type(self):
        self.assertIs(server.port_open("127.0.0.1", "8080"), False)

    def test_false_rather_than_raising_on_a_port_out_of_range(self):
        """connect_ex raises OverflowError, which is not an OSError."""
        self.assertIs(server.port_open("127.0.0.1", 999999), False)


class TestSpawn(unittest.TestCase):
    """popen is injected: the platform guard and argument handling are worth
    testing, starting a real console window is not."""

    def test_passes_argv_as_a_list_and_never_uses_a_shell(self):
        seen = {}

        def fake_popen(argv, **kwargs):
            seen["argv"] = argv
            seen["kwargs"] = kwargs
            return "proc"

        result = server.spawn(["a.exe", "--flag", "value with spaces"],
                              popen=fake_popen)
        self.assertEqual(result, "proc")
        self.assertEqual(seen["argv"], ["a.exe", "--flag", "value with spaces"])
        self.assertNotIn("shell", seen["kwargs"])

    def test_requests_its_own_console_on_windows(self):
        seen = {}
        server.spawn(["a.exe"], popen=lambda argv, **kw: seen.update(kw))
        expected = subprocess.CREATE_NEW_CONSOLE if sys.platform == "win32" else 0
        self.assertEqual(seen["creationflags"], expected)

    def test_returns_none_when_the_exe_has_moved(self):
        """llama-server.exe being moved, renamed or deleted mid-session is an
        ordinary event, and it used to reach the user as a raw OSError
        traceback. None is a reportable answer; an exception out of here is
        not."""
        def gone(argv, **kw):
            raise FileNotFoundError(2, "The system cannot find the file specified")

        self.assertIsNone(server.spawn([r"D:\gone\llama-server.exe"], popen=gone))

    def test_returns_none_when_the_exe_cannot_be_executed(self):
        def denied(argv, **kw):
            raise PermissionError(13, "Access is denied")

        self.assertIsNone(server.spawn(["a.exe"], popen=denied))

    def test_a_failed_spawn_flows_into_a_clean_wait_ready_failure(self):
        """The two halves of the contract, joined: spawn returns None, and a
        caller that passes that straight to wait_ready gets a printable failure
        rather than an AttributeError on None.poll()."""
        def gone(argv, **kw):
            raise FileNotFoundError(2, "no such file")

        proc = server.spawn(["a.exe"], popen=gone)
        ok, msg = server.wait_ready("127.0.0.1", 8080, proc,
                                    probe=lambda h, p: True, sleep=lambda s: None)
        self.assertIs(ok, False)
        self.assertIn("did not start", msg)


if __name__ == "__main__":
    unittest.main()
