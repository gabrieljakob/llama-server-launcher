"""draft-mtp takes an OPTIONAL draft model.

The launcher used to treat draft-mtp exactly like the ngram-* family: no draft
GGUF, ever. That is only true of the models whose multi-token-prediction head is
built into their own weights. For every other MTP setup the draft model is
required, and the launcher made it unreachable - the board hid the row,
active_keys dropped the key, and edit_group deleted a hand-edited value.

So draft-mtp is neither of the two existing tiers. These tests pin the third:
the row is offered, the flag is emitted when set, and nothing demands or
destroys it.
"""

import unittest

from launcher import board, catalog


def values(**over):
    v = catalog.catalog_defaults()
    v.update(over)
    return v


def group(key):
    return next(g for g in catalog.GROUPS if g.key == key)


class TestMtpAcceptsADraftModel(unittest.TestCase):
    def test_draft_model_row_is_offered_for_mtp(self):
        """The row has to be in editable_keys or there is no way to type a path,
        and in active_keys or the value could never reach the command line."""
        v = values(spec_type="draft-mtp")
        self.assertIn("draft_model", catalog.active_keys(v))
        self.assertIn("draft_model", catalog.editable_keys(v))

    def test_draft_ngl_row_is_offered_for_mtp(self):
        """--spec-draft-ngl is only meaningful alongside a draft GGUF, so it
        travels with the draft model row rather than being dropped separately."""
        v = values(spec_type="draft-mtp")
        self.assertIn("spec_ngl", catalog.active_keys(v))

    def test_mtp_emits_the_draft_model_flag_when_one_is_set(self):
        """The whole point. build_argv only emits this flag when the key is in
        active_keys AND a draft path is passed, so dropping the key silently
        deleted the flag from a config that clearly asked for it."""
        v = values(spec_type="draft-mtp", draft_model="d.gguf", spec_ngl="99")
        argv = catalog.build_argv(v, "m.gguf", "a", draft_path="D:/d.gguf")
        self.assertIn("--spec-draft-model", argv)
        self.assertEqual(argv[argv.index("--spec-draft-model") + 1], "D:/d.gguf")
        self.assertIn("--spec-draft-ngl", argv)

    def test_mtp_without_a_draft_model_is_still_allowed(self):
        """Optional, not required: a model carrying its own head must still
        launch with nothing on the draft row, and must not emit the flag."""
        v = values(spec_type="draft-mtp")
        self.assertIsNone(catalog.spec_error(v))
        argv = catalog.build_argv(v, "m.gguf", "a")
        self.assertNotIn("--spec-draft-model", argv)
        self.assertIn("--spec-type", argv)

    def test_mtp_with_a_draft_model_is_accepted(self):
        v = values(spec_type="draft-mtp", draft_model="d.gguf")
        self.assertIsNone(catalog.spec_error(v))


class TestMtpIsNotBuiltIn(unittest.TestCase):
    def test_spec_carries_own_head_is_false_for_mtp(self):
        """draft-mtp cannot answer this question for the whole family - whether
        the head is in the weights is a property of the model, not the type."""
        self.assertFalse(catalog.spec_carries_own_head(values(spec_type="draft-mtp")))

    def test_ngram_types_still_carry_their_own_head(self):
        """The tier that genuinely never takes a draft GGUF is unchanged. Without
        this, deleting the whole distinction would still pass the file."""
        for spec_type in ("ngram-mod", "ngram-simple", "ngram-cache",
                          "ngram-map-k", "ngram-map-k4v"):
            with self.subTest(spec_type=spec_type):
                v = values(spec_type=spec_type)
                self.assertTrue(catalog.spec_carries_own_head(v))
                self.assertNotIn("draft_model", catalog.active_keys(v))

    def test_the_board_shows_the_draft_model_rather_than_built_in(self):
        text = board.render_group(group("spec"), values(
            spec_type="draft-mtp", draft_model="d/MTP-Draft-Q8_0.gguf",
            spec_ngl="99"))
        self.assertIn("MTP-Draft-Q8_0.gguf", text)
        self.assertIn("draft ngl 99", text)
        self.assertNotIn("built-in", text)

    def test_the_board_does_not_claim_built_in_for_a_bare_mtp_row(self):
        """Even with no draft model set, the launcher cannot know the head is in
        the weights, so it must not assert it."""
        text = board.render_group(group("spec"), values(spec_type="draft-mtp"))
        self.assertIn("draft-mtp", text)
        self.assertNotIn("built-in", text)


class TestMtpDraftModelSurvives(unittest.TestCase):
    def scripted(self, answers):
        it = iter(answers)

        def ask(_prompt, **_kw):
            return next(it, "")
        return ask

    def test_switching_to_mtp_keeps_the_draft_model(self):
        """edit_group used to delete it and announce 'draft-mtp carries its own'.
        That destroyed a value the user had entered on purpose, and [s] made the
        loss permanent."""
        said = []
        v = values(spec_type="draft-dflash", draft_model="d.gguf")
        out = board.edit_group(group("spec"), v,
                               self.scripted(["draft-mtp", "", "", "3", "0", "0.75"]),
                               said.append)
        self.assertEqual(out["spec_type"], "draft-mtp")
        self.assertEqual(out["draft_model"], "d.gguf")
        self.assertNotIn("cleared the draft model", " ".join(said))

    def test_switching_to_an_ngram_type_still_clears_it(self):
        """The ngram-* family really does hide the row, so a stale value there is
        still unreachable and still has to be cleared."""
        said = []
        v = values(spec_type="draft-dflash", draft_model="d.gguf")
        out = board.edit_group(group("spec"), v,
                               self.scripted(["ngram-mod", "3", "0", "0.75"]),
                               said.append)
        self.assertEqual(out["spec_type"], "ngram-mod")
        self.assertIsNone(out["draft_model"])
        self.assertIn("cleared the draft model", " ".join(said))


if __name__ == "__main__":
    unittest.main()
