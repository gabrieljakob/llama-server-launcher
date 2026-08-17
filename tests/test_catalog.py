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


if __name__ == "__main__":
    unittest.main()
