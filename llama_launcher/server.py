"""Process and port handling. The only module that touches running processes."""
import collections
import os
import re
import socket
import subprocess
import sys
import time

import psutil


UNKNOWN = "unknown"

# Who holds a port: the pid, the process name, and the moment that process was
# created. The creation time is what tells THIS process apart from a later one
# that was handed the same pid.
Owner = collections.namedtuple("Owner", "pid name started")

# port_owner's third answer: the port's state could not be determined, so we do
# NOT know who holds it. Deliberately distinct from None ("asked, and the port
# is genuinely free") - a failed query is not evidence of a free port, and the
# caller must be able to tell them apart.
UNKNOWN_OWNER = Owner(None, UNKNOWN, None)


def process_name(pid, ps=psutil):
    """Name of the process `pid`.

    Three distinct answers: the name; "" if no such process (it exited, so
    there is nothing to stop); "unknown" if the OS would not say (we do not
    know, and must not assume). Never raises.

    `ps` is the psutil module, injectable so each answer can be reached in
    tests without a real process in that state."""
    try:
        return ps.Process(pid).name()
    except ps.NoSuchProcess:
        return ""                # includes a zombie: exited, not yet reaped
    except (ps.Error, OSError):
        return UNKNOWN


def process_started(pid, ps=psutil):
    """When the process `pid` was created, as psutil reports it, or None if
    that cannot be read. kill() compares two of these for equality, so the
    value is passed around untouched - never rounded, never reformatted."""
    try:
        return ps.Process(pid).create_time()
    except (ps.Error, OSError):
        return None


def _listens_on(conn, port, ps):
    """Whether a psutil connection row is a TCP listener on `port`.

    Decided by the row's state, not by a status word in some tool's localised
    output. getattr, because an unbound socket reports its local address as an
    empty tuple."""
    return (conn.status == ps.CONN_LISTEN
            and getattr(conn.laddr, "port", None) == port)


def _table_listener(port, ps):
    """(held, pid) for `port`, from the system-wide TCP table.

    `held` is True if any row listens on the port. `pid` is the first such row
    that names a process, or None if none does - Linux lists another user's
    listening socket without its pid. A later row that names one wins over an
    earlier row that does not: one port is often listed twice, once per
    address family.

    Raises ps.AccessDenied where the OS refuses the table outright, which is
    what macOS does for anyone but root."""
    held = False
    for conn in ps.net_connections(kind="tcp"):
        if _listens_on(conn, port, ps):
            if conn.pid is not None:
                return True, conn.pid
            held = True
    return held, None


def _walk_listener(port, ps):
    """pid of a process listening on `port`, found by asking each process for
    its own sockets, or None.

    The fallback for when the system-wide table is refused. It sees only the
    processes this user may inspect, so None here is NOT 'free' - port_owner
    cross-checks it."""
    for proc in ps.process_iter():
        try:
            conns = proc.net_connections(kind="tcp")
        except (ps.Error, OSError):
            continue             # denied, or it exited while we were walking
        if any(_listens_on(conn, port, ps) for conn in conns):
            return proc.pid
    return None


def port_owner(port, ps=psutil, probe=None):
    """Who holds `port`. Three answers, and the third one matters:

      - Owner(pid, name, started)   that process is listening
      - None                        asked, and nothing is listening: it is free
      - UNKNOWN_OWNER               could not determine; we do NOT know

    A failed lookup used to be reported as "free", which is the one reading the
    evidence does not support. The caller decides what to do about not knowing;
    this function will not decide it by guessing.

    `Owner(pid, "unknown", None)` is a fourth shading of the same idea: the
    port IS held and we know by which pid, but the OS would not name it.
    kill() refuses on that name, so it cannot become permission to stop it.

    Which lookup runs is decided by what psutil raises, not by sys.platform.
    The system-wide table is authoritative where it can be read. Where it is
    refused, each process is asked instead - and because that walk cannot see
    another user's listener, "found nothing" is confirmed with a local connect
    before it is allowed to mean "free". A listener bound only to some other
    interface escapes that probe; llama-server's own bind failure, which
    wait_ready reports as an exit code, is the backstop there.

    `probe` is injectable (default: port_open) so the cross-check is testable
    without a socket."""
    if probe is None:
        probe = port_open
    try:
        try:
            held, pid = _table_listener(port, ps)
        except ps.AccessDenied:
            pid = _walk_listener(port, ps)
            if pid is None:
                return UNKNOWN_OWNER if probe("127.0.0.1", port) else None
            held = True
    except (ps.Error, OSError):
        return UNKNOWN_OWNER
    if not held:
        return None
    if pid is None:
        return UNKNOWN_OWNER     # held, by a process the OS will not name
    name = process_name(pid, ps=ps)
    if name == "":
        return None              # the listener exited between the two reads
    return Owner(pid, name, process_started(pid, ps=ps))


# How long a server gets to shut down after being asked, before it is forced.
STOP_GRACE = 5


def _stop(pid, ps=psutil, grace=STOP_GRACE):
    """Stop one process: ask, wait, then force. True if it is not running
    afterwards. Separated from kill() so the guards can be tested without
    stopping anything real.

    Addresses exactly one pid, never a name: stopping by name would take out
    every llama-server on the machine, including ones this launcher never
    started and the user is still using.

    terminate() is TerminateProcess on Windows - what `taskkill /F` did - and
    SIGTERM elsewhere, where llama-server gets `grace` seconds to release the
    GPU and exit before SIGKILL.

    A process that is already gone counts as stopped: the outcome the caller
    needs, nothing running under that pid, holds."""
    try:
        proc = ps.Process(pid)
        proc.terminate()
        try:
            proc.wait(timeout=grace)
        except ps.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=grace)
        return True
    except ps.NoSuchProcess:
        return True
    except (ps.Error, OSError):
        # Refused (AccessDenied), or still alive after the force - the second
        # wait's TimeoutExpired lands here.
        return False


def kill(pid, *, expect_name, expect_started, expect_port=None,
         name_of=process_name, started_of=process_started, force=_stop,
         owner_of=port_owner):
    """Stop `pid`, but only if it is provably the process the caller means.
    Returns True only if it was stopped.

    `expect_name` and `expect_started` are REQUIRED and keyword-only,
    deliberately. A default of None would mean a caller who forgets one
    silently gets a weaker guard, and the whole point of this function is that
    stopping blind is unsafe: port_owner's snapshot can be minutes old by the
    time a user answers a confirmation prompt, and operating systems recycle
    pids. Every call site must state what it believes it is stopping.

    Three guards, each closing what the one before leaves open:

      - NAME. Refuses unless the pid still runs under `expect_name`. Refuses on
        "" (already gone) and on "unknown" (could not ask) - not knowing is not
        permission. This proves the pid is *a* llama-server.

      - START TIME. Refuses unless the pid's creation time still equals
        `expect_started`, the value port_owner recorded. A recycled pid has a
        different creation time, so it is refused even when the newcomer is
        also a llama-server - the case the name cannot see. Refuses when either
        reading is None: an owner we could not timestamp is one we cannot
        re-identify.

      - PORT (opt-in). With `expect_port`, re-confirms immediately before
        stopping that this pid still owns that port, and refuses if the lookup
        cannot say.

    What remains is the gap between the last check and the stop itself, which
    only a handle held from before the snapshot could close.

    `name_of`, `started_of`, `force` and `owner_of` are injectable so both the
    refuse paths AND the proceed path are testable without stopping a real
    process."""
    current = name_of(pid)
    if (not current or current == UNKNOWN
            or current.lower() != expect_name.lower()):
        return False
    if expect_started is None or started_of(pid) != expect_started:
        return False
    if expect_port is not None:
        owner = owner_of(expect_port)
        # None (port went free), UNKNOWN_OWNER (could not ask) and a different
        # pid all mean the same thing here: this is not provably the process
        # that holds the port, so it is not ours to stop.
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
               probe=port_open, sleep=time.sleep, clock=time.monotonic,
               where="check its console window"):
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
    mean matching the listener's pid to proc.pid on every probe.

    `where` finishes the "it died" message with the place its output went: its
    console window, or the log file it was started with."""
    if proc is None:
        # spawn() returns None when llama-server could not be started at all.
        # Without this, the poll below would probe a port nothing of ours is
        # ever going to open - and report a stranger's listener as success.
        return False, ("llama-server did not start - check that the "
                       "llama-server path is still correct")
    start = clock()
    while True:
        if proc.poll() is not None:
            return False, (f"llama-server exited with code {proc.returncode} "
                           f"before the port opened - {where}")
        if probe(host, port):
            return True, f"http://{host}:{port}"
        if clock() - start > timeout:
            return False, f"timed out after {timeout}s waiting for {host}:{port}"
        if tick:
            tick()
        sleep(0.5)


def log_path_for(name, port, log_dir):
    """The log file for one launched server: <log_dir>/<name>-<port>.log.

    One file per config and port, overwritten at each launch, so logs do not
    pile up. The config name is user text and can hold anything, so every
    character outside [A-Za-z0-9._-] becomes an underscore - which also means
    no name, however it is spelled, can address a file outside `log_dir`."""
    safe = re.sub(r"[^A-Za-z0-9._-]", "_", str(name))
    return os.path.join(log_dir, f"{safe}-{port}.log")


def spawn(argv, log_path=None, popen=subprocess.Popen):
    """Start llama-server. Returns the process handle, or None if it could not
    be started.

    Two ways to start, chosen by whether there is somewhere to send the output:

      - no `log_path`: in its own console window. This is Windows, where a
        second console is the natural place for a server's log.
      - a `log_path`: detached from this terminal, stdin closed, stdout and
        stderr written to that file. This is Linux and macOS, where there is
        no second console to open, and a child sharing this terminal would
        write over the board and die with it. start_new_session is what keeps
        Ctrl-C at the board, and closing the terminal, from reaching it.

    None rather than an exception, for a binary that cannot be run and for a
    log that cannot be opened alike - the exe having been moved or renamed
    mid-session is the ordinary case, and it used to escape as a raw OSError
    traceback. wait_ready(proc=None) turns None into a plain failure message,
    so even a caller that does not check gets a clean report.

    `popen` is injectable so the platform guard and argument handling can be
    tested without actually starting a process."""
    if log_path is None:
        flags = subprocess.CREATE_NEW_CONSOLE if sys.platform == "win32" else 0
        try:
            return popen(argv, creationflags=flags)
        except OSError:
            return None
    try:
        folder = os.path.dirname(log_path)
        if folder:
            os.makedirs(folder, exist_ok=True)
        # "wb" truncates: each launch starts its log afresh. Our handle is
        # closed as soon as the child has its own copy.
        with open(log_path, "wb") as log:
            return popen(argv, stdin=subprocess.DEVNULL, stdout=log,
                         stderr=subprocess.STDOUT, start_new_session=True)
    except OSError:
        return None
