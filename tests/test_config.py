import json
import os
import tempfile
import unittest

from launcher import config


class TestPaths(unittest.TestCase):
    ROOT = r"D:\LLM Models"

    def test_canon_folds_separators_and_case(self):
        self.assertEqual(config.canon("D:/LLM Models/a/b.gguf"),
                         config.canon(r"d:\llm models\A\B.gguf"))

    def test_resolve_path_joins_relative(self):
        self.assertEqual(config.resolve_path("Qwen/x.gguf", self.ROOT),
                         os.path.join(self.ROOT, "Qwen", "x.gguf"))

    def test_resolve_path_passes_absolute_through(self):
        p = r"C:\elsewhere\x.gguf"
        self.assertEqual(config.resolve_path(p, self.ROOT), p)

    def test_relativise_strips_the_root(self):
        self.assertEqual(
            config.relativise(r"D:\LLM Models\Qwen\x.gguf", self.ROOT),
            "Qwen/x.gguf")

    def test_relativise_keeps_paths_outside_the_root(self):
        p = r"C:\elsewhere\x.gguf"
        self.assertEqual(config.relativise(p, self.ROOT), p)


class TestResolveValues(unittest.TestCase):
    def data(self, defaults=None, settings=None):
        return ({"model_root": "D:/LLM Models",
                 "llama_server": "D:/llama.cpp/llama-server.exe",
                 "defaults": defaults or {},
                 "configs": [{"name": "c", "model": "m.gguf",
                              "settings": settings or {}}]})

    def test_catalog_default_when_nothing_overrides(self):
        d = self.data()
        self.assertEqual(config.resolve_values(d, d["configs"][0])["context"], 8192)

    def test_file_defaults_beat_catalog(self):
        d = self.data(defaults={"context": 4096})
        self.assertEqual(config.resolve_values(d, d["configs"][0])["context"], 4096)

    def test_config_settings_beat_file_defaults(self):
        d = self.data(defaults={"context": 4096}, settings={"context": 128000})
        self.assertEqual(config.resolve_values(d, d["configs"][0])["context"], 128000)

    def test_unknown_keys_are_ignored(self):
        d = self.data(settings={"nonsense": 1})
        self.assertNotIn("nonsense", config.resolve_values(d, d["configs"][0]))


class TestLoad(unittest.TestCase):
    def write(self, text):
        fd, path = tempfile.mkstemp(suffix=".json")
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
        self.addCleanup(os.unlink, path)
        return path

    def test_load_reads_a_valid_file(self):
        path = self.write(json.dumps({"version": 2, "model_root": "D:/M",
                                      "llama_server": "D:/s.exe",
                                      "defaults": {}, "configs": []}))
        self.assertEqual(config.load(path)["model_root"], "D:/M")

    def test_malformed_json_raises_with_position(self):
        path = self.write("{ broken")
        with self.assertRaises(config.ConfigError) as ctx:
            config.load(path)
        self.assertIn("line", str(ctx.exception))

    def test_a_non_utf8_file_reports_instead_of_tracebacking(self):
        """Every editor on this machine defaults to cp1252, so one umlaut in a
        model name is enough to produce a file we cannot decode. That is a
        UnicodeDecodeError - a ValueError, neither a JSONDecodeError nor an
        OSError - so it escaped both existing guards."""
        fd, path = tempfile.mkstemp(suffix=".json")
        with os.fdopen(fd, "wb") as f:
            f.write('{"model_root": "D:/M\u00fcnchen"}'.encode("cp1252"))
        self.addCleanup(os.unlink, path)
        with self.assertRaises(config.ConfigError) as ctx:
            config.load(path)
        message = str(ctx.exception)
        self.assertIn(path, message, "the message must name the file")
        self.assertIn("UTF-8", message)
        message.encode("cp1252")

    def test_an_unreadable_path_reports_instead_of_tracebacking(self):
        """A config replaced by a DIRECTORY - or locked by another program - is
        an OSError, not a FileNotFoundError, and reached the user raw."""
        folder = tempfile.mkdtemp()
        with self.assertRaises(config.ConfigError) as ctx:
            config.load(folder)
        self.assertIn(folder, str(ctx.exception))

    def test_a_missing_file_still_says_so(self):
        """Otherwise a blanket guard could report every failure as the wrong one."""
        with self.assertRaises(config.ConfigError) as ctx:
            config.load(os.path.join(tempfile.mkdtemp(), "nope.json"))
        self.assertIn("not found", str(ctx.exception))


class TestDocumentError(unittest.TestCase):
    """Valid JSON is not a valid document. Each of these used to surface as a
    KeyError or TypeError from whichever line happened to read the key first."""

    PATH = "D:/Scripts/launcher_configs.json"

    def doc(self, **over):
        d = {"version": 2, "model_root": "D:/M", "llama_server": "D:/s.exe",
             "defaults": {}, "configs": [{"name": "c", "model": "m.gguf"}]}
        d.update(over)
        return d

    def error(self, document):
        return config.document_error(document, self.PATH)

    def test_a_complete_document_has_no_error(self):
        self.assertIsNone(self.error(self.doc()))

    def test_an_empty_configs_list_is_fine(self):
        """A brand-new document has no configs yet; that is not an error."""
        self.assertIsNone(self.error(self.doc(configs=[])))

    def test_every_missing_key_is_named_along_with_the_file(self):
        for key in ("model_root", "llama_server", "configs"):
            with self.subTest(key=key):
                document = self.doc()
                del document[key]
                message = self.error(document)
                self.assertIsNotNone(message)
                self.assertIn(key, message)
                self.assertIn(self.PATH, message)

    def test_a_config_missing_name_or_model_is_named(self):
        for key in ("name", "model"):
            with self.subTest(key=key):
                cfg = {"name": "c", "model": "m.gguf"}
                del cfg[key]
                message = self.error(self.doc(configs=[cfg]))
                self.assertIsNotNone(message)
                self.assertIn(key, message)

    def test_wrong_types_are_caught_as_well_as_missing_keys(self):
        for document in (self.doc(model_root=5), self.doc(llama_server=[1]),
                         self.doc(configs={"a": 1}), self.doc(configs=["str"]),
                         self.doc(configs=[{"name": 5, "model": "m.gguf"}]),
                         self.doc(configs=[{"name": "c", "model": 5}]),
                         self.doc(configs=[{"name": "c", "model": "m",
                                            "settings": []}]),
                         self.doc(defaults=[]), ["not a document"], "text", None):
            with self.subTest(document=document):
                self.assertIsNotNone(self.error(document))

    def test_the_messages_survive_the_console_encoding(self):
        message = self.error(self.doc(configs=[{"name": "c"}]))
        message.encode("cp1252")


class TestMigration(unittest.TestCase):
    ROOT = "D:/LLM Models"
    EXE = "D:/llama.cpp/llama-server.exe"

    PROFILES = {
        "defaults": {"ngl": 99, "context": 8192, "host": "127.0.0.1",
                     "port": 8080, "temp": 0.6, "top_k": 20, "top_p": 0.95,
                     "min_p": 0.0, "flash_attn": True},
        "models": [
            {"name": "Qwen3.6-35B", "alias": "qwen3.6",
             "path": "D:/LLM Models/Qwen3.6/Qwen3.6-35B-A3B-UD-Q4_K_XL.gguf",
             "overrides": {"context": 8192, "temp": 0.6}},
            {"name": "dspark", "alias": "dspark",
             "path": "D:/LLM Models/ankk98/dspark-gemma/dspark_gemma4_12b_q4pure.gguf",
             "overrides": {"context": 4096}},
        ],
    }

    def migrate(self):
        return config.migrate(self.PROFILES, self.ROOT, self.EXE)

    def test_ngl_is_renamed_to_gpu_layers(self):
        doc, _ = self.migrate()
        self.assertEqual(doc["defaults"]["gpu_layers"], "99")
        self.assertNotIn("ngl", doc["defaults"])

    def test_flash_attn_true_becomes_on(self):
        doc, _ = self.migrate()
        self.assertEqual(doc["defaults"]["flash_attn"], "on")

    def test_each_model_becomes_a_config_keyed_by_alias(self):
        doc, _ = self.migrate()
        self.assertEqual([c["name"] for c in doc["configs"]], ["qwen3.6", "dspark"])

    def test_model_paths_are_relativised(self):
        doc, _ = self.migrate()
        self.assertEqual(doc["configs"][0]["model"],
                         "Qwen3.6/Qwen3.6-35B-A3B-UD-Q4_K_XL.gguf")

    def test_overrides_carry_across(self):
        doc, _ = self.migrate()
        self.assertEqual(doc["configs"][0]["settings"]["context"], 8192)

    def test_version_and_roots_are_written(self):
        doc, _ = self.migrate()
        self.assertEqual(doc["version"], 2)
        self.assertEqual(doc["model_root"], self.ROOT)
        self.assertEqual(doc["llama_server"], self.EXE)

    def test_report_flags_dspark_as_probably_a_draft_model(self):
        _, report = self.migrate()
        self.assertTrue(any("dspark" in line and "draft" in line.lower()
                            for line in report))

    def test_input_profiles_dict_is_not_mutated(self):
        """The caller may still be holding this dict. Migration reads only."""
        import copy
        before = copy.deepcopy(self.PROFILES)
        self.migrate()
        self.assertEqual(self.PROFILES, before)


class TestMigrationRobustness(unittest.TestCase):
    """Migration runs once, unattended, against the user's only config file.
    A partial or hand-edited entry must degrade, not abort."""

    ROOT = "D:/LLM Models"
    EXE = "D:/llama.cpp/llama-server.exe"

    def migrate(self, profiles):
        return config.migrate(profiles, self.ROOT, self.EXE)

    def test_entry_without_a_path_is_skipped_not_fatal(self):
        doc, report = self.migrate({"defaults": {}, "models": [
            {"name": "good", "alias": "good", "path": "D:/LLM Models/a/b.gguf"},
            {"name": "broken", "alias": "broken"},
        ]})
        self.assertEqual([c["name"] for c in doc["configs"]], ["good"])
        self.assertTrue(any("SKIPPED" in line and "path" in line for line in report))

    def test_entry_without_a_name_is_skipped_not_fatal(self):
        doc, report = self.migrate({"defaults": {},
                                    "models": [{"path": "D:/LLM Models/a/b.gguf"}]})
        self.assertEqual(doc["configs"], [])
        self.assertTrue(any("SKIPPED" in line for line in report))

    def test_uninterpretable_flash_attn_is_dropped_with_a_warning(self):
        doc, report = self.migrate({"defaults": {"flash_attn": "yes please"},
                                    "models": []})
        self.assertNotIn("flash_attn", doc["defaults"])
        self.assertTrue(any("WARNING" in line and "flash_attn" in line
                            for line in report))

    def test_an_already_valid_flash_attn_string_passes_through(self):
        doc, _ = self.migrate({"defaults": {"flash_attn": "auto"}, "models": []})
        self.assertEqual(doc["defaults"]["flash_attn"], "auto")

    def test_a_models_key_that_is_not_a_list_is_reported_not_fatal(self):
        """Migration is unattended and runs on the user's only config. Every
        wrong SHAPE below ended it with an AttributeError instead, leaving the
        launcher with no v2 document at all.

        Both shapes are checked on purpose. A number is not iterable at all; a
        dict IS, one key at a time, so without a check on `models` itself the
        per-entry guard would quietly absorb it and report the wrong thing."""
        for models in (5, "Qwen3.6", {"a": 1}):
            with self.subTest(models=models):
                doc, report = self.migrate({"defaults": {}, "models": models})
                self.assertEqual(doc["configs"], [])
                self.assertTrue(
                    any("models" in line for line in report),
                    f"the report must name 'models': {report}")

    def test_an_entry_that_is_not_an_object_is_skipped_not_fatal(self):
        doc, report = self.migrate({"defaults": {}, "models": [
            "just a string",
            {"name": "good", "alias": "good", "path": "D:/LLM Models/a/b.gguf"},
        ]})
        self.assertEqual([c["name"] for c in doc["configs"]], ["good"])
        self.assertTrue(any("SKIPPED entry 1" in line for line in report))

    def test_an_entry_whose_path_is_not_a_string_is_skipped_not_fatal(self):
        doc, report = self.migrate({"defaults": {}, "models": [
            {"name": "broken", "path": 5},
            {"name": "good", "alias": "good", "path": "D:/LLM Models/a/b.gguf"},
        ]})
        self.assertEqual([c["name"] for c in doc["configs"]], ["good"])
        self.assertTrue(any("SKIPPED entry 1" in line and "path" in line
                            for line in report))

    def test_an_entry_whose_name_is_not_a_string_is_skipped_not_fatal(self):
        doc, report = self.migrate({"defaults": {}, "models": [
            {"name": 7, "path": "D:/LLM Models/a/b.gguf"}]})
        self.assertEqual(doc["configs"], [])
        self.assertTrue(any("SKIPPED" in line for line in report))

    def test_overrides_that_are_not_an_object_are_dropped_with_a_warning(self):
        doc, report = self.migrate({"defaults": {}, "models": [
            {"name": "good", "path": "D:/LLM Models/a/b.gguf",
             "overrides": ["context", 4096]}]})
        self.assertEqual(doc["configs"][0]["settings"], {})
        self.assertTrue(any("WARNING" in line for line in report))

    def test_a_legacy_file_that_is_not_an_object_at_all_is_reported(self):
        doc, report = self.migrate(["not", "a", "profiles", "document"])
        self.assertEqual(doc["configs"], [])
        self.assertEqual(doc["version"], 2)
        self.assertTrue(any("SKIPPED" in line for line in report))

    def test_every_skip_message_survives_the_console_encoding(self):
        _, report = self.migrate({"models": [5, {"path": 1, "name": "x"}]})
        for line in report:
            line.encode("cp1252")

    def test_non_ascii_model_name_survives_migration(self):
        """Model names are user data off the user's disk and may contain
        anything. migrate() must carry them through verbatim without raising and
        without mangling them; making them printable is __main__'s job, via its
        stdout reconfigure. See the Global Constraints note on authored strings
        versus interpolated user data."""
        name = "\u4e2d\u6587-model"
        doc, report = self.migrate({"defaults": {}, "models": [
            {"name": name, "alias": name, "path": "D:/LLM Models/a/b.gguf"}]})
        self.assertEqual(doc["configs"][0]["name"], name)
        self.assertTrue(any(name in line for line in report))


class TestSave(unittest.TestCase):
    def doc(self, defaults=None):
        return {"version": 2, "model_root": "D:/M", "llama_server": "D:/s.exe",
                "defaults": defaults or {}, "configs": []}

    def test_a_value_equal_to_the_FILE_default_is_excluded(self):
        """The overlay is the entire point of this function, so one test must
        fail if it is removed. context=4096 differs from the catalog default of
        8192, but it IS the live file default, so a config sitting at 4096 has
        nothing of its own to save. Delete the overlay loop and this fails."""
        data = self.doc(defaults={"context": 4096})
        values = config.resolve_values(data, {"settings": {}})
        self.assertEqual(values["context"], 4096)
        self.assertEqual(config.diff_from_defaults(data, values), {})

    def test_diff_keeps_only_what_differs(self):
        data = self.doc(defaults={"context": 4096})
        values = config.resolve_values(data, {"settings": {}})
        values["port"] = 8082           # differs from the catalog default 8080
        values["temp"] = 0.6            # equals the catalog default
        diff = config.diff_from_defaults(data, values)
        # context is absent because it matches the FILE default, not because it
        # matches the catalog one - without the overlay it would appear here.
        self.assertEqual(diff, {"port": 8082})

    def test_diff_is_empty_when_nothing_changed(self):
        data = self.doc()
        values = config.resolve_values(data, {"settings": {}})
        self.assertEqual(config.diff_from_defaults(data, values), {})

    def test_save_round_trips(self):
        path = os.path.join(tempfile.mkdtemp(), "cfg.json")
        data = self.doc(defaults={"context": 4096})
        config.save(path, data)
        self.assertEqual(config.load(path)["defaults"]["context"], 4096)

    def test_save_leaves_no_temp_file_behind(self):
        folder = tempfile.mkdtemp()
        path = os.path.join(folder, "cfg.json")
        config.save(path, self.doc())
        self.assertEqual(os.listdir(folder), ["cfg.json"])

    def test_save_does_not_destroy_the_original_on_failure(self):
        path = os.path.join(tempfile.mkdtemp(), "cfg.json")
        config.save(path, self.doc(defaults={"context": 4096}))
        unserialisable = self.doc()
        unserialisable["configs"] = [{"bad": object()}]
        with self.assertRaises(Exception):
            config.save(path, unserialisable)
        self.assertEqual(config.load(path)["defaults"]["context"], 4096)

    def test_a_failed_save_leaves_no_temp_file(self):
        """The success path is covered above. The failure path is the one that
        matters: a half-written scratch file left beside the config is litter at
        best, and confusing at worst."""
        folder = tempfile.mkdtemp()
        path = os.path.join(folder, "cfg.json")
        config.save(path, self.doc())
        unserialisable = self.doc()
        unserialisable["configs"] = [{"bad": object()}]
        with self.assertRaises(Exception):
            config.save(path, unserialisable)
        self.assertEqual(os.listdir(folder), ["cfg.json"])

    def test_a_failing_save_raises_one_catchable_type_naming_the_file(self):
        """[s] must report and keep the board up. That needs a single exception
        type callers can name - a raw TypeError out of json.dump ended the
        session and took every unsaved edit with it."""
        path = os.path.join(tempfile.mkdtemp(), "cfg.json")
        unserialisable = self.doc()
        unserialisable["configs"] = [{"bad": object()}]
        with self.assertRaises(config.ConfigError) as ctx:
            config.save(path, unserialisable)
        self.assertIn(path, str(ctx.exception))

    def test_an_unwritable_target_also_raises_that_type(self):
        folder = tempfile.mkdtemp()
        target = os.path.join(folder, "sub")
        os.mkdir(target)                 # os.replace cannot overwrite a directory
        with self.assertRaises(config.ConfigError):
            config.save(target, self.doc())

    def test_temp_path_is_same_directory_and_process_qualified(self):
        """Same directory keeps os.replace atomic - it is only atomic within one
        volume. The pid keeps two launcher instances from colliding."""
        target = os.path.join(tempfile.mkdtemp(), "cfg.json")
        tmp = config._temp_path(target)
        self.assertEqual(os.path.dirname(tmp), os.path.dirname(target))
        self.assertIn(str(os.getpid()), os.path.basename(tmp))
        self.assertNotEqual(tmp, target)


if __name__ == "__main__":
    unittest.main()
