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


def process_name(pid):
    try:
        out = subprocess.run(["tasklist", "/FI", f"PID eq {pid}", "/FO", "CSV", "/NH"],
                             capture_output=True, text=True, timeout=10).stdout
    except (OSError, subprocess.SubprocessError):
        return "unknown"
    first = out.strip().splitlines()[0] if out.strip() else ""
    if first.startswith('"'):
        return first.split('","')[0].strip('"')
    return "unknown"


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
    return pid, process_name(pid)


def kill(pid):
    try:
        r = subprocess.run(["taskkill", "/PID", str(pid), "/F"],
                           capture_output=True, text=True, timeout=20)
        return r.returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False
