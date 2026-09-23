import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from shuffle_solver.deck import (
    FULL_DECK_KEYS,
    PRESETS,
    RANKS,
    SUITS,
    Card,
    ParseError,
    expand_ranks,
    format_cards,
    format_numbered,
    parse_cards,
    parse_deck,
    validate_deck,
)


def keys(cards):
    return [str(c) for c in cards]  # "AC" or "AC`" when face up


# --- single cards -------------------------------------------------------------

def test_single_card():
    assert parse_cards("AC") == [Card("A", "C")]


def test_single_card_face_up():
    assert parse_cards("AC`") == [Card("A", "C", True)]


def test_ten_as_t_or_10():
    assert parse_cards("TD, 10D") == [Card("T", "D"), Card("T", "D")]


def test_case_and_whitespace_insensitive():
    assert parse_cards("  a c ,  q h` ") == [Card("A", "C"), Card("Q", "H", True)]


def test_unicode_suits_accepted():
    assert parse_cards("A♠, 10♥") == [Card("A", "S"), Card("T", "H")]


# --- ranges -------------------------------------------------------------------

def test_ascending_range():
    assert keys(parse_cards("A-KC")) == [r + "C" for r in RANKS]


def test_descending_range():
    assert keys(parse_cards("K-AC")) == [r + "C" for r in reversed(RANKS)]


def test_single_rank_range():
    assert keys(parse_cards("5-5H")) == ["5H"]


def test_bare_range_takes_trailing_backtick():
    cards = parse_cards("A-KC`")
    assert len(cards) == 13 and all(c.face_up for c in cards)


def test_expand_ranks():
    assert expand_ranks("9", "K") == list("9TJQK")
    assert expand_ranks("K", "J") == list("KQJ")


# --- groups -------------------------------------------------------------------

def test_group_same_as_range():
    assert parse_cards("(A-8, 9-K)C") == parse_cards("A-KC")


def test_group_face_up_backtick_before_suit():
    cards = parse_cards("(A-8, 9-K)`C")
    assert keys(cards) == [r + "C`" for r in RANKS]


def test_group_of_single_ranks():
    assert keys(parse_cards("(A, 5, K)S")) == ["AS", "5S", "KS"]


def test_group_item_backtick_flags_only_that_item():
    cards = parse_cards("(A-2`, 3)C")
    assert keys(cards) == ["AC`", "2C`", "3C"]


def test_group_with_multiple_suits():
    assert keys(parse_cards("(A, K)CH")) == ["AC", "KC", "AH", "KH"]


def test_group_multiple_suits_backtick_after_suit_flags_that_suit_only():
    assert keys(parse_cards("(A, K)C`H")) == ["AC`", "KC`", "AH", "KH"]


def test_group_backtick_before_suits_flags_all_suits():
    assert keys(parse_cards("(A, K)`CH")) == ["AC`", "KC`", "AH`", "KH`"]


def test_group_of_full_cards_face_up():
    cards = parse_cards("(ACHSD)`")
    assert keys(cards) == ["AC`", "AH`", "AS`", "AD`"]


def test_group_of_full_cards_without_backtick():
    assert keys(parse_cards("(AC`, 2H)")) == ["AC`", "2H"]


# --- multi-suit chains --------------------------------------------------------

def test_multi_suit_single_rank():
    assert keys(parse_cards("ACHSD")) == ["AC", "AH", "AS", "AD"]


def test_multi_suit_backtick_at_end_flags_last_only():
    assert keys(parse_cards("ACHSD`")) == ["AC", "AH", "AS", "AD`"]


def test_multi_suit_backtick_after_first_flags_first_only():
    assert keys(parse_cards("AC`HSD")) == ["AC`", "AH", "AS", "AD"]


def test_range_with_multiple_suits():
    cards = parse_cards("A-KCHSD")
    assert keys(cards) == [r + s for s in "CHSD" for r in RANKS]


def test_range_multi_suit_backtick_flags_only_that_suit_range():
    # Local-attach rule applied to range chunks (not yet confirmed in the design doc).
    cards = parse_cards("A-KC`HSD")
    assert all(c.face_up for c in cards[:13])
    assert not any(c.face_up for c in cards[13:])


# --- worked example from the design doc ----------------------------------------

def test_worked_example():
    cards = parse_cards("(A-8, 9-K)`C, 2D, TH`, K-JS")
    assert keys(cards) == [r + "C`" for r in RANKS] + ["2D", "TH`", "KS", "QS", "JS"]


# --- separators ---------------------------------------------------------------

def test_newlines_and_trailing_commas_separate_entries():
    assert keys(parse_cards("AC\n2C,\n,3C,")) == ["AC", "2C", "3C"]


def test_empty_input():
    assert parse_cards("") == []
    assert parse_cards("  , ") == []


# --- errors --------------------------------------------------------------------

@pytest.mark.parametrize(
    "text",
    [
        "A",            # no suit
        "AX",           # bad suit
        "1C",           # bad rank
        "A-C",          # range missing end rank
        "A-KC-2",       # junk after entry
        "AC 2C",        # missing comma
        "((A)C)",       # nesting
        "(A-8C",        # unclosed
        "A-8)C",        # stray paren
        "()C",          # empty group
        "(A, 2)",       # bare ranks with no suit
        "(AC, 2)H",     # mixed full cards and bare ranks
        "(AC)H",        # full cards plus trailing suit
        "`AC",          # backtick with nothing on its left
        "AC``",         # double backtick
        "AC?",          # unknown char
    ],
)
def test_parse_errors(text):
    with pytest.raises(ParseError):
        parse_cards(text)


def test_parse_error_reports_position():
    with pytest.raises(ParseError) as exc:
        parse_cards("AC, 2X")
    assert exc.value.pos == 5
    assert "character 6" in str(exc.value)


# --- validation ----------------------------------------------------------------

def test_full_deck_valid():
    cards, report = parse_deck("A-KCHSD")
    assert report.ok and report.messages() == []


def test_duplicates_and_missing_reported():
    cards, report = parse_deck("A-KCHS, A-QD, AC")
    assert not report.ok
    assert report.count == 52
    assert report.duplicates == ["AC"]
    assert report.missing == ["KD"]
    msgs = " ".join(report.messages())
    assert "AC" in msgs and "KD" in msgs


def test_short_deck_reported():
    report = validate_deck(parse_cards("A-KC"))
    assert report.count == 13 and len(report.missing) == 39 and not report.ok


def test_face_up_does_not_affect_identity():
    report = validate_deck(parse_cards("AC, AC`"))
    assert report.duplicates == ["AC"]


# --- formatting ----------------------------------------------------------------

def test_format_compresses_runs():
    assert format_cards(parse_cards("A-KC, K-AD, 2H, 3H, 5S`, 4S`, 3S`")) == \
        "A-KC, K-AD, 2H, 3H, 5-3S`"


def test_format_uncompressed():
    assert format_cards(parse_cards("A-3C`"), compress=False) == "AC`, 2C`, 3C`"


def test_format_does_not_merge_different_facing():
    assert format_cards(parse_cards("AC, 2C`, 3C, 4C")) == "AC, 2C`, 3C, 4C"


def test_format_numbered():
    out = format_numbered(parse_cards("AC, TH`"))
    assert out.splitlines() == [" 1. A♣    ace of clubs", " 2. 10♥`  10 of hearts (face up)"]


card_strategy = st.builds(Card, st.sampled_from(RANKS), st.sampled_from(SUITS), st.booleans())


@settings(max_examples=300)
@given(st.lists(card_strategy, max_size=60), st.booleans())
def test_format_parse_round_trip(cards, compress):
    assert parse_cards(format_cards(cards, compress)) == cards


# --- presets -------------------------------------------------------------------

@pytest.mark.parametrize("name", list(PRESETS))
def test_presets_are_full_decks(name):
    assert validate_deck(PRESETS[name]).ok


def test_new_deck_order():
    cards = PRESETS["New deck order"]
    assert str(cards[0]) == "AH" and str(cards[12]) == "KH"
    assert str(cards[26]) == "KD" and str(cards[-1]) == "AS"


def test_full_deck_keys():
    assert len(set(FULL_DECK_KEYS)) == 52
