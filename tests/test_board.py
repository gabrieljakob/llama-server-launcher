import os
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

    def test_penalties_are_unset_by_default_and_shown_as_such(self):
        """No number should appear here until someone picks one. Pre-filling the
        server's own defaults would put values on the board that nobody chose,
        and they are not even uniform - 0.0 disables presence and frequency but
        1.0 is what disables repeat - so a pre-filled row would mislead."""
        text = board.render_group(self.group("penalties"), self.values())
        for token in ("presence -", "frequency -", "repeat -", "repeat-last-n -"):
            self.assertIn(token, text)
        for digit in "0123456789":
            self.assertNotIn(digit, text)

    def test_a_set_penalty_shows_its_value(self):
        text = board.render_group(self.group("penalties"),
                                  self.values(repeat_penalty=1.1))
        self.assertIn("repeat 1.1", text)
        self.assertIn("presence -", text)     # the others stay unset

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

    def test_mtp_is_not_labelled_built_in(self):
        """Whether the prediction head is in the weights is a property of the
        model, not of the type, so the row must not assert it. It used to say
        "(built-in, no draft model)" for every draft-mtp config."""
        text = board.render_group(self.group("spec"), self.values(spec_type="draft-mtp"))
        self.assertIn("draft-mtp", text)
        self.assertNotIn("built-in", text)

    def test_ngram_types_are_labelled_built_in(self):
        """The ngram-* family is the tier that genuinely never takes a draft
        GGUF. Testing more than one would-be member keeps a regression to
        `if spec_type == "ngram-mod"` from passing."""
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

    def test_an_unrecognised_type_is_not_called_built_in(self):
        """A typo is not a claim about the model. active_keys drops draft_model
        for 'ngram-modd' exactly as it does for 'ngram-mod', so the row used to
        print "(built-in, no draft model)" about a string the catalog cannot
        read - and print it while still holding the draft model it was about to
        delete. The retained value is what the row has to show."""
        text = board.render_group(self.group("spec"), self.values(
            spec_type="ngram-modd", draft_model="d/DFlash-Q8_0.gguf"))
        self.assertIn("ngram-modd", text)
        self.assertNotIn("built-in", text)
        self.assertIn("DFlash-Q8_0.gguf", text)

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


class TestBoardRendersAHandEditedConfig(unittest.TestCase):
    """The board is drawn BEFORE anything can be edited, so a value the catalog
    cannot make sense of must still reach the screen. Raising here locks the
    user out of the one screen that could repair the file - the tool cannot be
    used to fix itself. Every case below was a traceback."""

    def values(self, **over):
        v = catalog.catalog_defaults()
        v.update(over)
        return v

    def render(self, **over):
        return board.render_board(self.values(**over), set(), "hdr")

    def test_a_number_in_the_extra_args_row_renders(self):
        text = self.render(extra=5)
        self.assertIn("5", text)
        self.assertIn("!bad", text)

    def test_an_unbalanced_quote_in_extra_args_is_marked_not_shown_as_fine(self):
        """emit() silently drops this row, so showing it plainly would promise
        arguments the launch does not actually pass."""
        text = self.render(extra='--api-key "sk-abc')
        self.assertIn("--api-key", text)
        self.assertIn("!bad", text)

    def test_a_string_chat_template_kwargs_renders(self):
        text = self.render(chat_template_kwargs="x")
        self.assertIn("!bad", text)
        self.assertIn("x", text)

    def test_a_number_as_the_spec_type_renders(self):
        text = self.render(spec_type=3)
        self.assertIn("3", text)

    def test_a_valid_board_carries_no_bad_marker(self):
        """Otherwise 'mark everything' would pass every test above."""
        text = board.render_board(catalog.catalog_defaults(), set(), "hdr")
        self.assertNotIn("!bad", text)
        text = self.render(extra="--props", chat_template_kwargs={"a": True},
                           spec_type="draft-mtp")
        self.assertNotIn("!bad", text)
        self.assertIn("--props", text)

    def test_no_wrong_typed_value_on_any_row_can_take_the_board_down(self):
        """Swept rather than enumerated: a row added later must not reopen this."""
        for setting in (s for g in catalog.GROUPS for s in g.settings):
            for bad in (5, "x", [1], {"a": 1}, True, 0.5):
                with self.subTest(key=setting.key, bad=bad):
                    text = self.render(**{setting.key: bad})
                    self.assertIsInstance(text, str)
                    rows = [l for l in text.splitlines()
                            if l[1:3].strip().isdigit()]
                    self.assertEqual(len(rows), len(catalog.GROUPS))


class PowerShellBreak(Exception):
    """PowerShell would not run the pasted line as the one command it looks
    like: an operator or a newline landed outside quoting and ended the
    statement early. Everything after it goes somewhere else, or nowhere."""


def _ps_value_needs_requoting(value):
    """PowerShell 5.1's own decision about re-quoting one argument of a native
    command: it walks the value counting quote CHARACTERS - all of them, a
    backslash-escaped \\" included - and re-quotes as soon as it meets
    whitespace while that count is even.

    Measured against powershell.exe 5.1.26100.9168 by reading GetCommandLineW
    in the child: the value "{\\"a\\":\\"b c\\"}" has four quotes before its
    space and came out as ""{\\"a\\":\\"b c\\"}"", two arguments. The escaped
    quotes ARE counted; a version of this rule that skips them predicts the
    opposite and is wrong."""
    quotes = 0
    for ch in value:
        if ch == '"':
            quotes += 1
        elif ch.isspace() and quotes % 2 == 0:
            return True
    return False


def _ps_parse_tokens(text):
    """PowerShell's parser, over the part of a line it actually parses.

    Single quotes are literal ('' being one quote); double quotes group; a bare
    |, & or ; outside either ends the statement, and so does a newline. Those
    raise, because a pasted line that ends early is the failure this module
    exists to catch."""
    tokens, cur, started, i = [], [], False, 0
    while i < len(text):
        ch = text[i]
        if ch == "'":
            i += 1
            started = True
            while i < len(text):
                if text[i] == "'":
                    if text[i:i + 2] == "''":
                        cur.append("'")
                        i += 2
                        continue
                    i += 1
                    break
                cur.append(text[i])
                i += 1
        elif ch == '"':
            i += 1
            started = True
            while i < len(text) and text[i] != '"':
                cur.append(text[i])
                i += 1
            i += 1
        elif ch in "|&;\n":
            raise PowerShellBreak(f"{ch!r} outside quoting ends the statement")
        elif ch.isspace():
            if started or cur:
                tokens.append("".join(cur))
                cur, started = [], False
            i += 1
        else:
            cur.append(ch)
            started = True
            i += 1
    if started or cur:
        tokens.append("".join(cur))
    return tokens


def _ps_verbatim_tail(text):
    """The tail after --%, as the process receives it.

    Verbatim, with three measured exceptions. A newline ends the stop-parsing
    run outright - quoting does not save it, PowerShell reports an unterminated
    string. A | or & outside DOUBLE quotes ends it too (single quotes are not
    special here; PowerShell is no longer parsing them). And cmd-style %NAME% is
    expanded from the real environment even inside quotes."""
    in_quotes = False
    for ch in text:
        if ch == '"':
            in_quotes = not in_quotes
        elif ch == "\n":
            raise PowerShellBreak("a newline ends the --% tail")
        elif ch in "|&;" and not in_quotes:
            raise PowerShellBreak(f"{ch!r} ends the --% tail")
    out, i = [], 0
    while i < len(text):
        if text[i] == "%":
            end = text.find("%", i + 1)
            name = text[i + 1:end] if end > i else ""
            if name and name in os.environ:
                out.append(os.environ[name])
                i = end + 1
                continue
        out.append(text[i])
        i += 1
    return "".join(out)


def _runtime_argv(line):
    """A Windows command line, split back into argv the way the C runtime in
    the receiving binary splits it. Backslash-escaped quotes only: the doubled
    "" spelling is deliberately not modelled, because llama-server build 10453
    does not decode it reliably and board.py therefore never writes it."""
    args, cur, quoted, started, i = [], [], False, False, 0
    while i < len(line):
        ch = line[i]
        if ch == "\\":
            end = i
            while end < len(line) and line[end] == "\\":
                end += 1
            slashes = end - i
            started = True
            if end < len(line) and line[end] == '"':
                cur.append("\\" * (slashes // 2))
                if slashes % 2:
                    cur.append('"')
                    end += 1
            else:
                cur.append("\\" * slashes)
            i = end
        elif ch == '"':
            quoted = not quoted
            started = True
            i += 1
        elif ch in " \t" and not quoted:
            if started or cur:
                args.append("".join(cur))
                cur, started = [], False
            i += 1
        else:
            cur.append(ch)
            started = True
            i += 1
    if started or cur:
        args.append("".join(cur))
    return args


def pasted_into_powershell(command):
    """What the binary actually receives when `command` is pasted into
    PowerShell 5.1, as (executable, arguments).

    Every stage was validated against the real thing - powershell.exe
    5.1.26100.9168 driving llama-server.exe and a python argv echo that prints
    GetCommandLineW - on the forms this module generates AND on the ones it used
    to generate, including both failures being fixed: --% really did end at a
    bar, and a re-quoted {"a":"b c"} really did arrive as two arguments.

    Raises PowerShellBreak when the pasted line would not survive as one
    command, which is what the old simulator had no way to say."""
    head, marker, tail = command.partition(" --% ")
    if not head.startswith("& "):
        raise PowerShellBreak("no call operator")
    tokens = _ps_parse_tokens(head[2:])       # past PowerShell's call operator
    if not tokens:
        raise PowerShellBreak("no command")
    exe, tokens = tokens[0], tokens[1:]
    if marker:
        line = " ".join(tokens) + (" " if tokens else "") + _ps_verbatim_tail(tail)
    else:
        line = " ".join(
            ('"' + t + ("\\" if t.endswith("\\") else "") + '"')
            if _ps_value_needs_requoting(t) else t
            for t in tokens)
    return exe, _runtime_argv(line)


LLAMA_SERVER = r"D:\llama.cpp\llama-server.exe"


class TestAsPowerShell(unittest.TestCase):
    """[c] exists so the user can paste the command into PowerShell 5.1 and
    check it. A command that does not survive the paste is worse than none: it
    reports a problem with the settings that is really a problem with the
    quoting. Every expectation here was verified by running the generated line
    through powershell.exe into llama-server.exe --model nonexistent.gguf and
    reading back the arguments the binary reported."""

    ARGV = [
        ["a.exe", "--temp", "0.6"],
        ["a.exe", "--chat-template-kwargs", '{"system_prompt":"You are helpful"}'],
        ["a.exe", "--chat-template-kwargs", '{"a":"b c","d":"e"}'],
        ["a.exe", "--chat-template-kwargs", '{"preserve_thinking":true}'],
        ["a.exe", "--chat-template-kwargs", '{"a":"b|c","d":"e"}'],
        ["a.exe", "--model", r"D:\LLM Models\x.gguf", "--temp", "0.6"],
        ["a.exe", "--model", "D:\\LLM Models\\", "--temp", "0.6"],
        ["a.exe", '{"p":"C:\\"}', "--temp", "0.6"],
        ["a.exe", "--alias", "it's a model", "-ngl", "auto"],
        ["a.exe", "--alias", 'say "hi there" now'],
        ["a.exe", "--alias", 'x "y"z'],
        ["a.exe", "--alias", ""],
        ["a.exe", "--alias", "tab\there"],
        ["a.exe", "--alias", "qwen|draft"],
        ["a.exe", "--alias", "qwen|draft", "--temp", "0.6"],
        ["a.exe", "--alias", "line1\nline2"],
        ["a.exe", "--alias", "a&b;c"],
        ["a.exe", "--alias", "pct %USERNAME% here"],
        ["a.exe", "--alias", "dollar $HOME `tick"],
        ["a.exe", "--alias", "at@hash#paren(){}[],"],
        [r"D:\LLM Models\llama-server.exe", "--model", "m.gguf"],
    ]

    def test_every_argument_arrives_exactly_as_written(self):
        """The whole contract, checked by putting the generated line through the
        same mangling a real paste goes through."""
        for argv in self.ARGV:
            with self.subTest(argv=argv):
                exe, got = pasted_into_powershell(board.as_powershell(argv))
                self.assertEqual(exe, argv[0])
                self.assertEqual(got, argv[1:])

    def test_a_pipe_in_an_argument_does_not_end_the_command(self):
        """The verified regression. --% is a stop-parsing marker only "until the
        next newline or pipeline character", so
            & llama-server.exe --% --model m.gguf --alias qwen|draft
        made PowerShell try to run `draft` as a command - the alias and
        everything after it gone, with a CommandNotFoundException for a name
        nobody typed."""
        argv = ["a.exe", "--model", "m.gguf", "--alias", "qwen|draft"]
        _, got = pasted_into_powershell(board.as_powershell(argv))
        self.assertEqual(got, argv[1:])

    def test_a_pipe_inside_a_json_value_does_not_end_the_command(self):
        """Same break, reached through a value that is already quoted: the
        escaped quotes leave PowerShell's own count even at the bar, so the bar
        was outside quoting as far as its parser was concerned."""
        argv = ["a.exe", "--chat-template-kwargs", '{"a":"b|c"}']
        _, got = pasted_into_powershell(board.as_powershell(argv))
        self.assertEqual(got, argv[1:])

    def test_a_newline_in_an_argument_does_not_end_the_command(self):
        """The other half of the same marker limit, and the one that cannot be
        quoted out of a --% tail at all."""
        argv = ["a.exe", "--alias", "line1\nline2"]
        _, got = pasted_into_powershell(board.as_powershell(argv))
        self.assertEqual(got, argv[1:])

    def test_a_percent_name_is_not_expanded_into_the_command(self):
        """A --% tail expands cmd-style %NAME% from the real environment, even
        inside quotes, so an alias or a path written with percent signs around a
        real variable name was silently substituted in the pasted command."""
        name = next(iter(os.environ))
        argv = ["a.exe", "--alias", f"pct %{name}% here"]
        _, got = pasted_into_powershell(board.as_powershell(argv))
        self.assertEqual(got, argv[1:])

    def test_an_ampersand_or_semicolon_does_not_end_the_command(self):
        for value in ("a&b", "a;b", "a&b;c"):
            with self.subTest(value=value):
                argv = ["a.exe", "--alias", value]
                _, got = pasted_into_powershell(board.as_powershell(argv))
                self.assertEqual(got, argv[1:])

    def test_a_quoted_value_containing_spaces_is_not_split_into_three(self):
        """The older verified regression, which the fix above must not undo.
        PowerShell 5.1 counts the JSON's own quotes, decides the spaces are
        already quoted, adds nothing - and llama-server received
        {"system_prompt":"You / are / helpful"}. No arrangement of escaped
        quotes can fix that count, so this argument is the one case that still
        needs the stop-parsing marker, and the command shows it."""
        argv = ["a.exe", "--chat-template-kwargs",
                '{"system_prompt":"You are helpful"}']
        _, got = pasted_into_powershell(board.as_powershell(argv))
        self.assertEqual(got, argv[1:])
        self.assertEqual(
            board.as_powershell(argv),
            '& a.exe --% --chat-template-kwargs'
            r' "{\"system_prompt\":\"You are helpful\"}"')

    def test_the_marker_is_only_used_when_nothing_else_carries_the_argument(self):
        """It is the fallback, not the rule: everything the quoted form can
        carry must go that way, because the marker is what breaks on bars,
        newlines and %NAME%."""
        for argv in (["a.exe", "--temp", "0.6"],
                     ["a.exe", "--alias", "qwen|draft"],
                     ["a.exe", "--alias", "line1\nline2"],
                     ["a.exe", "--model", r"D:\LLM Models\x.gguf"],
                     ["a.exe", "--alias", 'say "hi there" now'],
                     ["a.exe", "--chat-template-kwargs", '{"a":"b|c"}']):
            with self.subTest(argv=argv):
                self.assertNotIn("--%", board.as_powershell(argv))

    def test_the_marker_form_still_quotes_bars_and_ampersands(self):
        """One argument forcing the marker must not take the others down with
        it. A bar or an ampersand ends a --% tail unless PowerShell's tokenizer
        sees it inside a string, so the marker form quotes for that too - which
        the quoted form does not need and would only make less readable."""
        argv = ["a.exe", "--model", "qwen|draft.gguf", "--alias", "a&b;c",
                "--chat-template-kwargs", '{"system_prompt":"You are helpful"}']
        line = board.as_powershell(argv)
        self.assertIn(" --% ", line)
        _, got = pasted_into_powershell(line)
        self.assertEqual(got, argv[1:])

    def test_a_trailing_backslash_does_not_swallow_the_next_argument(self):
        """A path ending in a backslash escaped the closing quote and ate every
        following argument into one. Verified against the real binary: it did."""
        argv = ["a.exe", "--model", "D:\\LLM Models\\", "--temp", "0.6"]
        _, got = pasted_into_powershell(board.as_powershell(argv))
        self.assertEqual(got, ["--model", "D:\\LLM Models\\", "--temp", "0.6"])

    def test_a_backslash_run_before_a_quote_is_doubled(self):
        """The backslash must be ADJACENT to the quote for the run to precede
        it - in "C:\\x" the x separates them and the rule correctly never fires."""
        out = board.as_powershell(["a.exe", '{"p":"C:\\"}'])
        self.assertIn(r'\\\"', out)

    def test_plain_arguments_are_left_bare(self):
        """Readability is the point of [c]: a line where every argument is
        wrapped in quoting it does not need is a line nobody checks."""
        self.assertEqual(board.as_powershell(["a.exe", "--temp", "0.6"]),
                         "& a.exe --temp 0.6")

    def test_a_path_with_spaces_is_quoted_and_readable(self):
        out = board.as_powershell(["a.exe", "--model", r"D:\LLM Models\x.gguf"])
        self.assertIn(r'"D:\LLM Models\x.gguf"', out)

    def test_an_executable_path_with_spaces_is_quoted_for_powershell(self):
        out = board.as_powershell([r"D:\LLM Models\llama-server.exe", "-h"])
        self.assertTrue(out.startswith(r"& 'D:\LLM Models\llama-server.exe'"))

    def test_the_call_operator_is_present(self):
        self.assertTrue(board.as_powershell(["a.exe"]).startswith("& "))

    def test_a_lone_executable_needs_no_arguments(self):
        self.assertEqual(board.as_powershell(["a.exe"]), "& a.exe")

    def test_a_non_string_in_argv_does_not_raise(self):
        """A hand-edited alias can be a number. [c] is a display path, and the
        board's rule is that a wrong-typed value still reaches the screen."""
        self.assertIn("5", board.as_powershell(["a.exe", "--alias", 5]))


@unittest.skipUnless(os.path.exists(LLAMA_SERVER) and os.path.exists(
    r"C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe"),
    "needs the real powershell.exe and llama-server.exe")
class TestAgainstRealPowerShell(unittest.TestCase):
    """The simulator above is a model, and a model is what missed this bug the
    last time: it had no notion of a bar ending a --% tail, so it passed a
    command that PowerShell refused to run. So the generated lines are also put
    through the REAL powershell.exe into the REAL llama-server.exe, which echoes
    its --model value back verbatim in

        srv  load_model: loading model '<value>'

    --model nonexistent.gguf never loads anything; the binary reports the path
    it was given and exits. One powershell.exe for the whole matrix."""

    PAYLOADS = [
        "qwen|draft",                             # the reported break
        "line1\nline2",                           # the other reported break
        "pct %USERNAME% here",                    # --% expanded this
        "a&b;c",
        r"D:\LLM Models\x.gguf",
        "D:\\LLM Models\\",
        'say "hi there" now',
        '{"a":"b|c","d":"e"}',
        '{"system_prompt":"You are helpful"}',    # needs the marker
        "it's a model",
    ]
    MARK = "load_model: loading model '"

    def test_every_payload_reaches_llama_server_intact(self):
        self.check([[LLAMA_SERVER, "--model", p, "--alias", "probe"]
                    for p in self.PAYLOADS], self.PAYLOADS)

    def test_a_marker_command_carries_its_other_arguments_too(self):
        """The spaced JSON forces the stop-parsing marker; the bar and the
        ampersand beside it are what used to end the tail early. Run for real,
        because this is exactly the combination the simulator has to be right
        about and was not."""
        argv = [LLAMA_SERVER, "--model", "qwen|draft.gguf", "--alias", "a&b;c",
                "--chat-template-kwargs", '{"system_prompt":"You are helpful"}']
        self.assertIn(" --% ", board.as_powershell(argv))
        self.check([argv], ["qwen|draft.gguf"])

    def check(self, argvs, expected):
        import subprocess
        import tempfile
        lines = []
        for i, argv in enumerate(argvs):
            lines.append("[Console]::Error.WriteLine('===%d===')" % i)
            lines.append(board.as_powershell(argv))
        with tempfile.TemporaryDirectory() as tmp:
            script = os.path.join(tmp, "probe.ps1")
            with open(script, "w", encoding="utf-8", newline="") as fh:
                fh.write("\n".join(lines) + "\n")
            proc = subprocess.run(
                ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass",
                 "-File", script], capture_output=True, text=True,
                encoding="utf-8", errors="replace", timeout=300)
        out = (proc.stderr or "") + "\n" + (proc.stdout or "")
        blocks, cur = {}, None
        for line in out.splitlines():
            if line.startswith("===") and line.endswith("==="):
                cur = int(line.strip("="))
                blocks[cur] = []
            elif cur is not None:
                blocks[cur].append(line)
        for i, payload in enumerate(expected):
            with self.subTest(payload=payload):
                body = "\n".join(blocks.get(i, []))
                self.assertIn(self.MARK, body,
                              f"llama-server never saw a --model value: {body[:300]}")
                rest = body.split(self.MARK, 1)[1]
                self.assertTrue(
                    rest.startswith(payload + "'"),
                    f"arrived as {rest[:120]!r}, not {payload!r}")


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

    def test_an_absurdly_long_digit_string_is_unknown_not_a_crash(self):
        """int() refuses a decimal string longer than 4300 digits - CPython's
        integer-string conversion limit - and raises ValueError. isdecimal() is
        happy with it, so the row-number branch took the launcher down on a
        pasted wall of digits. 4301 is the first length that does it."""
        self.assertEqual(board.dispatch("9" * 4301), "unknown")
        self.assertEqual(board.dispatch("1" * 20000), "unknown")
        self.assertEqual(board.dispatch("0" * 4300 + "3"), "unknown")

    def test_a_long_digit_string_within_the_limit_still_answers(self):
        """Otherwise 'call everything long unknown' would pass the test above
        while a 4300-digit string still crashed."""
        self.assertEqual(board.dispatch("9" * 4300), "unknown")
        self.assertEqual(board.dispatch("0" * 4299 + "3"), "edit:3")


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

    def test_enter_keeps_a_tri_value_instead_of_erasing_it(self):
        """The regression that made the final review say "not yet". Blank meant
        "unset" for tri types only, so pressing Enter through the toggles row
        destroyed a saved kv_unified - while the prompt showed [on], promising
        the opposite."""
        values = self.values(kv_unified="on", reasoning_preserve="off")
        out = board.edit_group(self.group("toggles"), values,
                               lambda prompt: "", lambda t: None)
        self.assertEqual(out["kv_unified"], "on")
        self.assertEqual(out["reasoning_preserve"], "off")

    def test_a_tri_is_cleared_with_a_dash(self):
        answers = iter(["", "", "", "", "-", "", "", ""])
        out = board.edit_group(self.group("toggles"),
                               self.values(reasoning_preserve="on"),
                               lambda prompt: next(answers), lambda t: None)
        self.assertIsNone(out["reasoning_preserve"])

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

    def test_mtp_offers_the_draft_model_prompt(self):
        """draft-mtp takes an OPTIONAL draft model, so the row has to be offered.
        Skipping it was what made the ordinary MTP setup - a separate draft GGUF
        - impossible to enter from the board at all."""
        out = board.edit_group(
            self.group("spec"), self.values(),
            self.scripted(["draft-mtp", "d/MTP-Draft.gguf", "99", "3", "0", "0.75"]),
            lambda t: None)
        self.assertEqual(out["spec_type"], "draft-mtp")
        self.assertEqual(out["draft_model"], "d/MTP-Draft.gguf")
        self.assertEqual(out["spec_ngl"], "99")
        self.assertEqual(out["spec_p_min"], 0.75)

    def test_mtp_leaves_the_draft_model_unset_when_the_row_is_blanked(self):
        """The head-in-the-weights case. Blank keeps the current value, which is
        nothing, and that must still be launchable."""
        out = board.edit_group(self.group("spec"), self.values(),
                               self.scripted(["draft-mtp", "", "", "3", "0", "0.75"]),
                               lambda t: None)
        self.assertEqual(out["spec_type"], "draft-mtp")
        self.assertIsNone(out["draft_model"])
        self.assertIsNone(catalog.spec_error(out), "must be launchable bare")

    def test_switching_to_a_built_in_type_clears_a_stale_draft_model(self):
        """Otherwise the user is stranded: editable_keys hides the draft-model
        row for the ngram-* family, so they cannot clear it, while spec_error
        refuses to launch and tells them to clear it. The UI must not issue an
        instruction it gives no way to obey.

        draft-mtp is deliberately NOT the type under test here any more - it
        keeps its draft model, because it can use one."""
        said = []
        out = board.edit_group(
            self.group("spec"),
            self.values(spec_type="draft-dflash", draft_model="d/DFlash.gguf"),
            self.scripted(["ngram-mod", "3", "0", "0.0"]), said.append)
        self.assertEqual(out["spec_type"], "ngram-mod")
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

    def test_visiting_the_row_to_repair_a_typo_does_not_destroy_the_draft_model(self):
        """The repair path, and it used to be the destructive one.

        A hand-edited spec_type with a typo in it - 'ngram-modd' - is refused by
        spec_error, which tells the user to fix it on the speculative row. Going
        there and pressing Enter through the prompts is not a decision to throw
        anything away: blank keeps the current value, everywhere. But an
        unrecognised type is not in DRAFT_MODEL_TYPES either, so active_keys
        dropped draft_model exactly as it does for a real built-in type, the
        clearing branch fired, and the row said

            cleared the draft model: ngram-modd carries its own

        of a string the catalog cannot interpret at all. run_board then marked
        the row dirty, so [s] wrote the loss to the file. The typo is still
        there afterwards - this test asserts that too, because a fix that
        quietly repaired the type would hide the same data loss."""
        for typo in ("ngram-modd", "draft-mtpp", "ngramm-mod"):
            with self.subTest(typo=typo):
                said = []
                out = board.edit_group(
                    self.group("spec"),
                    self.values(spec_type=typo, draft_model="d/DFlash.gguf"),
                    self.scripted(["", "", "", "", ""]), said.append)
                self.assertEqual(out["draft_model"], "d/DFlash.gguf",
                                 "the draft model was the user's, not ours")
                self.assertEqual(out["spec_type"], typo)
                self.assertFalse([s for s in said if "cleared" in s],
                                 f"said {said!r} about a type it cannot read")

    def test_switching_to_none_does_not_destroy_the_draft_model(self):
        """'none' does not carry its own prediction head - it means no
        speculative decoding at all - and nothing refuses a launch over a draft
        model that is simply not being used. Clearing it here would have been
        the same silent loss, with the same untrue reason."""
        said = []
        out = board.edit_group(
            self.group("spec"),
            self.values(spec_type="draft-dflash", draft_model="d/DFlash.gguf"),
            self.scripted(["none"]), said.append)
        self.assertEqual(out["spec_type"], "none")
        self.assertEqual(out["draft_model"], "d/DFlash.gguf")
        self.assertIsNone(catalog.spec_error(out))
        self.assertFalse([s for s in said if "cleared" in s])

    def test_the_reason_given_for_clearing_names_the_type_that_was_chosen(self):
        """The message is the only record the user gets of the value going
        away, so it has to be true: the normalised type actually in force."""
        said = []
        out = board.edit_group(
            self.group("spec"),
            self.values(spec_type="draft-dflash", draft_model="d/DFlash.gguf"),
            self.scripted([" ngram-mod , ngram-cache ", "3", "0", "0.0"]),
            said.append)
        message = "\n".join(said)
        self.assertIn("cleared the draft model", message)
        self.assertIn("ngram-mod,ngram-cache", message)
        self.assertIsNone(out["draft_model"])


if __name__ == "__main__":
    unittest.main()
