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

    def test_penalties_row_shows_all_four(self):
        """repeat defaults to 1.0, not 0.0 - it is a multiplier where 1.0 is the
        no-op, unlike presence and frequency where 0.0 is."""
        text = board.render_group(self.group("penalties"), self.values())
        for token in ("presence 0.0", "frequency 0.0",
                      "repeat 1.0", "repeat-last-n 64"):
            self.assertIn(token, text)

    def test_toggles_render_on_and_off(self):
        text = board.render_group(self.group("toggles"),
                                  self.values(jinja=True, metrics=False))
        self.assertIn("jinja on", text)
        self.assertIn("metrics off", text)

    def test_unset_tri_is_not_shown(self):
        text = board.render_group(self.group("toggles"), self.values(kv_unified=None))
        self.assertNotIn("kv-unified", text)

    def test_spec_none_renders_as_exactly_none(self):
        """assertEqual, not assertIn: the generic label formatter would emit
        'spec-type none' for an unhandled case, which contains 'none' and would
        satisfy a substring check while showing the user a different thing."""
        text = board.render_group(self.group("spec"), self.values(spec_type="none"))
        self.assertEqual(text, "none")

    def test_mtp_is_labelled_built_in(self):
        text = board.render_group(self.group("spec"), self.values(spec_type="draft-mtp"))
        self.assertIn("draft-mtp", text)
        self.assertIn("built-in", text)
        self.assertNotIn("draft ngl", text)   # meaningless without a draft model

    def test_ngram_types_are_also_labelled_built_in(self):
        """draft-mtp is not the only draft-model-free type. Testing only it would
        let a regression to `if spec_type == "draft-mtp"` pass, which is exactly
        the hardcoding the active_keys call exists to avoid."""
        for spec_type in ("ngram-mod", "ngram-simple", "ngram-cache"):
            with self.subTest(spec_type=spec_type):
                text = board.render_group(self.group("spec"),
                                          self.values(spec_type=spec_type))
                self.assertIn("built-in", text)

    def test_a_draft_type_shows_its_model_and_draft_ngl(self):
        """spec_ngl is editable, so it must be visible - a setting the user can
        change but cannot see is a trap."""
        text = board.render_group(self.group("spec"), self.values(
            spec_type="draft-dflash", draft_model="d/DFlash-Q8_0.gguf",
            spec_ngl="99"))
        self.assertIn("DFlash-Q8_0.gguf", text)
        self.assertIn("draft ngl 99", text)
        self.assertNotIn("built-in", text)

    def test_parallel_shows_auto_not_the_sentinel(self):
        """-1 is llama-server's 'choose for me'. Row 2 already prints 'auto' for
        the same concept; printing '-1' here leaks the sentinel."""
        text = board.render_group(self.group("batching"), self.values(parallel=-1))
        self.assertIn("-np auto", text)
        self.assertNotIn("-1", text)

    def test_parallel_shows_a_real_value_when_set(self):
        text = board.render_group(self.group("batching"), self.values(parallel=1))
        self.assertIn("-np 1", text)
        self.assertNotIn("auto", text)

    def test_empty_template_renders_as_none(self):
        text = board.render_group(self.group("template"), self.values())
        self.assertIn("(none)", text)

    def test_template_renders_key_equals_value(self):
        text = board.render_group(
            self.group("template"),
            self.values(chat_template_kwargs={"preserve_thinking": True}))
        self.assertIn("preserve_thinking=true", text)


class TestRenderBoard(unittest.TestCase):
    def rows(self, text):
        """The numbered rows, in order, without the header or footer."""
        return [l for l in text.splitlines() if l[1:3].strip().isdigit()]

    def test_rows_are_numbered_in_catalog_order(self):
        """Ordering matters: the number the user types is an index into GROUPS,
        so a reordered board would edit the wrong row. Counted against GROUPS
        rather than a literal, so adding a row does not falsify this test."""
        text = board.render_board(catalog.catalog_defaults(), set(), "hdr")
        rows = self.rows(text)
        self.assertEqual(len(rows), len(catalog.GROUPS))
        for i, (row, group) in enumerate(zip(rows, catalog.GROUPS), 1):
            self.assertIn(f"{i:>2}  ", row)
            self.assertIn(group.label, row)

    def test_the_footer_names_the_real_row_range(self):
        """A hardcoded [1-10] would silently lie once a row is added."""
        text = board.render_board(catalog.catalog_defaults(), set(), "hdr")
        self.assertIn(f"[1-{len(catalog.GROUPS)}] edit", text)

    def test_dirty_rows_are_starred(self):
        text = board.render_board(catalog.catalog_defaults(), {"batching"}, "hdr")
        starred = [l for l in text.splitlines() if l.startswith("*")]
        self.assertEqual(len(starred), 1)
        self.assertIn("batching", starred[0])


class TestRenderMenu(unittest.TestCase):
    CONFIGS = [{"name": "qwen3.6", "model": "Qwen3.6/q.gguf"},
               {"name": "gemma4", "model": "unsloth/g.gguf"}]

    def line_for(self, text, name):
        return [l for l in text.splitlines() if name in l][0]

    def test_lists_every_config_numbered(self):
        text = board.render_menu(self.CONFIGS, missing=set())
        self.assertIn("1  qwen3.6", text)
        self.assertIn("2  gemma4", text)

    def test_missing_models_are_marked_and_others_are_not(self):
        """Asserting only that the missing one IS marked would pass an
        implementation that marks everything."""
        text = board.render_menu(self.CONFIGS, missing={"gemma4"})
        self.assertIn("!missing", self.line_for(text, "gemma4"))
        self.assertNotIn("!missing", self.line_for(text, "qwen3.6"))

    def test_nothing_is_marked_when_nothing_is_missing(self):
        text = board.render_menu(self.CONFIGS, missing=set())
        self.assertNotIn("!missing", text)

    def test_file_sizes_are_shown_when_known(self):
        """Two of these models exceed the card's VRAM, so size is decision-
        relevant on the menu, not decoration."""
        text = board.render_menu(self.CONFIGS, missing=set(),
                                 sizes={"qwen3.6": 20_820_000_000})
        self.assertIn("19.4 GB", self.line_for(text, "qwen3.6"))

    def test_a_config_with_no_known_size_still_renders(self):
        text = board.render_menu(self.CONFIGS, missing=set(),
                                 sizes={"qwen3.6": 20_820_000_000})
        self.assertIn("gemma4", self.line_for(text, "gemma4"))
        self.assertNotIn("GB", self.line_for(text, "gemma4"))


class TestDispatch(unittest.TestCase):
    def test_digits_select_a_row(self):
        self.assertEqual(board.dispatch("7"), "edit:7")
        self.assertEqual(board.dispatch("10"), "edit:10")

    def test_out_of_range_digits_are_unknown(self):
        self.assertEqual(board.dispatch(str(len(catalog.GROUPS) + 1)), "unknown")
        self.assertEqual(board.dispatch("0"), "unknown")

    def test_letters_map_to_actions(self):
        self.assertEqual(board.dispatch("s"), "save")
        self.assertEqual(board.dispatch("c"), "command")
        self.assertEqual(board.dispatch("q"), "quit")

    def test_blank_launches(self):
        self.assertEqual(board.dispatch(""), "launch")

    def test_input_is_case_insensitive_and_trimmed(self):
        self.assertEqual(board.dispatch("  S  "), "save")

    def test_a_unicode_digit_int_cannot_parse_does_not_crash(self):
        """Superscript two satisfies str.isdigit() but int() rejects it, so an
        isdigit() gate crashes the launcher on a pasted character. The
        constraint is that invalid input never raises - unknown is fine."""
        self.assertEqual(board.dispatch("²"), "unknown")

    def test_a_real_unicode_digit_still_selects_a_row(self):
        """Arabic-Indic three is a genuine decimal digit; int() converts it.
        Narrowing to isdecimal() must not reject it."""
        self.assertEqual(board.dispatch("٣"), "edit:3")

    def test_no_input_raises(self):
        """Nothing typed at this prompt may escape as an exception."""
        for key in ["", "  ", "abc", "-1", "0", "11", "999999999999999999999",
                    "1.5", "²", "٣", "!", "  Q  ", "\t\n"]:
            with self.subTest(key=key):
                self.assertIsInstance(board.dispatch(key), str)


class TestEditGroup(unittest.TestCase):
    def group(self, key):
        return next(g for g in catalog.GROUPS if g.key == key)

    def values(self, **over):
        v = catalog.catalog_defaults()
        v.update(over)
        return v

    def scripted(self, answers):
        it = iter(answers)
        return lambda prompt: next(it)

    def test_blank_answer_keeps_the_current_value(self):
        out = board.edit_group(self.group("context"), self.values(context=8192),
                               self.scripted([""]), lambda t: None)
        self.assertEqual(out["context"], 8192)

    def test_valid_answer_is_stored_typed(self):
        out = board.edit_group(self.group("context"), self.values(),
                               self.scripted(["32768"]), lambda t: None)
        self.assertEqual(out["context"], 32768)

    def test_invalid_answer_reprompts_rather_than_raising(self):
        said = []
        out = board.edit_group(self.group("context"), self.values(),
                               self.scripted(["nonsense", "4096"]), said.append)
        self.assertEqual(out["context"], 4096)
        self.assertTrue(any("whole number" in s for s in said))

    def test_editing_a_multi_setting_row_walks_each(self):
        out = board.edit_group(self.group("net"), self.values(),
                               self.scripted(["0.0.0.0", "8082"]), lambda t: None)
        self.assertEqual(out["host"], "0.0.0.0")
        self.assertEqual(out["port"], 8082)

    def test_spec_type_is_always_editable_from_none(self):
        """Regression: row 8 must be reachable. 'none' is the default, and if the
        prompt loop used emission gating it would skip spec_type itself, leaving
        no path from 'none' to any speculative mode."""
        asked = []

        def ask(prompt):
            asked.append(prompt)
            return "draft-mtp" if len(asked) == 1 else ""

        out = board.edit_group(self.group("spec"), self.values(), ask, lambda t: None)
        self.assertTrue(asked, "spec_type was never prompted for")
        self.assertEqual(out["spec_type"], "draft-mtp")

    def test_spec_none_skips_the_remaining_prompts(self):
        """spec_type is asked and answered; the rest of the row is then skipped,
        so a second scripted answer would be left unconsumed."""
        answers = iter(["none", "UNREACHABLE"])
        consumed = []

        def ask(prompt):
            value = next(answers)
            consumed.append(value)
            return value

        out = board.edit_group(self.group("spec"), self.values(), ask, lambda t: None)
        self.assertEqual(consumed, ["none"])
        self.assertEqual(out["spec_type"], "none")

    def test_mtp_skips_the_draft_model_prompt(self):
        out = board.edit_group(self.group("spec"), self.values(),
                               self.scripted(["draft-mtp", "3", "0", "0.75"]),
                               lambda t: None)
        self.assertEqual(out["spec_type"], "draft-mtp")
        self.assertEqual(out["spec_p_min"], 0.75)
        self.assertIsNone(out["draft_model"])

    def test_switching_to_a_built_in_type_clears_a_stale_draft_model(self):
        """Otherwise the user is stranded: editable_keys hides the draft-model
        row for draft-mtp, so they cannot clear it, while spec_error refuses to
        launch and tells them to clear it. The UI must not issue an instruction
        it gives no way to obey."""
        said = []
        out = board.edit_group(
            self.group("spec"),
            self.values(spec_type="draft-dflash", draft_model="d/DFlash.gguf"),
            self.scripted(["draft-mtp", "3", "0", "0.0"]), said.append)
        self.assertEqual(out["spec_type"], "draft-mtp")
        self.assertIsNone(out["draft_model"])
        self.assertIsNone(catalog.spec_error(out), "must now be launchable")
        self.assertTrue(any("cleared the draft model" in s for s in said),
                        "clearing it silently would be its own surprise")

    def test_a_draft_type_keeps_its_draft_model(self):
        """The clearing must be specific to types that carry their own head."""
        out = board.edit_group(
            self.group("spec"),
            self.values(spec_type="draft-dflash", draft_model="d/DFlash.gguf"),
            self.scripted(["draft-dspark", "", "4", "0", "", "0.0"]), lambda t: None)
        self.assertEqual(out["draft_model"], "d/DFlash.gguf")


if __name__ == "__main__":
    unittest.main()
