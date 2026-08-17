"""Process and port handling. The only module that touches running processes."""
import socket
import subprocess
import sys
import time


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
    """Image name from `tasklist /FO CSV /NH` output, or "" if no such process.

    Detection is by the absence of a CSV row, not by wording or exit code:
    tasklist exits 0 for a no-match and prints a localised INFORMATION line."""
    first = text.strip().splitlines()[0] if text.strip() else ""
    if first.startswith('"'):
        return first.split('","')[0].strip('"')
    return ""


def process_name(pid):
    """Image name for `pid`.

    Three distinct answers: the name; "" if no such process (it exited, so there
    is nothing to kill); "unknown" if tasklist itself could not be run (we do not
    know, and must not assume)."""
    try:
        out = subprocess.run(["tasklist", "/FI", f"PID eq {pid}", "/FO", "CSV", "/NH"],
                             capture_output=True, text=True, timeout=10).stdout
    except (OSError, subprocess.SubprocessError):
        return "unknown"
    return parse_tasklist(out)


def port_owner(port):
    """(pid, process name) holding `port`, or None if it is free."""
    try:
        out = subprocess.run(["netstat", "-ano"], capture_output=True,
                             text=True, timeout=20).stdout
    except (OSError, subprocess.SubprocessError):
        return None
    pid = parse_netstat(out, port)
    if pid is None:
        return None
    name = process_name(pid)
    if name == "":
        return None            # the listener exited between netstat and tasklist
    return pid, name


def _force_kill(pid):
    """The actual taskkill. Separated so kill()'s guard can be tested without
    terminating anything real."""
    try:
        r = subprocess.run(["taskkill", "/PID", str(pid), "/F"],
                           capture_output=True, text=True, timeout=20)
        return r.returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def kill(pid, *, expect_name, name_of=process_name, force=_force_kill):
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

    `name_of` and `force` are injectable so both the refuse path AND the
    proceed path are testable without terminating a real process."""
    current = name_of(pid)
    if not current or current.lower() != expect_name.lower():
        return False
    return force(pid)


def port_open(host, port, timeout=0.5):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(timeout)
        return s.connect_ex((host, port)) == 0


def wait_ready(host, port, proc, timeout=300, tick=None,
               probe=port_open, sleep=time.sleep, clock=time.monotonic):
    """Poll until the port accepts a connection. Condition-based, not a fixed
    sleep: a 20 GB model takes far longer to load than a 1 GB one.

    Returns (ok, message). The injected probe/sleep/clock keep this testable
    without opening real sockets."""
    start = clock()
    while True:
        if probe(host, port):
            return True, f"http://{host}:{port}"
        if proc.poll() is not None:
            return False, (f"llama-server exited with code {proc.returncode} "
                           f"before the port opened - check its console window")
        if clock() - start > timeout:
            return False, f"timed out after {timeout}s waiting for {host}:{port}"
        if tick:
            tick()
        sleep(0.5)


def spawn(argv):
    flags = subprocess.CREATE_NEW_CONSOLE if sys.platform == "win32" else 0
    return subprocess.Popen(argv, creationflags=flags)
