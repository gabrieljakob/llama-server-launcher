# -*- coding: utf-8 -*-
import collections
import os
import socket
import subprocess
import sys
import tempfile
import unittest

import psutil

from llama_launcher import server

Addr = collections.namedtuple("Addr", "ip port")
# Rows from psutil.net_connections() carry a pid; a process's own rows do not.
Conn = collections.namedtuple("Conn", "laddr status pid")
OwnConn = collections.namedtuple("OwnConn", "laddr status")


def listening(port, pid, ip="127.0.0.1"):
    return Conn(Addr(ip, port), psutil.CONN_LISTEN, pid)


class FakeProcess:
    """Stands in for psutil.Process. Each read takes the exception it should
    raise, so every one of process_name's three answers can be reached."""

    def __init__(self, pid, name="llama-server", started=1000.5, conns=(),
                 name_error=None, started_error=None, conns_error=None):
        self.pid = pid
        self._name = name
        self._started = started
        self._conns = list(conns)
        self._name_error = name_error
        self._started_error = started_error
        self._conns_error = conns_error

    def name(self):
        if self._name_error is not None:
            raise self._name_error
        return self._name

    def create_time(self):
        if self._started_error is not None:
            raise self._started_error
        return self._started

    def net_connections(self, kind):
        if self._conns_error is not None:
            raise self._conns_error
        return list(self._conns)


class FakePs:
    """Stands in for the psutil MODULE, which is what server's functions take.

    The exception classes are psutil's own, so the `except ps.NoSuchProcess`
    clauses under test catch exactly what the real library raises. `calls`
    records every question asked of the machine: which pid, which table."""

    CONN_LISTEN = psutil.CONN_LISTEN
    Error = psutil.Error
    NoSuchProcess = psutil.NoSuchProcess
    AccessDenied = psutil.AccessDenied
    TimeoutExpired = psutil.TimeoutExpired

    def __init__(self, table=(), table_error=None, procs=()):
        self.table = list(table)
        self.table_error = table_error
        self.procs = {p.pid: p for p in procs}
        self.calls = []

    def net_connections(self, kind):
        self.calls.append(("net_connections", kind))
        if self.table_error is not None:
            raise self.table_error
        return list(self.table)

    def Process(self, pid):
        self.calls.append(("Process", pid))
        if pid not in self.procs:
            raise psutil.NoSuchProcess(pid)
        return self.procs[pid]

    def process_iter(self):
        self.calls.append(("process_iter",))
        return list(self.procs.values())


class TestProcessName(unittest.TestCase):
    """process_name is the guard on the stop path. Its three answers are
    different facts, and conflating any two of them is a safety bug."""

    def name(self, ps):
        return server.process_name(4321, ps=ps)

    def test_asks_about_exactly_one_pid(self):
        """The safety property. A lookup by NAME would answer about some other
        llama-server entirely."""
        ps = FakePs(procs=[FakeProcess(4321)])
        self.name(ps)
        self.assertEqual(ps.calls, [("Process", 4321)])

    def test_returns_the_name(self):
        ps = FakePs(procs=[FakeProcess(4321, name="llama-server")])
        self.assertEqual(self.name(ps), "llama-server")

    def test_a_process_that_is_gone_is_empty_string(self):
        """Answer two of three: it exited, so there is nothing to stop.
        FakePs raises NoSuchProcess for a pid it does not hold."""
        self.assertEqual(self.name(FakePs()), "")

    def test_a_zombie_is_gone_too(self):
        """Exited but not yet reaped. It holds no port and cannot be stopped."""
        zombie = FakeProcess(4321, name_error=psutil.ZombieProcess(4321))
        self.assertEqual(self.name(FakePs(procs=[zombie])), "")

    def test_access_denied_is_unknown_not_empty(self):
        """Answer three. "" would tell kill()'s guard a live process had
        exited; "unknown" says we could not ask, and not knowing is not
        permission."""
        denied = FakeProcess(4321, name_error=psutil.AccessDenied(4321))
        self.assertEqual(self.name(FakePs(procs=[denied])), "unknown")

    def test_an_os_error_is_unknown(self):
        broken = FakeProcess(4321, name_error=OSError("boom"))
        self.assertEqual(self.name(FakePs(procs=[broken])), "unknown")


class TestProcessStarted(unittest.TestCase):
    def test_returns_the_creation_time(self):
        ps = FakePs(procs=[FakeProcess(4321, started=1700000000.25)])
        self.assertEqual(server.process_started(4321, ps=ps), 1700000000.25)

    def test_a_process_that_is_gone_has_none(self):
        self.assertIsNone(server.process_started(4321, ps=FakePs()))

    def test_access_denied_is_none(self):
        denied = FakeProcess(4321, started_error=psutil.AccessDenied(4321))
        self.assertIsNone(server.process_started(4321, ps=FakePs(procs=[denied])))


def no_probe(host, port):
    raise AssertionError("the connect probe must not be consulted")


class TestPortOwner(unittest.TestCase):
    """Who holds a port, from the system-wide TCP table. Three answers, and
    the difference between "free" and "could not ask" is the point."""

    def owner(self, port, ps):
        return server.port_owner(port, ps=ps, probe=no_probe)

    def test_asks_for_the_tcp_table(self):
        ps = FakePs()
        self.owner(8080, ps)
        self.assertEqual(ps.calls[0], ("net_connections", "tcp"))

    def test_reports_the_pid_the_name_and_the_start_time(self):
        ps = FakePs(table=[listening(8080, 19004)],
                    procs=[FakeProcess(19004, name="llama-server", started=1000.5)])
        owner = self.owner(8080, ps)
        self.assertEqual(owner, server.Owner(19004, "llama-server", 1000.5))
        self.assertEqual((owner.pid, owner.name, owner.started),
                         (19004, "llama-server", 1000.5))

    def test_a_free_port_is_none(self):
        ps = FakePs(table=[listening(8080, 19004)], procs=[FakeProcess(19004)])
        self.assertIsNone(self.owner(9999, ps))

    def test_ignores_rows_that_are_not_listeners(self):
        """8082 has an ESTABLISHED row and a LISTEN row. The fixture puts the
        ESTABLISHED row FIRST and gives it a different pid. Both details are
        load-bearing: with the same pid, or with the listener first, this
        would pass with the status check deleted."""
        connected = Conn(Addr("127.0.0.1", 8082), psutil.CONN_ESTABLISHED, 31337)
        ps = FakePs(table=[connected, listening(8082, 24188)],
                    procs=[FakeProcess(31337), FakeProcess(24188)])
        self.assertEqual(self.owner(8082, ps).pid, 24188)

    def test_does_not_match_a_different_port(self):
        ps = FakePs(table=[listening(8080, 19004)], procs=[FakeProcess(19004)])
        self.assertIsNone(self.owner(808, ps))
        self.assertIsNone(self.owner(80800, ps))

    def test_a_row_without_an_address_is_skipped(self):
        """An unbound socket reports its address as an empty tuple."""
        ps = FakePs(table=[Conn((), psutil.CONN_LISTEN, 5)], procs=[FakeProcess(5)])
        self.assertIsNone(self.owner(8080, ps))

    def test_a_table_that_cannot_be_read_is_not_a_free_port(self):
        """'Could not determine' is not evidence the port is unused. Returning
        None here would send the launcher on to start a server on a port
        something else may well be holding."""
        owner = self.owner(8080, FakePs(table_error=psutil.Error()))
        self.assertIsNotNone(owner)
        self.assertEqual(owner, server.UNKNOWN_OWNER)
        self.assertIsNone(owner.pid)
        self.assertEqual(owner.name, "unknown")

    def test_an_os_error_reading_the_table_is_not_a_free_port(self):
        owner = self.owner(8080, FakePs(table_error=OSError("boom")))
        self.assertEqual(owner, server.UNKNOWN_OWNER)

    def test_a_listener_the_os_will_not_name_is_unknown(self):
        """Linux lists another user's listening socket without its pid. The
        port IS held; there is just nobody we are allowed to name."""
        ps = FakePs(table=[listening(8080, None)])
        self.assertEqual(self.owner(8080, ps), server.UNKNOWN_OWNER)

    def test_a_row_that_names_a_process_beats_one_that_does_not(self):
        """One port, two rows: an IPv6 row with no pid ahead of an IPv4 row
        with one. Stopping at the first would report a port we CAN identify
        as unidentifiable."""
        ps = FakePs(table=[listening(8080, None, ip="::"), listening(8080, 19004)],
                    procs=[FakeProcess(19004)])
        self.assertEqual(self.owner(8080, ps).pid, 19004)

    def test_a_listener_that_exited_meanwhile_reads_as_free(self):
        """The table saw it, the process is gone: the port really is free."""
        ps = FakePs(table=[listening(8080, 19004)])       # no such process
        self.assertIsNone(self.owner(8080, ps))

    def test_a_held_port_whose_owner_cannot_be_named_stays_unknown(self):
        """The port IS held; we just cannot say by what. Reporting it free
        would be a lie, and the name kill() refuses on keeps it unkillable."""
        denied = psutil.AccessDenied(19004)
        hidden = FakeProcess(19004, name_error=denied, started_error=denied)
        ps = FakePs(table=[listening(8080, 19004)], procs=[hidden])
        self.assertEqual(self.owner(8080, ps),
                         server.Owner(19004, "unknown", None))

    def test_the_probe_is_not_consulted_when_the_table_could_be_read(self):
        """The table is authoritative where the OS lets us read it. no_probe
        raises, so merely reaching these two answers is the assertion."""
        ps = FakePs(table=[listening(8080, 19004)], procs=[FakeProcess(19004)])
        self.assertIsNotNone(self.owner(8080, ps))
        self.assertIsNone(self.owner(9999, ps))


class TestPortOwnerWithoutTheSystemTable(unittest.TestCase):
    """macOS refuses the system-wide table to anyone but root, so the owner is
    found by asking each process for its own sockets. That walk cannot see
    another user's listener, which is why 'found nothing' is cross-checked
    with a connect before it is allowed to mean 'free'."""

    def ps(self, *procs):
        return FakePs(table_error=psutil.AccessDenied(), procs=procs)

    def own(self, port):
        return OwnConn(Addr("127.0.0.1", port), psutil.CONN_LISTEN)

    def test_falls_back_to_asking_each_process(self):
        ps = self.ps(FakeProcess(1), FakeProcess(19004, conns=[self.own(8080)]))
        owner = server.port_owner(8080, ps=ps, probe=no_probe)
        self.assertEqual(owner, server.Owner(19004, "llama-server", 1000.5))
        self.assertIn(("process_iter",), ps.calls)

    def test_skips_processes_that_deny_access_or_vanish(self):
        ps = self.ps(FakeProcess(1, conns_error=psutil.AccessDenied(1)),
                     FakeProcess(2, conns_error=psutil.NoSuchProcess(2)),
                     FakeProcess(19004, conns=[self.own(8080)]))
        self.assertEqual(server.port_owner(8080, ps=ps, probe=no_probe).pid, 19004)

    def test_finding_nothing_with_nothing_answering_is_free(self):
        ps = self.ps(FakeProcess(1, conns=[self.own(9000)]))
        self.assertIsNone(server.port_owner(8080, ps=ps, probe=lambda h, p: False))

    def test_finding_nothing_while_something_answers_is_unknown(self):
        """Somebody else's process holds it. Not ours to name, not ours to
        stop - and above all not free."""
        owner = server.port_owner(8080, ps=self.ps(FakeProcess(1)),
                                  probe=lambda h, p: True)
        self.assertEqual(owner, server.UNKNOWN_OWNER)

    def test_the_probe_is_a_local_connect_to_that_port(self):
        asked = []
        server.port_owner(8080, ps=self.ps(),
                          probe=lambda h, p: asked.append((h, p)) or False)
        self.assertEqual(asked, [("127.0.0.1", 8080)])


class Stoppable:
    """A fake psutil.Process for the stop sequence. `waits` scripts each wait()
    call in order: None means it exited in time, an exception is raised."""

    def __init__(self, waits=(None,), terminate_error=None, kill_error=None):
        self.pid = 4321
        self.calls = []
        self._waits = list(waits)
        self._terminate_error = terminate_error
        self._kill_error = kill_error

    def terminate(self):
        self.calls.append("terminate")
        if self._terminate_error is not None:
            raise self._terminate_error

    def kill(self):
        self.calls.append("kill")
        if self._kill_error is not None:
            raise self._kill_error

    def wait(self, timeout=None):
        self.calls.append(("wait", timeout))
        outcome = self._waits.pop(0)
        if outcome is not None:
            raise outcome


class TestStop(unittest.TestCase):
    """The one function that actually ends a process."""

    def stop(self, proc):
        ps = FakePs(procs=[proc])
        return server._stop(4321, ps=ps), ps

    def test_targets_exactly_one_pid(self):
        """THE regression this project exists to prevent. Stopping by name
        looks like a success while ending every llama-server on the machine -
        including ones the user started by hand and is still using."""
        _, ps = self.stop(Stoppable())
        self.assertEqual(ps.calls, [("Process", 4321)])

    def test_asks_first_and_does_not_force_a_process_that_exits_in_time(self):
        proc = Stoppable(waits=[None])
        result, _ = self.stop(proc)
        self.assertIs(result, True)
        self.assertEqual(server.STOP_GRACE, 5)
        self.assertEqual(proc.calls, ["terminate", ("wait", 5)])

    def test_forces_only_after_the_grace_period(self):
        proc = Stoppable(waits=[psutil.TimeoutExpired(5), None])
        result, _ = self.stop(proc)
        self.assertIs(result, True)
        self.assertEqual(proc.calls,
                         ["terminate", ("wait", 5), "kill", ("wait", 5)])

    def test_false_when_it_survives_even_the_force(self):
        proc = Stoppable(waits=[psutil.TimeoutExpired(5), psutil.TimeoutExpired(5)])
        result, _ = self.stop(proc)
        self.assertIs(result, False)

    def test_false_when_the_os_refuses(self):
        proc = Stoppable(terminate_error=psutil.AccessDenied(4321))
        result, _ = self.stop(proc)
        self.assertIs(result, False)
        self.assertEqual(proc.calls, ["terminate"])

    def test_a_process_that_is_already_gone_counts_as_stopped(self):
        """Nothing is running under that pid, which is what the caller asked
        for. FakePs raises NoSuchProcess for a pid it does not hold."""
        self.assertIs(server._stop(4321, ps=FakePs()), True)

    def test_a_process_that_exits_between_the_two_steps_counts_as_stopped(self):
        proc = Stoppable(waits=[psutil.TimeoutExpired(5)],
                         kill_error=psutil.NoSuchProcess(4321))
        result, _ = self.stop(proc)
        self.assertIs(result, True)

    def test_an_os_error_is_false(self):
        proc = Stoppable(terminate_error=OSError("boom"))
        result, _ = self.stop(proc)
        self.assertIs(result, False)


class TestKillGuard(unittest.TestCase):
    """kill() force-terminates a real process. port_owner's snapshot can be
    minutes old by the time a user answers a prompt, and Windows recycles PIDs -
    so identity is re-checked immediately before the kill.

    Every test here injects both `name_of` and `force`, so nothing real dies."""

    def kill(self, reported, expect="llama-server.exe"):
        """Returns (result, pids actually passed to the stopper)."""
        killed = []
        result = server.kill(4321, expect_name=expect, expect_started=1000.5,
                             name_of=lambda pid: reported,
                             started_of=lambda pid: 1000.5,
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

    def test_refuses_an_unreadable_name_even_if_that_is_the_expected_name(self):
        """"unknown" is process_name saying it could not ask. A binary that
        really is called "unknown" must not turn that into a match."""
        result, killed = self.kill("unknown", expect="unknown")
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
            server.kill(4321, expect_started=1000.5)
        with self.assertRaises(TypeError):
            server.kill(4321, "llama-server.exe", expect_started=1000.5)


class TestKillPortGuard(unittest.TestCase):
    """The name check proves the pid is *a* llama-server, not *the* one that
    held the port. Passing expect_port re-confirms ownership immediately before
    the kill, so a different llama-server that inherited the recycled pid is
    refused rather than killed."""

    def kill(self, owner, expect_port=8080, reported="llama-server.exe"):
        killed = []
        result = server.kill(4321, expect_name="llama-server.exe",
                             expect_started=1000.5, expect_port=expect_port,
                             name_of=lambda pid: reported,
                             started_of=lambda pid: 1000.5,
                             force=lambda pid: killed.append(pid) or True,
                             owner_of=lambda port: owner)
        return result, killed

    def test_proceeds_when_the_pid_still_owns_the_port(self):
        result, killed = self.kill(server.Owner(4321, "llama-server.exe", 1000.5))
        self.assertTrue(result)
        self.assertEqual(killed, [4321])

    def test_refuses_a_different_llama_server_on_the_same_pid(self):
        """Name matches, pid matches, but the port is now held by someone else:
        the process we meant to stop is gone and this one is a stranger."""
        result, killed = self.kill(server.Owner(9999, "llama-server.exe", 1000.5))
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
                             expect_started=1000.5,
                             name_of=lambda pid: "llama-server.exe",
                             started_of=lambda pid: 1000.5,
                             force=lambda pid: killed.append(pid) or True,
                             owner_of=boom)
        self.assertTrue(result)
        self.assertEqual(killed, [4321])

    def test_the_name_check_still_applies_with_a_port(self):
        result, killed = self.kill(server.Owner(4321, "notepad.exe", 1000.5), reported="notepad.exe")
        self.assertFalse(result)
        self.assertEqual(killed, [])


class TestKillStartGuard(unittest.TestCase):
    """The name proves the pid is *a* llama-server, and the port proves it is
    the one listening there NOW. Neither proves it is the process the user was
    asked about: that one may have exited, and a new llama-server may hold both
    its pid and its port. Only the creation time tells those two apart."""

    def kill(self, started_now, expect_started=1000.5, expect_port=None,
             owner=None):
        killed = []
        result = server.kill(4321, expect_name="llama-server",
                             expect_started=expect_started,
                             expect_port=expect_port,
                             name_of=lambda pid: "llama-server",
                             started_of=lambda pid: started_now,
                             force=lambda pid: killed.append(pid) or True,
                             owner_of=lambda port: owner)
        return result, killed

    def test_proceeds_when_the_start_time_is_unchanged(self):
        """The positive path, so 'always refuse' cannot pass this class."""
        result, killed = self.kill(1000.5)
        self.assertTrue(result)
        self.assertEqual(killed, [4321])

    def test_refuses_a_recycled_pid_even_under_the_same_name(self):
        result, killed = self.kill(2000.0)
        self.assertFalse(result)
        self.assertEqual(killed, [], "must not have called the stopper at all")

    def test_refuses_same_name_same_port_different_start_time(self):
        """The case the old guards could not see: every other check passes."""
        successor = server.Owner(4321, "llama-server", 2000.0)
        result, killed = self.kill(2000.0, expect_port=8080, owner=successor)
        self.assertFalse(result)
        self.assertEqual(killed, [])

    def test_refuses_when_the_start_time_cannot_be_read(self):
        result, killed = self.kill(None)
        self.assertFalse(result)
        self.assertEqual(killed, [])

    def test_refuses_when_no_start_time_was_recorded(self):
        """None == None must not read as 'unchanged'. An owner whose start
        time could not be read at snapshot time cannot be re-identified, and
        not knowing is not permission."""
        result, killed = self.kill(None, expect_started=None)
        self.assertFalse(result)
        self.assertEqual(killed, [])

    def test_expect_started_is_required_and_keyword_only(self):
        """For the reason expect_name is: a caller that forgets it must not
        silently get the weaker guard."""
        with self.assertRaises(TypeError):
            server.kill(4321, expect_name="llama-server")
        with self.assertRaises(TypeError):
            server.kill(4321, "llama-server", 1000.5)


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

    def test_a_dead_child_points_at_its_console_window_by_default(self):
        ok, msg = server.wait_ready("127.0.0.1", 8080, FakeProc(dies_after=1),
                                    probe=lambda h, p: False,
                                    sleep=lambda s: None)
        self.assertIs(ok, False)
        self.assertIn("check its console window", msg)

    def test_a_dead_child_points_at_its_log_when_there_is_one(self):
        ok, msg = server.wait_ready("127.0.0.1", 8080, FakeProc(dies_after=1),
                                    probe=lambda h, p: False,
                                    sleep=lambda s: None,
                                    where="see /logs/c-8080.log")
        self.assertIs(ok, False)
        self.assertIn("see /logs/c-8080.log", msg)
        self.assertNotIn("console window", msg)

    def test_a_child_that_never_started_is_not_told_about_an_exe(self):
        """The same message is read on Linux and macOS, where there is none."""
        ok, msg = server.wait_ready("127.0.0.1", 8080, None,
                                    sleep=lambda s: None)
        self.assertIn("did not start", msg)
        self.assertNotIn(".exe", msg)


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


class TestSpawnToALogFile(unittest.TestCase):
    """With a log path the server is detached and its output goes to a file -
    how Linux and macOS start it, having no second console to open."""

    def setUp(self):
        self.folder = tempfile.mkdtemp()
        self.log = os.path.join(self.folder, "logs", "c-8080.log")

    def spawn(self):
        seen = {}

        def fake_popen(argv, **kwargs):
            seen["argv"] = argv
            seen["kwargs"] = kwargs
            seen["log"] = kwargs["stdout"]
            return "proc"

        result = server.spawn(["llama-server", "--port", "8080"],
                              log_path=self.log, popen=fake_popen)
        return result, seen

    def test_output_goes_to_the_log_and_stdin_is_closed(self):
        result, seen = self.spawn()
        self.assertEqual(result, "proc")
        self.assertEqual(seen["argv"], ["llama-server", "--port", "8080"])
        self.assertEqual(seen["log"].name, self.log)
        self.assertIs(seen["kwargs"]["stderr"], subprocess.STDOUT)
        self.assertIs(seen["kwargs"]["stdin"], subprocess.DEVNULL)

    def test_the_server_is_detached_from_the_launchers_terminal(self):
        """Without a session of its own, Ctrl-C at the board and closing the
        terminal both reach the server."""
        _, seen = self.spawn()
        self.assertIs(seen["kwargs"]["start_new_session"], True)

    def test_no_console_window_is_requested(self):
        _, seen = self.spawn()
        self.assertNotIn("creationflags", seen["kwargs"])
        self.assertNotIn("shell", seen["kwargs"])

    def test_the_log_folder_is_created(self):
        self.assertFalse(os.path.exists(os.path.dirname(self.log)))
        self.spawn()
        self.assertTrue(os.path.isfile(self.log))

    def test_each_launch_starts_the_log_afresh(self):
        os.makedirs(os.path.dirname(self.log))
        with open(self.log, "w", encoding="utf-8") as f:
            f.write("the previous run")
        self.spawn()
        self.assertEqual(os.path.getsize(self.log), 0)

    def test_the_launchers_own_handle_is_closed_afterwards(self):
        """The child has its own copy. Keeping ours open would hold the file
        for as long as the launcher runs."""
        _, seen = self.spawn()
        self.assertTrue(seen["log"].closed)

    def test_a_log_that_cannot_be_opened_is_none_and_nothing_is_started(self):
        with open(os.path.join(self.folder, "logs"), "w", encoding="utf-8"):
            pass                              # a FILE where the folder goes

        def boom(argv, **kwargs):
            raise AssertionError("nothing may be started without its log")

        self.assertIsNone(server.spawn(["llama-server"], log_path=self.log,
                                       popen=boom))

    def test_returns_none_when_the_exe_has_moved(self):
        def gone(argv, **kwargs):
            raise FileNotFoundError(2, "No such file or directory")

        self.assertIsNone(server.spawn(["/gone/llama-server"],
                                       log_path=self.log, popen=gone))


class TestLogPathFor(unittest.TestCase):
    def test_named_after_the_config_and_the_port(self):
        self.assertEqual(server.log_path_for("qwen3.8", 8080, "logs"),
                         os.path.join("logs", "qwen3.8-8080.log"))

    def test_unsafe_characters_become_underscores(self):
        path = server.log_path_for("my config: v2", 8080, "logs")
        self.assertEqual(os.path.basename(path), "my_config__v2-8080.log")

    def test_a_name_cannot_climb_out_of_the_log_folder(self):
        """A config name is user text. However it is spelled, the file it
        names is directly inside the log folder."""
        folder = os.path.join("some", "logs")
        for name in ("../../etc/passwd", "..\\..\\boot.ini", "/abs", "C:\\x",
                     "..", "a/b", "qwen:3.8"):
            with self.subTest(name=name):
                path = server.log_path_for(name, 8080, folder)
                self.assertEqual(os.path.dirname(path), folder)
                self.assertNotIn("/", os.path.basename(path))
                self.assertNotIn("\\", os.path.basename(path))

    def test_a_name_that_is_not_a_string_still_makes_a_file_name(self):
        path = server.log_path_for(5, 8080, "logs")
        self.assertEqual(os.path.basename(path), "5-8080.log")


if __name__ == "__main__":
    unittest.main()
