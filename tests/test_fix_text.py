"""Unit tests for the OCR post-processing pipeline (no Tesseract required)."""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src import languages
from src.fix_text import detect_language, fix_code, normalize_unicode


class TestUnicode(unittest.TestCase):
    def test_curly_quotes_become_ascii(self):
        self.assertEqual(normalize_unicode("cnt <= ‘0’;"), "cnt <= '0';")

    def test_degree_sign_read_as_quote(self):
        self.assertEqual(normalize_unicode("if enable = ‘1° then"),
                         "if enable = '1' then")

    def test_doubled_quote_before_char_literal(self):
        self.assertEqual(normalize_unicode("(others => ''0')"), "(others => '0')")

    def test_plain_string_is_untouched(self):
        self.assertEqual(normalize_unicode('printf("ok");'), 'printf("ok");')


class TestLanguageDetection(unittest.TestCase):
    def test_detects_c(self):
        self.assertEqual(detect_language(
            '#include <stdio.h>\nint main() { printf("hi"); return 0; }'), "c")

    def test_detects_vhdl(self):
        self.assertEqual(detect_language(
            "library IEEE;\nentity foo is\nend entity;\n"
            "architecture rtl of foo is\nbegin\nend architecture;"), "vhdl")

    def test_empty_text_falls_back(self):
        self.assertEqual(detect_language(""), languages.DEFAULT.key)


class TestUnderscoreRepair(unittest.TestCase):
    """Underscores are thin and are the single most common VHDL OCR loss."""

    def test_rejoins_multi_part_type(self):
        out = fix_code("q : out std logic vector(7 downto 0);", lang="vhdl")
        self.assertIn("std_logic_vector", out)

    def test_rejoins_stray_underscore(self):
        out = fix_code("elsif rising _edge(clk) then", lang="vhdl")
        self.assertIn("rising_edge(clk)", out)

    def test_rejoins_trailing_underscore(self):
        out = fix_code("signal a : std_logic_ vector(3 downto 0);", lang="vhdl")
        self.assertIn("std_logic_vector", out)

    def test_rejoins_library_with_digits(self):
        out = fix_code("use IEEE.STD_LOGIC 1164.ALL;", lang="vhdl")
        self.assertIn("STD_LOGIC_1164", out)

    def test_leaves_adjacent_keywords_alone(self):
        out = fix_code("end process;\nend if;\n", lang="vhdl")
        self.assertNotIn("_", out)

    def test_learns_identifier_from_the_snippet(self):
        out = fix_code("int frame_count;\nframe count = 0;\n", lang="c")
        self.assertIn("frame_count = 0", out)


class TestTokenRepair(unittest.TestCase):
    def test_confusable_digit_uses_snippet_spelling(self):
        out = fix_code(
            "int array1[20];\nfor(i=0;i<20;i++){ arrayl[i]=i; }\n"
            "add(&array1[0]);\n", lang="c")
        self.assertNotIn("arrayl", out)
        self.assertIn("array1[i]", out)

    def test_rare_token_folds_into_frequent_neighbour(self):
        src = ("ZeigerTail->Next = ZeigerTail;\n"
               "ZdigerTail->ADCData = -2;\n"
               "free(ZeigerTail);\n"
               "x = ZeigerTail;\n")
        out = fix_code(src, lang="c")
        self.assertNotIn("ZdigerTail", out)

    def test_distinct_names_are_not_merged(self):
        # array1/array2/array3 are each frequent, so none is a unique neighbour
        src = "".join(f"array{n}[i] = {n}; array{n}[j] = {n}; array{n}[k] = {n};\n"
                      for n in (1, 2, 3))
        out = fix_code(src, lang="c")
        for n in (1, 2, 3):
            self.assertEqual(out.count(f"array{n}"), 3)

    def test_keyword_is_never_rewritten(self):
        out = fix_code("while (x) { return; }\n", lang="c")
        self.assertIn("while", out)

    def test_numbered_family_fixes_the_odd_one_out(self):
        # `Addl` stays wrong under frequency voting -- Add2/Add6/Add7 give it away
        src = ("variable Add6 : integer;\nvariable Add7 : integer;\n"
               "Add6 := Add6 + Addl;\nAdd7 := Add6 + Add2;\n"
               "DataOut1 <= Addl + Add6 + Add7;\n")
        out = fix_code(src, lang="vhdl")
        self.assertNotIn("Addl", out)
        self.assertIn("Add1", out)

    def test_single_correct_read_rescues_the_rest(self):
        # `Add1` in the declaration is enough to fix `Addl` at the use site,
        # even though the wrong spelling is not outnumbered
        out = fix_code("signal Add1 : integer;\nx <= Addl;\n", lang="vhdl")
        self.assertNotIn("Addl", out)
        self.assertEqual(out.count("Add1"), 2)

    def test_unstable_last_glyph_resolves_to_a_digit(self):
        # no occurrence is read correctly, but the same stem comes back with two
        # different digit look-alikes, so that position must be a digit
        out = fix_code("vall <= a;\nvali <= b;\nc <= vall;\n", lang="vhdl")
        self.assertNotIn("vall", out)
        self.assertNotIn("vali", out)
        self.assertEqual(out.count("val1"), 3)

    def test_plausible_word_ending_is_not_digitised(self):
        src = ("signal Add1 : integer;\nsignal Add2 : integer;\n"
               "signal Adds : integer;\n")
        out = fix_code(src, lang="vhdl")
        self.assertIn("Adds", out)

    def test_names_ending_in_l_or_i_are_left_alone(self):
        """Nothing in the snippet spells these with a digit, so they stay."""
        src = ("architecture rtl of foo is\n"
               "    signal sel   : std_logic;\n"
               "    signal total : integer;\n"
               "    signal ctrl  : std_logic;\n"
               "begin\n"
               "    total <= sel and ctrl;\n"
               "end architecture rtl;\n")
        out = fix_code(src, lang="vhdl")
        for name in ("rtl", "sel", "total", "ctrl"):
            self.assertIn(name, out)
        self.assertNotIn("se1", out)
        self.assertNotIn("tota1", out)
        self.assertNotIn("ctr1", out)

    def test_correctly_read_digit_is_never_downgraded(self):
        """The misreading outnumbers the truth; the truth must still win."""
        src = ("signal cnt1 : integer;\n"
               "cntl <= cntl + 1;\ncnti <= cntl;\nx <= cntl;\n")
        out = fix_code(src, lang="vhdl")
        self.assertNotIn("cntl", out)
        self.assertNotIn("cnti", out)
        self.assertNotIn("cntI", out)


class TestPunctuation(unittest.TestCase):
    def test_at_sign_is_a_misread_zero(self):
        out = fix_code("q : out std_logic_vector(WIDTH-1 downto @);", lang="vhdl")
        self.assertIn("downto 0)", out)

    def test_copyright_sign_is_a_misread_zero(self):
        out = fix_code("variable Add6 : integer range © to 7 := 0;", lang="vhdl")
        self.assertIn("range 0 to 7", out)
        self.assertNotIn("©", out)

    def test_other_ring_shapes_are_misread_zeros(self):
        for symbol in "®Ⓞ⊙◎◯○●〇":
            with self.subTest(symbol=symbol):
                out = fix_code(f"x <= {symbol};", lang="vhdl")
                self.assertIn("x <= 0;", out)

    def test_at_sign_inside_a_comment_survives(self):
        out = fix_code("-- contact a@b.com\nsignal x : std_logic;\n", lang="vhdl")
        self.assertIn("a@b.com", out)

    def test_copyright_notice_in_a_comment_survives(self):
        out = fix_code("-- © 2026 Acme Ltd\nsignal x : std_logic;\n", lang="vhdl")
        self.assertIn("© 2026 Acme Ltd", out)

    def test_semicolon_misread_as_five(self):
        out = fix_code("port (\n a : in std_logic\n )5\n", lang="vhdl")
        self.assertIn(");", out)

    def test_capital_o_in_value_position(self):
        out = fix_code("for(i=O; i<20; i++) {\n}\n", lang="c")
        self.assertIn("i=0;", out)

    def test_flip_flop_port_names_survive(self):
        # Q and D are the standard VHDL flip-flop ports, never misread digits
        src = ("u1 : dff port map (D => a, Q => b, clk => clk);\n"
               "u2 : dff port map (D => b, Q => c, clk => clk);\n")
        out = fix_code(src, lang="vhdl")
        self.assertIn("D => a", out)
        self.assertIn("Q => b", out)
        self.assertNotIn("0 =>", out)

    def test_space_before_semicolon_removed(self):
        out = fix_code("free(*p) ;\n", lang="c")
        self.assertIn("free(*p);", out)

    def test_call_parenthesis_tightened_but_keywords_kept(self):
        out = fix_code('if (x) {\nprintf ("hi");\n}\n', lang="c")
        self.assertIn("if (x)", out)
        self.assertIn('printf("hi")', out)

    def test_others_association_arrow_is_restored(self):
        out = fix_code("DataOut1 <= (others = '0');", lang="vhdl")
        self.assertIn("(others => '0')", out)

    def test_existing_arrow_is_not_doubled(self):
        out = fix_code("cnt <= (others => '0');", lang="vhdl")
        self.assertIn("(others => '0')", out)
        self.assertNotIn("=>>", out)

    def test_vhdl_keeps_idiomatic_space_before_paren(self):
        out = fix_code("process (clk)\nbegin\nend process;\n", lang="vhdl")
        self.assertIn("process (clk)", out)

    def test_reserved_word_before_paren_keeps_its_space(self):
        out = fix_code("type state_t is (s0, s1, s2);\n", lang="vhdl")
        self.assertIn("is (s0, s1, s2)", out)

    def test_function_call_is_still_tightened(self):
        out = fix_code("q <= std_logic_vector (cnt);\n", lang="vhdl")
        self.assertIn("std_logic_vector(cnt)", out)


class TestVhdlCharLiterals(unittest.TestCase):
    def test_at_sign_literal_becomes_zero(self):
        self.assertIn("'0'", fix_code("cnt <= '@';", lang="vhdl"))

    def test_letter_o_literal_becomes_zero(self):
        self.assertIn("'0'", fix_code("cnt <= 'O';", lang="vhdl"))

    def test_legal_values_are_left_alone(self):
        for value in ("'1'", "'Z'", "'X'", "'U'", "'-'"):
            self.assertIn(value, fix_code(f"cnt <= {value};", lang="vhdl"))

    def test_c_char_literal_is_not_touched(self):
        self.assertIn("'O'", fix_code("char c = 'O';", lang="c"))


class TestEdgeJunk(unittest.TestCase):
    """A screenshot that clips the previous column glues junk onto line starts."""

    def test_glyph_glued_to_keyword(self):
        out = fix_code("jvoid DefineListenStart() {\n}\n", lang="c")
        self.assertTrue(out.startswith("void DefineListenStart"), out)

    def test_glyph_before_closing_brace(self):
        out = fix_code("void f() {\n x = 1;\n-}\n", lang="c")
        self.assertIn("\n}", out)

    def test_bar_before_comment(self):
        out = fix_code("| /* hello */\nint x;\n", lang="c")
        self.assertTrue(out.startswith("/* hello */"), out)

    def test_real_code_is_not_eaten(self):
        out = fix_code("int x;\n-- not a c comment\n", lang="c")
        self.assertIn("int x;", out)


class TestComments(unittest.TestCase):
    def test_prose_in_comments_is_not_repaired(self):
        src = "/* Reservierung Speicher KnotenHead und KnotenTail auf Heap */\nint x;\n"
        self.assertIn("Reservierung Speicher KnotenHead und KnotenTail auf Heap",
                      fix_code(src, lang="c"))

    def test_string_contents_are_not_repaired(self):
        self.assertIn('"a  b   c"', fix_code('printf("a  b   c");\n', lang="c"))


class TestIndentation(unittest.TestCase):
    def test_c_braces(self):
        out = fix_code("int main() {\nint i;\nif (i) {\ni++;\n}\n}\n", lang="c")
        self.assertEqual(out, "int main() {\n    int i;\n    if (i) {\n"
                              "        i++;\n    }\n}\n")

    def test_preprocessor_stays_at_column_zero(self):
        out = fix_code("int main() {\n#define X 1\n}\n", lang="c")
        self.assertIn("\n#define X 1\n", out)

    def test_vhdl_blocks(self):
        out = fix_code(
            "architecture rtl of foo is\nsignal a : std_logic;\nbegin\n"
            "process (clk)\nbegin\nif a = '1' then\nb <= '0';\nend if;\n"
            "end process;\nend architecture rtl;\n", lang="vhdl")
        self.assertEqual(out, (
            "architecture rtl of foo is\n"
            "    signal a : std_logic;\n"
            "begin\n"
            "    process (clk)\n"
            "    begin\n"
            "        if a = '1' then\n"
            "            b <= '0';\n"
            "        end if;\n"
            "    end process;\n"
            "end architecture rtl;\n"))

    def test_vhdl_case_with_one_line_alternatives(self):
        out = fix_code("case sel is\nwhen \"00\" => y <= a;\n"
                       "when \"01\" => y <= b;\nwhen others => y <= c;\n"
                       "end case;\n", lang="vhdl")
        self.assertEqual(out, (
            "case sel is\n"
            '    when "00" => y <= a;\n'
            '    when "01" => y <= b;\n'
            "    when others => y <= c;\n"
            "end case;\n"))

    def test_vhdl_case_with_multi_line_alternatives(self):
        out = fix_code("case sel is\nwhen \"00\" =>\ny <= a;\n"
                       "when others =>\ny <= c;\nend case;\n", lang="vhdl")
        self.assertEqual(out, (
            "case sel is\n"
            '    when "00" =>\n'
            "        y <= a;\n"
            "    when others =>\n"
            "        y <= c;\n"
            "end case;\n"))

    def test_vhdl_nested_if_inside_a_when(self):
        out = fix_code("case sel is\nwhen \"00\" =>\nif x = '1' then\ny <= a;\n"
                       "end if;\nwhen others =>\ny <= c;\nend case;\n", lang="vhdl")
        self.assertEqual(out, (
            "case sel is\n"
            '    when "00" =>\n'
            "        if x = '1' then\n"
            "            y <= a;\n"
            "        end if;\n"
            "    when others =>\n"
            "        y <= c;\n"
            "end case;\n"))

    def test_conditional_assignment_is_not_a_case_alternative(self):
        out = fix_code("y <= a when sel = '1' else b;\n", lang="vhdl")
        self.assertEqual(out, "y <= a when sel = '1' else b;\n")

    def test_labelled_process_opens_a_block(self):
        out = fix_code("P1: process(Reset, Clk)\nvariable a : integer;\n"
                       "begin\nx <= a;\nend process P1;\n", lang="vhdl")
        self.assertEqual(out, (
            "P1: process(Reset, Clk)\n"
            "    variable a : integer;\n"
            "begin\n"
            "    x <= a;\n"
            "end process P1;\n"))

    def test_missing_end_if_does_not_cascade(self):
        """`end process` unwinds to the process, whatever the OCR lost inside."""
        out = fix_code("P1: process(Clk)\nbegin\nif a = '1' then\nx <= b;\n"
                       "end process P1;\n"
                       "P2: process(Clk)\nbegin\ny <= c;\nend process P2;\n",
                       lang="vhdl")
        lines = out.split("\n")
        self.assertEqual(lines[4], "end process P1;")
        self.assertEqual(lines[5], "P2: process(Clk)")
        self.assertEqual(lines[7], "    y <= c;")

    def test_signal_declaration_is_not_mistaken_for_a_label(self):
        out = fix_code("architecture rtl of foo is\nsignal cnt : integer;\n"
                       "begin\nend architecture rtl;\n", lang="vhdl")
        self.assertIn("    signal cnt : integer;", out)

    def test_generate_block(self):
        out = fix_code("g1: for i in 0 to 3 generate\nx(i) <= y(i);\n"
                       "end generate g1;\n", lang="vhdl")
        self.assertEqual(out, ("g1: for i in 0 to 3 generate\n"
                               "    x(i) <= y(i);\n"
                               "end generate g1;\n"))

    def test_column_alignment_is_preserved(self):
        out = fix_code("port (\nclk     : in  std_logic;\n);\n", lang="vhdl")
        self.assertIn("clk     : in  std_logic;", out)

    def test_reindent_can_be_disabled(self):
        out = fix_code("int main() {\n      weird;\n}\n", lang="c", reindent=False)
        self.assertIn("      weird;", out)


class TestRobustness(unittest.TestCase):
    def test_empty_input(self):
        self.assertEqual(fix_code(""), "")

    def test_whitespace_only(self):
        self.assertEqual(fix_code("   \n  \n").strip(), "")

    def test_unterminated_string_does_not_hang(self):
        self.assertIn("oops", fix_code('printf("oops\nint x;\n', lang="c"))

    def test_unterminated_block_comment(self):
        self.assertIn("half a comment", fix_code("/* half a comment\n", lang="c"))

    def test_auto_is_the_default(self):
        self.assertIn("entity", fix_code("entity foo is\nend entity;\n"))


if __name__ == "__main__":
    unittest.main()
