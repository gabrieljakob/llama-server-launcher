"""Entry-point behaviour that only shows up with a hand-edited config file.

Nothing here starts a process, opens a socket or touches the real
launcher_configs.json: CONFIG_PATH and LEGACY_PATH are redirected into a
temporary folder, and every `server` call is patched with a recorder that
fails loudly if it is reached when it should not be.
"""
import contextlib
import io
import json
import os
import tempfile
import unittest
from unittest import mock

import platformdirs

from llama_launcher import __main__ as main
from llama_launcher import catalog, config, server


class FakeProc:
    pid = 4242

    def poll(self):
        return None


class TestDocumentShapeIsCheckedBeforeUse(unittest.TestCase):
    """A config document that is valid JSON but missing a key used to come out
    as a bare KeyError from whichever line read it first. The message must name
    the file and the key, and the exit code must be non-zero."""

    def no_ask(self, prompt=""):
        raise AssertionError("the menu must not be reached with a broken config")

    def run_main(self, document, real_exe=True):
        folder = tempfile.mkdtemp()
        exe = os.path.join(folder, "llama-server.exe")
        if real_exe:
            with open(exe, "w", encoding="utf-8") as f:
                f.write("")
            if isinstance(document, dict) and "llama_server" in document:
                document["llama_server"] = exe
        path = os.path.join(folder, "launcher_configs.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(document, f)
        out = io.StringIO()
        with mock.patch.object(main, "CONFIG_PATH", path), \
             mock.patch.object(main, "LEGACY_PATH",
                               os.path.join(folder, "no-legacy.json")), \
             mock.patch.object(main, "ask", self.no_ask), \
             contextlib.redirect_stdout(out):
            code = main._main()
        return code, out.getvalue(), path

    def document(self, **over):
        doc = {"version": 2, "model_root": "D:/LLM Models",
               "llama_server": "PLACEHOLDER", "defaults": {},
               "configs": [{"name": "c", "model": "m.gguf", "settings": {}}]}
        doc.update(over)
        return doc

    def assertReported(self, document, needle):
        code, text, path = self.run_main(document)
        self.assertEqual(code, 1, f"must exit non-zero; said {text!r}")
        self.assertIn(needle, text, f"the message must name {needle}")
        self.assertIn(path, text, "the message must name the file")

    def test_a_document_without_configs_is_reported(self):
        doc = self.document()
        del doc["configs"]
        self.assertReported(doc, "configs")

    def test_a_document_without_model_root_is_reported(self):
        doc = self.document()
        del doc["model_root"]
        self.assertReported(doc, "model_root")

    def test_a_document_without_llama_server_is_reported(self):
        doc = self.document()
        del doc["llama_server"]
        code, text, path = self.run_main(doc, real_exe=False)
        self.assertEqual(code, 1)
        self.assertIn("llama_server", text)
        self.assertIn(path, text)

    def test_a_config_without_a_name_is_reported(self):
        self.assertReported(self.document(configs=[{"model": "m.gguf"}]), "name")

    def test_a_config_without_a_model_is_reported(self):
        self.assertReported(self.document(configs=[{"name": "c"}]), "model")

    def test_configs_that_is_not_a_list_is_reported(self):
        self.assertReported(self.document(configs={"name": "c"}), "configs")

    def test_a_config_that_is_not_an_object_is_reported(self):
        self.assertReported(self.document(configs=["just a string"]), "config 1")

    def test_a_whole_document_that_is_not_an_object_is_reported(self):
        code, text, path = self.run_main(["not", "a", "document"], real_exe=False)
        self.assertEqual(code, 1)
        self.assertIn(path, text)

    def test_a_valid_document_passes_the_shape_check(self):
        """Without this, 'always report an error' would satisfy every test
        above while making the launcher unable to start at all. The menu is
        reached, which is what no_ask raises to prove."""
        with self.assertRaises(AssertionError) as ctx:
            self.run_main(self.document())
        self.assertIn("menu must not be reached", str(ctx.exception))


class TestBoardKeepsRunningWhenSaveFails(unittest.TestCase):
    def board(self, data, cfg, answers):
        out = io.StringIO()
        answers = iter(answers)
        with mock.patch.object(main, "device_line", lambda exe: ""), \
             mock.patch.object(main, "ask", lambda prompt="": next(answers)), \
             contextlib.redirect_stdout(out):
            main.run_board(data, cfg)
        return out.getvalue()

    def test_a_failing_save_is_reported_instead_of_ending_the_session(self):
        """[s] exists to protect the user's edits. A traceback out of it
        destroys them, which is the opposite of what they pressed it for."""
        folder = tempfile.mkdtemp()
        path = os.path.join(folder, "cfg.json")
        data = {"version": 2, "model_root": folder, "llama_server": "x.exe",
                "defaults": {}, "configs": [],
                "junk": object()}          # json.dump cannot serialise this
        cfg = {"name": "c", "alias": "c", "model": "m.gguf", "settings": {}}
        with mock.patch.object(main, "CONFIG_PATH", path):
            text = self.board(data, cfg, ["s", "q"])
        self.assertIn("could not write", text)
        self.assertNotIn("saved to", text)
        self.assertEqual(os.listdir(folder), [],
                         "a failed save must leave no scratch file behind")

    def test_a_working_save_still_says_so(self):
        """Otherwise 'always report a failure' would pass the test above."""
        folder = tempfile.mkdtemp()
        path = os.path.join(folder, "cfg.json")
        data = {"version": 2, "model_root": folder, "llama_server": "x.exe",
                "defaults": {}, "configs": []}
        cfg = {"name": "c", "alias": "c", "model": "m.gguf", "settings": {}}
        with mock.patch.object(main, "CONFIG_PATH", path):
            text = self.board(data, cfg, ["s", "q"])
        self.assertIn("saved to", text)
        self.assertNotIn("could not write", text)

    def test_a_working_save_names_the_full_path(self):
        """The config no longer sits beside the code, so the bare file name
        tells nobody where to look."""
        folder = tempfile.mkdtemp()
        path = os.path.join(folder, "cfg.json")
        data = {"version": 2, "model_root": folder, "llama_server": "x.exe",
                "defaults": {}, "configs": []}
        cfg = {"name": "c", "alias": "c", "model": "m.gguf", "settings": {}}
        with mock.patch.object(main, "CONFIG_PATH", path):
            text = self.board(data, cfg, ["s", "q"])
        self.assertIn(f"saved to {path}", text)

    def test_a_save_that_fails_with_something_other_than_configerror_is_reported(self):
        """config.save promises one exception type for the write, but its own
        cleanup of the scratch file is unguarded - a scratch file that cannot be
        deleted replaces the ConfigError with a raw OSError. Anything out of
        save() has to reach the user as a message, not as a traceback that ends
        the session and takes the unsaved edits with it."""
        folder = tempfile.mkdtemp()

        def boom(path, data):
            raise OSError(13, "Permission denied")

        data = {"version": 2, "model_root": folder, "llama_server": "x.exe",
                "defaults": {}, "configs": []}
        cfg = {"name": "c", "alias": "c", "model": "m.gguf", "settings": {}}
        with mock.patch.object(main, "CONFIG_PATH",
                               os.path.join(folder, "cfg.json")), \
             mock.patch.object(config, "save", boom):
            text = self.board(data, cfg, ["s", "q"])
        self.assertIn("could not write", text)
        self.assertIn("Permission denied", text)
        self.assertNotIn("saved to", text)


class TestAFailedSaveLeavesTheDocumentUntouched(unittest.TestCase):
    """[s] appends a new config to the document and then writes it. When the
    write fails the append is still there, so an unrelated LATER save persists a
    config the user abandoned - verbatim the failure the comment beside that
    append says it fixed."""

    def board(self, data, cfg, answers):
        out = io.StringIO()
        answers = iter(answers)
        with mock.patch.object(main, "device_line", lambda exe: ""), \
             mock.patch.object(main, "ask", lambda prompt="": next(answers)), \
             contextlib.redirect_stdout(out):
            main.run_board(data, cfg)
        return out.getvalue()

    def setUp(self):
        self.folder = tempfile.mkdtemp()
        self.path = os.path.join(self.folder, "cfg.json")
        self.data = {"version": 2, "model_root": self.folder,
                     "llama_server": "x.exe", "defaults": {}, "configs": [],
                     "junk": object()}      # json.dump cannot serialise this

    def test_a_new_config_is_not_left_in_the_document(self):
        cfg = {"name": "abandoned", "alias": "a", "model": "m.gguf",
               "settings": {}}
        with mock.patch.object(main, "CONFIG_PATH", self.path):
            text = self.board(self.data, cfg, ["s", "q"])
        self.assertIn("could not write", text)
        self.assertEqual(self.data["configs"], [],
                         "the failed save must not leave the config behind")

    def test_a_later_save_of_another_config_does_not_persist_it(self):
        """The whole failure, end to end: the abandoned config must not appear
        in the file a different config's save writes."""
        abandoned = {"name": "abandoned", "alias": "a", "model": "m.gguf",
                     "settings": {}}
        keeper = {"name": "keeper", "alias": "k", "model": "k.gguf",
                  "settings": {}}
        with mock.patch.object(main, "CONFIG_PATH", self.path):
            self.board(self.data, abandoned, ["s", "q"])
            del self.data["junk"]            # the write can succeed now
            self.board(self.data, keeper, ["s", "q"])
        with open(self.path, encoding="utf-8") as f:
            written = json.load(f)
        self.assertEqual([c["name"] for c in written["configs"]], ["keeper"])

    def test_an_existing_config_keeps_the_settings_that_are_on_disk(self):
        """Same bug through the other door: the edits are written into the
        config object before the save, so a config already in the document
        carries them until something else saves successfully."""
        cfg = {"name": "c", "alias": "c", "model": "m.gguf",
               "settings": {"context": 4096}}
        self.data["configs"].append(cfg)
        with mock.patch.object(main, "CONFIG_PATH", self.path):
            self.board(self.data, cfg, ["1", "32768", "s", "q"])
        self.assertEqual(cfg["settings"], {"context": 4096},
                         "a failed save must not change what is saved")

    def test_a_working_save_still_adds_the_config_and_its_edits(self):
        """Otherwise 'never keep anything' would pass every test above and no
        config could ever be created."""
        del self.data["junk"]
        cfg = {"name": "new", "alias": "n", "model": "m.gguf", "settings": {}}
        with mock.patch.object(main, "CONFIG_PATH", self.path):
            text = self.board(self.data, cfg, ["1", "32768", "s", "q"])
        self.assertIn("saved to", text)
        self.assertEqual([c["name"] for c in self.data["configs"]], ["new"])
        with open(self.path, encoding="utf-8") as f:
            self.assertEqual(json.load(f)["configs"][0]["settings"],
                             {"context": 32768})


class TestSaveKeepsSettingsThisLauncherDoesNotKnow(unittest.TestCase):
    """A key the catalog has no entry for is one the user typed into the file
    themselves. [s] wrote back only catalog keys, so the next save deleted it
    without a word."""

    def board(self, data, cfg, answers, path):
        out = io.StringIO()
        answers = iter(answers)
        with mock.patch.object(main, "CONFIG_PATH", path), \
             mock.patch.object(main, "device_line", lambda exe: ""), \
             mock.patch.object(main, "ask", lambda prompt="": next(answers)), \
             contextlib.redirect_stdout(out):
            main.run_board(data, cfg)
        return out.getvalue()

    def save(self, settings, answers=("s", "q")):
        folder = tempfile.mkdtemp()
        path = os.path.join(folder, "cfg.json")
        data = {"version": 2, "model_root": folder, "llama_server": "x.exe",
                "defaults": {}, "configs": []}
        cfg = {"name": "c", "alias": "c", "model": "m.gguf",
               "settings": dict(settings)}
        data["configs"].append(cfg)
        text = self.board(data, cfg, list(answers), path)
        with open(path, encoding="utf-8") as f:
            return json.load(f)["configs"][0]["settings"], text

    def test_an_unknown_key_survives_the_save(self):
        written, _ = self.save({"context": 4096, "my_own_flag": "keep me"})
        self.assertEqual(written.get("my_own_flag"), "keep me")

    def test_the_user_is_told_which_keys_were_kept(self):
        """Keeping them silently is its own surprise: nothing on the board shows
        them, so a user who is not told cannot know they are still in the file
        and cannot know they are not being passed to llama-server."""
        _, text = self.save({"my_own_flag": "keep me"})
        self.assertIn("my_own_flag", text)
        self.assertIn("NOT passed", text)

    def test_edits_still_win_over_what_was_in_the_file(self):
        written, _ = self.save({"context": 4096, "my_own_flag": 1},
                               answers=("1", "32768", "s", "q"))
        self.assertEqual(written["context"], 32768)
        self.assertEqual(written["my_own_flag"], 1)

    def test_a_config_of_only_known_keys_says_nothing_about_kept_keys(self):
        """Otherwise 'always print the notice' would pass the test above."""
        written, text = self.save({"context": 4096})
        self.assertEqual(written, {"context": 4096})
        self.assertNotIn("does not know", text)


class TestFirstRunMigration(unittest.TestCase):
    """Uses a legacy file this test writes itself. The real
    model_profiles.json is the user's only rollback and is never opened here."""

    def migrate(self, folder, config_path,
                legacy_contents={"defaults": {}, "models": []}):
        legacy = os.path.join(folder, "model_profiles.json")
        with open(legacy, "w", encoding="utf-8") as f:
            json.dump(legacy_contents, f)
        out = io.StringIO()
        with mock.patch.object(main, "CONFIG_PATH", config_path), \
             mock.patch.object(main, "LEGACY_PATH", legacy), \
             contextlib.redirect_stdout(out):
            ok = main.first_run_migration("D:/M", "D:/s.exe")
        return ok, out.getvalue(), legacy

    def test_a_failing_migration_save_is_reported_not_raised(self):
        """This is the very first thing the launcher does. A traceback here is
        a tool that cannot start and does not say why."""
        folder = tempfile.mkdtemp()
        target = os.path.join(folder, "no-such-folder", "launcher_configs.json")
        ok, text, legacy = self.migrate(folder, target)
        self.assertIs(ok, False)
        self.assertIn("could not write", text)
        self.assertTrue(os.path.exists(legacy),
                        "the rollback file must be left untouched")

    def test_a_working_migration_still_writes_and_returns_true(self):
        """Otherwise 'always fail' would pass the test above and no first run
        could ever succeed."""
        folder = tempfile.mkdtemp()
        target = os.path.join(folder, "launcher_configs.json")
        ok, text, _ = self.migrate(
            folder, target,
            {"defaults": {"ngl": 99},
             "models": [{"name": "q", "path": "D:/LLM Models/a/b.gguf"}]})
        self.assertIs(ok, True)
        self.assertNotIn("could not write", text)
        with open(target, encoding="utf-8") as f:
            self.assertEqual(json.load(f)["configs"][0]["name"], "q")


class TestShowCommandIsValidated(unittest.TestCase):
    """[c] is what the user presses to CHECK a command before running it.
    Printing one llama-server would reject, with no word that it is invalid,
    is worse than printing nothing."""

    def board(self, cfg, answers):
        data = {"version": 2, "model_root": "D:/LLM Models",
                "llama_server": "D:/llama.cpp/llama-server.exe",
                "defaults": {}, "configs": []}
        out = io.StringIO()
        answers = iter(answers)
        with mock.patch.object(main, "device_line", lambda exe: ""), \
             mock.patch.object(main, "ask", lambda prompt="": next(answers)), \
             contextlib.redirect_stdout(out):
            main.run_board(data, cfg)
        return out.getvalue()

    def test_c_refuses_to_print_a_command_that_would_be_rejected(self):
        cfg = {"name": "c", "alias": "c", "model": "m.gguf",
               "settings": {"spec_type": "draft-dflash"}}   # needs a draft model
        text = self.board(cfg, ["c", "q"])
        self.assertNotIn("--model", text, "no command line may be printed")
        self.assertIn("draft model", text, "and the reason must be given")

    def test_c_still_prints_a_valid_command(self):
        """Otherwise 'never print anything' would pass the test above."""
        cfg = {"name": "c", "alias": "c", "model": "m.gguf", "settings": {}}
        text = self.board(cfg, ["c", "q"])
        self.assertIn("--model", text)
        self.assertIn("--alias", text)

    def test_c_prints_whatever_as_command_makes_of_the_argv(self):
        """[c] goes through the per-machine dispatcher, not straight to the
        PowerShell renderer."""
        cfg = {"name": "c", "alias": "c", "model": "m.gguf", "settings": {}}
        with mock.patch.object(main.board, "as_command",
                               lambda argv: "FROM-AS-COMMAND"):
            text = self.board(cfg, ["c", "q"])
        self.assertIn("FROM-AS-COMMAND", text)


class LaunchFixture(unittest.TestCase):
    """launch() up to, but never through, the point where a process starts."""

    KEEP = object()          # "leave spawn alone", told apart from a None result

    def setUp(self):
        self.folder = tempfile.mkdtemp()
        self.model = os.path.join(self.folder, "m.gguf")
        with open(self.model, "w", encoding="utf-8") as f:
            f.write("")
        self.data = {"version": 2, "model_root": self.folder,
                     "llama_server": "D:/llama.cpp/llama-server.exe",
                     "defaults": {}, "configs": []}
        self.cfg = {"name": "c", "alias": "c", "model": "m.gguf", "settings": {}}

    def values(self, **over):
        v = catalog.catalog_defaults()
        v.update(over)
        return v

    def launch(self, values, owner=None, ask=None, wait=None, spawn=KEEP,
               kill=True, log=None, answers=()):
        """Returns (result, printed text, calls). Nothing real is started.
        `answers` lists the hosts on which a connect probe finds a listener."""
        calls = {"owner_port": [], "wait_port": [], "killed": [], "asked": [],
                 "spawned": [], "kill_args": [], "log_path": [], "where": [],
                 "probed": []}

        def fake_owner(port):
            calls["owner_port"].append(port)
            return owner

        def fake_ask(prompt=""):
            calls["asked"].append(prompt)
            if ask is None:
                raise AssertionError("must not have prompted the user")
            return ask

        def fake_kill(pid, **kw):
            calls["killed"].append(pid)
            calls["kill_args"].append(kw)
            return kill

        def fake_wait(host, port, proc, **kw):
            calls["wait_port"].append(port)
            calls["where"].append(kw.get("where"))
            return wait if wait is not None else (True, f"http://{host}:{port}")

        def fake_spawn(argv, log_path=None):
            calls["spawned"].append(argv)
            calls["log_path"].append(log_path)
            return FakeProc() if spawn is self.KEEP else spawn

        def fake_port_open(host, port, timeout=0.5):
            calls["probed"].append((host, port))
            return host in answers

        out = io.StringIO()
        with mock.patch.object(server, "port_owner", fake_owner), \
             mock.patch.object(server, "kill", fake_kill), \
             mock.patch.object(server, "spawn", fake_spawn), \
             mock.patch.object(server, "wait_ready", fake_wait), \
             mock.patch.object(server, "port_open", fake_port_open), \
             mock.patch.object(main, "launch_log_path", lambda name, port: log), \
             mock.patch.object(main, "ask", fake_ask), \
             contextlib.redirect_stdout(out):
            result = main.launch(self.data, self.cfg, values)
        return result, out.getvalue(), calls


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


class TestPortIsUsableBeforeAnythingStarts(LaunchFixture):
    """A hand-edited config can write the port as a string. It emits fine as an
    argument, so the only thing that noticed was socket.connect_ex - a TypeError
    from inside wait_ready, after the server was already running."""

    def test_a_numeric_string_port_never_reaches_a_socket_as_a_string(self):
        result, text, calls = self.launch(self.values(port="8080"))
        self.assertIs(result, True)
        self.assertEqual(calls["owner_port"], [8080])
        self.assertEqual(calls["wait_port"], [8080])
        for got in calls["owner_port"] + calls["wait_port"]:
            self.assertIsInstance(got, int, "port_open would raise TypeError")

    def test_a_port_that_is_not_a_number_is_reported_not_raised(self):
        result, text, calls = self.launch(self.values(port="eighty-eighty"))
        self.assertIs(result, False)
        self.assertIn("eighty-eighty", text)
        self.assertIn("row 3", text)
        self.assertEqual(calls["owner_port"], [],
                         "nothing may be probed or started with a broken port")

    def test_a_normal_integer_port_is_unaffected(self):
        result, _, calls = self.launch(self.values(port=8082))
        self.assertIs(result, True)
        self.assertEqual(calls["wait_port"], [8082])


class TestHostIsUsableBeforeAnythingStarts(LaunchFixture):
    """The port got this guard; the host did not, and the host is read by
    wait_ready - AFTER llama-server is up. A bad one therefore cost an orphaned
    server in its own console window, a traceback, and the board with every
    unsaved edit on it."""

    def assertRefused(self, host, needle=None):
        result, text, calls = self.launch(self.values(host=host))
        self.assertIs(result, False)
        self.assertIn("row 3", text)
        if needle:
            self.assertIn(needle, text)
        self.assertEqual(calls["spawned"], [],
                         "nothing may be started with a host we cannot reach")
        self.assertEqual(calls["wait_port"], [])
        return text

    def test_a_host_that_is_not_a_string_is_reported_not_raised(self):
        """A hand-edited config can hold a number here; socket.connect_ex
        answers that with a TypeError, from inside the readiness poll."""
        self.assertRefused(5, "5")

    def test_a_missing_host_is_reported(self):
        self.assertRefused(None)

    def test_an_empty_host_is_reported(self):
        self.assertRefused("")

    def test_a_hostname_that_cannot_be_resolved_is_reported(self):
        self.assertRefused("not a host", "not a host")

    def test_an_ipv6_only_host_is_refused_rather_than_waited_on(self):
        """::1 is a real bind address and a real dead end: server.port_open
        probes AF_INET, so the server would come up and never be seen ready."""
        self.assertRefused("::1")

    def test_a_usable_host_still_launches(self):
        """Otherwise 'refuse every host' would pass every test above and
        nothing could ever be launched."""
        result, text, calls = self.launch(self.values(host="127.0.0.1"))
        self.assertIs(result, True)
        self.assertEqual(len(calls["spawned"]), 1)
        self.assertNotIn("row 3", text)

    def test_localhost_by_name_is_also_usable(self):
        result, _, calls = self.launch(self.values(host="localhost"))
        self.assertIs(result, True)
        self.assertEqual(len(calls["spawned"]), 1)


class TestSpawnThatCouldNotStartAnything(LaunchFixture):
    """server.spawn reports a start it could not make by returning None rather
    than raising OSError. A caller that treats that as a process hands None to
    wait_ready and prints a pid off it."""

    def test_a_spawn_that_returns_none_is_reported_as_a_failure(self):
        result, text, calls = self.launch(self.values(), spawn=None)
        self.assertIs(result, False)
        self.assertIn("could not be started", text)
        self.assertIn(self.data["llama_server"], text,
                      "the path that is wrong must be named")
        self.assertEqual(calls["wait_port"], [],
                         "there is no readiness to wait for")

    def test_a_spawn_that_works_still_launches(self):
        """Otherwise 'always report a failed spawn' would pass the test above."""
        result, text, calls = self.launch(self.values())
        self.assertIs(result, True)
        self.assertNotIn("could not be started", text)


class TestPortOwnerThatCouldNotBeDetermined(LaunchFixture):
    """server.port_owner has a third answer - it could not say who holds the
    port - and it is not the same as "somebody holds this port". Reading it as
    an owner told the user the port was held by a process called "unknown"."""

    def test_an_unknown_owner_on_a_port_that_answers_stops_the_launch(self):
        """'Could not say who' is not 'could not tell whether'. Something IS
        listening - another user's process, say - so starting would only have
        llama-server die on the bind while the stranger's open port is read
        as our server being ready."""
        result, text, calls = self.launch(self.values(),
                                          owner=server.UNKNOWN_OWNER,
                                          answers=("127.0.0.1",))
        self.assertIs(result, False)
        self.assertIn("cannot identify", text)
        self.assertIn("row 3", text)
        self.assertNotIn("starting anyway", text)
        self.assertEqual(calls["spawned"], [])
        self.assertEqual(calls["killed"], [])
        self.assertEqual(calls["asked"], [], "there is nobody to offer to stop")

    def test_the_configured_host_is_probed_as_well_as_loopback(self):
        """A listener bound only to the address the server is about to use is
        just as much in the way."""
        result, _, calls = self.launch(self.values(host="localhost"),
                                       owner=server.UNKNOWN_OWNER,
                                       answers=("localhost",))
        self.assertIs(result, False)
        self.assertEqual(calls["probed"],
                         [("127.0.0.1", 8080), ("localhost", 8080)])
        self.assertEqual(calls["spawned"], [])

    def test_the_default_host_is_probed_only_once(self):
        _, _, calls = self.launch(self.values(), owner=server.UNKNOWN_OWNER)
        self.assertEqual(calls["probed"], [("127.0.0.1", 8080)])

    def test_a_port_with_no_owner_is_not_probed(self):
        """The probe is only for the answer that could not name anyone."""
        _, _, calls = self.launch(self.values())
        self.assertEqual(calls["probed"], [])

    def test_an_unknown_owner_is_not_reported_as_a_foreign_process(self):
        result, text, calls = self.launch(self.values(),
                                          owner=server.UNKNOWN_OWNER)
        self.assertIs(result, True)
        self.assertIn("could not check", text)
        self.assertNotIn("not a llama-server", text)
        self.assertEqual(calls["killed"], [])
        self.assertEqual(len(calls["spawned"]), 1)

    def test_a_named_foreign_owner_still_stops_the_launch(self):
        """Otherwise 'treat every owner as unknown' would pass the test above
        and the launcher would start on top of somebody else's port."""
        result, text, calls = self.launch(self.values(),
                                          owner=server.Owner(4321, "nginx.exe", 1000.5))
        self.assertIs(result, False)
        self.assertIn("not a llama-server", text)
        self.assertEqual(calls["spawned"], [])


class TestAliasThatIsNotAString(LaunchFixture):
    def test_a_number_as_the_alias_does_not_take_the_launch_down(self):
        """A hand-edited "alias": 5 puts a number in argv, and Popen answers
        that with a TypeError - which spawn() does not turn into a report,
        because it is not an OSError."""
        self.cfg["alias"] = 5
        result, text, calls = self.launch(self.values())
        self.assertIs(result, True)
        self.assertIn("5", calls["spawned"][0])
        for arg in calls["spawned"][0]:
            self.assertIsInstance(arg, str, "Popen would raise TypeError")


class TestStartupSurvivesAConfigItCannotRead(unittest.TestCase):
    """config.load turns the file-level failures it knows about into a
    ConfigError. A document nested thousands of brackets deep is not one of
    them: json.load gives up with a RecursionError, which is neither a
    ValueError nor an OSError, so it escaped as a traceback from the first
    thing the launcher does."""

    def run_main(self, text):
        folder = tempfile.mkdtemp()
        path = os.path.join(folder, "launcher_configs.json")
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)
        out = io.StringIO()

        def no_ask(prompt=""):
            raise AssertionError("the menu must not be reached")

        with mock.patch.object(main, "CONFIG_PATH", path), \
             mock.patch.object(main, "LEGACY_PATH",
                               os.path.join(folder, "no-legacy.json")), \
             mock.patch.object(main, "ask", no_ask), \
             contextlib.redirect_stdout(out):
            code = main._main()
        return code, out.getvalue(), path

    def test_a_document_nested_too_deeply_is_reported_not_raised(self):
        code, text, path = self.run_main("[" * 200000 + "]" * 200000)
        self.assertEqual(code, 1)
        self.assertIn(path, text, "the message must name the file")
        self.assertIn("nested too deeply", text)

    def test_a_legacy_file_nested_too_deeply_is_reported_too(self):
        """The migration reads model_profiles.json through the same door, and
        it runs before anything else the launcher does."""
        folder = tempfile.mkdtemp()
        legacy = os.path.join(folder, "model_profiles.json")
        with open(legacy, "w", encoding="utf-8") as f:
            f.write("[" * 200000 + "]" * 200000)
        out = io.StringIO()
        with mock.patch.object(main, "CONFIG_PATH",
                               os.path.join(folder, "launcher_configs.json")), \
             mock.patch.object(main, "LEGACY_PATH", legacy), \
             contextlib.redirect_stdout(out):
            ok = main.first_run_migration("D:/M", "D:/s.exe")
        self.assertIs(ok, False)
        self.assertIn("cannot migrate", out.getvalue())
        self.assertTrue(os.path.exists(legacy),
                        "the rollback file must be left untouched")


class TestHostErrorAnswersInsteadOfRaising(unittest.TestCase):
    """host_error is a guard: it promises a string or None for ANY host a hand
    edit can put in the file. It caught OSError only, and socket.getaddrinfo
    encodes the name with the idna codec before it looks anything up - a codec
    that reports a name it cannot encode with UnicodeError, which is a
    ValueError and NOT an OSError. So the values it was written to refuse were
    exactly the ones that got past it, as a traceback out of main() - which
    catches only Abort - taking the board and every unsaved edit with it."""

    def assertRefused(self, host, port=8080):
        """Refused with a message that names the host, rather than raised."""
        try:
            answer = main.host_error(host, port)
        except Exception as exc:                 # noqa: BLE001 - that is the bug
            self.fail(f"host_error({host!r}) raised {type(exc).__name__}: {exc}")
        self.assertIsInstance(answer, str, "a refusal must be a message")
        self.assertIn(repr(host)[:20].strip("'"), answer,
                      "the message must name the host the user has to fix")
        return answer

    def test_a_label_over_63_characters_is_refused_not_raised(self):
        """The reported crash, at its exact threshold. 63 characters resolve
        (and fail) through the OSError path; the 64th makes idna give up with
        'label too long' before any lookup happens."""
        self.assertRefused("a" * 63)
        self.assertRefused("a" * 64)

    def test_a_non_ascii_name_trips_the_same_codec_sooner(self):
        """idna encodes to punycode before it measures, so a non-ASCII name
        exceeds the 63-character label limit at fewer characters than an ASCII
        one - 58 of these on this machine."""
        self.assertRefused("\u00e4" * 58)      # escaped: this file stays ASCII

    def test_a_name_with_an_empty_label_is_refused_not_raised(self):
        """A lone "." is a plausible hand edit and never reaches a lookup:
        idna rejects the empty label it makes."""
        self.assertRefused(".")

    def test_a_hostname_that_cannot_be_resolved_is_refused(self):
        """The OSError path the function already handled, kept under test so a
        fix to the Unicode path cannot quietly cost the original one."""
        self.assertRefused("not a host")

    def test_a_host_that_is_not_a_string_is_refused(self):
        self.assertRefused(5)
        self.assertRefused(None)

    def test_an_empty_host_is_refused(self):
        self.assertRefused("")
        self.assertRefused("   ")

    def test_an_ipv6_literal_is_refused(self):
        """::1 is a real llama-server bind address and a real dead end here:
        server.port_open probes AF_INET, so the server would come up and the
        readiness poll could never see it."""
        self.assertRefused("::1")

    def test_a_usable_host_is_not_refused(self):
        """Otherwise 'refuse everything' passes every test above and nothing
        could ever be launched."""
        self.assertIsNone(main.host_error("127.0.0.1", 8080))

    def test_a_usable_hostname_is_not_refused(self):
        self.assertIsNone(main.host_error("localhost", 8080))


class TestALabelTooLongDoesNotEndTheSession(LaunchFixture):
    """The same defect where it actually bit: launch() reads the host from a
    hand-edited config, and a UnicodeError here is not caught by anything
    between this line and the top of the program."""

    def test_a_too_long_label_is_reported_like_any_other_bad_host(self):
        result, text, calls = self.launch(self.values(host="a" * 64))
        self.assertIs(result, False, "a bad host must be reported, not raised")
        self.assertIn("row 3", text, "the user must be told where to fix it")
        self.assertEqual(calls["spawned"], [],
                         "nothing may be started with a host we cannot reach")
        self.assertEqual(calls["wait_port"], [])


class TestDraftModelIsCheckedOnlyWhenItIsEmitted(LaunchFixture):
    """launch() checked draft_model exists whenever the value was truthy, but
    build_argv emits --spec-draft-model only when active_keys says the spec type
    uses one. A stale path left on a config switched to an ngram-* type - which
    needs no draft GGUF - therefore blocked the launch over a flag that was
    never going to be sent."""

    def test_a_stale_draft_path_does_not_block_a_type_that_ignores_it(self):
        values = self.values(spec_type="ngram-mod",
                             draft_model="gone/stale-draft.gguf")
        self.assertIsNone(catalog.spec_error(values),
                          "precondition: the values themselves are valid")
        result, text, calls = self.launch(values)
        self.assertIs(result, True)
        self.assertNotIn("draft model is gone", text)
        self.assertNotIn("--spec-draft-model", calls["spawned"][0],
                         "precondition: the flag really is never sent")

    def test_draft_mtp_checks_a_draft_model_it_is_going_to_send(self):
        """draft-mtp emits --spec-draft-model whenever one is set, so a path that
        has gone missing must stop the launch exactly as it does for the required
        types. This used to be waved through: the flag was dropped before it
        could be sent, so the check had nothing to guard."""
        values = self.values(spec_type="draft-mtp",
                             draft_model="gone/stale-draft.gguf")
        result, text, calls = self.launch(values)
        self.assertIs(result, False)
        self.assertIn("draft model is gone", text)
        self.assertEqual(calls["spawned"], [])

    def test_bare_draft_mtp_launches_with_no_draft_model_at_all(self):
        """The head-in-the-weights case: nothing on the draft row, nothing to
        check, nothing to send. Without this, 'make draft-mtp required' would
        pass the test above and still be wrong."""
        values = self.values(spec_type="draft-mtp")
        result, text, calls = self.launch(values)
        self.assertIs(result, True)
        self.assertNotIn("draft model is gone", text)
        self.assertNotIn("--spec-draft-model", calls["spawned"][0])

    def test_a_missing_draft_model_still_stops_a_type_that_needs_one(self):
        """Otherwise 'delete the check' passes both tests above, and the launch
        goes ahead with a --spec-draft-model llama-server cannot open."""
        values = self.values(spec_type="draft-simple",
                             draft_model="gone/stale-draft.gguf")
        result, text, calls = self.launch(values)
        self.assertIs(result, False)
        self.assertIn("draft model is gone", text)
        self.assertEqual(calls["spawned"], [])

    def test_a_draft_model_that_is_there_still_launches_and_is_emitted(self):
        draft = os.path.join(self.folder, "d.gguf")
        with open(draft, "w", encoding="utf-8") as f:
            f.write("")
        values = self.values(spec_type="draft-simple", draft_model="d.gguf")
        result, text, calls = self.launch(values)
        self.assertIs(result, True)
        self.assertIn("--spec-draft-model", calls["spawned"][0])
        self.assertIn(draft, calls["spawned"][0])


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


if __name__ == "__main__":
    unittest.main()
