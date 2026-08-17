import unittest
from launcher import catalog


class TestCatalogShape(unittest.TestCase):
    def test_ten_groups_in_board_order(self):
        labels = [g.label for g in catalog.GROUPS]
        self.assertEqual(labels, [
            "context", "gpu layers", "host:port", "sampling", "toggles",
            "kv cache", "batching", "speculative", "template", "extra args",
        ])

    def test_every_setting_key_is_unique(self):
        keys = [s.key for g in catalog.GROUPS for s in g.settings]
        self.assertEqual(len(keys), len(set(keys)))

    def test_catalog_defaults_cover_every_key(self):
        keys = {s.key for g in catalog.GROUPS for s in g.settings}
        self.assertEqual(set(catalog.catalog_defaults()), keys)

    def test_mutable_defaults_are_not_shared_between_calls(self):
        """chat_template_kwargs defaults to a dict. If every caller received the
        same object, one caller mutating it in place would poison the catalog
        default for the entire process, and every config built afterwards would
        silently inherit the change."""
        a = catalog.catalog_defaults()
        b = catalog.catalog_defaults()
        self.assertIsNot(a["chat_template_kwargs"], b["chat_template_kwargs"])
        a["chat_template_kwargs"]["leaked"] = True
        self.assertEqual(catalog.catalog_defaults()["chat_template_kwargs"], {})


class TestParseValue(unittest.TestCase):
    def parse(self, key, text):
        return catalog.parse_value(catalog.settings_by_key()[key], text)

    def test_int_accepts_digits(self):
        self.assertEqual(self.parse("context", "32768"), (True, 32768))

    def test_int_rejects_words(self):
        ok, err = self.parse("context", "big")
        self.assertFalse(ok)
        self.assertIn("whole number", err)

    def test_int_rejects_out_of_range(self):
        ok, err = self.parse("port", "70000")
        self.assertFalse(ok)
        self.assertIn("1 and 65535", err)

    def test_unbounded_side_is_worded_not_symbolised(self):
        """context has a lower bound and no upper one. The message must stay
        ASCII: this console is cp1252 and printing a non-ASCII character raises
        UnicodeEncodeError, which would crash the launcher mid-edit."""
        ok, err = self.parse("context", "-5")
        self.assertFalse(ok)
        self.assertEqual(err, "must be at least 1")
        err.encode("cp1252")            # raises if a non-ASCII char creeps back in

    def test_every_error_message_survives_the_console_encoding(self):
        """Belt and braces across all types - any non-ASCII in a user-facing
        message is a latent crash."""
        cases = [("context", "big"), ("context", "-5"), ("port", "70000"),
                 ("temp", "nope"), ("top_p", "1.5"), ("cache_type_k", "q3_0"),
                 ("gpu_layers", "most"), ("kv_unified", "maybe"),
                 ("jinja", "maybe"), ("spec_type", "draft-mtp,nonsense"),
                 ("chat_template_kwargs", "{oops"),
                 ("chat_template_kwargs", "[1,2]")]
        for key, text in cases:
            ok, err = self.parse(key, text)
            self.assertFalse(ok, f"{key}={text!r} should have been rejected")
            err.encode("cp1252")

    def test_float_accepts_decimal(self):
        self.assertEqual(self.parse("temp", "0.6"), (True, 0.6))

    def test_float_rejects_out_of_range(self):
        ok, err = self.parse("top_p", "1.5")
        self.assertFalse(ok)
        self.assertIn("between", err)

    def test_choice_accepts_allowed(self):
        self.assertEqual(self.parse("cache_type_k", "q8_0"), (True, "q8_0"))

    def test_choice_rejects_unknown_and_lists_options(self):
        ok, err = self.parse("cache_type_k", "q3_0")
        self.assertFalse(ok)
        self.assertIn("q8_0", err)

    def test_gpu_layers_accepts_keywords_and_ints(self):
        self.assertEqual(self.parse("gpu_layers", "auto"), (True, "auto"))
        self.assertEqual(self.parse("gpu_layers", "all"), (True, "all"))
        self.assertEqual(self.parse("gpu_layers", "99"), (True, "99"))
        self.assertFalse(self.parse("gpu_layers", "most")[0])

    def test_tri_accepts_three_states(self):
        self.assertEqual(self.parse("kv_unified", ""), (True, None))
        self.assertEqual(self.parse("kv_unified", "on"), (True, "on"))
        self.assertEqual(self.parse("kv_unified", "off"), (True, "off"))

    def test_bool_accepts_yes_no(self):
        self.assertEqual(self.parse("jinja", "y"), (True, True))
        self.assertEqual(self.parse("jinja", "n"), (True, False))

    def test_spec_type_accepts_comma_separated_list(self):
        self.assertEqual(self.parse("spec_type", "draft-mtp"), (True, "draft-mtp"))
        ok, _ = self.parse("spec_type", "ngram-mod,ngram-cache")
        self.assertTrue(ok)

    def test_spec_type_rejects_unknown_member(self):
        ok, err = self.parse("spec_type", "draft-mtp,nonsense")
        self.assertFalse(ok)
        self.assertIn("nonsense", err)

    def test_json_accepts_object_and_rejects_array(self):
        self.assertEqual(
            self.parse("chat_template_kwargs", '{"preserve_thinking":true}'),
            (True, {"preserve_thinking": True}),
        )
        ok, err = self.parse("chat_template_kwargs", "[1,2]")
        self.assertFalse(ok)
        self.assertIn("object", err)

    def test_json_rejects_malformed(self):
        ok, err = self.parse("chat_template_kwargs", "{oops")
        self.assertFalse(ok)
        self.assertIn("JSON", err)


class TestEmit(unittest.TestCase):
    def emit(self, key, value):
        return catalog.emit(catalog.settings_by_key()[key], value)

    def test_valued_type_emits_flag_and_value(self):
        self.assertEqual(self.emit("context", 32768), ["-c", "32768"])

    def test_bool_true_emits_bare_flag(self):
        self.assertEqual(self.emit("jinja", True), ["--jinja"])

    def test_bool_false_emits_nothing(self):
        self.assertEqual(self.emit("metrics", False), [])

    def test_tri_unset_emits_nothing(self):
        self.assertEqual(self.emit("kv_unified", None), [])

    def test_tri_on_emits_flag(self):
        self.assertEqual(self.emit("kv_unified", "on"), ["--kv-unified"])

    def test_tri_off_emits_negated_flag(self):
        self.assertEqual(self.emit("kv_unified", "off"), ["--no-kv-unified"])
        self.assertEqual(self.emit("reasoning_preserve", "off"),
                         ["--no-reasoning-preserve"])

    def test_json_emits_compact_string(self):
        self.assertEqual(
            self.emit("chat_template_kwargs",
                      {"preserve_thinking": True, "enable_thinking": True}),
            ["--chat-template-kwargs",
             '{"preserve_thinking":true,"enable_thinking":true}'],
        )

    def test_empty_json_emits_nothing(self):
        self.assertEqual(self.emit("chat_template_kwargs", {}), [])

    def test_raw_is_shlex_split(self):
        self.assertEqual(self.emit("extra", '--props --alias "my model"'),
                         ["--props", "--alias", "my model"])


class TestSpecGating(unittest.TestCase):
    """One test per row of the spec's gating table (design doc section 5)."""

    def values(self, **over):
        v = catalog.catalog_defaults()
        v.update(over)
        return v

    def test_none_emits_no_spec_flags(self):
        argv = catalog.build_argv(self.values(spec_type="none"), "m.gguf", "a")
        self.assertFalse([x for x in argv if x.startswith("--spec")])

    def test_draft_type_without_draft_model_is_rejected(self):
        err = catalog.spec_error(self.values(spec_type="draft-dflash"))
        self.assertIsNotNone(err)
        self.assertIn("draft model", err)

    def test_draft_type_with_draft_model_is_accepted(self):
        v = self.values(spec_type="draft-dflash", draft_model="d.gguf")
        self.assertIsNone(catalog.spec_error(v))

    def test_mtp_emits_spec_type_but_no_draft_model(self):
        v = self.values(spec_type="draft-mtp", spec_n_max=3, spec_p_min=0.75)
        argv = catalog.build_argv(v, "m.gguf", "a")
        self.assertIn("--spec-type", argv)
        self.assertEqual(argv[argv.index("--spec-type") + 1], "draft-mtp")
        self.assertNotIn("--spec-draft-model", argv)
        self.assertIn("--spec-draft-n-max", argv)
        self.assertIn("--spec-draft-p-min", argv)

    def test_mtp_with_a_draft_model_is_rejected(self):
        v = self.values(spec_type="draft-mtp", draft_model="d.gguf")
        err = catalog.spec_error(v)
        self.assertIsNotNone(err)
        self.assertIn("built into", err)

    def test_ngram_needs_no_draft_model(self):
        v = self.values(spec_type="ngram-mod")
        self.assertIsNone(catalog.spec_error(v))
        argv = catalog.build_argv(v, "m.gguf", "a")
        self.assertNotIn("--spec-draft-model", argv)
        self.assertIn("--spec-type", argv)

    def test_none_drops_spec_type_from_emission_but_not_from_editing(self):
        """The two key sets differ by exactly this one key. Without it, row 8
        would be unreachable: 'none' is the default, so nothing could ever
        switch it on."""
        v = self.values(spec_type="none")
        self.assertNotIn("spec_type", catalog.active_keys(v))
        self.assertIn("spec_type", catalog.editable_keys(v))

    def test_editable_and_active_agree_once_spec_is_on(self):
        v = self.values(spec_type="draft-mtp")
        self.assertEqual(catalog.editable_keys(v), catalog.active_keys(v))


class TestAnchorCommands(unittest.TestCase):
    """Both anchor tests from design section 9. Containment, not equality:
    the catalog also emits settings the hand-written commands leave at
    llama-server's own defaults."""

    def assertPairsPresent(self, argv, pairs):
        for flag, value in pairs:
            self.assertIn(flag, argv, f"{flag} missing from argv")
            if value is not None:
                self.assertEqual(argv[argv.index(flag) + 1], value,
                                 f"{flag} has wrong value")

    def test_gemma4dflash(self):
        v = catalog.catalog_defaults()
        v.update({"context": 128000, "port": 8082, "gpu_layers": "99",
                  "parallel": 1, "batch": 512, "ubatch": 128,
                  "reasoning": "on", "metrics": True, "flash_attn": "on",
                  "spec_type": "draft-dflash", "spec_n_max": 4, "spec_ngl": "99",
                  "draft_model": "DFlash.gguf"})
        argv = catalog.build_argv(v, "gemma.gguf", "gemma4dflash",
                                  draft_path="D:\\d\\DFlash.gguf")
        self.assertPairsPresent(argv, [
            ("--model", "gemma.gguf"), ("--alias", "gemma4dflash"),
            ("--spec-draft-model", "D:\\d\\DFlash.gguf"),
            ("--spec-type", "draft-dflash"), ("--spec-draft-n-max", "4"),
            ("--spec-draft-ngl", "99"), ("--host", "127.0.0.1"),
            ("--port", "8082"), ("-np", "1"), ("-ngl", "99"),
            ("-c", "128000"), ("-b", "512"), ("-ub", "128"),
            ("--flash-attn", "on"), ("--reasoning", "on"),
        ])
        self.assertIn("--jinja", argv)
        self.assertIn("--metrics", argv)

    def test_qwen38_preserve_thinking_coding(self):
        v = catalog.catalog_defaults()
        v.update({"temp": 0.6, "presence_penalty": 0.0, "kv_unified": "on",
                  "spec_type": "draft-mtp", "spec_n_max": 3, "spec_p_min": 0.75,
                  "chat_template_kwargs": {"preserve_thinking": True,
                                           "enable_thinking": True}})
        argv = catalog.build_argv(v, "qwen.gguf", "qwen3.8")
        self.assertPairsPresent(argv, [
            ("--spec-type", "draft-mtp"), ("--spec-draft-n-max", "3"),
            ("--spec-draft-p-min", "0.75"), ("--temp", "0.6"),
            ("--presence-penalty", "0.0"),
            ("--chat-template-kwargs",
             '{"preserve_thinking":true,"enable_thinking":true}'),
        ])
        self.assertIn("--kv-unified", argv)
        self.assertNotIn("--spec-draft-model", argv)


class TestSpecErrorMessagesAreAscii(unittest.TestCase):
    """parse_value's messages are guarded in TestParseValue. spec_error's are the
    other user-facing strings this module produces, and they reach print() the same
    way. A non-ASCII character here crashes the launcher on this cp1252 console."""

    def values(self, **over):
        v = catalog.catalog_defaults()
        v.update(over)
        return v

    def test_missing_draft_model_message_is_ascii(self):
        err = catalog.spec_error(self.values(spec_type="draft-dflash"))
        self.assertIsNotNone(err)
        err.encode("cp1252")

    def test_mtp_with_draft_model_message_is_ascii(self):
        err = catalog.spec_error(
            self.values(spec_type="draft-mtp", draft_model="d.gguf"))
        self.assertIsNotNone(err)
        err.encode("cp1252")


class TestMultiValueSpecType(unittest.TestCase):
    """--spec-type takes a comma-separated LIST. Verified against build 10453:
    `--spec-type ngram-mod,ngram-cache` parses (it fails only on the model),
    while `--spec-type not-a-real-type` is rejected at argument-parse time with
    "unknown speculative type". So the pair must reach the binary as ONE token."""

    def values(self, spec_type):
        v = catalog.catalog_defaults()
        v["spec_type"] = spec_type
        return v

    def test_comma_separated_types_emit_as_one_token(self):
        argv = catalog.build_argv(self.values("ngram-mod,ngram-cache"), "m.gguf", "a")
        self.assertEqual(argv[argv.index("--spec-type") + 1], "ngram-mod,ngram-cache")

    def test_multi_value_gating_needs_no_draft_model(self):
        v = self.values("ngram-mod,ngram-cache")
        self.assertIsNone(catalog.spec_error(v))
        self.assertNotIn("--spec-draft-model", catalog.build_argv(v, "m.gguf", "a"))

    def test_a_draft_type_mixed_into_the_list_still_requires_a_model(self):
        """The list form must not be a hole in the gating."""
        err = catalog.spec_error(self.values("ngram-mod,draft-dflash"))
        self.assertIsNotNone(err)
        self.assertIn("draft model", err)


if __name__ == "__main__":
    unittest.main()
