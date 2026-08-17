"""Tests for the machine-independence layer: device detection and first-run paths.

These exist because the launcher used to carry two hardcoded constants pointing at
one particular D: drive, and a GPU check that shelled out to nvidia-smi. Neither
worked on anyone else's machine. The replacements are covered here because the last
piece of untested startup code in this project - host_error - shipped a crash.
"""
import os
import tempfile
import unittest

from launcher import __main__ as main


class TestParseDevices(unittest.TestCase):
    """Real `llama-server --list-devices` output, per backend. The point of asking
    the binary rather than nvidia-smi is that the BUILD decides: a CUDA card with a
    Vulkan-only build reports Vulkan, and that is the truth the user needs."""

    def test_cuda_build(self):
        text = ("Available devices:\n"
                "  CUDA0: NVIDIA GeForce RTX 4080 (16375 MiB, 15074 MiB free)\n")
        self.assertEqual(main.parse_devices(text),
                         "CUDA0: NVIDIA GeForce RTX 4080 (16375 MiB, 15074 MiB free)")

    def test_rocm_build(self):
        text = ("Available devices:\n"
                "  ROCm0: AMD Radeon RX 7900 XTX (24560 MiB, 24000 MiB free)\n")
        self.assertIn("ROCm0", main.parse_devices(text))
        self.assertIn("Radeon", main.parse_devices(text))

    def test_vulkan_build(self):
        text = ("Available devices:\n"
                "  Vulkan0: AMD Radeon RX 6800 (16384 MiB, 16000 MiB free)\n")
        self.assertIn("Vulkan0", main.parse_devices(text))

    def test_metal_build(self):
        text = ("Available devices:\n"
                "  Metal0: Apple M3 Max (40536 MiB, 40000 MiB free)\n")
        self.assertIn("Metal0", main.parse_devices(text))

    def test_two_devices_are_both_shown(self):
        text = ("Available devices:\n"
                "  CUDA0: NVIDIA A (1 MiB, 1 MiB free)\n"
                "  CUDA1: NVIDIA B (2 MiB, 2 MiB free)\n")
        out = main.parse_devices(text)
        self.assertIn("CUDA0", out)
        self.assertIn("CUDA1", out)

    def test_cpu_only_build_says_so(self):
        """A build with no GPU backend prints the header and nothing else. That is
        not an error, and blank would read as 'detection failed'."""
        self.assertEqual(main.parse_devices("Available devices:\n"), "CPU only")

    def test_empty_output_says_cpu_only(self):
        self.assertEqual(main.parse_devices(""), "CPU only")

    def test_the_header_is_never_shown_as_a_device(self):
        out = main.parse_devices("Available devices:\n  CUDA0: X (1 MiB)\n")
        self.assertNotIn("Available", out)


class TestDeviceLine(unittest.TestCase):
    def test_a_missing_binary_is_blank_not_a_crash(self):
        """Called on every board render, so it must never raise."""
        self.assertEqual(main.device_line(r"D:\definitely\not\here.exe"), "")

    def test_a_non_string_is_blank_not_a_crash(self):
        for bad in (None, 5, ["x"]):
            with self.subTest(bad=bad):
                self.assertEqual(main.device_line(bad), "")


class TestGuessModelRoot(unittest.TestCase):
    """Pre-fills the model folder during migration by deriving it from the legacy
    file's own paths, so the user usually just presses Enter."""

    def test_common_parent_of_several_models(self):
        profiles = {"models": [
            {"path": "D:/LLM Models/Qwen/a.gguf"},
            {"path": "D:/LLM Models/unsloth/b.gguf"},
        ]}
        self.assertEqual(main.guess_model_root(profiles), os.path.normpath("D:/LLM Models"))

    def test_parent_of_a_single_model(self):
        profiles = {"models": [{"path": "D:/LLM Models/Qwen/a.gguf"}]}
        self.assertEqual(main.guess_model_root(profiles),
                         os.path.normpath("D:/LLM Models/Qwen"))

    def test_no_models_gives_no_guess(self):
        self.assertIsNone(main.guess_model_root({"models": []}))
        self.assertIsNone(main.guess_model_root({}))

    @unittest.skipUnless(os.name == "nt", "drive letters are a Windows concept")
    def test_models_on_different_drives_give_no_guess(self):
        """commonpath raises across drives. 'there is no common root' is a real
        answer, not an error to propagate."""
        profiles = {"models": [{"path": "C:/a/x.gguf"}, {"path": "D:/b/y.gguf"}]}
        self.assertIsNone(main.guess_model_root(profiles))

    def test_malformed_entries_are_ignored_not_fatal(self):
        profiles = {"models": [
            "not a dict",
            {"path": 5},
            {"path": "   "},
            {"no_path": "x"},
            {"path": "D:/LLM Models/Qwen/a.gguf"},
        ]}
        self.assertEqual(main.guess_model_root(profiles),
                         os.path.normpath("D:/LLM Models/Qwen"))

    def test_entirely_malformed_input_gives_no_guess(self):
        self.assertIsNone(main.guess_model_root({"models": ["x", {"path": 1}]}))


class TestAskPath(unittest.TestCase):
    """Drives the prompt with a scripted `ask`, so no terminal is involved."""

    def setUp(self):
        self.folder = tempfile.mkdtemp()
        self.file = os.path.join(self.folder, "llama-server.exe")
        with open(self.file, "w", encoding="utf-8") as f:
            f.write("x")

    def scripted(self, answers):
        it = iter(answers)
        return lambda prompt: next(it)

    def test_blank_accepts_the_guess(self):
        got = main.ask_path("exe", self.file, must_be_dir=False,
                            ask=self.scripted([""]))
        self.assertEqual(got, self.file)

    def test_a_typed_path_wins_over_the_guess(self):
        got = main.ask_path("dir", "D:/nowhere", must_be_dir=True,
                            ask=self.scripted([self.folder]))
        self.assertEqual(got, self.folder)

    def test_surrounding_quotes_are_stripped(self):
        """Windows Explorer's 'Copy as path' wraps the result in double quotes."""
        got = main.ask_path("exe", None, must_be_dir=False,
                            ask=self.scripted([f'"{self.file}"']))
        self.assertEqual(got, self.file)

    def test_a_bad_path_re_prompts_rather_than_failing(self):
        got = main.ask_path("exe", None, must_be_dir=False,
                            ask=self.scripted(["D:/nope.exe", "", self.file]))
        self.assertEqual(got, self.file)

    def test_a_file_is_rejected_where_a_folder_is_wanted(self):
        got = main.ask_path("dir", None, must_be_dir=True,
                            ask=self.scripted([self.file, self.folder]))
        self.assertEqual(got, self.folder)

    def test_a_folder_is_rejected_where_a_file_is_wanted(self):
        got = main.ask_path("exe", None, must_be_dir=False,
                            ask=self.scripted([self.folder, self.file]))
        self.assertEqual(got, self.file)


class TestFindLlamaServer(unittest.TestCase):
    def test_returns_a_real_path_or_none_and_never_raises(self):
        """Probes drive letters that may not exist; must not blow up on any of
        them, and must not return a path that is not actually there."""
        found = main.find_llama_server()
        if found is not None:
            self.assertTrue(os.path.isfile(found))

    def test_the_executable_name_matches_the_platform(self):
        self.assertTrue(main.SERVER_EXE.startswith("llama-server"))
        if os.name == "nt":
            self.assertTrue(main.SERVER_EXE.endswith(".exe"))
        else:
            self.assertFalse(main.SERVER_EXE.endswith(".exe"))


if __name__ == "__main__":
    unittest.main()
