# -*- coding: utf-8 -*-
import unittest

from launcher import server

NETSTAT = """
Aktive Verbindungen

  Proto  Lokale Adresse         Remoteadresse          Status           PID
  TCP    0.0.0.0:135            0.0.0.0:0              ABHÖREN          1832
  TCP    127.0.0.1:8080         0.0.0.0:0              ABHÖREN          19004
  TCP    127.0.0.1:8082         0.0.0.0:0              ABHÖREN          24188
  TCP    127.0.0.1:8082         127.0.0.1:51234        HERGESTELLT      24188
  TCP    127.0.0.1:8090         127.0.0.1:51999        WARTEND          0
  TCP    [::]:445               [::]:0                 ABHÖREN          4
"""


class TestParseNetstat(unittest.TestCase):
    def test_finds_the_listening_pid(self):
        self.assertEqual(server.parse_netstat(NETSTAT, 8080), 19004)
        self.assertEqual(server.parse_netstat(NETSTAT, 8082), 24188)

    def test_returns_none_for_a_free_port(self):
        self.assertIsNone(server.parse_netstat(NETSTAT, 9999))

    def test_ignores_established_rows(self):
        """8082 has both a LISTENING and an ESTABLISHED row; only the
        listener identifies the owner."""
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


if __name__ == "__main__":
    unittest.main()
