import unittest
from launcher import catalog


class TestCatalogShape(unittest.TestCase):
    def test_groups_are_in_board_order(self):
        labels = [g.label for g in catalog.GROUPS]
        self.assertEqual(labels, [
            "context", "gpu layers", "host:port", "sampling", "penalties",
            "reasoning", "toggles", "kv cache", "batching", "speculative",
            "template", "extra args",
        ])

    def test_the_reasoning_row_holds_every_reasoning_lever(self):
        """All four --reasoning* flags on one row, and none of them left behind
        on toggles. They are one concept, and the toggles row was already the
        widest on the board before it had to carry a budget as well."""
        by_group = {g.key: [s.key for s in g.settings] for g in catalog.GROUPS}
        self.assertEqual(by_group["reasoning"],
                         ["reasoning", "reasoning_effort", "reasoning_preserve",
                          "reasoning_budget"])
        for key in by_group["reasoning"]:
            self.assertNotIn(key, by_group["toggles"])

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

    def test_reasoning_effort_accepts_the_documented_levels(self):
        """Verified against build 10453: default/minimal/low/medium/high/xhigh/max
        all parse at the command line. The value is handed to the chat template,
        which is what actually decides whether a level does anything."""
        for level in catalog.REASONING_EFFORTS:
            with self.subTest(level=level):
                self.assertEqual(self.parse("reasoning_effort", level), (True, level))

    def test_reasoning_effort_rejects_an_unknown_level(self):
        ok, err = self.parse("reasoning_effort", "extreme")
        self.assertFalse(ok)
        self.assertIn("xhigh", err)

    def test_float_rejects_nan_and_infinity(self):
        """nan defeats every bound - nan < lo and nan > hi are BOTH False - so
        it reached the config file, where json.dump writes a bare NaN that is
        not valid JSON and no strict parser will read back."""
        for key, text in [("top_p", "nan"), ("min_p", "NaN"), ("temp", "inf"),
                          ("spec_p_min", "-inf"), ("temp", "1e999")]:
            with self.subTest(key=key, text=text):
                ok, _ = self.parse(key, text)
                self.assertFalse(ok, f"{key}={text} must be rejected")

    def test_extra_args_keep_windows_backslashes(self):
        """POSIX shlex ate them: a --lora path became 'D:LLM' plus
        'Modelsadaptersx.gguf', silently, on the way to a real server."""
        ok, args = catalog.split_extra('--lora "D:\\LLM Models\\adapters\\x.gguf"')
        self.assertTrue(ok)
        self.assertEqual(args, ["--lora", "D:\\LLM Models\\adapters\\x.gguf"])

    def test_extra_args_split_unquoted_input_on_spaces_only(self):
        ok, args = catalog.split_extra("--chat-template-file D:\\t\\qwen.jinja")
        self.assertTrue(ok)
        self.assertEqual(args, ["--chat-template-file", "D:\\t\\qwen.jinja"])

    def test_extra_args_report_an_unbalanced_quote(self):
        ok, err = catalog.split_extra('--api-key "sk-abc')
        self.assertFalse(ok)
        self.assertIn("unbalanced", err)
        self.assertFalse(self.parse("extra", '--api-key "sk-abc')[0])

    def test_a_server_default_setting_can_be_set_and_unset(self):
        """Settings whose catalog default is None are ones we simply do not pass.
        They must be resettable, or a value set once could never be cleared."""
        self.assertEqual(self.parse("repeat_penalty", "1.1"), (True, 1.1))
        self.assertEqual(self.parse("repeat_penalty", "-"), (True, None))
        self.assertEqual(self.parse("repeat_last_n", "-"), (True, None))
        self.assertEqual(self.parse("frequency_penalty", "-"), (True, None))

    def test_dash_is_not_a_magic_value_for_settings_that_have_a_default(self):
        """temp has a real catalog default, so "-" there is just bad input."""
        ok, err = self.parse("temp", "-")
        self.assertFalse(ok)
        self.assertIn("number", err)

    def test_choice_rejects_unknown_and_lists_options(self):
        ok, err = self.parse("cache_type_k", "q3_0")
        self.assertFalse(ok)
        self.assertIn("q8_0", err)

    def test_gpu_layers_accepts_keywords_and_ints(self):
        self.assertEqual(self.parse("gpu_layers", "auto"), (True, "auto"))
        self.assertEqual(self.parse("gpu_layers", "all"), (True, "all"))
        self.assertEqual(self.parse("gpu_layers", "99"), (True, "99"))
        self.assertFalse(self.parse("gpu_layers", "most")[0])

    def test_gpu_layers_refuses_digits_the_binary_cannot_read(self):
        """isdigit() is not the guard here, and isdecimal() is not either.

        This setting is STORED AS TEXT and emit() sends the text - there is no
        int() in the path to normalise it, unlike the int type. So a pasted
        superscript two, an Arabic-Indic three or a fullwidth 99 - all isdigit,
        the last two isdecimal as well - used to be accepted, written to the
        config file and handed to llama-server verbatim, which answers
            error while handling argument "-ngl": invalid stoi argument
        and then EXITS 0. wait_ready reports "exited with code 0 before the port
        opened" and names nothing at all. Both -ngl rows go through this branch,
        so both are checked.

        The characters are built with chr() rather than written out: every
        literal in this repo stays ASCII, because the console is cp1252 and a
        non-ASCII character reaching print() kills the launcher."""
        superscript_two, arabic_three = chr(0xB2), chr(0x663)
        fullwidth_nine = chr(0xFF19)
        for key in ("gpu_layers", "spec_ngl"):
            for text in (superscript_two, arabic_three,
                         fullwidth_nine * 2, "9" + arabic_three):
                with self.subTest(key=key, text=text):
                    ok, err = self.parse(key, text)
                    self.assertFalse(ok, f"{text!r} must not be accepted")
                    self.assertTrue(err.isascii(), "message must stay ASCII")

    def test_the_int_type_normalises_such_digits_instead(self):
        """The same characters on an int setting are NOT a defect: parse_value
        returns the int, and emit() writes str(int), which is ASCII. Asserted so
        that the gpu_layers guard is not copied onto rows that do not need it."""
        ok, value = self.parse("context", chr(0x663))
        self.assertTrue(ok)
        self.assertEqual(value, 3)
        setting = catalog.settings_by_key()["context"]
        self.assertEqual(catalog.emit(setting, value), ["-c", "3"])

    def test_tri_accepts_three_states(self):
        # "-" is the unset token, not blank: blank now means "keep the current
        # value" for every type, so that pressing Enter through the toggles row
        # cannot erase a saved setting.
        self.assertEqual(self.parse("kv_unified", "-"), (True, None))
        self.assertEqual(self.parse("kv_unified", "on"), (True, "on"))
        self.assertEqual(self.parse("kv_unified", "off"), (True, "off"))

    def test_bool_accepts_yes_no(self):
        self.assertEqual(self.parse("jinja", "y"), (True, True))
        self.assertEqual(self.parse("jinja", "n"), (True, False))

    def test_reasoning_budget_accepts_the_three_documented_shapes(self):
        """-1 unrestricted, 0 ends thinking immediately, N>0 is a token budget.
        '-' puts the row back to unset, where we pass no flag at all."""
        self.assertEqual(self.parse("reasoning_budget", "-1"), (True, -1))
        self.assertEqual(self.parse("reasoning_budget", "0"), (True, 0))
        self.assertEqual(self.parse("reasoning_budget", "512"), (True, 512))
        self.assertEqual(self.parse("reasoning_budget", "-"), (True, None))

    def test_reasoning_budget_rejects_below_unrestricted(self):
        """-1 is the smallest thing the flag means. Build 10453 takes -2 without
        a word, so nothing downstream would tell the user their budget was
        nonsense - it has to be refused where the row can still be fixed."""
        ok, err = self.parse("reasoning_budget", "-2")
        self.assertFalse(ok)
        self.assertEqual(err, "must be at least -1")
        err.encode("cp1252")

    def test_spec_type_accepts_comma_separated_list(self):
        self.assertEqual(self.parse("spec_type", "draft-mtp"), (True, "draft-mtp"))
        ok, _ = self.parse("spec_type", "ngram-mod,ngram-cache")
        self.assertTrue(ok)

    def test_spec_type_rejects_unknown_member(self):
        ok, err = self.parse("spec_type", "draft-mtp,nonsense")
        self.assertFalse(ok)
        self.assertIn("nonsense", err)

    def test_a_near_miss_typo_is_refused_at_the_prompt_and_names_itself(self):
        """This is where a typo is SUPPOSED to be caught, and it already is - so
        the only way 'ngram-modd' reaches the board is a hand-edited config, and
        the row must survive being visited with one on it. Locked in here
        because the repair path in board.edit_group depends on it: nothing
        typed at that prompt can put an unknown type into the values."""
        for typo in ("ngram-modd", "draft-mtpp", "ngramm-mod", "NGRAM-MOD",
                     "ngram-mod,ngram-cach"):
            with self.subTest(typo=typo):
                ok, err = self.parse("spec_type", typo)
                self.assertFalse(ok, f"{typo!r} must not be accepted")
                self.assertIn("unknown spec type", err)
                self.assertTrue(err.isascii())

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

    def test_raw_is_split_with_windows_rules(self):
        self.assertEqual(self.emit("extra", '--props --alias "my model"'),
                         ["--props", "--alias", "my model"])

    def test_reasoning_budget_emits_flag_and_value(self):
        self.assertEqual(self.emit("reasoning_budget", -1),
                         ["--reasoning-budget", "-1"])
        self.assertEqual(self.emit("reasoning_budget", 0),
                         ["--reasoning-budget", "0"])

    def test_an_unset_server_default_emits_nothing(self):
        """Settings with None default are not passed; they let llama-server use
        its own defaults."""
        self.assertEqual(self.emit("presence_penalty", None), [])
        self.assertEqual(self.emit("repeat_penalty", None), [])
        self.assertEqual(self.emit("repeat_last_n", None), [])
        self.assertEqual(self.emit("reasoning_budget", None), [])


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

    def test_bare_mtp_emits_spec_type_and_the_shared_knobs(self):
        """No draft path passed, so no --spec-draft-model: the head-in-the-
        weights case. The shared knobs travel with every active spec type."""
        v = self.values(spec_type="draft-mtp", spec_n_max=3, spec_p_min=0.75)
        argv = catalog.build_argv(v, "m.gguf", "a")
        self.assertIn("--spec-type", argv)
        self.assertEqual(argv[argv.index("--spec-type") + 1], "draft-mtp")
        self.assertNotIn("--spec-draft-model", argv)
        self.assertIn("--spec-draft-n-max", argv)
        self.assertIn("--spec-draft-p-min", argv)

    def test_mtp_never_demands_a_draft_model(self):
        """It is the optional tier: valid with one and valid without. Only the
        DRAFT_MODEL_TYPES four are refused for going bare."""
        self.assertIsNone(catalog.spec_error(self.values(spec_type="draft-mtp")))
        self.assertIsNone(catalog.spec_error(
            self.values(spec_type="draft-mtp", draft_model="d.gguf")))

    def test_the_flag_needs_the_resolved_path_not_just_the_setting(self):
        """build_argv emits --spec-draft-model from its draft_path argument, not
        from values: the caller resolves the path against the model root first.
        A set draft_model with no resolved path emits nothing, for every type."""
        for spec_type in ("draft-mtp", "draft-dflash"):
            with self.subTest(spec_type=spec_type):
                v = self.values(spec_type=spec_type, draft_model="d.gguf")
                argv = catalog.build_argv(v, "m.gguf", "a")
                self.assertNotIn("--spec-draft-model", argv)
                argv = catalog.build_argv(v, "m.gguf", "a", draft_path="D:/d.gguf")
                self.assertIn("--spec-draft-model", argv)

    def test_ngram_needs_no_draft_model(self):
        v = self.values(spec_type="ngram-mod")
        self.assertIsNone(catalog.spec_error(v))
        argv = catalog.build_argv(v, "m.gguf", "a")
        self.assertNotIn("--spec-draft-model", argv)
        self.assertIn("--spec-type", argv)

    def test_every_draft_model_type_requires_a_draft_model(self):
        """The final review found draft-simple and draft-eagle3 appeared in NO
        test: removing either from DRAFT_MODEL_TYPES let a draft-less config
        launch and the suite stayed green. Cover all four by name."""
        for spec_type in ("draft-simple", "draft-eagle3", "draft-dflash",
                          "draft-dspark"):
            with self.subTest(spec_type=spec_type):
                err = catalog.spec_error(self.values(spec_type=spec_type))
                self.assertIsNotNone(err, f"{spec_type} must demand a draft model")
                self.assertIn("draft model", err)
                ok = self.values(spec_type=spec_type, draft_model="d.gguf")
                self.assertIsNone(catalog.spec_error(ok))

    def test_none_drops_spec_type_from_emission_but_not_from_editing(self):
        """The two key sets differ by exactly this one key. Without it, row 10
        would be unreachable: 'none' is the default, so nothing could ever
        switch it on."""
        v = self.values(spec_type="none")
        self.assertNotIn("spec_type", catalog.active_keys(v))
        self.assertIn("spec_type", catalog.editable_keys(v))

    def test_editable_and_active_agree_once_spec_is_on(self):
        v = self.values(spec_type="draft-mtp")
        self.assertEqual(catalog.editable_keys(v), catalog.active_keys(v))


class TestWrongTypesNeverRaise(unittest.TestCase):
    """A hand-edited config can hold any JSON type on any key. build_argv is
    reached from [Enter] and from [c], and neither may traceback - the board is
    the only place the value can be repaired, so the tool has to survive long
    enough to get there. The bad value must also not be smuggled into argv."""

    def values(self, **over):
        v = catalog.catalog_defaults()
        v.update(over)
        return v

    def argv(self, **over):
        return catalog.build_argv(self.values(**over), "m.gguf", "a")

    def test_a_number_in_the_extra_args_row_emits_nothing(self):
        argv = self.argv(extra=5)
        self.assertNotIn("5", argv)
        self.assertNotIn(5, argv)

    def test_an_unbalanced_quote_in_extra_args_emits_nothing(self):
        argv = self.argv(extra='--api-key "sk-abc')
        self.assertNotIn("--api-key", argv)

    def test_a_non_object_chat_template_kwargs_emits_nothing(self):
        """json.dumps would serialise a bare string quite happily and hand
        llama-server a --chat-template-kwargs it refuses to parse."""
        for bad in ("x", [1, 2], 7):
            with self.subTest(bad=bad):
                self.assertNotIn("--chat-template-kwargs", self.argv(
                    chat_template_kwargs=bad))

    def test_a_valid_chat_template_kwargs_is_still_emitted(self):
        """Otherwise 'always drop it' would pass the test above."""
        self.assertIn("--chat-template-kwargs",
                      self.argv(chat_template_kwargs={"preserve_thinking": True}))

    def test_a_number_as_the_spec_type_does_not_raise(self):
        argv = self.argv(spec_type=3)
        self.assertIn("--model", argv)
        self.assertEqual(catalog.spec_types_of(self.values(spec_type=3)), ["3"])

    def test_a_wrong_typed_spec_type_is_refused_by_name_at_launch(self):
        err = catalog.spec_error(self.values(spec_type=3))
        self.assertIsNotNone(err)
        self.assertIn("3", err)
        err.encode("cp1252")

    def test_every_setting_survives_a_wrong_typed_value(self):
        """Swept rather than enumerated: a new row must not reopen this hole."""
        for setting in (s for g in catalog.GROUPS for s in g.settings):
            for bad in (5, "x", [1], {"a": 1}, True):
                with self.subTest(key=setting.key, bad=bad):
                    out = catalog.build_argv(self.values(**{setting.key: bad}),
                                             "m.gguf", "a")
                    self.assertTrue(all(isinstance(x, str) for x in out),
                                    "argv must be strings all the way down")


class TestSpecTypeNoneIsNotAListMember(unittest.TestCase):
    """--spec-type takes a comma-separated list, and 'none' means no
    speculative decoding AT ALL. "none,draft-mtp" is a contradiction that the
    launcher used to emit as one token for llama-server to choke on."""

    def values(self, spec_type):
        v = catalog.catalog_defaults()
        v["spec_type"] = spec_type
        return v

    def test_none_mixed_with_a_real_type_is_rejected(self):
        for text in ("none,draft-mtp", "draft-mtp,none", "none,ngram-mod",
                     "none,none,draft-dflash"):
            with self.subTest(text=text):
                err = catalog.spec_error(self.values(text))
                self.assertIsNotNone(err, f"{text} must be refused")
                self.assertIn("none", err)
                err.encode("cp1252")

    def test_none_on_its_own_is_still_fine(self):
        """Otherwise 'reject anything mentioning none' would pass the test
        above and no config could ever launch without speculative decoding."""
        self.assertIsNone(catalog.spec_error(self.values("none")))

    def test_a_list_without_none_is_still_fine(self):
        self.assertIsNone(catalog.spec_error(self.values("ngram-mod,ngram-cache")))


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
                  "reasoning": "on", "reasoning_effort": "xhigh", "spec_type": "draft-mtp",
                  "spec_n_max": 3, "spec_p_min": 0.75,
                  "chat_template_kwargs": {"preserve_thinking": True}})
        argv = catalog.build_argv(v, "qwen.gguf", "qwen3.8")
        self.assertPairsPresent(argv, [
            ("--spec-type", "draft-mtp"), ("--spec-draft-n-max", "3"),
            ("--spec-draft-p-min", "0.75"), ("--temp", "0.6"),
            ("--presence-penalty", "0.0"), ("--reasoning", "on"),
            ("--reasoning-effort", "xhigh"),
            ("--chat-template-kwargs", '{"preserve_thinking":true}'),
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

    def test_all_none_list_message_is_ascii(self):
        err = catalog.spec_error(self.values(spec_type="none,none"))
        self.assertIsNotNone(err)
        err.encode("cp1252")

    def test_wrong_typed_draft_model_message_is_ascii(self):
        err = catalog.spec_error(self.values(draft_model=7))
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


class TestAllNoneSpecList(unittest.TestCase):
    """Typing "none,none" at the speculative row and pressing Enter used to kill
    the launcher: parse_value accepted it, then spec_error took others[0] of an
    empty list. Rejected at edit time now, and spec_error stays total for the
    hand-edited config that never passed through parse_value."""

    def values(self, **over):
        v = catalog.catalog_defaults()
        v.update(over)
        return v

    def parse(self, text):
        return catalog.parse_value(catalog.settings_by_key()["spec_type"], text)

    def test_parse_rejects_a_list_that_is_only_none_repeated(self):
        for text in ("none,none", "none,none,none", " none , none "):
            with self.subTest(text=text):
                ok, err = self.parse(text)
                self.assertFalse(ok, f"{text!r} must be refused")
                self.assertIn("none", err)
                err.encode("cp1252")

    def test_parse_rejects_none_mixed_with_a_real_type(self):
        for text, other in (("none,draft-mtp", "draft-mtp"),
                            ("ngram-mod,none", "ngram-mod")):
            with self.subTest(text=text):
                ok, err = self.parse(text)
                self.assertFalse(ok, f"{text!r} must be refused")
                self.assertIn(other, err)
                err.encode("cp1252")

    def test_parse_still_accepts_a_single_none_and_a_plain_list(self):
        """Otherwise 'reject anything containing none' would pass the two tests
        above and no config could switch speculative decoding off again."""
        self.assertEqual(self.parse("none"), (True, "none"))
        self.assertEqual(self.parse(""), (True, "none"))
        self.assertEqual(self.parse("ngram-mod,ngram-cache"),
                         (True, "ngram-mod,ngram-cache"))

    def test_spec_error_reports_an_all_none_list_instead_of_raising(self):
        for text in ("none,none", "none,none,none"):
            with self.subTest(text=text):
                err = catalog.spec_error(self.values(spec_type=text))
                self.assertIsNotNone(err, f"{text!r} must be refused")
                self.assertIn("none", err)
                err.encode("cp1252")

    def test_an_all_none_list_is_speculative_off(self):
        """It means 'off', so it must not gate the spec keys ON - that emitted
        --spec-* flags for a config that asked for no speculative decoding."""
        v = self.values(spec_type="none,none")
        for key in ("spec_type", "draft_model", "spec_ngl", "spec_n_max",
                    "spec_n_min", "spec_p_min"):
            self.assertNotIn(key, catalog.active_keys(v))
        argv = catalog.build_argv(v, "m.gguf", "a")
        self.assertFalse([x for x in argv if x.startswith("--spec")],
                         f"no --spec flag may survive: {argv}")


class TestSpecTypeIsEmittedNormalised(unittest.TestCase):
    """Verified against build 10453: a hand-edited "ngram-mod, ngram-cache" was
    emitted verbatim and the binary answered
        unknown speculative type:  ngram-cache
    - the space is part of the type name by the time it splits the token. What
    spec_error validated (the stripped members) must be what is sent."""

    def values(self, spec_type):
        v = catalog.catalog_defaults()
        v["spec_type"] = spec_type
        return v

    def test_spaces_around_members_are_stripped_before_emission(self):
        for text in ("ngram-mod, ngram-cache", " ngram-mod ,ngram-cache",
                     "ngram-mod ,  ngram-cache "):
            with self.subTest(text=text):
                v = self.values(text)
                self.assertIsNone(catalog.spec_error(v))
                argv = catalog.build_argv(v, "m.gguf", "a")
                self.assertEqual(argv[argv.index("--spec-type") + 1],
                                 "ngram-mod,ngram-cache")

    def test_a_single_type_with_stray_spaces_is_stripped_too(self):
        v = self.values(" draft-mtp ")
        argv = catalog.build_argv(v, "m.gguf", "a")
        self.assertEqual(argv[argv.index("--spec-type") + 1], "draft-mtp")

    def test_emit_normalises_on_its_own(self):
        setting = catalog.settings_by_key()["spec_type"]
        self.assertEqual(catalog.emit(setting, "ngram-mod, ngram-cache"),
                         ["--spec-type", "ngram-mod,ngram-cache"])


class TestWrongTypedDraftModel(unittest.TestCase):
    """Both launch and [c] do config.resolve_path(values["draft_model"], root)
    whenever the value is truthy, and os.path.isabs(7) raises TypeError - a
    traceback out of the board, from a hand-edited config, on Enter. Both call
    spec_error first, so refusing here is what turns it into a message."""

    BAD = (7, 1.5, ["d.gguf"], {"path": "d.gguf"}, True)

    def values(self, **over):
        v = catalog.catalog_defaults()
        v.update(over)
        return v

    def test_a_non_string_draft_model_is_refused_whatever_the_spec_type(self):
        # Every spec type, because the caller reads draft_model unconditionally:
        # a leftover number on a "none" config crashed it just as hard.
        for spec_type in ("none", "draft-mtp", "ngram-mod", "draft-dflash"):
            for bad in self.BAD:
                with self.subTest(spec_type=spec_type, bad=bad):
                    err = catalog.spec_error(
                        self.values(spec_type=spec_type, draft_model=bad))
                    self.assertIsNotNone(
                        err, f"draft_model={bad!r} must be refused")
                    self.assertIn("draft model", err)
                    err.encode("cp1252")

    def test_a_string_draft_model_and_an_unset_one_are_still_fine(self):
        """Otherwise 'always refuse' passes the test above and no draft type
        could launch at all."""
        self.assertIsNone(catalog.spec_error(
            self.values(spec_type="draft-dflash", draft_model="d/DFlash.gguf")))
        self.assertIsNone(catalog.spec_error(self.values(spec_type="ngram-mod")))


class TestBlankDraftModel(unittest.TestCase):
    """'   ' is truthy in Python, so a draft-model row holding nothing but
    spaces satisfied every `if values.get("draft_model")` in the launcher.
    spec_error called it a valid path and let the launch through; resolve_path
    then joined it onto the model root and the only thing the user was told was
    "draft model is gone", naming a path made of spaces. Blank after strip is
    absent, and absent is what the message for it already says."""

    def values(self, **over):
        v = catalog.catalog_defaults()
        v.update(over)
        return v

    BLANK = ("   ", "", "\t", " \n ")

    def test_a_whitespace_only_draft_model_is_not_a_draft_model(self):
        for blank in self.BLANK:
            with self.subTest(blank=blank):
                err = catalog.spec_error(
                    self.values(spec_type="draft-dflash", draft_model=blank))
                self.assertIsNotNone(err, f"{blank!r} must not count as a path")
                self.assertIn("needs a draft model", err)

    def test_a_real_path_and_a_padded_one_are_still_accepted(self):
        """Otherwise 'always refuse' passes the test above. A path with spaces
        AROUND a real name is a real path - this machine's models live under
        D:\\LLM Models - so only blank-after-strip is refused."""
        for good in ("d/DFlash.gguf", "  d/DFlash.gguf  ", "D:\\LLM Models\\d.gguf"):
            with self.subTest(good=good):
                self.assertIsNone(catalog.spec_error(
                    self.values(spec_type="draft-dflash", draft_model=good)))

    def test_a_blank_draft_model_is_no_error_for_a_type_that_needs_none(self):
        self.assertIsNone(catalog.spec_error(
            self.values(spec_type="ngram-mod", draft_model="   ")))


class TestSpecCarriesOwnHead(unittest.TestCase):
    """The predicate behind the draft-model clearing on row 10. It must be true
    only for a type the catalog RECOGNISES and that genuinely runs without a
    separate draft GGUF - never for a typo, which the catalog knows nothing
    about, and never for 'none', which means no speculative decoding at all."""

    def values(self, spec_type):
        v = catalog.catalog_defaults()
        v["spec_type"] = spec_type
        return v

    def test_true_for_the_built_in_types(self):
        for spec_type in ("ngram-simple", "ngram-mod",
                          "ngram-cache", "ngram-mod,ngram-cache"):
            with self.subTest(spec_type=spec_type):
                self.assertTrue(
                    catalog.spec_carries_own_head(self.values(spec_type)))

    def test_false_for_draft_mtp(self):
        """draft-mtp can take a draft model, so the type alone does not say the
        head is built in - that depends on the weights. Saying True here hid the
        draft-model row and dropped the flag for every MTP config."""
        self.assertFalse(catalog.spec_carries_own_head(self.values("draft-mtp")))
        self.assertFalse(
            catalog.spec_carries_own_head(self.values("draft-mtp,ngram-mod")))

    def test_false_for_an_unrecognised_or_typod_type(self):
        for spec_type in ("ngram-modd", "draft-mtpp", "", "3",
                          "ngram-mod,ngram-cach", "  "):
            with self.subTest(spec_type=spec_type):
                self.assertFalse(
                    catalog.spec_carries_own_head(self.values(spec_type)),
                    f"{spec_type!r} is not a type this catalog understands")

    def test_false_for_none_and_for_types_that_want_a_draft_model(self):
        for spec_type in ("none", "none,none", "none,ngram-mod", "draft-dflash",
                          "draft-simple", "ngram-mod,draft-dflash"):
            with self.subTest(spec_type=spec_type):
                self.assertFalse(
                    catalog.spec_carries_own_head(self.values(spec_type)))

    def test_it_is_total_over_hand_edited_types(self):
        for spec_type in (7, 1.5, None, ["ngram-mod"], {"a": 1}, True):
            with self.subTest(spec_type=spec_type):
                catalog.spec_carries_own_head(self.values(spec_type))


class TestExtraArgsCanBeCleared(unittest.TestCase):
    """Blank keeps the current value for every row, so "-" is the only way back
    to an empty one. On this row "-" used to be stored literally and emitted as
    a bare argument, which the binary rejects - the row could never be cleared."""

    def parse(self, text):
        return catalog.parse_value(catalog.settings_by_key()["extra"], text)

    def test_a_dash_clears_the_row(self):
        self.assertEqual(self.parse("-"), (True, ""))

    def test_a_cleared_row_emits_nothing(self):
        ok, value = self.parse("-")
        self.assertTrue(ok)
        setting = catalog.settings_by_key()["extra"]
        self.assertEqual(catalog.emit(setting, value), [])
        v = catalog.catalog_defaults()
        v["extra"] = value
        self.assertNotIn("-", catalog.build_argv(v, "m.gguf", "a"))

    def test_a_cleared_row_still_renders_as_a_string(self):
        """None would have worked for emission and then shown up on the board as
        a wrong-typed value, since the raw renderer only accepts strings."""
        self.assertIsInstance(self.parse("-")[1], str)

    def test_real_extra_args_are_untouched(self):
        self.assertEqual(self.parse("--props"), (True, "--props"))
        self.assertEqual(self.parse('--alias "my model"'),
                         (True, '--alias "my model"'))


class TestStaleDraftModelDoesNotBlockBuiltInTypes(unittest.TestCase):
    """A draft model the active spec type cannot use is not an error: active_keys
    strips it from argv, so the flag cannot reach llama-server. Refusing blocked
    a launch whose command line was already right, and named a row the board
    hides for these very types."""

    def values(self, **over):
        v = catalog.catalog_defaults()
        v.update(over)
        return v

    def test_built_in_types_launch_with_a_stale_draft_model(self):
        for spec_type in ("draft-mtp", "ngram-mod", "ngram-cache",
                          "ngram-mod,ngram-cache"):
            with self.subTest(spec_type=spec_type):
                v = self.values(spec_type=spec_type, draft_model="d/old.gguf")
                self.assertIsNone(catalog.spec_error(v),
                                  f"{spec_type} must launch anyway")
                argv = catalog.build_argv(v, "m.gguf", "a")
                self.assertNotIn("--spec-draft-model", argv)
                self.assertNotIn("d/old.gguf", argv)

    def test_a_draft_type_in_the_list_still_uses_the_draft_model(self):
        """Not refusing must not become 'never emit it': mixed with a type that
        does need a draft GGUF, the model is used and the flag is sent."""
        v = self.values(spec_type="draft-mtp,draft-dflash",
                        draft_model="d/DFlash.gguf")
        self.assertIsNone(catalog.spec_error(v))
        argv = catalog.build_argv(v, "m.gguf", "a", draft_path="D:\\d\\DFlash.gguf")
        self.assertIn("--spec-draft-model", argv)
        self.assertEqual(argv[argv.index("--spec-draft-model") + 1],
                         "D:\\d\\DFlash.gguf")

    def test_a_missing_draft_model_is_still_refused(self):
        err = catalog.spec_error(self.values(spec_type="draft-dflash"))
        self.assertIsNotNone(err)
        self.assertIn("draft model", err)


class TestSpecErrorIsTotal(unittest.TestCase):
    """spec_error gates both [Enter] and [c]. Raising takes down the only screen
    the offending value can be repaired from, so it must return a string or None
    for anything a hand edit can put in the file."""

    def test_no_values_dict_makes_it_raise(self):
        bad_values = [5, 1.5, "none,none", ["draft-mtp"], {"a": 1}, True, None,
                      "", "none", "none,draft-mtp", " , , ", "draft-mtp,",
                      "NONE,none"]
        for spec in bad_values:
            for draft in (None, "", "d.gguf", 7, ["d.gguf"], {"p": 1}, True):
                with self.subTest(spec_type=spec, draft_model=draft):
                    v = catalog.catalog_defaults()
                    v["spec_type"] = spec
                    v["draft_model"] = draft
                    err = catalog.spec_error(v)      # must not raise
                    if err is not None:
                        self.assertIsInstance(err, str)
                        err.encode("cp1252")

    def test_an_empty_values_dict_is_survivable(self):
        self.assertIsNone(catalog.spec_error({}))


if __name__ == "__main__":
    unittest.main()
