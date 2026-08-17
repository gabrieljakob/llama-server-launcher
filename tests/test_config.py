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


if __name__ == "__main__":
    unittest.main()
