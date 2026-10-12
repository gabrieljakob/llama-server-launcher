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
