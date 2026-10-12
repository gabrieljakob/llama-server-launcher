"""The process layer against a real process, on whatever OS this runs on.

test_server.py proves the contracts with a fake psutil. These prove the real
psutil honours them HERE: that a listener can be found without root, that its
creation time reads the same twice, and - on macOS, where the system-wide
socket table is refused - that the per-process fallback finds it.

The child is a few lines of Python that bind a port and sleep. It prints its
own pid, because on a Windows venv sys.executable is a redirector and the
process that ends up listening is that redirector's child.
"""
import socket
import subprocess
import sys
import time
import unittest

import psutil

from llama_launcher import server

CHILD = ("import os, socket, time\n"
         "s = socket.socket()\n"
         "s.bind(('127.0.0.1', 0))\n"
         "s.listen(1)\n"
         "print(os.getpid(), s.getsockname()[1], flush=True)\n"
         "time.sleep(120)\n")


def free_port():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class LiveListener(unittest.TestCase):
    """A real child process listening on a real port, torn down afterwards."""

    def setUp(self):
        self.child = subprocess.Popen([sys.executable, "-c", CHILD],
                                      stdout=subprocess.PIPE, text=True)
        self.addCleanup(self.stop_child)
        pid, port = self.child.stdout.readline().split()
        self.pid, self.port = int(pid), int(port)

    def stop_child(self):
        for pid in {getattr(self, "pid", self.child.pid), self.child.pid}:
            try:
                psutil.Process(pid).kill()
            except psutil.Error:
                pass
        self.child.wait(timeout=10)
        self.child.stdout.close()


class TestFindingARealListener(LiveListener):
    def test_the_listener_is_found_by_its_port(self):
        owner = server.port_owner(self.port)
        self.assertIsNotNone(owner, "a listening port must not read as free")
        self.assertEqual(owner.pid, self.pid)

    def test_its_name_is_readable_and_agrees_with_process_name(self):
        """Not compared with sys.executable: a venv redirector on Windows and
        a framework build on macOS both run under a name that differs from it.
        What kill() needs is that the two lookups agree and are readable."""
        owner = server.port_owner(self.port)
        self.assertNotIn(owner.name, ("", server.UNKNOWN))
        self.assertEqual(owner.name, server.process_name(self.pid))

    def test_its_creation_time_reads_the_same_twice(self):
        """kill() compares this for equality, so it has to be stable here."""
        owner = server.port_owner(self.port)
        self.assertIsNotNone(owner.started)
        self.assertEqual(server.process_started(self.pid), owner.started)
        self.assertEqual(server.process_started(self.pid), owner.started)

    def test_a_process_that_has_exited_has_no_name(self):
        psutil.Process(self.pid).kill()
        self.child.wait(timeout=10)
        deadline = time.monotonic() + 5
        while server.process_name(self.pid) != "" and time.monotonic() < deadline:
            time.sleep(0.1)
        self.assertEqual(server.process_name(self.pid), "")


class TestAFreePort(unittest.TestCase):
    def test_a_port_nothing_listens_on_reads_as_free(self):
        """On macOS this goes the long way round - table refused, every
        process asked, then the connect probe - and must still be None."""
        self.assertIsNone(server.port_owner(free_port()))


class TestStoppingARealListener(LiveListener):
    """Each refusal is checked the only way that means anything: the process
    is still there, still listening, afterwards."""

    def still_listening(self):
        owner = server.port_owner(self.port)
        return owner is not None and owner.pid == self.pid

    def test_the_wrong_name_is_refused_and_the_process_survives(self):
        owner = server.port_owner(self.port)
        stopped = server.kill(owner.pid, expect_name="not-" + owner.name,
                              expect_started=owner.started,
                              expect_port=self.port)
        self.assertIs(stopped, False)
        self.assertTrue(self.still_listening())

    def test_the_wrong_start_time_is_refused_and_the_process_survives(self):
        owner = server.port_owner(self.port)
        stopped = server.kill(owner.pid, expect_name=owner.name,
                              expect_started=owner.started + 60,
                              expect_port=self.port)
        self.assertIs(stopped, False)
        self.assertTrue(self.still_listening())

    def test_the_wrong_port_is_refused_and_the_process_survives(self):
        owner = server.port_owner(self.port)
        stopped = server.kill(owner.pid, expect_name=owner.name,
                              expect_started=owner.started,
                              expect_port=free_port())
        self.assertIs(stopped, False)
        self.assertTrue(self.still_listening())

    def test_the_right_identity_stops_it_and_frees_the_port(self):
        owner = server.port_owner(self.port)
        stopped = server.kill(owner.pid, expect_name=owner.name,
                              expect_started=owner.started,
                              expect_port=self.port)
        self.assertIs(stopped, True)
        deadline = time.monotonic() + 10
        while (server.port_owner(self.port) is not None
               and time.monotonic() < deadline):
            time.sleep(0.1)
        self.assertIsNone(server.port_owner(self.port))


if __name__ == "__main__":
    unittest.main()
