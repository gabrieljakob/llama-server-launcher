"""Process and port handling. The only module that touches running processes."""
import subprocess


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


def kill(pid, expect_name=None, name_of=process_name):
    """Force-stop `pid`. Returns True only if it was actually killed.

    `expect_name` re-verifies identity immediately before killing, and callers
    that got their pid from port_owner should always pass it. That snapshot can
    be minutes old by the time a user answers a confirmation prompt; if the
    server exited in the meantime and Windows recycled its pid, killing blind
    would terminate an unrelated process. Refuses on a mismatch, on "" (already
    gone) and on "unknown" (tasklist failed) - not knowing is not permission.

    `name_of` is injectable so the guard is testable without spawning anything."""
    if expect_name is not None:
        current = name_of(pid)
        if not current or current.lower() != expect_name.lower():
            return False
    try:
        r = subprocess.run(["taskkill", "/PID", str(pid), "/F"],
                           capture_output=True, text=True, timeout=20)
        return r.returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False
