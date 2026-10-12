"""Process and port handling. The only module that touches running processes."""
import socket
import subprocess
import sys
import time


# Every console tool used here (tasklist, netstat, taskkill) prints in the
# console OEM codepage, not the ANSI codepage Python's text=True assumes.
#
# On this German Windows, tasklist's no-match line is
#   "INFORMATION: Es werden keine Aufgaben ... ausgefuehrt."
# where the "ue" is really U+00FC: byte 0x81 in the OEM codepage, and UNDEFINED
# in cp1252. With text=True that decode blows up inside subprocess's reader
# THREAD - so the traceback prints to stderr, .stdout comes back None, and no
# try/except wrapped around subprocess.run ever sees it. parse_tasklist(None)
# then raised AttributeError on EVERY dead pid, taking out the guard on the
# kill path. netstat and taskkill are localised the same way.
#
# encoding=OEM is the fix. errors="replace" is the belt to that braces: it makes
# a decode failure structurally impossible, so the reader thread can never die
# and hand us None again. Only ASCII fields (image names, pids, ports) are ever
# parsed out of this text, so a replacement character in localised prose is
# harmless.
OEM = "oem" if sys.platform == "win32" else "utf-8"

UNKNOWN = "unknown"

# port_owner's third answer: netstat could not be run, or did not come back
# usable, so we do NOT know who holds the port. Deliberately distinct from
# None ("asked, and the port is genuinely free") - a failed query is not
# evidence of a free port, and the caller must be able to tell them apart.
UNKNOWN_OWNER = (None, UNKNOWN)


def _console(argv, timeout, run=subprocess.run):
    """Run a Windows console tool, decoding its OEM-codepage output.

    Returns the CompletedProcess, or None if the tool could not be run at all.
    Every console call in this module goes through here, so the OEM decode
    cannot be fixed in one place and forgotten in another.

    `run` is injectable so each call site's exact argv can be asserted in tests
    without running anything real."""
    try:
        return run(argv, capture_output=True, encoding=OEM, errors="replace",
                   timeout=timeout)
    except (OSError, subprocess.SubprocessError):
        return None


def parse_netstat(text, port):
    """PID listening on `port`, or None. Matches row shape rather than the
    status word, because that word is localised (ABHOEREN on a German
    Windows, LISTENING on an English one)."""
    for line in text.splitlines():
        parts = line.split()
        if len(parts) < 5 or parts[0].upper() != "TCP":
            continue
        local, remote, pid = parts[1], parts[2], parts[-1]
        if local.rsplit(":", 1)[-1] != str(port):
            continue
        if not remote.endswith(":0"):        # a listener has no peer
            continue
        if pid.isdigit():
            return int(pid)
    return None


def parse_tasklist(text):
    """Image name from `tasklist /FO CSV /NH` output.

    Three answers, matching process_name's contract:
      - the image name
      - ""        no such process (no CSV row)
      - "unknown" `text` is None, i.e. we never got output to read

    Detection is by the absence of a CSV row, not by wording or exit code:
    tasklist exits 0 for a no-match and prints a localised INFORMATION line.

    None is tolerated rather than trusted-away: it means the output could not
    be read, which is NOT the same as "the process is gone". Returning ""
    there would tell kill()'s guard a live process had exited."""
    if text is None:
        return UNKNOWN
    first = text.strip().splitlines()[0] if text.strip() else ""
    if first.startswith('"'):
        return first.split('","')[0].strip('"')
    return ""


def process_name(pid, run=subprocess.run):
    """Image name for `pid`.

    Three distinct answers: the name; "" if no such process (it exited, so there
    is nothing to kill); "unknown" if tasklist itself could not be run, exited
    non-zero, or produced no readable output (we do not know, and must not
    assume). Never raises."""
    r = _console(["tasklist", "/FI", f"PID eq {pid}", "/FO", "CSV", "/NH"],
                 10, run)
    if r is None or r.returncode != 0:
        return UNKNOWN
    return parse_tasklist(r.stdout)


def port_owner(port, run=subprocess.run):
    """Who holds `port`. Three answers, and the third one matters:

      - (pid, name)     that process is listening
      - None            netstat answered and nothing is listening: it is free
      - UNKNOWN_OWNER   netstat could not be asked; we do NOT know

    A failed netstat used to be reported as "free", which is the one reading the
    evidence does not support. The caller decides what to do about not knowing;
    this function will not decide it by guessing.

    `(pid, "unknown")` is a fourth shading of the same idea: the port IS held,
    but tasklist could not say by what. kill() refuses on that name, so it
    cannot become permission to kill."""
    r = _console(["netstat", "-ano"], 20, run)
    if r is None or r.returncode != 0 or r.stdout is None:
        return UNKNOWN_OWNER
    pid = parse_netstat(r.stdout, port)
    if pid is None:
        return None
    name = process_name(pid, run=run)
    if name == "":
        return None            # the listener exited between netstat and tasklist
    return pid, name


def _force_kill(pid, run=subprocess.run):
    """The actual taskkill. Separated so kill()'s guard can be tested without
    terminating anything real.

    Targets one pid with /PID. Never /IM: an image-name kill would take out
    every llama-server on the machine, including ones this launcher never
    started and the user is still using."""
    r = _console(["taskkill", "/PID", str(pid), "/F"], 20, run)
    return r is not None and r.returncode == 0


def kill(pid, *, expect_name, expect_port=None, name_of=process_name,
         force=_force_kill, owner_of=port_owner):
    """Force-stop `pid`, but only if it is still `expect_name`. Returns True
    only if it was actually killed.

    `expect_name` is REQUIRED and keyword-only, deliberately. A default of None
    would mean a caller who forgets it silently gets unguarded killing, and the
    whole point of this function is that killing blind is unsafe: port_owner's
    snapshot can be minutes old by the time a user answers a confirmation
    prompt, and Windows recycles pids. Every call site must state what it
    believes it is killing.

    Refuses on a name mismatch, on "" (already gone) and on "unknown" (tasklist
    failed) - not knowing is not permission.

    THE REMAINING RACE, and it is real: the name check proves the pid is *a*
    llama-server, not *the* llama-server that held the port. Between port_owner's
    snapshot and here, the original could exit and a DIFFERENT llama-server (say,
    one the user started by hand) could take both the pid and the port. Passing
    `expect_port` closes most of that window by re-confirming, immediately before
    the kill, that this pid still owns the port we mean to free; it refuses if
    netstat cannot say. It cannot close the window completely - any check ends
    some microseconds before the taskkill, and only a kernel handle held from
    before the snapshot could make identity atomic. Narrower, honestly, is the
    best this pair of console tools can do.

    `name_of`, `force` and `owner_of` are injectable so both the refuse path AND
    the proceed path are testable without terminating a real process."""
    current = name_of(pid)
    if not current or current.lower() != expect_name.lower():
        return False
    if expect_port is not None:
        owner = owner_of(expect_port)
        # None (port went free), UNKNOWN_OWNER (netstat failed) and a different
        # pid all mean the same thing here: this is not provably the process
        # that holds the port, so it is not ours to kill.
        if not owner or owner[0] != pid:
            return False
    return force(pid)


def port_open(host, port, timeout=0.5):
    """True only if a TCP connection to host:port succeeds.

    Anything that cannot be connected to is a closed port from here: an
    unresolvable or IPv6-only host (gaierror), a host or port of the wrong type
    from a hand-edited config (TypeError), a port outside 0-65535
    (OverflowError). This is a probe, and a probe reports rather than raises -
    it is called in a poll loop where an exception would abort the wait
    entirely."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(timeout)
            return s.connect_ex((host, port)) == 0
    except (OSError, TypeError, ValueError, OverflowError):
        return False


def wait_ready(host, port, proc, timeout=300, tick=None,
               probe=port_open, sleep=time.sleep, clock=time.monotonic):
    """Poll until the port accepts a connection. Condition-based, not a fixed
    sleep: a 20 GB model takes far longer to load than a 1 GB one.

    Returns (ok, message). The injected probe/sleep/clock keep this testable
    without opening real sockets.

    LIVENESS IS CHECKED BEFORE THE PORT, and the order is the whole point. An
    open port is not proof that OUR child opened it - a foreign process may
    already be listening there, which is exactly why llama-server would have
    died on startup in the first place. Probing first read that foreign
    listener as our success and sent the user to someone else's server. Asking
    "is the child alive?" first means a dead child is always reported as dead.
    A window remains while the child is alive but doomed; closing it fully would
    mean matching the listener's pid to proc.pid on every probe."""
    if proc is None:
        # spawn() returns None when llama-server could not be started at all.
        # Without this, the poll below would probe a port nothing of ours is
        # ever going to open - and report a stranger's listener as success.
        return False, ("llama-server did not start - check that the "
                       "llama-server.exe path is still correct")
    start = clock()
    while True:
        if proc.poll() is not None:
            return False, (f"llama-server exited with code {proc.returncode} "
                           f"before the port opened - check its console window")
        if probe(host, port):
            return True, f"http://{host}:{port}"
        if clock() - start > timeout:
            return False, f"timed out after {timeout}s waiting for {host}:{port}"
        if tick:
            tick()
        sleep(0.5)


def spawn(argv, popen=subprocess.Popen):
    """Start llama-server in its own console window.

    Returns the process handle, or None if it could not be started - the exe
    having been moved, renamed or deleted mid-session is the ordinary case, and
    it used to escape as a raw OSError traceback. Returning None keeps that a
    reportable outcome: wait_ready(proc=None) turns it into a plain failure
    message, so even a caller that does not check gets a clean report instead
    of a stack trace.

    `popen` is injectable so the platform guard and argument handling can be
    tested without actually starting a process."""
    flags = subprocess.CREATE_NEW_CONSOLE if sys.platform == "win32" else 0
    try:
        return popen(argv, creationflags=flags)
    except OSError:
        return None
