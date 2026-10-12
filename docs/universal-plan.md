# llama-server Launcher — Universal Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the launcher installable with one command and correct on Windows, Linux and macOS.

**Architecture:** The package is renamed and given a `pyproject.toml` with a console-script entry point. The config file moves to the per-user folder. `server.py` keeps its function names and its three-answer contract but asks `psutil` instead of parsing `netstat`/`tasklist`/`taskkill`, and gains a start-time guard on the stop path. Two small bootstrap scripts install a tagged GitHub release through `uv`, and a CI matrix runs the suite and both scripts on three operating systems.

**Tech Stack:** Python 3.12+, `psutil`, `platformdirs`, `hatchling`, `uv`, standard-library `unittest`, GitHub Actions, POSIX `sh`, Windows PowerShell 5.1.

**Spec:** `docs/universal-design.md` — read it before starting any task. Section numbers below (§) refer to it.

## Global Constraints

- **Python floor:** `requires-python = ">=3.12"`.
- **Runtime dependencies, exactly:** `psutil>=6.0` and `platformdirs>=4`. Nothing else. Textual is **not** added by this plan.
- **Names:** command `llama-launcher`; distribution `llama-launcher`; import package `llama_launcher`; repository `llama-server-launcher`; config file `launcher_configs.json`; version `0.1.0`.
- **`server.py` is the only module that touches running processes.** `config.py` is not modified by any task.
- **"Could not ask" is never read as "free".** `port_owner` keeps three answers: an `Owner`, `None`, or `UNKNOWN_OWNER`.
- **Every existing behaviour of the text board on Windows is preserved.**
- **Tests:** standard-library `unittest` only, no pytest. A test is kept only if breaking the behaviour it covers makes it fail — every code task ends with a mutation check. A test is skipped on a platform only when the thing it tests does not exist there.
- **Bootstrap scripts:** `install.ps1` runs under Windows PowerShell 5.1 (no `&&`, no ternary); `install.sh` is POSIX `sh`, not bash. HTTPS only. No `sudo`, no elevation. Neither touches the config file.
- **Not in scope:** PyPI, release automation, the TUI, defaults or presets, config sharing.
- **Who does what in git.** Implementers commit locally and never `git push`, open a pull request, tag or release. The orchestrator pushes the branch and opens the pull request once Task 10 passes — the owner authorised that on 2026-10-12. Merging, publishing the `v0.1.0` release and the manual pass against the real server remain the owner's.
- **Commits:** Conventional Commits, `type(scope): subject`. Allowed types: `feat`, `fix`, `perf`, `refactor`, `test`, `docs`, `chore`. Scope is one lowercase word. Subject aims for 72 characters. Body is prose, at most 250 characters, wrapped at 72–80 columns. **No trailers of any kind** — no `Co-Authored-By`, no `Generated with`.
- **Staging:** always `git add` explicit paths, never `git add -A` or `git add .` — `docs/tui-plan.md` is an unrelated untracked file that must stay out of every commit. Run `git diff --staged --stat` before each commit and confirm only the listed files are staged.
- **README voice:** the README's first-person passages stay first-person.

## Review Focus

Input classes the spec implies that are most likely to bite a real user, each pinned by a named test in the task that owns the code:

1. **The per-user config folder cannot be created or written** (locked-down profile, read-only home). Startup must not crash, and the first save must name the path that failed. → Task 2: `test_a_config_folder_that_cannot_be_created_does_not_crash_startup`, `test_first_run_reports_the_path_it_could_not_write`.
2. **`--config` is given a folder instead of a file.** It must be reported with the path and exit 1, not raise. → Task 2: `test_config_pointing_at_a_folder_is_reported_not_raised`.
3. **One port appears in the socket table more than once** (an IPv4 and an IPv6 row, or a row the OS will not attribute next to one it will). The identifiable owner must be returned, not "unknown". → Task 3: `test_a_row_that_names_a_process_beats_one_that_does_not`.
4. **A config name containing path characters** (`../x`, `a/b`, `C:\x`, `qwen:3.8`) on Linux or macOS. The log file must stay inside the log folder. → Task 5: `test_a_name_cannot_climb_out_of_the_log_folder`.
5. **The log folder cannot be written** on Linux or macOS. Nothing may be started, and the failure must name the log path. → Task 5: `test_a_log_that_cannot_be_opened_is_none_and_nothing_is_started`, `test_a_failed_start_names_the_log_it_could_not_open`.

## Before you start

- **Environment, measured 2026-10-12:** Windows 11 with Python 3.12.10 and 3.14, `uv` 0.11.7, `gh` 2.97.0, Git with `core.autocrlf=true`. WSL has Ubuntu 26.04 with Python 3.14.4, `curl` and `wget`, but **no `uv` and no `psutil`**.
- **Task 3 installs `uv` into the WSL user's home** with Astral's installer (no `sudo`). That is the one change this plan makes outside the repository.
- **Baseline:** on `main`, `python -B -m unittest discover -s tests -t .` runs 388 tests, all passing on Windows. Under WSL the same suite has 3 failures, all in `tests/test_config.py::TestPaths`; Task 6 fixes them.
- **`psutil` wheels** (7.2.2, checked on PyPI): Windows x64 and arm64, macOS x64 and arm64, Linux glibc and musl on x86-64 and aarch64. Anything else needs a C toolchain.
- **GitHub state:** the repository has no releases; `https://github.com/gabrieljakob/llama-server-launcher/releases/latest` redirects to `/releases`, which is what the install scripts read as "no published release".

## Commands used throughout

All from the repository root, `D:\Projects\Model Launcher CLI Script`.

**The suite on Windows** (Bash or PowerShell):

```bash
uv run python -B -m unittest discover -s tests -t .
```

**One test class:**

```bash
uv run python -B -m unittest tests.test_server.TestPortOwner -v
```

**The suite under WSL** (run from the PowerShell tool; available from Task 3 on):

```powershell
wsl -d Ubuntu -- bash -lc "cd '/mnt/d/Projects/Model Launcher CLI Script' && UV_PROJECT_ENVIRONMENT=~/.venvs/llama-launcher ~/.local/bin/uv run --locked python -B -m unittest discover -s tests -t ."
```

`UV_PROJECT_ENVIRONMENT` keeps the Linux virtual environment out of the shared tree, where it would collide with the Windows `.venv`. `--locked` stops Linux from rewriting `uv.lock`.

**Mutation checks** always run *after* the task's commit, so the mutated file can be put back with `git restore <file>`. After the last one, `git status --short` must show only `?? docs/tui-plan.md`.

## File structure

```
pyproject.toml                  new      Task 1   packaging, entry point, dependencies
uv.lock                         new      Task 1   pinned dev/CI environment
.gitignore                      modify   Task 1   + .venv/
.gitattributes                  new      Task 7   install.sh stays LF on every checkout
launch_model.bat                modify   Task 1   wraps `uv run llama-launcher`
install.ps1                     new      Task 7   Windows bootstrap
install.sh                      new      Task 7   Linux/macOS bootstrap
.github/workflows/ci.yml        new      Task 8   3-OS test matrix + install-script job
README.md                       modify   Task 1 (one line), Task 9 (the rest)
llama_launcher/                 renamed from launcher/ in Task 1
  __main__.py                   modify   Tasks 2, 3, 4, 5, 6
  server.py                     modify   Tasks 3, 4, 5
  catalog.py                    modify   Task 6   split_extra_windows / _posix / dispatch
  board.py                      modify   Task 6   as_command
  config.py                     untouched
tests/
  test_cli.py                   new      Task 2   flags, config location, adoption
  test_server.py                modify   Tasks 3, 4, 5
  test_server_live.py           new      Tasks 3, 4, 5   real-process integration tests
  test_main.py                  modify   Tasks 3, 4, 5
  test_setup.py                 modify   Task 4   device_line decoding
  test_catalog.py               modify   Task 6
  test_board.py                 modify   Task 6
  test_config.py                modify   Task 6
```

---

### Task 1: Branch, rename the package, add packaging

**Files:**
- Rename: `launcher/` → `llama_launcher/`
- Create: `pyproject.toml`, `uv.lock` (generated)
- Modify: `tests/test_board.py:4`, `tests/test_catalog.py:2`, `tests/test_config.py:6`, `tests/test_main.py:16-17`, `tests/test_server.py:7`, `tests/test_setup.py:12`, `tests/test_spec_mtp.py:16`, `launch_model.bat`, `.gitignore`, `README.md:92`

**Interfaces:**
- Consumes: nothing.
- Produces: the import package `llama_launcher`; the console script `llama-launcher` → `llama_launcher.__main__:main`; `uv run` as the way every later task runs code.

- [ ] **Step 1: Create the branch off `main`**

```bash
git switch -c universal main
git status --short
```

Expected: exactly three untracked files — `docs/tui-plan.md`, `docs/universal-design.md`, `docs/universal-plan.md`. (`docs/tui-design.md` disappears from the working tree; it is tracked only on `tui`.)

- [ ] **Step 2: Commit the spec and this plan**

```bash
git add docs/universal-design.md docs/universal-plan.md
git diff --staged --stat
git commit -m "docs: universal foundation design and plan"
```

- [ ] **Step 3: Confirm the baseline before changing anything**

```bash
python -B -m unittest discover -s tests -t . 2>&1 | grep -E "^Ran |^OK|^FAILED"
```

Expected: `Ran 388 tests` and `OK`.

- [ ] **Step 4: Rename the package**

```bash
git mv launcher llama_launcher
```

- [ ] **Step 5: Update the eight import lines**

Use the Edit tool (not `sed`: the working tree has CRLF line endings). In each file, replace `from launcher import` with `from llama_launcher import`:

| File | Line(s) |
|---|---|
| `tests/test_board.py` | 4 |
| `tests/test_catalog.py` | 2 |
| `tests/test_config.py` | 6 |
| `tests/test_main.py` | 16 and 17 |
| `tests/test_server.py` | 7 |
| `tests/test_setup.py` | 12 |
| `tests/test_spec_mtp.py` | 16 |

In `launch_model.bat` line 7, change `"%PYTHON%" -m launcher` to `"%PYTHON%" -m llama_launcher`.
In `README.md` line 92, change `python -m launcher` to `python -m llama_launcher`.

- [ ] **Step 6: Verify nothing still imports the old name, and the suite is unchanged**

```bash
grep -rnE "(from|import) launcher\b|-m launcher\b" --include=*.py --include=*.bat --include=*.md . | grep -v "^./docs/" | grep -v "^./.sdd"
python -B -m unittest discover -s tests -t . 2>&1 | grep -E "^Ran |^OK|^FAILED"
```

Expected: the `grep` prints nothing; then `Ran 388 tests` and `OK`.

- [ ] **Step 7: Commit the rename**

```bash
git add -u llama_launcher tests launch_model.bat README.md
git diff --staged --stat
git commit -m "refactor: rename the launcher package to llama_launcher" -m "A top-level module called launcher is too generic to install into
anyone's environment. History follows the files through git mv."
```

Expected in the stat: five renames under `llama_launcher/`, seven test files, `launch_model.bat`, `README.md`.

- [ ] **Step 8: Write `pyproject.toml`**

```toml
[build-system]
requires = ["hatchling>=1.27"]
build-backend = "hatchling.build"

[project]
name = "llama-launcher"
version = "0.1.0"
description = "An interactive board for llama.cpp's llama-server: pick a named configuration, adjust it, launch."
readme = "README.md"
requires-python = ">=3.12"
license = "MIT"
license-files = ["LICENSE"]
authors = [{ name = "Gabriel Jakob" }]
keywords = ["llama.cpp", "llama-server", "gguf", "launcher"]
classifiers = [
    "Environment :: Console",
    "Operating System :: Microsoft :: Windows",
    "Operating System :: POSIX :: Linux",
    "Operating System :: MacOS",
    "Programming Language :: Python :: 3.12",
    "Programming Language :: Python :: 3.13",
    "Programming Language :: Python :: 3.14",
]
dependencies = [
    "psutil>=6.0",
    "platformdirs>=4",
]

[project.scripts]
llama-launcher = "llama_launcher.__main__:main"

[project.urls]
Repository = "https://github.com/gabrieljakob/llama-server-launcher"

[tool.hatch.build.targets.wheel]
packages = ["llama_launcher"]
```

The explicit `packages` line is belt and braces: hatchling would find the directory on its own, and this makes it impossible for `tests/` to end up in the wheel.

- [ ] **Step 9: Ignore the virtual environment**

Append to `.gitignore`:

```
# uv's project environment. Rebuilt from uv.lock by `uv sync`.
.venv/
```

- [ ] **Step 10: Replace `launch_model.bat`**

```bat
@echo off
setlocal
where uv >nul 2>&1 || (
  echo uv is not installed. Run install.ps1, or see https://docs.astral.sh/uv/
  pause
  exit /b 1
)
uv run --project "%~dp0." llama-launcher %*
pause
```

`"%~dp0."` and not `"%~dp0"`: the expansion ends in a backslash, and a backslash before the closing quote would escape it.

- [ ] **Step 11: Create the lock file and the environment**

```bash
uv lock
uv sync
```

Expected: `uv.lock` is created listing `llama-launcher`, `psutil` and `platformdirs`; `.venv/` is created.

- [ ] **Step 12: Verify the suite, the metadata and the entry point through `uv`**

```bash
uv run python -B -m unittest discover -s tests -t . 2>&1 | grep -E "^Ran |^OK|^FAILED"
uv run python -c "import importlib.metadata as m; print(m.version('llama-launcher')); print([e.value for e in m.entry_points(group='console_scripts') if e.name == 'llama-launcher'])"
```

Expected: `Ran 388 tests`, `OK`, then `0.1.0` and `['llama_launcher.__main__:main']`.

- [ ] **Step 13: Verify the wheel contains the package and nothing else**

```bash
uv build --wheel --out-dir "$TEMP/llama-launcher-wheel-check"
uv run python -m zipfile -l "$TEMP/llama-launcher-wheel-check/llama_launcher-0.1.0-py3-none-any.whl"
rm -r "$TEMP/llama-launcher-wheel-check"
```

Expected: only paths under `llama_launcher/` and `llama_launcher-0.1.0.dist-info/`. No `tests/`, no `docs/`.

- [ ] **Step 14: Commit the packaging**

```bash
git add pyproject.toml uv.lock .gitignore launch_model.bat
git diff --staged --stat
git commit -m "chore: add pyproject.toml, a console-script entry point and uv.lock" -m "Makes the launcher installable as llama-launcher. psutil and
platformdirs are declared here and first imported by later commits.
launch_model.bat now runs through uv so a clone gets them too."
```

---

### Task 2: Config in the per-user folder, `--config` and `--version`

**Files:**
- Modify: `llama_launcher/__main__.py:1-24` (imports and path constants), `:145-157` (`first_run_setup`), `:505-533` (`main`, `first_run_fresh`)
- Create: `tests/test_cli.py`

**Interfaces:**
- Consumes: the `llama_launcher` package and `uv run` from Task 1.
- Produces, all in `llama_launcher.__main__`:
  - `APP = "llama-launcher"`, `CONFIG_NAME = "launcher_configs.json"`
  - `CONFIG_PATH: str` — per-user path by default; rebound by `main()` when `--config` is given
  - `ADOPT_PATH: str` — `<folder containing the package>/launcher_configs.json`
  - `version() -> str`
  - `parse_args(argv: list[str]) -> argparse.Namespace` with `.config: str | None`
  - `adopt_existing_config(source: str, target: str) -> bool`
  - `main(argv: list[str] | None = None) -> int`

- [ ] **Step 1: Confirm no existing test calls `main.main()` without arguments**

`main()` is about to read `sys.argv`, which under `unittest` holds the test runner's own arguments.

```bash
grep -n "main\.main(" tests/*.py
```

Expected: no output.

- [ ] **Step 2: Write the failing tests**

Create `tests/test_cli.py`:

```python
"""Command-line flags and where the config file lives.

Nothing here touches the real per-user config. CONFIG_PATH and ADOPT_PATH are
redirected into a temporary folder, and where a test goes through main() the
board itself (_main) is replaced by a recorder.
"""
import contextlib
import io
import os
import sys
import tempfile
import tomllib
import unittest
from unittest import mock

from llama_launcher import __main__ as main


def write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)


def read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


class TestDefaultConfigPath(unittest.TestCase):
    def test_it_is_the_folder_each_os_keeps_config_in(self):
        """Spelled out per OS rather than recomputed with platformdirs, so a
        wrong app name, a stray author folder or a non-roaming path all fail."""
        if sys.platform == "win32":
            base = os.environ["APPDATA"]
        elif sys.platform == "darwin":
            base = os.path.expanduser("~/Library/Application Support")
        else:
            base = (os.environ.get("XDG_CONFIG_HOME")
                    or os.path.expanduser("~/.config"))
        expected = os.path.join(base, "llama-launcher", "launcher_configs.json")
        self.assertEqual(os.path.normcase(main.CONFIG_PATH),
                         os.path.normcase(expected))

    def test_it_is_not_inside_the_source_tree(self):
        """The whole point: beside the code is a folder a reinstall replaces."""
        tree = os.path.abspath(main.SCRIPTS) + os.sep
        self.assertFalse(os.path.abspath(main.CONFIG_PATH).startswith(tree))

    def test_the_file_to_adopt_is_the_one_beside_the_package(self):
        self.assertEqual(main.ADOPT_PATH,
                         os.path.join(main.SCRIPTS, "launcher_configs.json"))


class TestAdoptExistingConfig(unittest.TestCase):
    """A config written next to the code by a pre-0.1.0 clone is carried into
    the per-user folder once, and never at the expense of what is there."""

    def setUp(self):
        self.folder = tempfile.mkdtemp()
        self.source = os.path.join(self.folder, "clone", "launcher_configs.json")
        self.target = os.path.join(self.folder, "user", "llama-launcher",
                                   "launcher_configs.json")

    def adopt(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            result = main.adopt_existing_config(self.source, self.target)
        return result, out.getvalue()

    def test_a_config_beside_the_package_is_copied_across(self):
        write(self.source, '{"version": 2}')
        result, text = self.adopt()
        self.assertIs(result, True)
        self.assertEqual(read(self.target), '{"version": 2}')
        self.assertIn(self.target, text, "the user must be told where it went")

    def test_the_original_is_left_in_place(self):
        write(self.source, '{"version": 2}')
        self.adopt()
        self.assertEqual(read(self.source), '{"version": 2}')

    def test_an_existing_per_user_config_is_never_overwritten(self):
        write(self.source, "from the clone")
        write(self.target, "already mine")
        result, text = self.adopt()
        self.assertIs(result, False)
        self.assertEqual(read(self.target), "already mine")
        self.assertEqual(text, "")

    def test_nothing_to_adopt_is_silent(self):
        result, text = self.adopt()
        self.assertIs(result, False)
        self.assertEqual(text, "")
        self.assertFalse(os.path.exists(self.target))

    def test_a_copy_that_fails_is_reported_not_raised(self):
        write(self.source, "x")
        write(os.path.join(self.folder, "user"), "")   # a FILE where the folder goes
        result, text = self.adopt()
        self.assertIs(result, False)
        self.assertIn("could not copy", text)


class TestMainFlags(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.mkdtemp()
        self.default = os.path.join(self.folder, "user", "llama-launcher",
                                    "launcher_configs.json")
        self.clone = os.path.join(self.folder, "clone", "launcher_configs.json")

    def run_main(self, argv):
        """Returns (exit code, everything printed, the CONFIG_PATH the board
        was started with - or None if it never started)."""
        seen = {}

        def fake_main():
            seen["path"] = main.CONFIG_PATH
            return 0

        out = io.StringIO()
        with mock.patch.object(main, "CONFIG_PATH", self.default), \
             mock.patch.object(main, "ADOPT_PATH", self.clone), \
             mock.patch.object(main, "_main", fake_main), \
             contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
            try:
                code = main.main(argv)
            except SystemExit as exc:
                code = exc.code
        return code, out.getvalue(), seen.get("path")

    def test_without_flags_the_per_user_path_is_used(self):
        code, _, path = self.run_main([])
        self.assertEqual(code, 0)
        self.assertEqual(path, self.default)

    def test_config_replaces_the_path(self):
        chosen = os.path.join(self.folder, "elsewhere", "mine.json")
        _, _, path = self.run_main(["--config", chosen])
        self.assertEqual(path, os.path.abspath(chosen))

    def test_config_expands_the_home_folder(self):
        given = os.path.join("~", "llama-launcher-test-never-written.json")
        _, _, path = self.run_main(["--config", given])
        self.assertEqual(path, os.path.abspath(os.path.expanduser(given)))

    def test_the_config_folder_exists_before_anything_is_saved(self):
        """config.save writes its scratch file beside the target, so the
        folder has to be there first."""
        self.run_main([])
        self.assertTrue(os.path.isdir(os.path.dirname(self.default)))

    def test_a_config_folder_that_cannot_be_created_does_not_crash_startup(self):
        write(os.path.join(self.folder, "user"), "")   # a FILE where the folder goes
        code, _, path = self.run_main([])
        self.assertEqual(code, 0, "the first save reports it; startup must not")
        self.assertEqual(path, self.default)

    def test_a_clone_config_is_adopted_when_no_flag_is_given(self):
        write(self.clone, '{"version": 2}')
        _, text, _ = self.run_main([])
        self.assertEqual(read(self.default), '{"version": 2}')
        self.assertIn(self.default, text)

    def test_config_skips_adoption(self):
        """--config says exactly which file to use. Copying another one in
        beside it, or into the per-user folder, is not what was asked for."""
        write(self.clone, '{"version": 2}')
        chosen = os.path.join(self.folder, "elsewhere", "mine.json")
        self.run_main(["--config", chosen])
        self.assertFalse(os.path.exists(chosen))
        self.assertFalse(os.path.exists(self.default))

    def test_version_prints_the_version_from_pyproject_and_exits_zero(self):
        with open(os.path.join(main.SCRIPTS, "pyproject.toml"), "rb") as f:
            declared = tomllib.load(f)["project"]["version"]
        code, text, path = self.run_main(["--version"])
        self.assertEqual(code, 0)
        self.assertEqual(text.strip(), f"llama-launcher {declared}")
        self.assertIsNone(path, "the board must not be started")

    def test_an_unknown_flag_is_refused_before_anything_runs(self):
        code, _, path = self.run_main(["--nope"])
        self.assertEqual(code, 2)
        self.assertIsNone(path)


class TestConfigThatCannotBeRead(unittest.TestCase):
    def test_config_pointing_at_a_folder_is_reported_not_raised(self):
        folder = tempfile.mkdtemp()

        def no_ask(prompt=""):
            raise AssertionError("the menu must not be reached")

        out = io.StringIO()
        with mock.patch.object(main, "CONFIG_PATH", main.CONFIG_PATH), \
             mock.patch.object(main, "ask", no_ask), \
             contextlib.redirect_stdout(out):
            code = main.main(["--config", folder])
        self.assertEqual(code, 1)
        self.assertIn(folder, out.getvalue(), "the message must name the path")


class TestFirstRunNamesTheFullPath(unittest.TestCase):
    """'Edit launcher_configs.json' told a user where to look only while the
    file sat beside the code. Now it has to say the whole path."""

    def setUp(self):
        self.folder = tempfile.mkdtemp()
        self.path = os.path.join(self.folder, "deep", "launcher_configs.json")

    def test_setup_says_where_the_two_paths_are_stored(self):
        out = io.StringIO()
        with mock.patch.object(main, "CONFIG_PATH", self.path), \
             mock.patch.object(main, "ask_path",
                               lambda label, guess, must_be_dir: self.folder), \
             mock.patch.object(main, "find_llama_server", lambda: None), \
             contextlib.redirect_stdout(out):
            main.first_run_setup()
        self.assertIn(self.path, out.getvalue())

    def test_a_fresh_config_says_where_it_was_written(self):
        os.makedirs(os.path.dirname(self.path))
        out = io.StringIO()
        with mock.patch.object(main, "CONFIG_PATH", self.path), \
             mock.patch.object(main, "LEGACY_PATH",
                               os.path.join(self.folder, "no-legacy.json")), \
             contextlib.redirect_stdout(out):
            ok = main.first_run_fresh(self.folder, "llama-server")
        self.assertIs(ok, True)
        self.assertIn(self.path, out.getvalue())

    def test_first_run_reports_the_path_it_could_not_write(self):
        write(os.path.join(self.folder, "deep"), "")   # a FILE where the folder goes
        out = io.StringIO()
        with mock.patch.object(main, "CONFIG_PATH", self.path), \
             mock.patch.object(main, "LEGACY_PATH",
                               os.path.join(self.folder, "no-legacy.json")), \
             contextlib.redirect_stdout(out):
            ok = main.first_run_fresh(self.folder, "llama-server")
        self.assertIs(ok, False)
        self.assertIn("could not write", out.getvalue())
        self.assertIn(self.path, out.getvalue())


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 3: Run the tests to verify they fail**

```bash
uv run python -B -m unittest tests.test_cli 2>&1 | tail -n 6
```

Expected: errors, the first being `AttributeError: module 'llama_launcher.__main__' has no attribute 'ADOPT_PATH'` (or `adopt_existing_config`).

- [ ] **Step 4: Replace the imports and path constants in `llama_launcher/__main__.py`**

Replace the import block (lines 2-9) with:

```python
import argparse
import glob
import importlib.metadata
import os
import socket
import shutil
import subprocess
import sys

import platformdirs

from . import board, catalog, config, server
```

Replace the four lines that define `HERE`, `SCRIPTS`, `CONFIG_PATH` and `LEGACY_PATH` with:

```python
APP = "llama-launcher"
CONFIG_NAME = "launcher_configs.json"

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.dirname(HERE)
# Per-user, in the folder each OS keeps application config in - NOT beside the
# code. Installed as a tool, "beside the code" is a site-packages folder that
# the next reinstall replaces, taking every saved config with it.
CONFIG_PATH = os.path.join(
    platformdirs.user_config_dir(APP, appauthor=False, roaming=True), CONFIG_NAME)
# Where the config lived before 0.1.0: beside the package. That only means
# anything in a clone, and adopt_existing_config() copies it across once.
ADOPT_PATH = os.path.join(SCRIPTS, CONFIG_NAME)
LEGACY_PATH = os.path.join(SCRIPTS, "model_profiles.json")
```

- [ ] **Step 5: Make the two first-run messages name the full path**

In `first_run_setup`, replace the two `print` lines at the top of the body with:

```python
    print("Setting up. Two paths are needed; both are stored in")
    print(f"{CONFIG_PATH}\nand can be edited there later.\n")
```

In `first_run_fresh`, replace the `wrote ...` line with:

```python
    print(f"  wrote {CONFIG_PATH}; found {found} model file(s).")
```

- [ ] **Step 6: Add `version`, `parse_args` and `adopt_existing_config`, and replace `main`**

Insert these three functions immediately above `def main():`, then replace the whole of `main` with the version below.

```python
def version():
    """The installed version, or a marker when run from a tree that was never
    installed (no metadata to read)."""
    try:
        return importlib.metadata.version(APP)
    except importlib.metadata.PackageNotFoundError:
        return "0+unknown"


def parse_args(argv):
    parser = argparse.ArgumentParser(
        prog=APP,
        description="An interactive board for llama.cpp's llama-server.")
    parser.add_argument("--version", action="version",
                        version=f"{APP} {version()}")
    # argparse runs help text through %-formatting, and a path may hold a %.
    shown = CONFIG_PATH.replace("%", "%%")
    parser.add_argument("--config", metavar="PATH",
                        help=f"use this config file instead of {shown}")
    return parser.parse_args(argv)


def adopt_existing_config(source, target):
    """Copy a config left beside the package into the per-user folder.

    Before 0.1.0 the config was written next to the code, so anyone who ran the
    launcher from a clone has one there. Copied once, never over a file that is
    already in the per-user folder, and the original is left alone: it is the
    user's only copy until this succeeds, and their rollback after.

    Returns True only if a copy was made. Reports a failed copy instead of
    raising - this runs before anything else, and the fallback (first-run
    setup) is a working launcher rather than a traceback."""
    if os.path.exists(target) or not os.path.isfile(source):
        return False
    try:
        os.makedirs(os.path.dirname(target), exist_ok=True)
        shutil.copyfile(source, target)
    except OSError as exc:
        print(f"  could not copy {source} to {target}: {exc}")
        return False
    print(f"  copied your existing config to {target}")
    print(f"  ({source} is left in place and is no longer read)\n")
    return True


def main(argv=None):
    global CONFIG_PATH
    args = parse_args(sys.argv[1:] if argv is None else argv)
    if args.config:
        # Exactly the file that was asked for: no adoption, no second guess.
        CONFIG_PATH = os.path.abspath(os.path.expanduser(args.config))
    else:
        adopt_existing_config(ADOPT_PATH, CONFIG_PATH)
    try:
        # config.save writes its scratch file beside the target, so the folder
        # has to exist before the first save. A failure here is not reported:
        # the save that needs the folder reports it, and names the path.
        os.makedirs(os.path.dirname(CONFIG_PATH), exist_ok=True)
    except OSError:
        pass
    try:
        return _main()
    except Abort:
        # Ctrl-C or a closed stdin, from any depth. Quitting is the honest
        # response: nothing unsaved is written, and the alternative is guessing
        # which prompt the user meant to escape.
        print("  quit")
        return 0
```

Note for the reviewer: §4 says the folder is "created on first save". It is created at startup instead, because `config.py` may not change and `tests/test_main.py::test_a_failing_migration_save_is_reported_not_raised` depends on a save into a missing folder failing.

- [ ] **Step 7: Run the new tests, then the whole suite**

```bash
uv run python -B -m unittest tests.test_cli -v 2>&1 | tail -n 4
uv run python -B -m unittest discover -s tests -t . 2>&1 | grep -E "^Ran |^OK|^FAILED"
```

Expected: `Ran 21 tests` and `OK` for `tests.test_cli`; then `Ran 409 tests` and `OK` (388 + 21).

- [ ] **Step 8: Check the flags by hand**

```bash
uv run llama-launcher --version
uv run llama-launcher --help
```

Expected: `llama-launcher 0.1.0`; then usage text listing `--version` and `--config PATH`, the latter naming a path under `AppData\Roaming\llama-launcher`.

Do **not** run `uv run llama-launcher` with no flags in this task: it would copy the owner's real `launcher_configs.json` into `%APPDATA%`. That happens deliberately in Task 10.

- [ ] **Step 9: Commit**

```bash
git add llama_launcher/__main__.py tests/test_cli.py
git diff --staged --stat
git commit -m "feat(cli): keep the config in the per-user folder; add --config and --version" -m "Beside the code stops being a place once the package is installed.
A config a clone left there is copied across once and never over an
existing one. First-run messages now print the full path."
```

- [ ] **Step 10: Mutation check**

For each row: make the change, run the command, confirm the named test fails, then `git restore llama_launcher/__main__.py`.

| Mutation in `llama_launcher/__main__.py` | Test that must fail |
|---|---|
| In `adopt_existing_config`, change `if os.path.exists(target) or not os.path.isfile(source):` to `if not os.path.isfile(source):` | `TestAdoptExistingConfig.test_an_existing_per_user_config_is_never_overwritten` |
| In `main`, delete the `else:` branch that calls `adopt_existing_config`, and call it unconditionally before the `if` | `TestMainFlags.test_config_skips_adoption` |
| In `main`, delete the `os.makedirs(...)` `try` block | `TestMainFlags.test_the_config_folder_exists_before_anything_is_saved` |
| In `CONFIG_PATH`, change `appauthor=False` to `appauthor="llama"` | `TestDefaultConfigPath.test_it_is_the_folder_each_os_keeps_config_in` (on Windows) |

```bash
uv run python -B -m unittest tests.test_cli 2>&1 | tail -n 12
```

Finish with `git status --short` showing only `?? docs/tui-plan.md`.

---

### Task 3: Find a port's owner with `psutil`

**Files:**
- Modify: `llama_launcher/server.py` — imports; everything from `UNKNOWN = "unknown"` through the end of `port_owner`, except `_console`, which stays until Task 4
- Modify: `llama_launcher/__main__.py` — one line in `launch`
- Modify: `tests/test_server.py` — everything from the top through the end of `class TestPortOwner`
- Modify: `tests/test_main.py:435`, `:445`, `:568` — owner fixtures
- Create: `tests/test_server_live.py`

**Interfaces:**
- Consumes: `psutil>=6.0` from Task 1's `pyproject.toml`.
- Produces, in `llama_launcher.server`:
  - `Owner = namedtuple("Owner", "pid name started")`
  - `UNKNOWN = "unknown"`; `UNKNOWN_OWNER = Owner(None, UNKNOWN, None)`
  - `process_name(pid, ps=psutil) -> str` — the name, `""` if gone, `"unknown"` if it cannot be read
  - `process_started(pid, ps=psutil) -> float | None`
  - `port_owner(port, ps=psutil, probe=None) -> Owner | None` — `None` means free; `UNKNOWN_OWNER` means could not determine
- Unchanged in this task: `kill`, `_force_kill`, `_console`, `OEM`, `port_open`, `wait_ready`, `spawn`.
- Produces, in `tests/test_server.py`, for Tasks 4 and 5 to reuse: `Addr`, `Conn`, `OwnConn`, `listening()`, `FakeProcess`, `FakePs`.

- [ ] **Step 1: Install `uv` in WSL and record the Linux baseline**

From the PowerShell tool:

```powershell
wsl -d Ubuntu -- bash -lc "curl -LsSf https://astral.sh/uv/install.sh | sh"
wsl -d Ubuntu -- bash -lc "~/.local/bin/uv --version"
wsl -d Ubuntu -- bash -lc "cd '/mnt/d/Projects/Model Launcher CLI Script' && UV_PROJECT_ENVIRONMENT=~/.venvs/llama-launcher ~/.local/bin/uv run --locked python -B -m unittest discover -s tests -t . 2>&1 | grep -E '^(FAIL|ERROR):|^Ran |^OK|^FAILED'"
```

Expected from the last command: `Ran 409 tests`, `FAILED (failures=3, skipped=4)`, and exactly three `FAIL:` lines, all in `tests.test_config.TestPaths`. Those are Task 6's. Any other failure is a defect in Task 1 or 2: stop and fix it there.

- [ ] **Step 2: Replace the top of `tests/test_server.py`**

Replace everything from line 1 through the end of `class TestPortOwner` (the line before `class TestForceKill`) with:

```python
# -*- coding: utf-8 -*-
import collections
import socket
import subprocess
import sys
import unittest

import psutil

from llama_launcher import server

Addr = collections.namedtuple("Addr", "ip port")
# Rows from psutil.net_connections() carry a pid; a process's own rows do not.
Conn = collections.namedtuple("Conn", "laddr status pid")
OwnConn = collections.namedtuple("OwnConn", "laddr status")


def listening(port, pid, ip="127.0.0.1"):
    return Conn(Addr(ip, port), psutil.CONN_LISTEN, pid)


class FakeProcess:
    """Stands in for psutil.Process. Each read takes the exception it should
    raise, so every one of process_name's three answers can be reached."""

    def __init__(self, pid, name="llama-server", started=1000.5, conns=(),
                 name_error=None, started_error=None, conns_error=None):
        self.pid = pid
        self._name = name
        self._started = started
        self._conns = list(conns)
        self._name_error = name_error
        self._started_error = started_error
        self._conns_error = conns_error

    def name(self):
        if self._name_error is not None:
            raise self._name_error
        return self._name

    def create_time(self):
        if self._started_error is not None:
            raise self._started_error
        return self._started

    def net_connections(self, kind):
        if self._conns_error is not None:
            raise self._conns_error
        return list(self._conns)


class FakePs:
    """Stands in for the psutil MODULE, which is what server's functions take.

    The exception classes are psutil's own, so the `except ps.NoSuchProcess`
    clauses under test catch exactly what the real library raises. `calls`
    records every question asked of the machine: which pid, which table."""

    CONN_LISTEN = psutil.CONN_LISTEN
    Error = psutil.Error
    NoSuchProcess = psutil.NoSuchProcess
    AccessDenied = psutil.AccessDenied
    TimeoutExpired = psutil.TimeoutExpired

    def __init__(self, table=(), table_error=None, procs=()):
        self.table = list(table)
        self.table_error = table_error
        self.procs = {p.pid: p for p in procs}
        self.calls = []

    def net_connections(self, kind):
        self.calls.append(("net_connections", kind))
        if self.table_error is not None:
            raise self.table_error
        return list(self.table)

    def Process(self, pid):
        self.calls.append(("Process", pid))
        if pid not in self.procs:
            raise psutil.NoSuchProcess(pid)
        return self.procs[pid]

    def process_iter(self):
        self.calls.append(("process_iter",))
        return list(self.procs.values())


class TestProcessName(unittest.TestCase):
    """process_name is the guard on the stop path. Its three answers are
    different facts, and conflating any two of them is a safety bug."""

    def name(self, ps):
        return server.process_name(4321, ps=ps)

    def test_asks_about_exactly_one_pid(self):
        """The safety property. A lookup by NAME would answer about some other
        llama-server entirely."""
        ps = FakePs(procs=[FakeProcess(4321)])
        self.name(ps)
        self.assertEqual(ps.calls, [("Process", 4321)])

    def test_returns_the_name(self):
        ps = FakePs(procs=[FakeProcess(4321, name="llama-server")])
        self.assertEqual(self.name(ps), "llama-server")

    def test_a_process_that_is_gone_is_empty_string(self):
        """Answer two of three: it exited, so there is nothing to stop.
        FakePs raises NoSuchProcess for a pid it does not hold."""
        self.assertEqual(self.name(FakePs()), "")

    def test_a_zombie_is_gone_too(self):
        """Exited but not yet reaped. It holds no port and cannot be stopped."""
        zombie = FakeProcess(4321, name_error=psutil.ZombieProcess(4321))
        self.assertEqual(self.name(FakePs(procs=[zombie])), "")

    def test_access_denied_is_unknown_not_empty(self):
        """Answer three. "" would tell kill()'s guard a live process had
        exited; "unknown" says we could not ask, and not knowing is not
        permission."""
        denied = FakeProcess(4321, name_error=psutil.AccessDenied(4321))
        self.assertEqual(self.name(FakePs(procs=[denied])), "unknown")

    def test_an_os_error_is_unknown(self):
        broken = FakeProcess(4321, name_error=OSError("boom"))
        self.assertEqual(self.name(FakePs(procs=[broken])), "unknown")


class TestProcessStarted(unittest.TestCase):
    def test_returns_the_creation_time(self):
        ps = FakePs(procs=[FakeProcess(4321, started=1700000000.25)])
        self.assertEqual(server.process_started(4321, ps=ps), 1700000000.25)

    def test_a_process_that_is_gone_has_none(self):
        self.assertIsNone(server.process_started(4321, ps=FakePs()))

    def test_access_denied_is_none(self):
        denied = FakeProcess(4321, started_error=psutil.AccessDenied(4321))
        self.assertIsNone(server.process_started(4321, ps=FakePs(procs=[denied])))


def no_probe(host, port):
    raise AssertionError("the connect probe must not be consulted")


class TestPortOwner(unittest.TestCase):
    """Who holds a port, from the system-wide TCP table. Three answers, and
    the difference between "free" and "could not ask" is the point."""

    def owner(self, port, ps):
        return server.port_owner(port, ps=ps, probe=no_probe)

    def test_asks_for_the_tcp_table(self):
        ps = FakePs()
        self.owner(8080, ps)
        self.assertEqual(ps.calls[0], ("net_connections", "tcp"))

    def test_reports_the_pid_the_name_and_the_start_time(self):
        ps = FakePs(table=[listening(8080, 19004)],
                    procs=[FakeProcess(19004, name="llama-server", started=1000.5)])
        owner = self.owner(8080, ps)
        self.assertEqual(owner, server.Owner(19004, "llama-server", 1000.5))
        self.assertEqual((owner.pid, owner.name, owner.started),
                         (19004, "llama-server", 1000.5))

    def test_a_free_port_is_none(self):
        ps = FakePs(table=[listening(8080, 19004)], procs=[FakeProcess(19004)])
        self.assertIsNone(self.owner(9999, ps))

    def test_ignores_rows_that_are_not_listeners(self):
        """8082 has an ESTABLISHED row and a LISTEN row. The fixture puts the
        ESTABLISHED row FIRST and gives it a different pid. Both details are
        load-bearing: with the same pid, or with the listener first, this
        would pass with the status check deleted."""
        connected = Conn(Addr("127.0.0.1", 8082), psutil.CONN_ESTABLISHED, 31337)
        ps = FakePs(table=[connected, listening(8082, 24188)],
                    procs=[FakeProcess(31337), FakeProcess(24188)])
        self.assertEqual(self.owner(8082, ps).pid, 24188)

    def test_does_not_match_a_different_port(self):
        ps = FakePs(table=[listening(8080, 19004)], procs=[FakeProcess(19004)])
        self.assertIsNone(self.owner(808, ps))
        self.assertIsNone(self.owner(80800, ps))

    def test_a_row_without_an_address_is_skipped(self):
        """An unbound socket reports its address as an empty tuple."""
        ps = FakePs(table=[Conn((), psutil.CONN_LISTEN, 5)], procs=[FakeProcess(5)])
        self.assertIsNone(self.owner(8080, ps))

    def test_a_table_that_cannot_be_read_is_not_a_free_port(self):
        """'Could not determine' is not evidence the port is unused. Returning
        None here would send the launcher on to start a server on a port
        something else may well be holding."""
        owner = self.owner(8080, FakePs(table_error=psutil.Error()))
        self.assertIsNotNone(owner)
        self.assertEqual(owner, server.UNKNOWN_OWNER)
        self.assertIsNone(owner.pid)
        self.assertEqual(owner.name, "unknown")

    def test_an_os_error_reading_the_table_is_not_a_free_port(self):
        owner = self.owner(8080, FakePs(table_error=OSError("boom")))
        self.assertEqual(owner, server.UNKNOWN_OWNER)

    def test_a_listener_the_os_will_not_name_is_unknown(self):
        """Linux lists another user's listening socket without its pid. The
        port IS held; there is just nobody we are allowed to name."""
        ps = FakePs(table=[listening(8080, None)])
        self.assertEqual(self.owner(8080, ps), server.UNKNOWN_OWNER)

    def test_a_row_that_names_a_process_beats_one_that_does_not(self):
        """One port, two rows: an IPv6 row with no pid ahead of an IPv4 row
        with one. Stopping at the first would report a port we CAN identify
        as unidentifiable."""
        ps = FakePs(table=[listening(8080, None, ip="::"), listening(8080, 19004)],
                    procs=[FakeProcess(19004)])
        self.assertEqual(self.owner(8080, ps).pid, 19004)

    def test_a_listener_that_exited_meanwhile_reads_as_free(self):
        """The table saw it, the process is gone: the port really is free."""
        ps = FakePs(table=[listening(8080, 19004)])       # no such process
        self.assertIsNone(self.owner(8080, ps))

    def test_a_held_port_whose_owner_cannot_be_named_stays_unknown(self):
        """The port IS held; we just cannot say by what. Reporting it free
        would be a lie, and the name kill() refuses on keeps it unkillable."""
        denied = psutil.AccessDenied(19004)
        hidden = FakeProcess(19004, name_error=denied, started_error=denied)
        ps = FakePs(table=[listening(8080, 19004)], procs=[hidden])
        self.assertEqual(self.owner(8080, ps),
                         server.Owner(19004, "unknown", None))

    def test_the_probe_is_not_consulted_when_the_table_could_be_read(self):
        """The table is authoritative where the OS lets us read it. no_probe
        raises, so merely reaching these two answers is the assertion."""
        ps = FakePs(table=[listening(8080, 19004)], procs=[FakeProcess(19004)])
        self.assertIsNotNone(self.owner(8080, ps))
        self.assertIsNone(self.owner(9999, ps))


class TestPortOwnerWithoutTheSystemTable(unittest.TestCase):
    """macOS refuses the system-wide table to anyone but root, so the owner is
    found by asking each process for its own sockets. That walk cannot see
    another user's listener, which is why 'found nothing' is cross-checked
    with a connect before it is allowed to mean 'free'."""

    def ps(self, *procs):
        return FakePs(table_error=psutil.AccessDenied(), procs=procs)

    def own(self, port):
        return OwnConn(Addr("127.0.0.1", port), psutil.CONN_LISTEN)

    def test_falls_back_to_asking_each_process(self):
        ps = self.ps(FakeProcess(1), FakeProcess(19004, conns=[self.own(8080)]))
        owner = server.port_owner(8080, ps=ps, probe=no_probe)
        self.assertEqual(owner, server.Owner(19004, "llama-server", 1000.5))
        self.assertIn(("process_iter",), ps.calls)

    def test_skips_processes_that_deny_access_or_vanish(self):
        ps = self.ps(FakeProcess(1, conns_error=psutil.AccessDenied(1)),
                     FakeProcess(2, conns_error=psutil.NoSuchProcess(2)),
                     FakeProcess(19004, conns=[self.own(8080)]))
        self.assertEqual(server.port_owner(8080, ps=ps, probe=no_probe).pid, 19004)

    def test_finding_nothing_with_nothing_answering_is_free(self):
        ps = self.ps(FakeProcess(1, conns=[self.own(9000)]))
        self.assertIsNone(server.port_owner(8080, ps=ps, probe=lambda h, p: False))

    def test_finding_nothing_while_something_answers_is_unknown(self):
        """Somebody else's process holds it. Not ours to name, not ours to
        stop - and above all not free."""
        owner = server.port_owner(8080, ps=self.ps(FakeProcess(1)),
                                  probe=lambda h, p: True)
        self.assertEqual(owner, server.UNKNOWN_OWNER)

    def test_the_probe_is_a_local_connect_to_that_port(self):
        asked = []
        server.port_owner(8080, ps=self.ps(),
                          probe=lambda h, p: asked.append((h, p)) or False)
        self.assertEqual(asked, [("127.0.0.1", 8080)])


class Completed:
    """Minimal stand-in for subprocess.CompletedProcess."""

    def __init__(self, stdout="", returncode=0):
        self.stdout = stdout
        self.stderr = ""
        self.returncode = returncode


class FakeRun:
    """Stands in for subprocess.run: records the exact argv and kwargs of the
    taskkill call. Removed with taskkill itself in the next task."""

    def __init__(self, raises=None, **answers):
        self.calls = []                  # (argv, kwargs) per call, in order
        self.raises = raises
        self.answers = answers

    def __call__(self, argv, **kwargs):
        self.calls.append((argv, kwargs))
        if self.raises is not None:
            raise self.raises
        return self.answers.get(argv[0], Completed())

    def argv(self, tool):
        for argv, _ in self.calls:
            if argv[0] == tool:
                return argv
        raise AssertionError(f"{tool} was never run; ran {self.tools()}")

    def kwargs(self, tool):
        for argv, kwargs in self.calls:
            if argv[0] == tool:
                return kwargs
        raise AssertionError(f"{tool} was never run; ran {self.tools()}")

    def tools(self):
        return [argv[0] for argv, _ in self.calls]


class TestConsoleDecoding(unittest.TestCase):
    """taskkill is the last console tool on this path, and the next task
    replaces it. Until then its output is still OEM-encoded and it can still
    hang, so both guarantees stay under test."""

    def test_taskkill_decodes_with_the_oem_codepage(self):
        run = FakeRun(taskkill=Completed(""))
        server._force_kill(4321, run=run)
        self.assertEqual(run.kwargs("taskkill")["encoding"], server.OEM)
        self.assertEqual(run.kwargs("taskkill")["errors"], "replace")

    @unittest.skipUnless(sys.platform == "win32", "OEM is a Windows codepage")
    def test_oem_is_the_console_codepage_not_the_ansi_one(self):
        self.assertEqual(server.OEM, "oem")

    def test_taskkill_has_a_timeout(self):
        run = FakeRun(taskkill=Completed(""))
        server._force_kill(4321, run=run)
        self.assertGreater(run.kwargs("taskkill")["timeout"], 0)
```

`class TestForceKill` and everything after it are untouched in this task.

- [ ] **Step 3: Make the launch fixtures use `Owner`**

In `tests/test_main.py`, three fixtures pass a two-tuple as the port's owner. Replace each:

| Line | Old | New |
|---|---|---|
| 435 | `owner=(4321, "llama-server-proxy.exe")` | `owner=server.Owner(4321, "llama-server-proxy.exe", 1000.5)` |
| 445 | `owner=(4321, "LLAMA-SERVER.EXE"),` | `owner=server.Owner(4321, "LLAMA-SERVER.EXE", 1000.5),` |
| 568 | `owner=(4321, "nginx.exe")` | `owner=server.Owner(4321, "nginx.exe", 1000.5)` |

- [ ] **Step 4: Create the live tests**

Create `tests/test_server_live.py`:

```python
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


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 5: Run the tests to verify they fail**

```bash
uv run python -B -m unittest tests.test_server.TestPortOwner tests.test_server_live 2>&1 | tail -n 6
```

Expected: errors such as `AttributeError: module 'llama_launcher.server' has no attribute 'Owner'` and `TypeError: port_owner() got an unexpected keyword argument 'ps'`.

- [ ] **Step 6: Rewrite the lookup half of `llama_launcher/server.py`**

Replace the import block at the top with:

```python
import collections
import socket
import subprocess
import sys
import time

import psutil
```

Leave the long comment about OEM codepages, `OEM = ...` and `_console` exactly as they are — `_force_kill` still uses them until Task 4.

Replace the `UNKNOWN` / `UNKNOWN_OWNER` block with:

```python
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
```

Delete `parse_netstat` and `parse_tasklist` entirely. Replace `process_name` and `port_owner` with:

```python
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
```

- [ ] **Step 7: Unpack the `Owner` in `launch`**

In `llama_launcher/__main__.py`, inside `launch`, change

```python
        pid, name = owner
```

to

```python
        pid, name = owner.pid, owner.name
```

Nothing else in `launch` changes in this task: the `"llama-server.exe"` comparison and the `server.kill(pid, expect_name=name)` call are Task 4's.

- [ ] **Step 8: Run the tests on Windows**

```bash
uv run python -B -m unittest tests.test_server tests.test_server_live -v 2>&1 | tail -n 4
uv run python -B -m unittest discover -s tests -t . 2>&1 | grep -E "^Ran |^OK|^FAILED"
```

Expected: `OK` for both; the full suite reports `Ran 414 tests` and `OK` (409 − 12 parser tests − 1 + 3 + 5 + 5 in `test_server.py`, + 5 live).

- [ ] **Step 9: Run the suite under WSL**

Use the WSL command from "Commands used throughout", piped through `grep -E '^(FAIL|ERROR):|^Ran |^OK|^FAILED'`.

Expected: `Ran 414 tests`, `FAILED (failures=3, skipped=4)`, and the same three `tests.test_config.TestPaths` failures as in Step 1 — nothing else. In particular all five tests in `tests.test_server_live` pass on Linux.

If `test_its_creation_time_reads_the_same_twice` fails on either OS, stop: §12 of the spec says the equality check then gains a tolerance, and that is a change to Task 4's guard to raise with the owner before continuing.

- [ ] **Step 10: Commit**

```bash
git add llama_launcher/server.py llama_launcher/__main__.py tests/test_server.py tests/test_main.py tests/test_server_live.py
git diff --staged --stat
git commit -m "feat(server): find a port's owner with psutil on every OS" -m "Replaces netstat and tasklist parsing and the localised-output
hazards that came with it. Where the socket table is refused (macOS),
each process is asked, and a miss is confirmed by a connect before it
is allowed to mean free."
```

- [ ] **Step 11: Mutation check**

For each row: make the change in `llama_launcher/server.py`, run the command, confirm the named test fails, then `git restore llama_launcher/server.py`.

| Mutation | Test that must fail |
|---|---|
| In `_listens_on`, delete `conn.status == ps.CONN_LISTEN and` | `TestPortOwner.test_ignores_rows_that_are_not_listeners` |
| In `_table_listener`, replace the `if conn.pid is not None:` block and `held = True` with a bare `return True, conn.pid` | `TestPortOwner.test_a_row_that_names_a_process_beats_one_that_does_not` |
| In `port_owner`, change `return UNKNOWN_OWNER if probe("127.0.0.1", port) else None` to `return None` | `TestPortOwnerWithoutTheSystemTable.test_finding_nothing_while_something_answers_is_unknown` |
| In `port_owner`, change the outer `return UNKNOWN_OWNER` (under `except (ps.Error, OSError)`) to `return None` | `TestPortOwner.test_a_table_that_cannot_be_read_is_not_a_free_port` |
| In `process_name`, change `return ""` to `return UNKNOWN` | `TestProcessName.test_a_process_that_is_gone_is_empty_string` |

```bash
uv run python -B -m unittest tests.test_server 2>&1 | tail -n 12
```

Finish with `git status --short` showing only `?? docs/tui-plan.md`.

---

### Task 4: Stop through `psutil`, guard by start time, identify by the configured binary

**Files:**
- Modify: `llama_launcher/server.py` — delete the OEM comment, `OEM`, `_console`, `_force_kill`; add `STOP_GRACE`, `_stop`; replace `kill`
- Modify: `llama_launcher/__main__.py` — add `is_llama_server`; the port-owner block of `launch`; the decode in `device_line`
- Modify: `tests/test_server.py` — delete `Completed`, `FakeRun`, `TestConsoleDecoding`, `TestForceKill`; add `Stoppable`, `TestStop`, `TestKillStartGuard`; adjust `TestKillGuard`, `TestKillPortGuard`
- Modify: `tests/test_main.py` — `LaunchFixture`, `TestPortOwnerIdentity`; add `TestIsLlamaServer`
- Modify: `tests/test_setup.py` — one test in `TestDeviceLine`
- Modify: `tests/test_server_live.py` — add `TestStoppingARealListener`

**Interfaces:**
- Consumes from Task 3: `Owner`, `UNKNOWN_OWNER`, `process_name`, `process_started`, `port_owner`; `FakePs`, `FakeProcess` in `tests/test_server.py`; `LiveListener`, `free_port` in `tests/test_server_live.py`.
- Produces, in `llama_launcher.server`:
  - `STOP_GRACE = 5`
  - `_stop(pid, ps=psutil, grace=STOP_GRACE) -> bool`
  - `kill(pid, *, expect_name, expect_started, expect_port=None, name_of=process_name, started_of=process_started, force=_stop, owner_of=port_owner) -> bool`
- Produces, in `llama_launcher.__main__`:
  - `is_llama_server(name, llama_server) -> bool`
- Removed from `llama_launcher.server`: `OEM`, `_console`, `_force_kill`.

- [ ] **Step 1: Replace the stop tests in `tests/test_server.py`**

Delete `class Completed`, `class FakeRun`, `class TestConsoleDecoding` and `class TestForceKill`. Where `TestForceKill` was, put:

```python
class Stoppable:
    """A fake psutil.Process for the stop sequence. `waits` scripts each wait()
    call in order: None means it exited in time, an exception is raised."""

    def __init__(self, waits=(None,), terminate_error=None, kill_error=None):
        self.pid = 4321
        self.calls = []
        self._waits = list(waits)
        self._terminate_error = terminate_error
        self._kill_error = kill_error

    def terminate(self):
        self.calls.append("terminate")
        if self._terminate_error is not None:
            raise self._terminate_error

    def kill(self):
        self.calls.append("kill")
        if self._kill_error is not None:
            raise self._kill_error

    def wait(self, timeout=None):
        self.calls.append(("wait", timeout))
        outcome = self._waits.pop(0)
        if outcome is not None:
            raise outcome


class TestStop(unittest.TestCase):
    """The one function that actually ends a process."""

    def stop(self, proc):
        ps = FakePs(procs=[proc])
        return server._stop(4321, ps=ps), ps

    def test_targets_exactly_one_pid(self):
        """THE regression this project exists to prevent. Stopping by name
        looks like a success while ending every llama-server on the machine -
        including ones the user started by hand and is still using."""
        _, ps = self.stop(Stoppable())
        self.assertEqual(ps.calls, [("Process", 4321)])

    def test_asks_first_and_does_not_force_a_process_that_exits_in_time(self):
        proc = Stoppable(waits=[None])
        result, _ = self.stop(proc)
        self.assertIs(result, True)
        self.assertEqual(server.STOP_GRACE, 5)
        self.assertEqual(proc.calls, ["terminate", ("wait", 5)])

    def test_forces_only_after_the_grace_period(self):
        proc = Stoppable(waits=[psutil.TimeoutExpired(5), None])
        result, _ = self.stop(proc)
        self.assertIs(result, True)
        self.assertEqual(proc.calls,
                         ["terminate", ("wait", 5), "kill", ("wait", 5)])

    def test_false_when_it_survives_even_the_force(self):
        proc = Stoppable(waits=[psutil.TimeoutExpired(5), psutil.TimeoutExpired(5)])
        result, _ = self.stop(proc)
        self.assertIs(result, False)

    def test_false_when_the_os_refuses(self):
        proc = Stoppable(terminate_error=psutil.AccessDenied(4321))
        result, _ = self.stop(proc)
        self.assertIs(result, False)
        self.assertEqual(proc.calls, ["terminate"])

    def test_a_process_that_is_already_gone_counts_as_stopped(self):
        """Nothing is running under that pid, which is what the caller asked
        for. FakePs raises NoSuchProcess for a pid it does not hold."""
        self.assertIs(server._stop(4321, ps=FakePs()), True)

    def test_a_process_that_exits_between_the_two_steps_counts_as_stopped(self):
        proc = Stoppable(waits=[psutil.TimeoutExpired(5)],
                         kill_error=psutil.NoSuchProcess(4321))
        result, _ = self.stop(proc)
        self.assertIs(result, True)

    def test_an_os_error_is_false(self):
        proc = Stoppable(terminate_error=OSError("boom"))
        result, _ = self.stop(proc)
        self.assertIs(result, False)
```

- [ ] **Step 2: Adjust `TestKillGuard` and `TestKillPortGuard` for the new required argument**

In `TestKillGuard`, replace the `kill` helper with:

```python
    def kill(self, reported, expect="llama-server.exe"):
        """Returns (result, pids actually passed to the stopper)."""
        killed = []
        result = server.kill(4321, expect_name=expect, expect_started=1000.5,
                             name_of=lambda pid: reported,
                             started_of=lambda pid: 1000.5,
                             force=lambda pid: killed.append(pid) or True)
        return result, killed
```

and replace `test_expect_name_is_required_and_keyword_only` with:

```python
    def test_expect_name_is_required_and_keyword_only(self):
        """A default would let a caller silently fall back to unguarded killing."""
        with self.assertRaises(TypeError):
            server.kill(4321, expect_started=1000.5)
        with self.assertRaises(TypeError):
            server.kill(4321, "llama-server.exe", expect_started=1000.5)
```

In `TestKillPortGuard`, replace the `kill` helper with:

```python
    def kill(self, owner, expect_port=8080, reported="llama-server.exe"):
        killed = []
        result = server.kill(4321, expect_name="llama-server.exe",
                             expect_started=1000.5, expect_port=expect_port,
                             name_of=lambda pid: reported,
                             started_of=lambda pid: 1000.5,
                             force=lambda pid: killed.append(pid) or True,
                             owner_of=lambda port: owner)
        return result, killed
```

replace the three tuple owners in that class —

| Old | New |
|---|---|
| `self.kill((4321, "llama-server.exe"))` | `self.kill(server.Owner(4321, "llama-server.exe", 1000.5))` |
| `self.kill((9999, "llama-server.exe"))` | `self.kill(server.Owner(9999, "llama-server.exe", 1000.5))` |
| `self.kill((4321, "notepad.exe"), reported="notepad.exe")` | `self.kill(server.Owner(4321, "notepad.exe", 1000.5), reported="notepad.exe")` |

— and in `test_the_port_check_is_opt_in_and_costs_nothing_when_unused`, replace the direct call with:

```python
        result = server.kill(4321, expect_name="llama-server.exe",
                             expect_started=1000.5,
                             name_of=lambda pid: "llama-server.exe",
                             started_of=lambda pid: 1000.5,
                             force=lambda pid: killed.append(pid) or True,
                             owner_of=boom)
```

Immediately after `class TestKillPortGuard`, add:

```python
class TestKillStartGuard(unittest.TestCase):
    """The name proves the pid is *a* llama-server, and the port proves it is
    the one listening there NOW. Neither proves it is the process the user was
    asked about: that one may have exited, and a new llama-server may hold both
    its pid and its port. Only the creation time tells those two apart."""

    def kill(self, started_now, expect_started=1000.5, expect_port=None,
             owner=None):
        killed = []
        result = server.kill(4321, expect_name="llama-server",
                             expect_started=expect_started,
                             expect_port=expect_port,
                             name_of=lambda pid: "llama-server",
                             started_of=lambda pid: started_now,
                             force=lambda pid: killed.append(pid) or True,
                             owner_of=lambda port: owner)
        return result, killed

    def test_proceeds_when_the_start_time_is_unchanged(self):
        """The positive path, so 'always refuse' cannot pass this class."""
        result, killed = self.kill(1000.5)
        self.assertTrue(result)
        self.assertEqual(killed, [4321])

    def test_refuses_a_recycled_pid_even_under_the_same_name(self):
        result, killed = self.kill(2000.0)
        self.assertFalse(result)
        self.assertEqual(killed, [], "must not have called the stopper at all")

    def test_refuses_same_name_same_port_different_start_time(self):
        """The case the old guards could not see: every other check passes."""
        successor = server.Owner(4321, "llama-server", 2000.0)
        result, killed = self.kill(2000.0, expect_port=8080, owner=successor)
        self.assertFalse(result)
        self.assertEqual(killed, [])

    def test_refuses_when_the_start_time_cannot_be_read(self):
        result, killed = self.kill(None)
        self.assertFalse(result)
        self.assertEqual(killed, [])

    def test_refuses_when_no_start_time_was_recorded(self):
        """None == None must not read as 'unchanged'. An owner whose start
        time could not be read at snapshot time cannot be re-identified, and
        not knowing is not permission."""
        result, killed = self.kill(None, expect_started=None)
        self.assertFalse(result)
        self.assertEqual(killed, [])

    def test_expect_started_is_required_and_keyword_only(self):
        """For the reason expect_name is: a caller that forgets it must not
        silently get the weaker guard."""
        with self.assertRaises(TypeError):
            server.kill(4321, expect_name="llama-server")
        with self.assertRaises(TypeError):
            server.kill(4321, "llama-server", 1000.5)
```

- [ ] **Step 3: Rework the launch tests in `tests/test_main.py`**

In `LaunchFixture.launch`, change the signature, the `calls` dictionary and `fake_kill`:

```python
    def launch(self, values, owner=None, ask=None, wait=None, spawn=KEEP,
               kill=True):
        """Returns (result, printed text, calls). Nothing real is started."""
        calls = {"owner_port": [], "wait_port": [], "killed": [], "asked": [],
                 "spawned": [], "kill_args": []}
```

```python
        def fake_kill(pid, **kw):
            calls["killed"].append(pid)
            calls["kill_args"].append(kw)
            return kill
```

Replace the whole of `class TestPortOwnerIdentity` with:

```python
class TestPortOwnerIdentity(LaunchFixture):
    """What counts as 'our' llama-server: a process whose name equals the file
    name of the binary in the config. Not a literal, and never a substring."""

    def owner(self, name):
        return server.Owner(4321, name, 1000.5)

    def test_a_process_whose_name_merely_contains_llama_server_is_not_ours(self):
        """"llama-server-proxy.exe" contains "llama-server", so a substring
        test offered somebody else's process up for a stop."""
        result, text, calls = self.launch(
            self.values(), owner=self.owner("llama-server-proxy.exe"))
        self.assertIs(result, False)
        self.assertIn("not a llama-server", text)
        self.assertEqual(calls["asked"], [], "must not have offered to stop it")
        self.assertEqual(calls["killed"], [])

    def test_the_configured_binary_is_recognised(self):
        """Otherwise 'never match' would pass the test above and the launcher
        could never take back its own port."""
        result, text, calls = self.launch(
            self.values(), owner=self.owner("llama-server.exe"), ask="y")
        self.assertIs(result, True)
        self.assertEqual(calls["killed"], [4321])
        self.assertNotIn("not a llama-server", text)

    @unittest.skipUnless(os.name == "nt", "file names fold case on Windows only")
    def test_the_match_ignores_case_on_windows(self):
        result, _, calls = self.launch(
            self.values(), owner=self.owner("LLAMA-SERVER.EXE"), ask="y")
        self.assertIs(result, True)
        self.assertEqual(calls["killed"], [4321])

    @unittest.skipIf(os.name == "nt", "file names are case-sensitive off Windows")
    def test_the_match_is_exact_off_windows(self):
        result, text, calls = self.launch(
            self.values(), owner=self.owner("LLAMA-SERVER.EXE"))
        self.assertIs(result, False)
        self.assertIn("not a llama-server", text)
        self.assertEqual(calls["killed"], [])

    def test_a_binary_under_another_name_is_recognised_by_that_name(self):
        self.data["llama_server"] = "/opt/llama/bin/llama-server-vulkan"
        result, _, calls = self.launch(
            self.values(), owner=self.owner("llama-server-vulkan"), ask="y")
        self.assertIs(result, True)
        self.assertEqual(calls["killed"], [4321])

    def test_the_standard_name_is_not_ours_when_another_binary_is_configured(self):
        """The check follows the config, not a built-in idea of the name."""
        self.data["llama_server"] = "/opt/llama/bin/llama-server-vulkan"
        result, text, calls = self.launch(
            self.values(), owner=self.owner("llama-server"))
        self.assertIs(result, False)
        self.assertIn("not a llama-server", text)
        self.assertEqual(calls["killed"], [])

    def test_the_stop_is_asked_to_verify_name_start_time_and_port(self):
        """All three guards, from the one production call site. kill() could
        always re-check the port; nothing ever asked it to."""
        _, _, calls = self.launch(
            self.values(port=8082), owner=self.owner("llama-server.exe"), ask="y")
        self.assertEqual(calls["kill_args"],
                         [{"expect_name": "llama-server.exe",
                           "expect_started": 1000.5,
                           "expect_port": 8082}])

    def test_a_stop_that_is_refused_ends_the_launch_and_starts_nothing(self):
        result, text, calls = self.launch(
            self.values(), owner=self.owner("llama-server.exe"), ask="y",
            kill=False)
        self.assertIs(result, False)
        self.assertIn("was not stopped", text)
        self.assertEqual(calls["spawned"], [])


class TestIsLlamaServer(unittest.TestCase):
    def test_equal_names_match(self):
        self.assertIs(
            main.is_llama_server("llama-server", "/usr/local/bin/llama-server"),
            True)

    def test_a_longer_or_shorter_name_does_not_match(self):
        for name in ("llama-server-proxy", "xllama-server", "llama-serve"):
            with self.subTest(name=name):
                self.assertIs(
                    main.is_llama_server(name, "/usr/local/bin/llama-server"),
                    False)

    def test_the_folder_of_the_binary_is_ignored(self):
        self.assertIs(
            main.is_llama_server("llama-server.exe",
                                 "D:/llama.cpp/build/bin/llama-server.exe"),
            True)

    def test_a_value_that_is_not_a_string_is_never_a_match(self):
        """llama_server comes from a hand-edited file and the name from a
        lookup that can fail; neither may raise here."""
        for name, exe in ((None, "/x/llama-server"), ("llama-server", 5),
                          ("llama-server", None), (5, 5)):
            with self.subTest(name=name, exe=exe):
                self.assertIs(main.is_llama_server(name, exe), False)

    def test_an_empty_name_is_never_a_match(self):
        self.assertIs(main.is_llama_server("", "/x/llama-server"), False)
        self.assertIs(main.is_llama_server("", "/x/folder/"), False)
```

- [ ] **Step 4: Add the decoding test to `tests/test_setup.py`**

Add `from unittest import mock` to the imports, and add this method to `class TestDeviceLine`:

```python
    def test_a_device_name_outside_ascii_is_read_as_utf8(self):
        """llama-server writes UTF-8. The console codepage this used to be
        decoded with belonged to netstat and tasklist, not to llama-server."""
        class Done:
            stdout = ("Available devices:\n"
                      "  Vulkan0: Ger\u00e4t (1 MiB)\n").encode("utf-8")

        with mock.patch.object(main.subprocess, "run", lambda *a, **k: Done()):
            self.assertIn("Ger\u00e4t", main.device_line("llama-server"))
```

- [ ] **Step 5: Add the live stop tests**

Append to `tests/test_server_live.py`, above the `if __name__` line:

```python
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
```

- [ ] **Step 6: Run the tests to verify they fail**

```bash
uv run python -B -m unittest tests.test_server tests.test_main tests.test_setup tests.test_server_live 2>&1 | tail -n 6
```

Expected: errors, among them `AttributeError: module 'llama_launcher.server' has no attribute '_stop'`, `TypeError: kill() got an unexpected keyword argument 'expect_started'` and `AttributeError: ... has no attribute 'is_llama_server'`.

- [ ] **Step 7: Rewrite the stop half of `llama_launcher/server.py`**

Delete the long comment about OEM codepages, the `OEM = ...` line, `_console` and `_force_kill`. Replace `kill` with the two definitions below, placed after `port_owner`.

```python
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
    if not current or current.lower() != expect_name.lower():
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
```

- [ ] **Step 8: Identify by the configured binary, and pass all three guards, in `llama_launcher/__main__.py`**

Add this function immediately above `def launch(`:

```python
def is_llama_server(name, llama_server):
    """Whether a process called `name` is the configured llama-server binary.

    Compared with the FILE NAME of the binary in the config, so it is right on
    every OS without a table of names ("llama-server.exe" here, "llama-server"
    there) and right for a user whose build is called something else.

    Equality, never a substring: "llama-server-proxy" contains "llama-server"
    and would have been offered up for a stop as though it were ours. normcase
    folds case on Windows, where file names are case-insensitive, and leaves it
    alone everywhere else.

    Both arguments come from places a hand edit or a failed lookup can reach,
    so anything that is not a non-empty string is simply not a match."""
    if not isinstance(name, str) or not isinstance(llama_server, str):
        return False
    expected = os.path.basename(llama_server)
    return bool(expected) and os.path.normcase(name) == os.path.normcase(expected)
```

In `launch`, replace everything from `owner = server.port_owner(port)` down to (not including) `print(f"\n  starting {cfg['name']} ...")` with:

```python
    owner = server.port_owner(port)
    if owner and owner.pid is None:
        # port_owner's third answer: the lookup could not be made, so the
        # port's state is unknown. Not evidence that it is busy, and not
        # evidence that it is free - saying "held by unknown (pid None)" would
        # be neither. Going on is the honest choice: llama-server refuses to
        # start on a taken port, and wait_ready reports that as an exit code.
        print(f"  could not check whether port {port} is free - starting anyway")
        owner = None
    if owner:
        if not is_llama_server(owner.name, data["llama_server"]):
            print(f"\n  port {port} is held by {owner.name} (pid {owner.pid}), "
                  f"not a llama-server. Change the port on row 3.\n")
            return False
        if ask(f"  port {port} is held by llama-server (pid {owner.pid}). "
               f"Stop it? [Y/n] ").strip().lower() in ("", "y"):
            # All three guards, re-checked at the moment of the stop. The
            # snapshot above is as old as the user's pause at this prompt, and
            # pids are recycled - without the name and the start time, a server
            # that exited meanwhile could hand its pid to something unrelated;
            # without the port, to another llama-server we never meant.
            if not server.kill(owner.pid, expect_name=owner.name,
                               expect_started=owner.started, expect_port=port):
                print(f"  pid {owner.pid} was not stopped - it is no longer the "
                      f"{owner.name} that held port {port}, or stopping it was "
                      f"refused. Re-check the port and try again.")
                return False
            print(f"  stopped pid {owner.pid}")
        else:
            return False

```

In `device_line`, replace the last line with:

```python
    # llama-server writes UTF-8. errors="replace" because this is a display
    # line called on every board render, and must never raise.
    return parse_devices(out.decode("utf-8", errors="replace"))
```

- [ ] **Step 9: Run the tests on Windows**

```bash
uv run python -B -m unittest tests.test_server tests.test_main tests.test_setup tests.test_server_live 2>&1 | tail -n 4
uv run python -B -m unittest discover -s tests -t . 2>&1 | grep -E "^Ran |^OK|^FAILED"
grep -nE "\bOEM\b|_console|_force_kill|parse_netstat|parse_tasklist|subprocess\.run" llama_launcher/server.py
```

Expected: `OK`; then `Ran 437 tests` and `OK (skipped=1)` — 414 + 7 in `test_server.py`, + 4 live, + 11 in `test_main.py`, + 1 in `test_setup.py`; the one skip is `test_the_match_is_exact_off_windows`. The final `grep` prints nothing. (`_stop`'s docstring still names `taskkill /F`, to say what `terminate()` replaces; that mention is deliberate.)

- [ ] **Step 10: Run the suite under WSL**

Expected: `Ran 437 tests`, `FAILED (failures=3, skipped=4)`, the same three `TestPaths` failures and no others. All four tests in `TestStoppingARealListener` pass on Linux — this is the first time a stop has run there.

- [ ] **Step 11: Commit**

```bash
git add llama_launcher/server.py llama_launcher/__main__.py tests/test_server.py tests/test_main.py tests/test_setup.py tests/test_server_live.py
git diff --staged --stat
git commit -m "feat(server): stop servers through psutil and refuse a recycled pid" -m "kill() now also requires the creation time recorded with the port's
owner, and launch passes the port too - it never did. Identity is the
configured binary's file name, so it holds on every OS. Stopping asks
before it forces."
```

- [ ] **Step 12: Mutation check**

For each row: make the change, run the command, confirm the named test fails, then `git restore` the file.

| File | Mutation | Test that must fail |
|---|---|---|
| `server.py` | In `kill`, change `if expect_started is None or started_of(pid) != expect_started:` to `if started_of(pid) != expect_started:` | `TestKillStartGuard.test_refuses_when_no_start_time_was_recorded` |
| `server.py` | In `kill`, delete the start-time `if` and its `return False` | `TestKillStartGuard.test_refuses_a_recycled_pid_even_under_the_same_name` and `TestStoppingARealListener.test_the_wrong_start_time_is_refused_and_the_process_survives` |
| `server.py` | In `_stop`, change `proc.terminate()` to `proc.kill()` | `TestStop.test_asks_first_and_does_not_force_a_process_that_exits_in_time` |
| `server.py` | In `_stop`, change the first `except ps.NoSuchProcess:` `return True` to `return False` | `TestStop.test_a_process_that_is_already_gone_counts_as_stopped` |
| `__main__.py` | In `is_llama_server`, change the comparison to `os.path.normcase(expected) in os.path.normcase(name)` | `TestPortOwnerIdentity.test_a_process_whose_name_merely_contains_llama_server_is_not_ours` |
| `__main__.py` | In `launch`, delete `, expect_port=port` from the `server.kill` call | `TestPortOwnerIdentity.test_the_stop_is_asked_to_verify_name_start_time_and_port` |

```bash
uv run python -B -m unittest tests.test_server tests.test_main tests.test_server_live 2>&1 | tail -n 14
```

Finish with `git status --short` showing only `?? docs/tui-plan.md`.

---

### Task 5: Start detached with a log file on Linux and macOS

**Files:**
- Modify: `llama_launcher/server.py` — imports; add `log_path_for`; replace `spawn`; two messages and one parameter in `wait_ready`
- Modify: `llama_launcher/__main__.py` — add `LOG_DIR`, `launch_log_path`; the spawn block of `launch`
- Modify: `tests/test_server.py` — imports; add `TestSpawnToALogFile`, `TestLogPathFor`; three tests in `TestWaitReady`
- Modify: `tests/test_main.py` — imports; `LaunchFixture`; add `TestLaunchLogPath`, `TestLaunchWithALog`
- Modify: `tests/test_server_live.py` — imports; add `TestSpawningForReal`

**Interfaces:**
- Consumes: `platformdirs` and `APP` from Task 2; `LaunchFixture` as left by Task 4.
- Produces, in `llama_launcher.server`:
  - `log_path_for(name, port, log_dir) -> str`
  - `spawn(argv, log_path=None, popen=subprocess.Popen) -> Popen | None`
  - `wait_ready(host, port, proc, timeout=300, tick=None, probe=port_open, sleep=time.sleep, clock=time.monotonic, where="check its console window") -> (bool, str)`
- Produces, in `llama_launcher.__main__`:
  - `LOG_DIR: str`
  - `launch_log_path(cfg_name, port, platform=None) -> str | None`

- [ ] **Step 1: Write the failing tests in `tests/test_server.py`**

Add `import os` and `import tempfile` to the imports. Add these three methods to `class TestWaitReady`:

```python
    def test_a_dead_child_points_at_its_console_window_by_default(self):
        ok, msg = server.wait_ready("127.0.0.1", 8080, FakeProc(dies_after=1),
                                    probe=lambda h, p: False,
                                    sleep=lambda s: None)
        self.assertIs(ok, False)
        self.assertIn("check its console window", msg)

    def test_a_dead_child_points_at_its_log_when_there_is_one(self):
        ok, msg = server.wait_ready("127.0.0.1", 8080, FakeProc(dies_after=1),
                                    probe=lambda h, p: False,
                                    sleep=lambda s: None,
                                    where="see /logs/c-8080.log")
        self.assertIs(ok, False)
        self.assertIn("see /logs/c-8080.log", msg)
        self.assertNotIn("console window", msg)

    def test_a_child_that_never_started_is_not_told_about_an_exe(self):
        """The same message is read on Linux and macOS, where there is none."""
        ok, msg = server.wait_ready("127.0.0.1", 8080, None,
                                    sleep=lambda s: None)
        self.assertIn("did not start", msg)
        self.assertNotIn(".exe", msg)
```

Add these two classes immediately after `class TestSpawn`:

```python
class TestSpawnToALogFile(unittest.TestCase):
    """With a log path the server is detached and its output goes to a file -
    how Linux and macOS start it, having no second console to open."""

    def setUp(self):
        self.folder = tempfile.mkdtemp()
        self.log = os.path.join(self.folder, "logs", "c-8080.log")

    def spawn(self):
        seen = {}

        def fake_popen(argv, **kwargs):
            seen["argv"] = argv
            seen["kwargs"] = kwargs
            seen["log"] = kwargs["stdout"]
            return "proc"

        result = server.spawn(["llama-server", "--port", "8080"],
                              log_path=self.log, popen=fake_popen)
        return result, seen

    def test_output_goes_to_the_log_and_stdin_is_closed(self):
        result, seen = self.spawn()
        self.assertEqual(result, "proc")
        self.assertEqual(seen["argv"], ["llama-server", "--port", "8080"])
        self.assertEqual(seen["log"].name, self.log)
        self.assertIs(seen["kwargs"]["stderr"], subprocess.STDOUT)
        self.assertIs(seen["kwargs"]["stdin"], subprocess.DEVNULL)

    def test_the_server_is_detached_from_the_launchers_terminal(self):
        """Without a session of its own, Ctrl-C at the board and closing the
        terminal both reach the server."""
        _, seen = self.spawn()
        self.assertIs(seen["kwargs"]["start_new_session"], True)

    def test_no_console_window_is_requested(self):
        _, seen = self.spawn()
        self.assertNotIn("creationflags", seen["kwargs"])
        self.assertNotIn("shell", seen["kwargs"])

    def test_the_log_folder_is_created(self):
        self.assertFalse(os.path.exists(os.path.dirname(self.log)))
        self.spawn()
        self.assertTrue(os.path.isfile(self.log))

    def test_each_launch_starts_the_log_afresh(self):
        os.makedirs(os.path.dirname(self.log))
        with open(self.log, "w", encoding="utf-8") as f:
            f.write("the previous run")
        self.spawn()
        self.assertEqual(os.path.getsize(self.log), 0)

    def test_the_launchers_own_handle_is_closed_afterwards(self):
        """The child has its own copy. Keeping ours open would hold the file
        for as long as the launcher runs."""
        _, seen = self.spawn()
        self.assertTrue(seen["log"].closed)

    def test_a_log_that_cannot_be_opened_is_none_and_nothing_is_started(self):
        with open(os.path.join(self.folder, "logs"), "w", encoding="utf-8"):
            pass                              # a FILE where the folder goes

        def boom(argv, **kwargs):
            raise AssertionError("nothing may be started without its log")

        self.assertIsNone(server.spawn(["llama-server"], log_path=self.log,
                                       popen=boom))

    def test_returns_none_when_the_exe_has_moved(self):
        def gone(argv, **kwargs):
            raise FileNotFoundError(2, "No such file or directory")

        self.assertIsNone(server.spawn(["/gone/llama-server"],
                                       log_path=self.log, popen=gone))


class TestLogPathFor(unittest.TestCase):
    def test_named_after_the_config_and_the_port(self):
        self.assertEqual(server.log_path_for("qwen3.8", 8080, "logs"),
                         os.path.join("logs", "qwen3.8-8080.log"))

    def test_unsafe_characters_become_underscores(self):
        path = server.log_path_for("my config: v2", 8080, "logs")
        self.assertEqual(os.path.basename(path), "my_config__v2-8080.log")

    def test_a_name_cannot_climb_out_of_the_log_folder(self):
        """A config name is user text. However it is spelled, the file it
        names is directly inside the log folder."""
        folder = os.path.join("some", "logs")
        for name in ("../../etc/passwd", "..\\..\\boot.ini", "/abs", "C:\\x",
                     "..", "a/b", "qwen:3.8"):
            with self.subTest(name=name):
                path = server.log_path_for(name, 8080, folder)
                self.assertEqual(os.path.dirname(path), folder)
                self.assertNotIn("/", os.path.basename(path))
                self.assertNotIn("\\", os.path.basename(path))

    def test_a_name_that_is_not_a_string_still_makes_a_file_name(self):
        path = server.log_path_for(5, 8080, "logs")
        self.assertEqual(os.path.basename(path), "5-8080.log")
```

- [ ] **Step 2: Write the failing tests in `tests/test_main.py`**

Add `import platformdirs` after the standard-library imports.

In `LaunchFixture.launch`, change the signature, the `calls` dictionary, `fake_wait` and `fake_spawn`, and add one patch:

```python
    def launch(self, values, owner=None, ask=None, wait=None, spawn=KEEP,
               kill=True, log=None):
        """Returns (result, printed text, calls). Nothing real is started."""
        calls = {"owner_port": [], "wait_port": [], "killed": [], "asked": [],
                 "spawned": [], "kill_args": [], "log_path": [], "where": []}
```

```python
        def fake_wait(host, port, proc, **kw):
            calls["wait_port"].append(port)
            calls["where"].append(kw.get("where"))
            return wait if wait is not None else (True, f"http://{host}:{port}")

        def fake_spawn(argv, log_path=None):
            calls["spawned"].append(argv)
            calls["log_path"].append(log_path)
            return FakeProc() if spawn is self.KEEP else spawn
```

and in the `with` statement, add this line after the `server.wait_ready` patch:

```python
             mock.patch.object(main, "launch_log_path", lambda name, port: log), \
```

Add these two classes at the end of the file, above the `if __name__` line:

```python
class TestLaunchLogPath(unittest.TestCase):
    def test_windows_gets_a_console_window_and_no_log(self):
        self.assertIsNone(main.launch_log_path("c", 8080, platform="win32"))

    def test_linux_and_macos_get_a_log_in_the_per_user_log_folder(self):
        for platform in ("linux", "darwin"):
            with self.subTest(platform=platform):
                self.assertEqual(
                    main.launch_log_path("c", 8080, platform=platform),
                    os.path.join(main.LOG_DIR, "c-8080.log"))

    def test_the_log_folder_is_the_per_user_one(self):
        self.assertEqual(
            main.LOG_DIR,
            platformdirs.user_log_dir("llama-launcher", appauthor=False))


class TestLaunchWithALog(LaunchFixture):
    LOG = os.path.join("logs", "c-8080.log")

    def test_the_log_path_is_handed_to_spawn_and_shown(self):
        result, text, calls = self.launch(self.values(), log=self.LOG)
        self.assertIs(result, True)
        self.assertEqual(calls["log_path"], [self.LOG])
        self.assertIn(f"log: {self.LOG}", text,
                      "the user must be told where the output went")

    def test_without_a_log_none_is_mentioned(self):
        _, text, calls = self.launch(self.values())
        self.assertEqual(calls["log_path"], [None])
        self.assertNotIn("log:", text)

    def test_a_failed_start_names_the_log_it_could_not_open(self):
        result, text, calls = self.launch(self.values(), spawn=None,
                                          log=self.LOG)
        self.assertIs(result, False)
        self.assertIn("could not be started", text)
        self.assertIn(f"could not be opened for writing: {self.LOG}", text)
        self.assertEqual(calls["wait_port"], [])

    def test_wait_ready_is_told_to_point_at_the_log(self):
        _, _, calls = self.launch(self.values(), log=self.LOG)
        self.assertEqual(calls["where"], [f"see {self.LOG}"])

    def test_wait_ready_is_told_to_point_at_the_console_window_without_one(self):
        _, _, calls = self.launch(self.values())
        self.assertEqual(calls["where"], ["check its console window"])
```

- [ ] **Step 3: Add live tests that start a real child through `spawn`**

The unit tests above inject `popen`. These leave it alone, once, so the real `Popen` is shown to accept these arguments and to do what they ask.

In `tests/test_server_live.py`, add `import os` and `import tempfile` to the imports, and add this class above the `if __name__` line:

```python
class TestSpawningForReal(unittest.TestCase):
    """spawn() with popen left alone: a real child and a real file."""

    def setUp(self):
        self.log = os.path.join(tempfile.mkdtemp(), "logs", "c-1.log")

    def test_the_childs_output_lands_in_the_log(self):
        proc = server.spawn([sys.executable, "-c",
                             "print('started', flush=True)"],
                            log_path=self.log)
        self.assertIsNotNone(proc)
        proc.wait(timeout=30)
        with open(self.log, encoding="utf-8") as f:
            self.assertIn("started", f.read())

    @unittest.skipIf(os.name == "nt", "sessions are a POSIX concept")
    def test_the_child_runs_in_a_session_of_its_own(self):
        """What actually keeps Ctrl-C at the board from reaching the server."""
        proc = server.spawn([sys.executable, "-c", "import time; time.sleep(30)"],
                            log_path=self.log)
        self.addCleanup(proc.wait, 10)
        self.addCleanup(proc.kill)
        self.assertNotEqual(os.getsid(proc.pid), os.getsid(0))
```

- [ ] **Step 4: Run the tests to verify they fail**

```bash
uv run python -B -m unittest tests.test_server tests.test_main tests.test_server_live 2>&1 | tail -n 6
```

Expected: errors, among them `AttributeError: module 'llama_launcher.server' has no attribute 'log_path_for'`, `TypeError: spawn() got an unexpected keyword argument 'log_path'` and `AttributeError: ... does not have the attribute 'launch_log_path'`.

- [ ] **Step 5: Implement in `llama_launcher/server.py`**

Add `import os` and `import re` to the imports (alphabetical order: `collections`, `os`, `re`, `socket`, `subprocess`, `sys`, `time`).

In `wait_ready`, add `where="check its console window"` as the last parameter, add this sentence to the end of its docstring —

```
    `where` finishes the "it died" message with the place its output went: its
    console window, or the log file it was started with.
```

— and replace the two failure messages:

```python
        return False, ("llama-server did not start - check that the "
                       "llama-server path is still correct")
```

```python
            return False, (f"llama-server exited with code {proc.returncode} "
                           f"before the port opened - {where}")
```

Replace `spawn` with these two functions:

```python
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
```

- [ ] **Step 6: Implement in `llama_launcher/__main__.py`**

Add after the `LEGACY_PATH` line:

```python
# Where a launched server's output goes on Linux and macOS. Windows gives each
# server a console window of its own instead.
LOG_DIR = platformdirs.user_log_dir(APP, appauthor=False)
```

Add this function immediately above `def launch(`:

```python
def launch_log_path(cfg_name, port, platform=None):
    """Where this launch's output goes, or None if the server gets a console
    window of its own.

    Windows has a second console to open and Linux and macOS do not, so there
    the output goes to a file instead - one per config and port, overwritten
    at each launch. `platform` is injectable so both answers are testable on
    either kind of machine."""
    if (platform or sys.platform) == "win32":
        return None
    return server.log_path_for(cfg_name, port, LOG_DIR)
```

In `launch`, replace everything from `print(f"\n  starting {cfg['name']} ...")` through the `ok, msg = server.wait_ready(...)` statement with:

```python
    log_path = launch_log_path(cfg["name"], port)
    print(f"\n  starting {cfg['name']} ...")
    if log_path:
        print(f"  log: {log_path}")
    proc = server.spawn(argv, log_path=log_path)
    if proc is None:
        # spawn() reports a start it could not make by returning None instead of
        # raising - the exe having been moved, renamed or deleted mid-session is
        # an ordinary outcome, and it used to arrive here as an OSError
        # traceback. Said here rather than left to wait_ready, because there is
        # no readiness to wait for and the path that is wrong is worth naming.
        print(f"\n  FAILED: llama-server could not be started from "
              f"{data['llama_server']}\n  Check that path - the file may have "
              f"been moved or renamed.")
        if log_path:
            print(f"  Or its log could not be opened for writing: {log_path}")
        print()
        return False
    where = f"see {log_path}" if log_path else "check its console window"
    ok, msg = server.wait_ready(host, port, proc, where=where,
                                tick=lambda: print(".", end="", flush=True))
```

The two lines after it (`print()` and the `-> {msg}` / `FAILED:` line) and `return ok` stay as they are.

- [ ] **Step 7: Run the tests on Windows and under WSL**

```bash
uv run python -B -m unittest tests.test_server tests.test_main tests.test_server_live 2>&1 | tail -n 4
uv run python -B -m unittest discover -s tests -t . 2>&1 | grep -E "^Ran |^OK|^FAILED"
```

Expected: `OK`; then `Ran 462 tests` and `OK (skipped=2)` — 437 + 15 in `test_server.py` + 8 in `test_main.py` + 2 live. The second skip is the POSIX session test.

Then the WSL command. Expected: `Ran 462 tests`, `FAILED (failures=3, skipped=4)`, the same three `TestPaths` failures and no others. `TestSpawningForReal.test_the_child_runs_in_a_session_of_its_own` runs and passes there.

- [ ] **Step 8: Commit**

```bash
git add llama_launcher/server.py llama_launcher/__main__.py tests/test_server.py tests/test_main.py tests/test_server_live.py
git diff --staged --stat
git commit -m "feat(server): start detached with a log file on Linux and macOS" -m "There is no second console to open there, and a child sharing the
launcher's terminal would write over the board and die with it.
Windows keeps its console window. Failure messages point at whichever
of the two applies."
```

- [ ] **Step 9: Mutation check**

| File | Mutation | Test that must fail |
|---|---|---|
| `server.py` | In `spawn`, delete `, start_new_session=True` | `TestSpawnToALogFile.test_the_server_is_detached_from_the_launchers_terminal` (and, under WSL, `TestSpawningForReal.test_the_child_runs_in_a_session_of_its_own`) |
| `server.py` | In `spawn`, change `"wb"` to `"ab"` | `TestSpawnToALogFile.test_each_launch_starts_the_log_afresh` |
| `server.py` | In `log_path_for`, change the pattern to `r"[^A-Za-z0-9._/\\-]"` | `TestLogPathFor.test_a_name_cannot_climb_out_of_the_log_folder` |
| `__main__.py` | In `launch`, change `server.spawn(argv, log_path=log_path)` to `server.spawn(argv)` | `TestLaunchWithALog.test_the_log_path_is_handed_to_spawn_and_shown` |
| `__main__.py` | In `launch_log_path`, change `== "win32"` to `!= "win32"` | `TestLaunchLogPath.test_windows_gets_a_console_window_and_no_log` |

```bash
uv run python -B -m unittest tests.test_server tests.test_main 2>&1 | tail -n 14
```

Finish with `git status --short` showing only `?? docs/tui-plan.md`.

---

### Task 6: `[c]` and the extra-args row follow the host shell; path tests run everywhere

**Files:**
- Modify: `llama_launcher/catalog.py` — imports; rename `split_extra` to `split_extra_windows`; add `split_extra_posix`, `split_extra`
- Modify: `llama_launcher/board.py` — imports; add `as_command`
- Modify: `llama_launcher/__main__.py` — one call in `run_board`
- Modify: `tests/test_catalog.py`, `tests/test_board.py`, `tests/test_main.py`, `tests/test_config.py`

**Interfaces:**
- Consumes: nothing from earlier tasks beyond the package.
- Produces, in `llama_launcher.catalog`:
  - `split_extra_windows(text) -> (True, list[str]) | (False, str)` — the existing function under its accurate name
  - `split_extra_posix(text) -> (True, list[str]) | (False, str)`
  - `split_extra(text, windows=None) -> (True, list[str]) | (False, str)` — dispatches; `windows=None` means `os.name == "nt"`
- Produces, in `llama_launcher.board`:
  - `as_command(argv, windows=None) -> str`
- Unchanged: `board.as_powershell` and every test of it.

- [ ] **Step 1: Write the failing tests in `tests/test_catalog.py`**

The file's imports are `import unittest` and `from llama_launcher import catalog`. Add `import os` as the first line.

In `test_extra_args_keep_windows_backslashes` and `test_extra_args_split_unquoted_input_on_spaces_only`, change `catalog.split_extra(` to `catalog.split_extra_windows(`. Those two assert Windows rules, so they name the Windows function and pass on every OS. Leave `test_extra_args_report_an_unbalanced_quote` alone: an unbalanced quote is an error under both sets of rules.

Add at the end of the file, above the `if __name__` line:

```python
class TestSplitExtraPosix(unittest.TestCase):
    """The extra-args row on Linux and macOS, read the way a shell reads it."""

    def test_double_quotes_group_a_path_with_spaces(self):
        self.assertEqual(
            catalog.split_extra_posix('--lora "/models/my adapters/x.gguf"'),
            (True, ["--lora", "/models/my adapters/x.gguf"]))

    def test_single_quotes_group_too(self):
        self.assertEqual(catalog.split_extra_posix("--alias 'my model'"),
                         (True, ["--alias", "my model"]))

    def test_a_backslash_escapes_a_space(self):
        self.assertEqual(
            catalog.split_extra_posix("--lora /models/my\\ adapters/x.gguf"),
            (True, ["--lora", "/models/my adapters/x.gguf"]))

    def test_an_unbalanced_quote_is_reported_not_raised(self):
        ok, err = catalog.split_extra_posix('--api-key "sk-abc')
        self.assertFalse(ok)
        self.assertIn("unbalanced", err)

    def test_empty_text_is_no_arguments(self):
        self.assertEqual(catalog.split_extra_posix(""), (True, []))


class TestSplitExtraDispatch(unittest.TestCase):
    """One string, two readings: a backslash is an ordinary character on
    Windows and an escape everywhere else."""

    TEXT = "--lora D:\\x\\y.gguf"

    def test_windows_rules_keep_the_backslashes(self):
        self.assertEqual(catalog.split_extra(self.TEXT, windows=True),
                         (True, ["--lora", "D:\\x\\y.gguf"]))

    def test_posix_rules_treat_them_as_escapes(self):
        self.assertEqual(catalog.split_extra(self.TEXT, windows=False),
                         (True, ["--lora", "D:xy.gguf"]))

    def test_the_default_follows_the_machine(self):
        native = (catalog.split_extra_windows if os.name == "nt"
                  else catalog.split_extra_posix)
        self.assertEqual(catalog.split_extra(self.TEXT), native(self.TEXT))
```

- [ ] **Step 2: Write the failing tests in `tests/test_board.py` and `tests/test_main.py`**

In `tests/test_board.py`, add `import shlex` to the imports, and add this class immediately above the `@unittest.skipUnless(os.path.exists(LLAMA_SERVER) ...` decorator of `TestAgainstRealPowerShell`:

```python
class TestAsCommand(unittest.TestCase):
    """[c] prints a line for the shell this machine's user works in."""

    ARGV = ["/opt/llama/llama-server", "--model", "/models/my model.gguf",
            "--chat-template-kwargs", '{"a":"b c"}', "--alias", "it's $HOME|x"]

    def test_windows_gets_the_powershell_form(self):
        self.assertEqual(board.as_command(self.ARGV, windows=True),
                         board.as_powershell(self.ARGV))

    def test_elsewhere_a_posix_shell_reads_it_back_exactly(self):
        """The property that matters: what the shell would hand the binary is
        what the launch itself passes - spaces, quotes, $ and | included."""
        line = board.as_command(self.ARGV, windows=False)
        self.assertEqual(shlex.split(line), self.ARGV)

    def test_the_posix_form_is_not_the_powershell_form(self):
        line = board.as_command(self.ARGV, windows=False)
        self.assertFalse(line.startswith("& "))
        self.assertNotIn("--%", line)

    def test_a_non_string_in_argv_does_not_raise(self):
        """A hand-edited alias can be a number, and [c] is a display path."""
        line = board.as_command(["llama-server", "--alias", 5], windows=False)
        self.assertIn("5", line)

    def test_the_default_follows_the_machine(self):
        self.assertEqual(board.as_command(self.ARGV),
                         board.as_command(self.ARGV, windows=os.name == "nt"))
```

In `tests/test_main.py`, add this method to `class TestShowCommandIsValidated`:

```python
    def test_c_prints_whatever_as_command_makes_of_the_argv(self):
        """[c] goes through the per-machine dispatcher, not straight to the
        PowerShell renderer."""
        cfg = {"name": "c", "alias": "c", "model": "m.gguf", "settings": {}}
        with mock.patch.object(main.board, "as_command",
                               lambda argv: "FROM-AS-COMMAND"):
            text = self.board(cfg, ["c", "q"])
        self.assertIn("FROM-AS-COMMAND", text)
```

- [ ] **Step 3: Run the tests to verify they fail**

```bash
uv run python -B -m unittest tests.test_catalog tests.test_board tests.test_main 2>&1 | tail -n 6
```

Expected: errors, among them `AttributeError: module 'llama_launcher.catalog' has no attribute 'split_extra_windows'` and `AttributeError: module 'llama_launcher.board' has no attribute 'as_command'`.

- [ ] **Step 4: Implement in `llama_launcher/catalog.py`**

Add `import os` and `import shlex` to the imports (alphabetical: `copy`, `json`, `math`, `os`, `shlex`).

Rename the existing function: change the line `def split_extra(text):` to `def split_extra_windows(text):`. Its body and docstring stay exactly as they are. Immediately after it, add:

```python
def split_extra_posix(text):
    """Split the extra-args row by POSIX shell rules: a backslash escapes, and
    both ' and " group.

    The mirror image of split_extra_windows, and right for the same reason on
    the other side. This row exists for path-bearing flags, and on Linux and
    macOS a user writes those the way their shell reads them - `my\\ models`
    or 'my models'. Windows rules there would hand llama-server the backslash
    and the quote characters themselves.

    shlex raises on input it cannot finish. That is reported, not raised,
    because this text can come from a hand-edited config file.

    Returns (True, [args]) or (False, error)."""
    try:
        return True, shlex.split(text)
    except ValueError as exc:
        return False, f"unbalanced quote or trailing backslash - {exc}"


def split_extra(text, windows=None):
    """Split the extra-args row by the rules of the machine this runs on.

    A config's extra-args string carries machine paths and was never portable,
    so it is read the way that machine's shell would read it. `windows` is
    injectable so both sets of rules are testable on either kind of machine."""
    if windows is None:
        windows = os.name == "nt"
    return split_extra_windows(text) if windows else split_extra_posix(text)
```

The three existing callers — two in `catalog.py`, one in `board.py` — call `split_extra(text)` and need no change.

- [ ] **Step 5: Implement in `llama_launcher/board.py` and `llama_launcher/__main__.py`**

In `board.py`, add `import shlex` after `import os`, and add this function immediately after `as_powershell`:

```python
def as_command(argv, windows=None):
    """argv -> a command line for the shell this machine's user works in.

    PowerShell on Windows, where as_powershell does the real work. A POSIX
    shell everywhere else, where shlex.join is the whole job: one quoting
    scheme, and no second parser downstream to satisfy. str(), because a
    hand-edited alias can be a number and [c] is a display path - the board's
    rule is that a wrong-typed value still reaches the screen.

    `windows` is injectable so both forms are testable on either machine."""
    if windows is None:
        windows = os.name == "nt"
    if windows:
        return as_powershell(argv)
    return shlex.join(str(arg) for arg in argv)
```

In `__main__.py`, in `run_board`, change

```python
            print("\n" + board.as_powershell(argv) + "\n")
```

to

```python
            print("\n" + board.as_command(argv) + "\n")
```

- [ ] **Step 6: Run the tests, then commit the feature**

```bash
uv run python -B -m unittest tests.test_catalog tests.test_board tests.test_main 2>&1 | tail -n 4
```

Expected: `OK`.

```bash
git add llama_launcher/catalog.py llama_launcher/board.py llama_launcher/__main__.py tests/test_catalog.py tests/test_board.py tests/test_main.py
git diff --staged --stat
git commit -m "feat(board): quote [c] and split extra args by the host shell's rules" -m "Both assumed Windows: [c] printed PowerShell everywhere, and extra
args kept backslashes literal, which on Linux and macOS hands the
server the escape characters themselves. Windows behaviour is
unchanged."
```

- [ ] **Step 7: Make the three Windows path tests honest, and add their POSIX twins**

In `tests/test_config.py`, add this line immediately above `class TestPaths`:

```python
WINDOWS_PATHS = unittest.skipUnless(
    os.name == "nt",
    "drive letters, backslashes and case folding are Windows path rules")
```

Put `@WINDOWS_PATHS` on the line above each of these three methods of `TestPaths`: `test_canon_folds_separators_and_case`, `test_resolve_path_passes_absolute_through`, `test_relativise_strips_the_root`. The other two methods of that class pass on every OS and stay unguarded.

Add this class immediately after `TestPaths`:

```python
@unittest.skipIf(os.name == "nt", "POSIX path rules")
class TestPathsPosix(unittest.TestCase):
    """The same three properties as the guarded tests in TestPaths, with the
    paths a Linux or macOS config actually holds."""

    ROOT = "/srv/LLM Models"

    def test_canon_folds_separators_but_not_case(self):
        self.assertEqual(config.canon("/srv/LLM Models//a/./b.gguf"),
                         config.canon("/srv/LLM Models/a/b.gguf"))
        self.assertNotEqual(config.canon("/srv/LLM Models/A/b.gguf"),
                            config.canon("/srv/LLM Models/a/b.gguf"))

    def test_resolve_path_passes_absolute_through(self):
        p = "/elsewhere/x.gguf"
        self.assertEqual(config.resolve_path(p, self.ROOT), p)

    def test_relativise_strips_the_root(self):
        self.assertEqual(
            config.relativise("/srv/LLM Models/Qwen/x.gguf", self.ROOT),
            "Qwen/x.gguf")
```

- [ ] **Step 8: Run the whole suite on Windows and under WSL**

```bash
uv run python -B -m unittest discover -s tests -t . 2>&1 | grep -E "^Ran |^OK|^FAILED"
```

Expected: `Ran 479 tests` and `OK (skipped=5)` — 462 + 8 in `test_catalog.py` + 5 in `test_board.py` + 1 in `test_main.py` + 3 in `test_config.py`. The five skips are the three POSIX path twins, the POSIX session test and `test_the_match_is_exact_off_windows`.

Then the WSL command. Expected: `Ran 479 tests` and **`OK (skipped=7)`** — the first fully green run on Linux. The seven skips are the three Windows path tests, the Windows case-folding identity test, the drive-letter test in `test_setup.py`, and the two tests that need the real `powershell.exe`.

- [ ] **Step 9: Commit the test change**

```bash
git add tests/test_config.py
git diff --staged --stat
git commit -m "test(config): guard the Windows path tests and add POSIX twins" -m "Three tests asserted drive letters, backslashes and case folding
through os.path and so failed on Linux, where the code under test is
correct. Each now runs where its rules exist."
```

- [ ] **Step 10: Mutation check**

| File | Mutation | Test that must fail |
|---|---|---|
| `catalog.py` | In `split_extra`, change the `return` to `return split_extra_posix(text)` | `TestSplitExtraDispatch.test_windows_rules_keep_the_backslashes` |
| `catalog.py` | In `split_extra_posix`, change `shlex.split(text)` to `text.split()` | `TestSplitExtraPosix.test_double_quotes_group_a_path_with_spaces` |
| `board.py` | In `as_command`, change the last line to `return " ".join(str(arg) for arg in argv)` | `TestAsCommand.test_elsewhere_a_posix_shell_reads_it_back_exactly` |
| `__main__.py` | In `run_board`, change `board.as_command(argv)` back to `board.as_powershell(argv)` | `TestShowCommandIsValidated.test_c_prints_whatever_as_command_makes_of_the_argv` |

```bash
uv run python -B -m unittest tests.test_catalog tests.test_board tests.test_main 2>&1 | tail -n 12
```

Finish with `git status --short` showing only `?? docs/tui-plan.md`.

---

### Task 7: The bootstrap scripts

**Files:**
- Create: `.gitattributes`, `install.sh`, `install.ps1`

**Interfaces:**
- Consumes: the `llama-launcher` console script and `--version` from Tasks 1 and 2.
- Produces: two scripts with one shared contract —
  - environment variable `LLAMA_LAUNCHER_SOURCE`: a path or URL to install instead of the latest release (used by Task 8's CI job)
  - on success, the last lines printed include `installed: llama-launcher <version>`
  - with no published release and no override: a message containing `no published release` and a non-zero exit

There are no unit tests for shell scripts in this repository. The checks in this task are the scripts being run, on Windows and under WSL, in both the success and the refusal path. They install into scratch folders (`UV_TOOL_DIR`, `UV_TOOL_BIN_DIR`), so nothing is added to the owner's real tool directory.

- [ ] **Step 1: Pin `install.sh` to LF line endings**

This machine has `core.autocrlf=true`. A CRLF `install.sh` fails in `sh` with `$'\r': command not found`, and Step 6 runs the working-tree copy from WSL. Create `.gitattributes` **before** creating the script:

```
# A CRLF shell script does not run. Keep this one LF on every checkout.
install.sh text eol=lf
```

- [ ] **Step 2: Write `install.sh`**

```sh
#!/bin/sh
# llama-launcher installer for Linux and macOS.
#
#   curl -fsSL https://raw.githubusercontent.com/gabrieljakob/llama-server-launcher/main/install.sh | sh
#
# What it does, and nothing else:
#   1. installs uv with Astral's official installer, if uv is not on PATH
#   2. finds the latest llama-launcher release on GitHub
#   3. installs it with `uv tool install` (uv fetches a suitable Python itself)
#
# No sudo. Run it again to update. Remove with:  uv tool uninstall llama-launcher
# Your config file is not touched by installing, updating or removing.
#
# Set LLAMA_LAUNCHER_SOURCE to a path or URL to install that instead of the
# latest release - which is how this script is tested.
#
# Everything is inside one function that is called on the last line, so a
# download that is cut off part-way defines nothing and runs nothing.

main() {
    set -eu
    repo="gabrieljakob/llama-server-launcher"

    say() { printf '%s\n' "$*"; }
    fail() { printf 'install: %s\n' "$*" >&2; exit 1; }
    have() { command -v "$1" >/dev/null 2>&1; }

    # Every download refuses to follow a redirect to plain HTTP.
    fetch() {
        if have curl; then
            curl --proto '=https' --tlsv1.2 -fsSL "$1"
        elif have wget; then
            wget --https-only -qO- "$1"
        else
            fail "curl or wget is required"
        fi
    }

    # The tag of the latest release, or nothing. .../releases/latest redirects
    # to .../releases/tag/<tag>. With no release it redirects to .../releases,
    # and for a repository that cannot be seen it is a 404.
    latest_tag() {
        url="https://github.com/$repo/releases/latest"
        final=""
        if have curl; then
            final=$(curl --proto '=https' --tlsv1.2 -fsSLI -o /dev/null \
                         -w '%{url_effective}' "$url" 2>/dev/null) || final=""
        elif have wget; then
            final=$(wget --https-only --max-redirect=0 -S --spider "$url" 2>&1 \
                    | sed -n 's/^ *[Ll]ocation: *\([^ ]*\).*/\1/p' \
                    | tr -d '\r' | tail -n 1) || final=""
        fi
        case "$final" in
            */releases/tag/*) printf '%s' "${final##*/releases/tag/}" ;;
        esac
    }

    if ! have uv; then
        say "uv not found - installing it with Astral's installer"
        fetch https://astral.sh/uv/install.sh | sh
        PATH="${XDG_BIN_HOME:-$HOME/.local/bin}:$PATH"
        export PATH
        have uv || fail "uv was installed but is not on PATH yet; open a new terminal and run this again"
    fi

    src="${LLAMA_LAUNCHER_SOURCE:-}"
    if [ -n "$src" ]; then
        say "installing llama-launcher from $src"
    else
        tag=$(latest_tag)
        [ -n "$tag" ] || fail "no published release of $repo was found"
        src="llama-launcher @ https://github.com/$repo/archive/refs/tags/$tag.tar.gz"
        say "installing llama-launcher $tag"
    fi

    # --force so that running this again is how you update.
    uv tool install --force --python '>=3.12' "$src"

    bin=$(uv tool dir --bin)
    say ""
    say "installed: $("$bin/llama-launcher" --version)"
    if have llama-launcher; then
        say "run it with:  llama-launcher"
    else
        say "llama-launcher is not on PATH in this shell yet."
        say "run:  uv tool update-shell   then open a new terminal and run:  llama-launcher"
    fi
}

main
```

- [ ] **Step 3: Write `install.ps1`**

```powershell
# llama-launcher installer for Windows (Windows PowerShell 5.1 or newer).
#
#   irm https://raw.githubusercontent.com/gabrieljakob/llama-server-launcher/main/install.ps1 | iex
#
# What it does, and nothing else:
#   1. installs uv with Astral's official installer, if uv is not on PATH
#   2. finds the latest llama-launcher release on GitHub
#   3. installs it with `uv tool install` (uv fetches a suitable Python itself)
#
# No administrator rights. Run it again to update. Remove with:
#   uv tool uninstall llama-launcher
# Your config file is not touched by installing, updating or removing.
#
# Set $env:LLAMA_LAUNCHER_SOURCE to a path or URL to install that instead of
# the latest release - which is how this script is tested.
#
# Everything runs inside one script block. A download that is cut off part-way
# is a parse error that runs nothing, and no variable or preference set here
# outlives the script. The one thing that does persist, for this window only,
# is uv's folder on PATH - and only if uv had to be installed.

& {
    $ErrorActionPreference = 'Stop'
    $repo = 'gabrieljakob/llama-server-launcher'
    [Net.ServicePointManager]::SecurityProtocol =
        [Net.ServicePointManager]::SecurityProtocol -bor [Net.SecurityProtocolType]::Tls12

    # One request with redirects NOT followed, so every hop can be checked and
    # a redirect to plain HTTP is refused.
    function Open-Https([string]$url) {
        if (-not $url.StartsWith('https://')) { throw "refusing a non-HTTPS URL: $url" }
        $request = [Net.HttpWebRequest]::Create($url)
        $request.AllowAutoRedirect = $false
        $request.UserAgent = 'llama-launcher-install'
        return $request.GetResponse()
    }

    # Where $url redirects to, or '' if it does not redirect.
    function Get-RedirectTarget([string]$url) {
        $response = Open-Https $url
        try {
            $code = [int]$response.StatusCode
            if ($code -ge 300 -and $code -lt 400) { return [string]$response.Headers['Location'] }
            return ''
        } finally { $response.Close() }
    }

    # The body at $url, following redirects by hand.
    function Get-HttpsText([string]$url) {
        for ($hop = 0; $hop -lt 6; $hop++) {
            $response = Open-Https $url
            try {
                $code = [int]$response.StatusCode
                if ($code -ge 300 -and $code -lt 400) {
                    $url = [string]$response.Headers['Location']
                    continue
                }
                $reader = New-Object IO.StreamReader($response.GetResponseStream())
                return $reader.ReadToEnd()
            } finally { $response.Close() }
        }
        throw "too many redirects fetching $url"
    }

    if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
        Write-Host "uv not found - installing it with Astral's installer"
        # Run from a file in a child PowerShell: Astral's script ends in `exit`
        # on failure, and here that would close the window this is typed in.
        $installer = Join-Path ([IO.Path]::GetTempPath()) ('uv-install-' + [Guid]::NewGuid().ToString('N') + '.ps1')
        Set-Content -Path $installer -Value (Get-HttpsText 'https://astral.sh/uv/install.ps1') -Encoding UTF8
        try {
            & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $installer
            if ($LASTEXITCODE -ne 0) { throw "uv's installer failed (exit $LASTEXITCODE)" }
        } finally {
            Remove-Item -Path $installer -ErrorAction SilentlyContinue
        }
        $env:Path = "$HOME\.local\bin;$env:Path"
        if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
            throw 'uv was installed but is not on PATH yet; open a new terminal and run this again'
        }
    }

    $source = $env:LLAMA_LAUNCHER_SOURCE
    if ($source) {
        Write-Host "installing llama-launcher from $source"
    } else {
        # .../releases/latest redirects to .../releases/tag/<tag>. With no
        # release it redirects to .../releases, and a repository that cannot
        # be seen is a 404, which GetResponse raises.
        $location = ''
        try { $location = Get-RedirectTarget "https://github.com/$repo/releases/latest" } catch { $location = '' }
        if ($location -notmatch '/releases/tag/([^/?#]+)$') {
            throw "no published release of $repo was found"
        }
        $tag = $Matches[1]
        $source = "llama-launcher @ https://github.com/$repo/archive/refs/tags/$tag.zip"
        Write-Host "installing llama-launcher $tag"
    }

    # --force so that running this again is how you update.
    & uv tool install --force --python '>=3.12' $source
    if ($LASTEXITCODE -ne 0) { throw "uv tool install failed (exit $LASTEXITCODE)" }

    $bin = (& uv tool dir --bin | Select-Object -First 1)
    Write-Host ''
    Write-Host "installed: $(& (Join-Path $bin 'llama-launcher.exe') --version)"
    if (Get-Command llama-launcher -ErrorAction SilentlyContinue) {
        Write-Host 'run it with:  llama-launcher'
    } else {
        Write-Host 'llama-launcher is not on PATH in this window yet.'
        Write-Host 'run:  uv tool update-shell   then open a new terminal and run:  llama-launcher'
    }
}
```

- [ ] **Step 4: Check both scripts parse**

From the PowerShell tool:

```powershell
[void][ScriptBlock]::Create((Get-Content -Raw .\install.ps1)); 'install.ps1 parses'
wsl -d Ubuntu -- bash -lc "cd '/mnt/d/Projects/Model Launcher CLI Script' && sh -n install.sh && echo 'install.sh parses' && (od -c install.sh | grep -c '\\r' || true)"
```

Expected: `install.ps1 parses`; `install.sh parses`; then `0` — the number of lines of the dump that contain a carriage return. Anything but `0` means the file was written with CRLF: check `.gitattributes` exists and rewrite the script.

- [ ] **Step 5: Run `install.ps1` on Windows — the success path, then the refusal path**

Each block is one PowerShell tool call; environment variables set in a call do not outlive it.

```powershell
$check = Join-Path $env:TEMP 'llama-launcher-install-check'; $env:LLAMA_LAUNCHER_SOURCE = (Get-Location).Path; $env:UV_TOOL_DIR = "$check\tools"; $env:UV_TOOL_BIN_DIR = "$check\bin"; Get-Content -Raw .\install.ps1 | Invoke-Expression; & "$check\bin\llama-launcher.exe" --version; Remove-Item -Recurse -Force $check
```

Expected: `installing llama-launcher from D:\Projects\Model Launcher CLI Script`, uv's own output, `installed: llama-launcher 0.1.0`, the "not on PATH in this window yet" hint (the scratch bin folder is not on PATH), then `llama-launcher 0.1.0` once more from the direct call.

```powershell
Remove-Item Env:LLAMA_LAUNCHER_SOURCE -ErrorAction SilentlyContinue; Get-Content -Raw .\install.ps1 | Invoke-Expression
```

Expected: an error whose message is `no published release of gabrieljakob/llama-server-launcher was found`, and nothing installed. (The repository has no releases yet. This is the one path that exercises the real GitHub lookup before Task 10.)

- [ ] **Step 6: Run `install.sh` under WSL — the success path, then the refusal path**

```powershell
wsl -d Ubuntu -- bash -lc "cd '/mnt/d/Projects/Model Launcher CLI Script' && PATH=~/.local/bin:/usr/bin:/bin LLAMA_LAUNCHER_SOURCE=. UV_TOOL_DIR=/tmp/llama-launcher-install-check/tools UV_TOOL_BIN_DIR=/tmp/llama-launcher-install-check/bin sh install.sh && /tmp/llama-launcher-install-check/bin/llama-launcher --version; rm -rf /tmp/llama-launcher-install-check"
```

Expected: `installing llama-launcher from .`, uv's output, `installed: llama-launcher 0.1.0`, the PATH hint, then `llama-launcher 0.1.0`.

```powershell
wsl -d Ubuntu -- bash -lc "cd '/mnt/d/Projects/Model Launcher CLI Script' && PATH=~/.local/bin:/usr/bin:/bin sh install.sh || echo REFUSED"
```

Expected: `install: no published release of gabrieljakob/llama-server-launcher was found`, then `REFUSED`.

The "uv is missing, install it" branch is not exercised locally — both machines now have uv. Task 8's CI job runs each script on a clean runner, which is where that branch is proven.

- [ ] **Step 7: Commit**

```bash
git add .gitattributes install.sh install.ps1
git update-index --chmod=+x install.sh
git diff --staged --stat
git commit -m "feat(install): one-line bootstrap scripts for Windows, Linux and macOS" -m "Each installs uv if it is missing, then the latest tagged release as
a uv tool. No elevation, HTTPS only, and the body is one block so a
truncated download runs nothing. LLAMA_LAUNCHER_SOURCE overrides the
source for CI."
```

---

### Task 8: Continuous integration

**Files:**
- Create: `.github/workflows/ci.yml`

**Interfaces:**
- Consumes: `uv.lock` (Task 1), the test suite, `install.sh` and `install.ps1` with `LLAMA_LAUNCHER_SOURCE` (Task 7).
- Produces: a workflow named `CI` at `.github/workflows/ci.yml` — the file name Task 9's README badge points at.

Action versions were looked up on 2026-10-12: `actions/checkout` is at `v7.0.1` and `astral-sh/setup-uv` at `v10.3.0`. They are pinned to those exact tags.

- [ ] **Step 1: Write `.github/workflows/ci.yml`**

```yaml
name: CI

on:
  push:
  pull_request:

permissions:
  contents: read

jobs:
  test:
    name: tests (${{ matrix.os }}, Python ${{ matrix.python }})
    runs-on: ${{ matrix.os }}
    strategy:
      fail-fast: false
      matrix:
        os: [windows-latest, ubuntu-latest, macos-latest]
        python: ["3.12", "3.14"]
    env:
      # uv reads this itself, so the matrix does not depend on an action input.
      UV_PYTHON: ${{ matrix.python }}
    steps:
      - uses: actions/checkout@v7.0.1
      - uses: astral-sh/setup-uv@v10.3.0
      - name: Install
        run: uv sync --locked
      - name: Test
        run: uv run python -m unittest discover -s tests -t . -v

  install:
    # No uv is installed first: each script has to bring it, as it does for a
    # user who has nothing.
    name: install script (${{ matrix.os }})
    runs-on: ${{ matrix.os }}
    strategy:
      fail-fast: false
      matrix:
        os: [windows-latest, ubuntu-latest, macos-latest]
    env:
      LLAMA_LAUNCHER_SOURCE: ${{ github.workspace }}
    steps:
      - uses: actions/checkout@v7.0.1
      - name: install.sh
        if: runner.os != 'Windows'
        run: |
          sh install.sh
          expected="llama-launcher $(sed -n 's/^version = "\(.*\)"/\1/p' pyproject.toml)"
          actual="$("$HOME/.local/bin/llama-launcher" --version)"
          echo "expected: $expected"
          echo "actual:   $actual"
          test "$actual" = "$expected"
      - name: install.ps1
        if: runner.os == 'Windows'
        shell: powershell
        run: |
          Get-Content -Raw .\install.ps1 | Invoke-Expression
          $version = (Select-String -Path pyproject.toml -Pattern '^version = "(.*)"').Matches[0].Groups[1].Value
          $expected = "llama-launcher $version"
          $actual = & "$HOME\.local\bin\llama-launcher.exe" --version
          Write-Host "expected: $expected"
          Write-Host "actual:   $actual"
          if ($actual -ne $expected) { throw "version mismatch" }
```

`shell: powershell` is Windows PowerShell 5.1, not PowerShell 7 — the version the constraint is about. Piping the file into `Invoke-Expression` is exactly what the one-liner does.

- [ ] **Step 2: Check the file is well-formed YAML with the two jobs**

```bash
uv run --no-project --with pyyaml python -c "import yaml; d = yaml.safe_load(open('.github/workflows/ci.yml', encoding='utf-8')); print(sorted(d['jobs'])); print(d['jobs']['test']['strategy']['matrix'])"
```

Expected: `['install', 'test']` and `{'os': ['windows-latest', 'ubuntu-latest', 'macos-latest'], 'python': ['3.12', '3.14']}`.

This proves the syntax and nothing more. Whether the workflow passes is only known once the branch is pushed, which is the owner's action in Task 10.

- [ ] **Step 3: Commit**

```bash
git add .github/workflows/ci.yml
git diff --staged --stat
git commit -m "chore(ci): test on three operating systems and run both install scripts"
```

---

### Task 9: README

**Files:**
- Modify: `README.md`

**Interfaces:**
- Consumes: everything user-visible from Tasks 1–8 — the command name, the one-liners, the config folders, the log folders, the CI workflow file name.
- Produces: nothing other tasks depend on.

The README's first-person passages ("I wrote them under one rule…", "Five things I learned the hard way…") are the owner's voice. Keep them first-person; edit only what is listed.

- [ ] **Step 1: Badges and contents**

Replace the five badge lines (from `[![Python]` through `[![License]`) with:

```markdown
[![CI](https://github.com/gabrieljakob/llama-server-launcher/actions/workflows/ci.yml/badge.svg)](https://github.com/gabrieljakob/llama-server-launcher/actions/workflows/ci.yml)
[![Python](https://img.shields.io/badge/python-3.12%2B-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![Platform](https://img.shields.io/badge/platform-Windows%20%7C%20Linux%20%7C%20macOS-555)](#requirements)
[![License](https://img.shields.io/badge/license-MIT-blue)](#licence)
```

In the Contents list, replace the last line

```markdown
- [Porting](#porting) · [Windows and locale notes](#windows-and-locale-notes)
```

with

```markdown
- [Windows and locale notes](#windows-and-locale-notes)
```

- [ ] **Step 2: Highlights**

Replace these three rows of the Highlights table:

| Old row begins | New row |
|---|---|
| `\| **Zero install** \|` | `\| **One-line install** \| One command on Windows, Linux or macOS. It brings its own Python, so you need neither Python nor git first. \|` |
| `\| **Nothing hardcoded** \|` | `\| **Nothing hardcoded** \| Two paths, asked once on first run, kept in your per-user config folder and editable in JSON forever after. \|` |
| `\| **Safe port takeover** \|` | `\| **Safe port takeover** \| Offers to stop what owns the port *only* if it is your llama-server, and re-checks its name, its start time and the port at the moment it stops it. \|` |

(The backslashes before the pipes above are this plan's table escaping. In the README the rows use plain pipes.)

- [ ] **Step 3: Requirements and Quick start**

Replace everything from the `## Requirements` heading down to (not including) the `## The board` heading with:

````markdown
## Requirements

- Windows, Linux or macOS
- Any `llama-server` build and some `.gguf` files

The installer brings [uv](https://docs.astral.sh/uv/), and uv brings Python 3.12+ and the two
libraries the launcher uses, [psutil](https://github.com/giampaolo/psutil) and
[platformdirs](https://github.com/tox-dev/platformdirs). psutil ships prebuilt for x86-64 and
arm64 on all three systems; on anything else uv needs a C compiler to build it.

Works with whatever backend your llama.cpp was built against. The launcher asks the binary what
devices it has rather than assuming a vendor, so an AMD card with a Vulkan build reports Vulkan,
and a CPU-only build says so.

## Quick start

**Windows**, in PowerShell:

```powershell
irm https://raw.githubusercontent.com/gabrieljakob/llama-server-launcher/main/install.ps1 | iex
```

**Linux and macOS:**

```bash
curl -fsSL https://raw.githubusercontent.com/gabrieljakob/llama-server-launcher/main/install.sh | sh
```

Then:

```bash
llama-launcher
```

The installer needs no administrator rights. It installs uv if you do not have it, then installs
the latest release as a uv tool. Run the same line again to update, and
`uv tool uninstall llama-launcher` to remove it. Your config is not touched by any of the three.

<details>
<summary><b>Rather read the script before you run it?</b></summary>

<br>

Both are short. Download, read, then run:

```powershell
irm https://raw.githubusercontent.com/gabrieljakob/llama-server-launcher/main/install.ps1 -OutFile install.ps1
notepad install.ps1
powershell -ExecutionPolicy Bypass -File .\install.ps1
```

```bash
curl -fsSL https://raw.githubusercontent.com/gabrieljakob/llama-server-launcher/main/install.sh -o install.sh
less install.sh
sh install.sh
```

</details>

From a clone instead:

```bash
git clone https://github.com/gabrieljakob/llama-server-launcher.git
cd llama-server-launcher
uv run llama-launcher
```

On Windows you can also double-click `launch_model.bat` in the clone.

On first run it asks for two paths and stores them in your config file:

```
Setting up. Two paths are needed; both are stored in
C:\Users\you\AppData\Roaming\llama-launcher\launcher_configs.json
and can be edited there later.

  llama-server executable [C:\llama.cpp\llama-server.exe]:
  folder containing your .gguf models: D:\models
```

Both are pre-filled where possible — `llama-server` is looked up on `PATH` and in the usual build
locations, and if you have a legacy `model_profiles.json` the model folder is derived from the
paths already in it. Press <kbd>Enter</kbd> to accept a suggestion.

Then press <kbd>n</kbd> to build a config from any `.gguf` it finds.

````

- [ ] **Step 4: The board and Configuration**

In the key table under `## The board`, replace the `<kbd>c</kbd>` row with:

```markdown
| <kbd>c</kbd> | Print the equivalent command line, quoted for the shell you are in — PowerShell on Windows, a POSIX shell on Linux and macOS |
```

Under `## Configuration`, replace the line ``Everything lives in `launcher_configs.json`:`` with:

```markdown
Everything lives in one file, `launcher_configs.json`, in your per-user config folder:

| OS | Folder |
|---|---|
| Windows | `%APPDATA%\llama-launcher\` |
| Linux | `~/.config/llama-launcher/` (or `$XDG_CONFIG_HOME/llama-launcher/`) |
| macOS | `~/Library/Application Support/llama-launcher/` |

`llama-launcher --config PATH` uses a different file. If you ran the launcher from a clone before
0.1.0, the `launcher_configs.json` beside the code is copied to that folder the first time you
start it, and the original is left where it was.

It looks like this:
```

- [ ] **Step 5: Launching**

Replace the body of `## Launching` (both paragraphs) with:

```markdown
The launcher checks what owns the target port and offers to stop it **only if it is your
llama-server** — the process name has to equal the file name of the binary in your config, not
merely contain it. Before it stops anything it re-checks three things: the name, the port, and the
moment the process was started. A port snapshot can be minutes old by the time you answer, and
operating systems recycle PIDs; a different process that inherited the PID has a different start
time and is left alone. Servers on other ports are never touched, so `:8080` and `:8082` coexist.

Stopping asks first: the server gets five seconds to shut down before it is forced.

On Windows the server starts in its own console window. On Linux and macOS it starts detached,
with its output in a log file whose path is printed — under `~/.local/state/llama-launcher/log/`
on Linux and `~/Library/Logs/llama-launcher/` on macOS. There is one file per config and port,
overwritten at each launch.

After spawning, the launcher polls until the port actually accepts a connection, watching for the
child exiting, and reports one of three outcomes: the URL, the exit code, or a timeout.
```

- [ ] **Step 6: Tests and Layout**

Under `## Tests`, replace the code block's command with `uv run python -m unittest discover -s tests -t . -v`, and replace the line `**377 tests, standard library only.**` with:

```markdown
Every push runs them on Windows, Linux and macOS, on Python 3.12 and 3.14, together with both
install scripts. Most of the process layer is tested against a fake; `tests/test_server_live.py`
then starts a real process on each OS and finds it, refuses to stop it under the wrong identity,
and stops it under the right one.
```

Change the `<summary>` of the details block from `<b>Why the count is not the point</b>` to `<b>How these tests earned their place</b>`. Leave the first-person text inside it unchanged.

Replace the code block under `## Layout` with:

```
install.ps1     Windows bootstrap
install.sh      Linux and macOS bootstrap
llama_launcher/
  catalog.py    setting definitions, validation, argv emission, speculative gating
  config.py     load/save, four-layer resolution, migration, atomic writes
  server.py     port ownership, guarded stop, spawn, readiness polling
  board.py      config menu, settings board, row editors, shell quoting
  __main__.py   entry point; wiring only
tests/
docs/           design specs and implementation plans
```

- [ ] **Step 7: Porting, and the Windows notes**

Delete the whole `## Porting` section — its heading and all three paragraphs. What it described as future work is done.

Under `## Windows and locale notes`:

- Change the summary to `<b>Three things I learned the hard way on a non-English Windows</b>`.
- Delete the first two bullets (the one beginning `` `netstat` and `tasklist` print **localised** output`` and the one beginning `` `tasklist`'s "no such process" line``). The launcher no longer runs either tool.
- Replace the bullet beginning `The extra-args row splits by **Windows** rules` with:

```markdown
- On Windows the extra-args row splits by **Windows** rules, not POSIX — `shlex.split` treats
  backslash as an escape and quietly turns `D:\LLM Models\x.gguf` into two mangled fragments. On
  Linux and macOS it uses POSIX rules, because there that is what you would type in a shell.
```

- Replace the bullet beginning `` `[c]` quotes for PowerShell`` with:

```markdown
- On Windows `[c]` quotes for PowerShell, which needs different escaping from `cmd.exe` for the
  same argument. Launching is unaffected either way: arguments are passed as a list and never
  built into a command string.
```

- [ ] **Step 8: Check nothing stale is left, then commit**

```bash
grep -nE "python -m launcher|python -m llama_launcher|netstat|tasklist|taskkill|377|Zero install|dependencies-none|#porting|Windows-only" README.md
```

Expected: no output.

```bash
git add README.md
git diff --staged --stat
git commit -m "docs: README for the cross-platform, installable launcher"
```

---

### Task 10: Final verification and handoff

**Files:** none modified.

**Interfaces:**
- Consumes: the finished branch.
- Produces: a branch that is ready for the owner to push, and a list of what only the owner does.

- [ ] **Step 1: The whole suite, both machines, from a clean tree**

```bash
git status --short
uv sync --locked
uv run python -B -m unittest discover -s tests -t . 2>&1 | grep -E "^Ran |^OK|^FAILED"
```

Expected: only `?? docs/tui-plan.md`; then `Ran 479 tests` and `OK (skipped=5)`.

Then the WSL command. Expected: `Ran 479 tests` and `OK (skipped=7)`.

- [ ] **Step 2: Check the spec's file layout against the tree**

```bash
git diff --stat main..universal -- . ":(exclude)docs" ":(exclude)uv.lock"
git diff --stat main..universal -- llama_launcher/config.py
```

Expected from the first: the files in "File structure" above and no others. Expected from the second: only the rename line for `config.py`, with no content change — the spec says `config.py` is untouched.

- [ ] **Step 3: Manual pass against the real `llama-server.exe` — the owner's, before merging**

§12 of the spec requires this before merging, and it cannot be automated: it starts a real server on the owner's GPU and reads their real config. **Neither an implementer nor the orchestrator runs it.** It goes into the pull request description as a pre-merge checklist. The first start also performs the one-time adoption: it copies `launcher_configs.json` from the repository root into `%APPDATA%\llama-launcher\`.

The owner runs `uv run llama-launcher` in a terminal and checks, in order:

| # | Do | Expect |
|---|---|---|
| 1 | Start it | `copied your existing config to C:\Users\Gabe\AppData\Roaming\llama-launcher\launcher_configs.json`, then the usual config menu with every config present |
| 2 | Open a small config, press <kbd>Enter</kbd> | A new console window, dots, then `-> http://127.0.0.1:<port>  (pid N)` |
| 3 | Start the launcher again, open the **same** config, press <kbd>Enter</kbd> | `port <port> is held by llama-server (pid N). Stop it? [Y/n]` |
| 4 | Answer `y` | `stopped pid N`, the first console window closes, and the server starts again |
| 5 | Stop that server by closing its window. In another terminal run `python -m http.server 8080 --bind 127.0.0.1`. Launch a config on port 8080 | `port 8080 is held by python.exe (pid N), not a llama-server. Change the port on row 3.` — and **no** offer to stop it |
| 6 | Press <kbd>c</kbd> on any board | A line beginning `& ` that pastes into PowerShell and runs |
| 7 | Quit, start again | No "copied your existing config" line the second time |

Any deviation is a defect: fix it in the task that owns the code, with a test, before going on.

- [ ] **Step 4: Report what was and was not verified**

Report: the suite on Windows and on Linux under WSL; both install scripts with a local source, and their refusal path against GitHub. **Not** verified locally: anything on macOS, the "uv is missing" branch of either script, the installed-from-a-release path, and the manual pass of Step 3.

- [ ] **Step 5: Push and open the pull request — the orchestrator's, not an implementer's**

```bash
git push -u origin universal
```

Then open a pull request from `universal` into `main` with `gh pr create`. Its body states what changed, what was verified and where, what was not, and carries Step 3's table as a pre-merge checklist for the owner. No trailers, no "generated with" line.

CI then runs the suite on three operating systems and both install scripts on clean runners. This is the first evidence about macOS, including the per-process socket lookup of §5.2 — `tests/test_server_live.py` is what proves it. A CI failure is a defect: it goes back through the fix loop, with a test where one is possible, and is pushed to the same branch.

- [ ] **Step 6: What remains the owner's**

1. **The manual pass** of Step 3.
2. **Merge to `main`** once CI is green on all nine jobs (six test, three install).
3. **Publish the release:** `gh release create v0.1.0 --title "v0.1.0" --generate-notes`. This is what makes the one-liners in the README work for the public.
4. **The hand check from §9 of the spec:** run the real one-liner once in a fresh PowerShell window and once in WSL, and confirm each ends with `installed: llama-launcher 0.1.0`.

## Deliberate deviations from the spec

Each is small; each is listed so a reviewer does not have to find it.

| Spec | Plan | Why |
|---|---|---|
| §4: the config folder is "created on first save" | Created at startup, in `main()` | `config.py` may not change, and an existing test depends on a save into a missing folder failing |
| §5.1 lists `_force_kill`'s `taskkill` call as deleted | The function is replaced by `_stop` | It no longer forces first, so the old name would mislead; `kill()` keeps its `force=` parameter |
| §5.1 says `OEM` is deleted outright | `device_line` in `__main__.py` used it too; it now decodes UTF-8 | That is what llama-server writes; the OEM codepage belonged to the console tools |
| §6: `split_extra` "dispatches on `os.name`" | `split_extra(text, windows=None)` and `as_command(argv, windows=None)` | Same default, but both branches are testable on either machine without patching `os.name` |
| §3: hatchling needs "no include configuration" | `packages = ["llama_launcher"]` is stated explicitly | Makes it impossible for `tests/` to reach the wheel |
| §7 step 1: install uv "with Astral's official installer" | On Windows it is saved to a temp file and run in a child PowerShell | Astral's script calls `exit` on failure, which under `irm \| iex` would close the user's window |
| §8 lists the live tests | Two more are added: a real child's output reaches the log, and it runs in its own session | The unit tests inject `Popen`; these show the real one accepts the arguments |
