# llama-server Launcher — Universal Foundation Design

**Date:** 2026-10-11
**Status:** Design approved in conversation; this document awaits review
**Branch:** a new branch off `main` (not `tui`)
**Supersedes:** the "Porting" section of the README, and the zero-dependency constraint

---

## 1. Context

The launcher works on one machine: the author's. Three things stop anyone else from using
it.

1. **It is Windows-only.** `server.py` shells out to `netstat`, `tasklist` and `taskkill`,
   and `__main__.py` identifies a server by the literal image name `llama-server.exe`.
2. **It cannot be installed.** There is no `pyproject.toml`, the only way to run it is
   from a clone, and the config file is written next to the code — a location that does
   not exist in any useful sense once the package is installed.
3. **Its defaults are one person's.** That is real, but it is the *next* sub-project, not
   this one.

The goal behind this work is public adoption: a stranger on Windows, Linux or macOS should
get from a one-line command to a running board. This document covers the part that makes
that true. It is the first of four sub-projects, each with its own spec and plan:

| # | Sub-project | State |
|---|---|---|
| 1 | **Universal foundation** — this document | being designed |
| 2 | Neutral defaults and presets | not started |
| 3 | TUI on Textual (replaces `docs/tui-design.md`) | not started |
| 4 | Sharing kit — config export/import, demo, README | not started |

### Decisions already made

- **Dependencies are allowed.** The TUI will be built on Textual, so the "standard library
  only" rule is retired. This sub-project adds `psutil` and `platformdirs`; Textual arrives
  with sub-project 3.
- **Installation is a one-line bootstrap script**, installing from a tagged GitHub release
  through `uv`. PyPI is not part of this work. The names `llama-launcher`,
  `llama-server-launcher` and `llama-launch` were all unclaimed on PyPI on 2026-10-11, so
  publishing later stays open and would not change the one-liner.
- **The process layer moves to `psutil` on all three operating systems**, replacing the
  console-tool parsing rather than adding POSIX parsers beside it.

### Baseline, measured

`python -m unittest discover -s tests -t .` on 2026-10-11:

| Where | Result |
|---|---|
| Windows 11, Python 3.12 | 388 tests, all pass |
| WSL Ubuntu, Python 3.14 | 388 tests, **3 fail**, 4 skipped |

The three Linux failures are all in `tests/test_config.py::TestPaths`
(`test_canon_folds_separators_and_case`, `test_resolve_path_passes_absolute_through`,
`test_relativise_strips_the_root`). Each asserts Windows path semantics — drive letters,
backslashes, case folding — through `os.path`. The code under test is correct on both
platforms; the tests are Windows tests without a guard. Nothing else in the suite depends
on the OS, which means the pure modules are already portable and the work is concentrated
where this document says it is.

## 2. Goals and non-goals

**Goals**

- One command installs the launcher on Windows, Linux and macOS, with neither Python nor
  git required beforehand.
- The launcher finds, identifies and stops a llama-server on all three, with the same
  safety guarantees it has on Windows today — and one more (§5.3).
- Config lives in the per-user location each OS expects, and survives reinstalls.
- Every push is tested on all three operating systems.
- Every existing behaviour of the text board is preserved on Windows.

**Non-goals**

- The TUI, and anything Textual (sub-project 3).
- Changing catalog defaults or adding presets (sub-project 2).
- Config sharing, export or import (sub-project 4).
- PyPI, winget, scoop, Homebrew, or standalone executables.
- Downloading or building llama.cpp for the user. First-run setup still asks where
  `llama-server` is.
- Automating releases. A release is a version bump, a tag and `gh release create`, done
  by hand.

## 3. Names and packaging

| Thing | Name |
|---|---|
| Command | `llama-launcher` |
| Distribution (`pyproject.toml` `name`) | `llama-launcher` |
| Import package | `llama_launcher` (renamed from `launcher`) |
| GitHub repository | `llama-server-launcher` (unchanged) |

The package is renamed with `git mv launcher llama_launcher` so history follows. A
top-level module called `launcher` is too generic to install into anyone's environment.
The rename touches eight import lines in `tests/`, `launch_model.bat`, and the README.

**`pyproject.toml`**

- Build backend: `hatchling`. The flat layout is kept; the package directory matches the
  distribution name, so no include configuration is needed and `tests/` stays out of the
  wheel.
- `requires-python = ">=3.12"`, unchanged. `uv` downloads a suitable interpreter when the
  machine has none, so the floor costs users nothing.
- `dependencies = ["psutil>=6.0", "platformdirs>=4"]`. `psutil` 6.0 is the floor because
  it introduced `Process.net_connections()`, which §5.2 depends on.
- `[project.scripts] llama-launcher = "llama_launcher.__main__:main"`.
- `version = "0.1.0"`, single-sourced here and read at runtime with
  `importlib.metadata.version`.
- A committed `uv.lock` pins the development and CI environment.

**Command line.** `__main__.py` gains `argparse` with two flags:

- `--version` prints the version and exits.
- `--config PATH` uses that file instead of the per-user one (§4).

`python -m llama_launcher` keeps working inside the environment. `launch_model.bat` stays
for people running from a clone and becomes a one-line wrapper around
`uv run llama-launcher`.

## 4. Config location

The config file moves out of the source tree.

| OS | Folder |
|---|---|
| Windows | `%APPDATA%\llama-launcher\` |
| Linux | `$XDG_CONFIG_HOME/llama-launcher/`, defaulting to `~/.config/llama-launcher/` |
| macOS | `~/Library/Application Support/llama-launcher/` |

These come from `platformdirs.user_config_dir("llama-launcher", appauthor=False,
roaming=True)`. The file keeps its name, `launcher_configs.json`, and its schema; nothing
about its contents changes.

**Resolution**, in order:

1. `--config PATH`, used as given.
2. Otherwise the per-user folder above.

The resolved path lives where it does today, in `__main__.CONFIG_PATH`, so the twelve
places in `tests/test_main.py` that redirect it keep working unchanged.

**Adoption of an existing file.** When the per-user file does not exist, `--config` was
not given, and a `launcher_configs.json` sits in the folder that contains the package
directory — the repository root, in a clone — the launcher copies it into the per-user
folder and prints one line saying where it went. The original is left in place. That
situation only arises in a clone — the author's — and it is what carries the existing
configs across without a manual step.

The legacy `model_profiles.json` migration is untouched: it still looks next to the
package, and writes its result to the resolved config path.

**Consequences.**

- The folder is created on first save. `config.save` already writes a temp file in the
  target's folder and replaces atomically; that keeps working once the folder exists.
- First-run setup prints the **full** config path instead of the bare file name, because
  "edit `launcher_configs.json`" no longer tells anyone where to look.

## 5. The process layer

`server.py` remains the only module that touches running processes, and keeps its
function names. Its internals move from three console tools to `psutil`.

### 5.1 Interface

```python
Owner = namedtuple("Owner", "pid name started")
UNKNOWN = "unknown"
UNKNOWN_OWNER = Owner(None, UNKNOWN, None)

port_owner(port)                 -> Owner | None | UNKNOWN_OWNER
process_name(pid)                -> name | "" | "unknown"
kill(pid, *, expect_name, expect_started, expect_port=None) -> bool
port_open(host, port, timeout)   -> bool                      # unchanged
wait_ready(host, port, proc, …)  -> (ok, message)             # logic unchanged
spawn(argv, log_path=None)       -> Popen | None
```

`psutil` is reached through one injectable parameter, the way `run=subprocess.run` is
today, so unit tests still assert behaviour without touching a real process.

Deleted outright: `OEM`, `_console`, `parse_netstat`, `parse_tasklist`, `_force_kill`'s
`taskkill` call, and the long comment about OEM codepages — the hazard it documents no
longer exists.

### 5.2 Finding who owns a port

The three-answer contract is kept exactly, because the rest of the launcher is built on
the difference between "free" and "could not ask":

| Answer | Meaning |
|---|---|
| `Owner(pid, name, started)` | that process is listening |
| `None` | asked, and nothing is listening |
| `UNKNOWN_OWNER` | could not determine — **never** read as free |

The lookup is one algorithm, and which branch runs is decided by what `psutil` raises,
not by `sys.platform`:

1. Ask for the system-wide TCP table (`psutil.net_connections("tcp")`) and look for a
   socket in `CONN_LISTEN` state on the port.
2. If that raises `AccessDenied` — expected on macOS without root — walk
   `psutil.process_iter()` and ask each process for its own listening sockets, skipping
   processes that deny access or vanish.
3. If a listener is found but the OS will not say which process owns it (another user's
   process on Linux), the answer is `UNKNOWN_OWNER`.
4. If step 2 finds nothing, that is not yet proof the port is free: a listener owned by
   another user is invisible to a per-process walk. A connect probe to `127.0.0.1` on
   that port settles it — if something answers, the result is `UNKNOWN_OWNER`; only if
   nothing does is it `None`. A listener bound solely to some other interface escapes the
   probe; llama-server's own bind failure, which `wait_ready` reports as an exit code, is
   the backstop there.
5. Any other `psutil.Error` is `UNKNOWN_OWNER`.

`process_name` keeps its three answers: the name, `""` when the process no longer exists,
and `"unknown"` on `AccessDenied` or any other failure to read it.

### 5.3 Stopping a server

`kill` keeps both guards it has and gains a third.

- **Name** (kept): refuses unless the pid is still running under `expect_name`. Refuses on
  `""` and on `"unknown"`.
- **Port** (kept, opt-in): with `expect_port`, re-confirms immediately before stopping
  that this pid still owns that port.
- **Start time** (new, required): `port_owner` records the process's creation time, and
  `kill` refuses unless the pid's creation time still equals `expect_started`. A recycled
  pid has a different creation time, so it cannot be stopped by mistake even when the new
  occupant is also a llama-server — the case the current docstring calls "the remaining
  race, and it is real".

`expect_started` is keyword-only and has no default, for the reason `expect_name` has
none: a caller that forgets it must not silently get a weaker guard.

`__main__.launch` passes all three. Today it passes only the name — the port re-check
exists in `kill` but the one production call site never asks for it — so this also closes
a gap between what the README promises and what the code does.

**The stop itself:** `terminate()`, wait up to five seconds, then `kill()` and wait again.
On Windows `terminate()` is `TerminateProcess`, which is what `taskkill /F` did. On Linux
and macOS it is `SIGTERM`, so llama-server gets the chance to shut down cleanly before
`SIGKILL`. A process that has already exited by the time the stop is attempted counts as
stopped: the outcome the caller needs — nothing running under that pid — holds.

### 5.4 What counts as a llama-server

`__main__.launch` currently compares the port owner's name with the literal
`"llama-server.exe"`. It will compare with the **file name of the configured
`llama_server` binary** instead, through `os.path.normcase` — case-insensitive on Windows,
exact elsewhere. That is right on every OS without a table of names, and it also covers a
user whose binary is called something else.

The comparison stays an equality test, never a substring test, for the reason already
recorded in the code: `llama-server-proxy` must not be offered up for a kill.

A server started through a wrapper script or a differently-named symlink will not match,
and the launcher will decline to stop it and say what holds the port. That is the safe
failure.

### 5.5 Spawning

| OS | Behaviour |
|---|---|
| Windows | Unchanged: its own console window (`CREATE_NEW_CONSOLE`) |
| Linux, macOS | Detached (`start_new_session=True`), stdin closed, stdout and stderr written to a log file |

On Linux and macOS there is no second console to open, and a child that shares the
launcher's terminal would write over the board and die with it. The log file goes in
`platformdirs.user_log_dir("llama-launcher", appauthor=False)`, named
`<config name>-<port>.log` with any character outside `[A-Za-z0-9._-]` replaced by `_`,
and is truncated at each launch so logs do not accumulate. The launcher prints its path
when it starts the server.

`spawn` takes the path as `log_path`. Windows passes `None` for now. The TUI
(sub-project 3) will pass a log path on every OS; this is the same mechanism, introduced
where it is first needed.

`wait_ready`'s polling logic is untouched. Two of its messages change wording: the
failure text points at the log file when there is one and at the console window
otherwise, and "the llama-server.exe path" becomes "the llama-server path".

## 6. Two more Windows assumptions

The README says nothing outside `server.py` assumes an OS. Two things do.

**The `[c]` command line.** `board.as_powershell` is the only renderer. A new
`board.as_command(argv)` dispatches: `as_powershell` on Windows, `shlex.join` elsewhere.
`as_powershell` itself, and its tests, are untouched — it is a pure function and its
tests pass on every OS.

**The extra-args row.** `catalog.split_extra` deliberately splits by Windows rules, where
a backslash is an ordinary character. On Linux and macOS that is wrong in the other
direction: a user there expects `\ ` and single quotes to behave as in their shell. The
existing function becomes `split_extra_windows`, a new `split_extra_posix` wraps
`shlex.split` and reports an unbalanced quote as `(False, message)` instead of raising,
and `split_extra` dispatches on `os.name`.

A config file's extra-args string is therefore read by the rules of the machine it is on.
That is correct: such strings carry machine paths and were never portable.

## 7. The bootstrap scripts

Two files at the repository root, fetched from `main`:

```
irm https://raw.githubusercontent.com/gabrieljakob/llama-server-launcher/main/install.ps1 | iex
curl -fsSL https://raw.githubusercontent.com/gabrieljakob/llama-server-launcher/main/install.sh | sh
```

This is the pattern uv, rustup and Claude Code use. `npx` was considered and rejected: it
is Node's runner, and requiring Node to bootstrap a Python tool means two runtimes instead
of none. Python's equivalent, `uvx llama-launcher`, needs the package on PyPI, which was
considered twice and declined for this release; step 2 below is the only place that would
change if that decision is revisited.

The pipe is into `sh`, not `bash`: the script is POSIX, so it also runs where bash is not
installed. Windows has no `| bash` at all, which is why it gets its own PowerShell line.

Both do the same four things:

1. **Ensure `uv`.** If `uv` is not on `PATH`, install it with Astral's official installer
   and make it available for the rest of the script.
2. **Choose the source.** If `LLAMA_LAUNCHER_SOURCE` is set, use it — a local path or any
   URL; this is how CI and development exercise the script. Otherwise find the latest
   release tag by reading the redirect from the repository's `releases/latest` URL, and
   use that tag's source archive.
3. **Install.** `uv tool install --force` on that source, asking `uv` for a Python that
   satisfies the 3.12 floor. `--force` makes re-running the one-liner the way to update.
4. **Report.** Print the installed version and the command to run. If `llama-launcher`
   does not resolve on `PATH`, print the `uv tool update-shell` hint instead of leaving
   the user with "command not found".

Constraints:

- `install.ps1` runs under Windows PowerShell 5.1, the version every Windows 10 and 11
  machine has. No `&&`, no ternary, TLS 1.2 set explicitly.
- `install.sh` is POSIX `sh`, not bash, and falls back from `curl` to `wget`.
- **A truncated download must not run half a script.** The whole body of `install.sh` is
  one function, called on the last line, so a connection that drops mid-transfer leaves
  `sh` with an unfinished definition and nothing executed. `install.ps1` is wrapped in a
  script block for the same reason, and so that it leaves no variables or changed
  preferences behind in the user's session.
- **HTTPS only.** Every download the scripts make refuses to follow a redirect to plain
  HTTP (`curl --proto '=https' --tlsv1.2`, `wget --https-only`).
- **A release, never `main`.** The scripts are fetched from `main`, but what they install
  is the latest tagged release.
- Neither asks for elevation or uses `sudo`, and neither edits anything beyond what `uv`
  itself manages.
- Neither touches the config file. Uninstalling is `uv tool uninstall llama-launcher`,
  which leaves the config in place.
- If there is no published release, the script says so and exits non-zero.
- Both are short enough to read before running. The README shows the two-step form —
  download the script, read it, then run it — next to the one-liner, for anyone who will
  not pipe a download into a shell.

A short install URL on a domain of its own is not part of this work. It would be a
redirect to these same files and can be added later without changing either script.

## 8. Testing

Standard-library `unittest`, the same runner, the same bar: a test is kept only if
breaking the behaviour it covers makes it fail.

**Removed with the code they covered** (15): `TestParseNetstat`, `TestParseTasklist`,
`TestConsoleDecoding`.

**Rewritten against a fake `psutil`, same contracts** (19): `TestProcessName`,
`TestPortOwner`, `TestForceKill`. Each contract in §5.2 and §5.3 gets a case, including
the `AccessDenied` fallback, the unidentifiable listener, and the connect-probe
cross-check.

**Kept:** `TestKillGuard` and `TestKillPortGuard` (extended with the start-time guard,
including "same name, same port, different start time is refused"), `TestWaitReady`,
`TestPortOpen`, `TestSpawn` (extended with the detached log-file case).

**New: `tests/test_server_live.py`.** Integration tests against a real child process — a
few lines of Python that bind a port and wait. They assert that `port_owner` finds its
pid and name; that the creation time read twice is equal; that `kill` under the wrong
name, and under the wrong start time, refuses and the process is still alive afterwards;
that `kill` under the right identity stops it and the port then reads free. These run
everywhere, and they are what proves the macOS branch of §5.2.

**New unit tests** for config-path resolution and adoption, the two command-line flags,
`as_command` dispatch, `split_extra_posix`, the configured-binary identity check, and
log-file naming.

**The three path tests** from §1 get a Windows-only guard and POSIX twins that assert the
same three properties with POSIX paths. A test is skipped on a platform only when the
thing it tests does not exist there; nothing is skipped to make a run green.

**`tests/test_main.py`** fakes `server.port_owner` with two-tuples in its launch tests;
those become `Owner` values.

## 9. Continuous integration

One workflow, `.github/workflows/ci.yml`, on every push and pull request.

- **Test job.** Matrix of `windows-latest`, `ubuntu-latest`, `macos-latest` × Python 3.12
  and 3.14. `uv sync`, then the unittest command.
- **Install job.** On each OS, run that OS's bootstrap script with
  `LLAMA_LAUNCHER_SOURCE` pointing at the checkout, then assert `llama-launcher --version`
  prints the version from `pyproject.toml`.

The one path CI cannot exercise before a release exists is step 2's "find the latest
release". It is checked by hand after `v0.1.0` is published: the real one-liner, once on
Windows and once in WSL.

## 10. README

- Quick start becomes the two one-liners, with "from a clone: `uv run llama-launcher`"
  below them.
- The platform badge changes from Windows to Windows, Linux and macOS.
- "Dependencies: none" and "Zero install" go. The highlights table gains the one-line
  install in their place.
- The hard-coded test-count badge — already stale, reading 377 against 388 — becomes the
  CI status badge.
- "Porting" is deleted; "Windows and locale notes" loses the two items about `netstat` and
  `tasklist` and keeps the rest.
- "Configuration" says where the file lives on each OS.

## 11. Releasing

Not automated. For `v0.1.0`:

1. The branch is merged to `main` with CI green on all three operating systems.
2. `gh release create v0.1.0` — **the repository owner's action**, since it is what makes
   the one-liner live for the public.
3. The hand check from §9.

## 12. Risks

| Risk | Mitigation |
|---|---|
| macOS refuses the system-wide socket table | The per-process branch of §5.2, proven by the live tests on `macos-latest`. When it cannot tell, the answer is "unknown", never "free" |
| Creation time not stable enough for an equality check on some OS | The live test reads it twice on all three. If one proves unstable, the comparison gains a tolerance — decided by that evidence, not in advance |
| Replacing tested Windows code regresses Windows | Guard contracts are kept test-for-test; the live tests run on Windows; and a manual pass against the real `llama-server.exe` — launch, port takeover, refusal on a foreign process — before merging |
| `psutil` has no wheel for an unusual platform | `uv` would need a compiler there. The plan confirms which platforms `psutil` publishes wheels for; anything outside that set is documented as needing a build toolchain |
| A change to `main` breaks the bootstrap script for everyone | The install job runs both scripts on every push |
| GitHub changes how `releases/latest` redirects | Would surface as the script's "no published release" exit. Accepted; the fix is a one-line change to a script served from `main` |

## 13. File layout after implementation

```
pyproject.toml                  new
uv.lock                         new
install.ps1                     new
install.sh                      new
launch_model.bat                now wraps `uv run llama-launcher`
.github/workflows/ci.yml        new
llama_launcher/                 renamed from launcher/
  catalog.py                    + split_extra_windows / split_extra_posix
  config.py                     unchanged
  server.py                     rewritten on psutil; same function names
  board.py                      + as_command
  __main__.py                   + argparse, config-path resolution, adoption,
                                  identity by configured binary, log path
tests/
  test_server.py                parsers removed; three classes rewritten
  test_server_live.py           new
  test_config.py                three path tests guarded, POSIX twins added
  test_main.py                  Owner values; new flag and path tests
  (the rest)                    import line only
docs/
  universal-design.md           this document
```
