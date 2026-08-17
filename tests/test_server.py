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
    so identity is re-checked immediately before the kill."""

    def test_refuses_when_the_name_no_longer_matches(self):
        killed = server.kill(4321, expect_name="llama-server.exe",
                             name_of=lambda pid: "notepad.exe")
        self.assertFalse(killed)

    def test_refuses_when_the_process_has_vanished(self):
        killed = server.kill(4321, expect_name="llama-server.exe",
                             name_of=lambda pid: "")
        self.assertFalse(killed)

    def test_refuses_when_the_name_is_unknown(self):
        """'unknown' means tasklist itself failed. Not knowing is not permission."""
        killed = server.kill(4321, expect_name="llama-server.exe",
                             name_of=lambda pid: "unknown")
        self.assertFalse(killed)


if __name__ == "__main__":
    unittest.main()
