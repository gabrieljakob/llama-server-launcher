# -*- coding: utf-8 -*-
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

    def test_expect_name_is_required_and_keyword_only(self):
        """A default would let a caller silently fall back to unguarded killing."""
        with self.assertRaises(TypeError):
            server.kill(4321)
        with self.assertRaises(TypeError):
            server.kill(4321, "llama-server.exe")     # positional not allowed


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
        self.assertTrue(ok)

    def test_reports_failure_when_the_process_dies(self):
        ok, msg = server.wait_ready("127.0.0.1", 8080, FakeProc(dies_after=2),
                                    timeout=5, tick=lambda: None,
                                    probe=lambda h, p: False,
                                    sleep=lambda s: None)
        self.assertFalse(ok)
        self.assertIn("exited", msg)

    def test_reports_failure_on_timeout(self):
        clock = iter([0, 1, 2, 3, 999])
        ok, msg = server.wait_ready("127.0.0.1", 8080, FakeProc(),
                                    timeout=5, tick=lambda: None,
                                    probe=lambda h, p: False,
                                    sleep=lambda s: None,
                                    clock=lambda: next(clock))
        self.assertFalse(ok)
        self.assertIn("timed out", msg)


if __name__ == "__main__":
    unittest.main()
