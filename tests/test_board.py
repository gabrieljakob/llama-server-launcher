import unittest

from launcher import board, catalog


class TestRenderGroup(unittest.TestCase):
    def values(self, **over):
        v = catalog.catalog_defaults()
        v.update(over)
        return v

    def group(self, key):
        return next(g for g in catalog.GROUPS if g.key == key)

    def test_single_setting_group_shows_its_value(self):
        text = board.render_group(self.group("context"), self.values(context=32768))
        self.assertIn("32768", text)

    def test_multi_setting_group_labels_each_value(self):
        text = board.render_group(self.group("sampling"), self.values())
        for token in ("temp 0.6", "top-k 20", "top-p 0.95"):
            self.assertIn(token, text)

    def test_toggles_render_on_and_off(self):
        text = board.render_group(self.group("toggles"),
                                  self.values(jinja=True, metrics=False))
        self.assertIn("jinja on", text)
        self.assertIn("metrics off", text)

    def test_unset_tri_is_not_shown(self):
        text = board.render_group(self.group("toggles"), self.values(kv_unified=None))
        self.assertNotIn("kv-unified", text)

    def test_spec_none_renders_as_none(self):
        text = board.render_group(self.group("spec"), self.values(spec_type="none"))
        self.assertIn("none", text)

    def test_mtp_is_labelled_built_in(self):
        text = board.render_group(self.group("spec"), self.values(spec_type="draft-mtp"))
        self.assertIn("draft-mtp", text)
        self.assertIn("built-in", text)

    def test_empty_template_renders_as_none(self):
        text = board.render_group(self.group("template"), self.values())
        self.assertIn("(none)", text)

    def test_template_renders_key_equals_value(self):
        text = board.render_group(
            self.group("template"),
            self.values(chat_template_kwargs={"preserve_thinking": True}))
        self.assertIn("preserve_thinking=true", text)


class TestRenderBoard(unittest.TestCase):
    def test_rows_are_numbered_one_to_ten(self):
        text = board.render_board(catalog.catalog_defaults(), set(), "hdr")
        for n in range(1, 11):
            self.assertIn(f"{n:>3}  ", text)

    def test_dirty_rows_are_starred(self):
        text = board.render_board(catalog.catalog_defaults(), {"batching"}, "hdr")
        starred = [l for l in text.splitlines() if l.startswith("*")]
        self.assertEqual(len(starred), 1)
        self.assertIn("batching", starred[0])


class TestRenderMenu(unittest.TestCase):
    CONFIGS = [{"name": "qwen3.6", "model": "Qwen3.6/q.gguf"},
               {"name": "gemma4", "model": "unsloth/g.gguf"}]

    def test_lists_every_config_numbered(self):
        text = board.render_menu(self.CONFIGS, missing=set())
        self.assertIn("1  qwen3.6", text)
        self.assertIn("2  gemma4", text)

    def test_missing_models_are_marked(self):
        text = board.render_menu(self.CONFIGS, missing={"gemma4"})
        line = [l for l in text.splitlines() if "gemma4" in l][0]
        self.assertIn("!missing", line)


if __name__ == "__main__":
    unittest.main()
