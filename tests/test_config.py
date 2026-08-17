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


if __name__ == "__main__":
    unittest.main()
