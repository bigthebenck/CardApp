"""Cards, the typed shorthand grammar, deck validation and preset stacks.

Shorthand summary (whitespace ignored, case-insensitive):

    AC            ace of clubs
    AC`           ace of clubs, face up (backtick flags the card on its left)
    A-KC          ace..king of clubs; K-AC runs downward. A trailing backtick
                  flags the whole range (a bare range is one atomic entry)
    ACHSD         AC, AH, AS, AD -- repeated suit letters, in typed order
    AC`HSD        only AC face up;   ACHSD`  only AD face up
    A-KCH         clubs A..K, then hearts A..K; A-KC`HS flags only the clubs
    (A-8, 9-K)C   one suit for several ranks/ranges
    (A-8, 9-K)`C  ... all face up (backtick right after the closing paren)
    (ACHSD)`      whole chain of full cards face up

Entries are separated by commas (or newlines). Parentheses never nest. Inside
a group every item is either a bare rank/range (the suit comes after the
closing paren) or a full card chain (no suit after the paren) -- not a mix.
"""

from dataclasses import dataclass

RANKS = "A23456789TJQK"
SUITS = "CHSD"
SUIT_SYMBOLS = {"C": "♣", "H": "♥", "S": "♠", "D": "♦"}
SUIT_NAMES = {"C": "clubs", "H": "hearts", "S": "spades", "D": "diamonds"}
RANK_NAMES = {"A": "ace", "T": "10", "J": "jack", "Q": "queen", "K": "king"}
BACKTICKS = "`‵"  # plain backtick, plus the reversed prime some fonts render it as

_SYMBOL_TO_SUIT = {v: k for k, v in SUIT_SYMBOLS.items()}
_SYMBOL_TO_SUIT.update({"♤": "S", "♡": "H", "♢": "D", "♧": "C"})


@dataclass(frozen=True)
class Card:
    rank: str
    suit: str
    face_up: bool = False

    def __post_init__(self):
        if self.rank not in RANKS:
            raise ValueError(f"bad rank {self.rank!r}")
        if self.suit not in SUITS:
            raise ValueError(f"bad suit {self.suit!r}")

    @property
    def key(self):
        """Identity ignoring the face-up display flag."""
        return self.rank + self.suit

    def with_face_up(self, face_up):
        return Card(self.rank, self.suit, face_up)

    def pretty(self):
        rank = "10" if self.rank == "T" else self.rank
        return rank + SUIT_SYMBOLS[self.suit] + ("`" if self.face_up else "")

    def name(self):
        rank = RANK_NAMES.get(self.rank, self.rank)
        return f"{rank} of {SUIT_NAMES[self.suit]}" + (" (face up)" if self.face_up else "")

    def __str__(self):
        return self.key + ("`" if self.face_up else "")


FULL_DECK_KEYS = [r + s for s in SUITS for r in RANKS]


# --- tokenizer ------------------------------------------------------------------


class ParseError(ValueError):
    def __init__(self, message, pos=None):
        self.pos = pos
        where = f" (at character {pos + 1})" if pos is not None else ""
        super().__init__(message + where)


RANK, SUIT, DASH, COMMA, LPAREN, RPAREN, TICK, END = (
    "rank", "suit", "-", ",", "(", ")", "`", "end",
)


@dataclass(frozen=True)
class _Tok:
    type: str
    value: str
    pos: int


def _tokenize(text):
    toks = []
    i = 0
    while i < len(text):
        ch = text[i]
        up = ch.upper()
        if ch in " \t\r":
            i += 1
        elif ch in "\n;":
            toks.append(_Tok(COMMA, ",", i))
            i += 1
        elif ch == "1" and i + 1 < len(text) and text[i + 1] == "0":
            toks.append(_Tok(RANK, "T", i))
            i += 2
        elif up in RANKS:
            toks.append(_Tok(RANK, up, i))
            i += 1
        elif up in SUITS:
            toks.append(_Tok(SUIT, up, i))
            i += 1
        elif ch in _SYMBOL_TO_SUIT:
            toks.append(_Tok(SUIT, _SYMBOL_TO_SUIT[ch], i))
            i += 1
        elif ch in BACKTICKS:
            toks.append(_Tok(TICK, "`", i))
            i += 1
        elif ch in "-–—":
            toks.append(_Tok(DASH, "-", i))
            i += 1
        elif ch in ",()":
            toks.append(_Tok(ch, ch, i))
            i += 1
        else:
            raise ParseError(f"unexpected character {ch!r}", i)
    toks.append(_Tok(END, "", len(text)))
    return toks


# --- parser ------------------------------------------------------------------------


def expand_ranks(first, last):
    """Ranks from ``first`` to ``last`` inclusive, in either direction."""
    a, b = RANKS.index(first), RANKS.index(last)
    step = 1 if b >= a else -1
    return [RANKS[k] for k in range(a, b + step, step)]


@dataclass
class _RankItem:
    ranks: list
    face_up: bool


class _Parser:
    def __init__(self, text):
        self.toks = _tokenize(text)
        self.i = 0

    @property
    def tok(self):
        return self.toks[self.i]

    def take(self, type_=None):
        tok = self.tok
        if type_ is not None and tok.type != type_:
            raise ParseError(f"expected {self._describe(type_)}, found {self._found(tok)}", tok.pos)
        self.i += 1
        return tok

    def accept(self, type_):
        if self.tok.type == type_:
            return self.take()
        return None

    @staticmethod
    def _describe(type_):
        return {RANK: "a rank", SUIT: "a suit letter (C, H, S, D)", RPAREN: "')'",
                END: "end of input", COMMA: "','"}.get(type_, repr(type_))

    @staticmethod
    def _found(tok):
        return "end of input" if tok.type == END else repr(tok.value)

    def parse(self):
        cards = []
        while self.tok.type != END:
            if self.accept(COMMA):
                continue  # tolerate empty entries / trailing commas
            cards.extend(self.entry())
            if self.tok.type not in (COMMA, END):
                raise ParseError(
                    f"expected ',' between entries, found {self._found(self.tok)}", self.tok.pos
                )
        return cards

    def entry(self):
        if self.tok.type == LPAREN:
            return self.group()
        if self.tok.type == RANK:
            return self.chain()
        raise ParseError(f"expected a card, range or '(' but found {self._found(self.tok)}", self.tok.pos)

    def rank_spec(self):
        first = self.take(RANK).value
        if self.accept(DASH):
            return expand_ranks(first, self.take(RANK).value)
        return [first]

    def suit_chunks(self):
        """SUIT '`'? repeated; each chunk is (suit, face_up)."""
        chunks = []
        while self.tok.type == SUIT:
            suit = self.take().value
            chunks.append((suit, self.accept(TICK) is not None))
        return chunks

    def chain(self):
        ranks = self.rank_spec()
        chunks = self.suit_chunks()
        if not chunks:
            raise ParseError(f"expected a suit letter (C, H, S, D), found {self._found(self.tok)}",
                             self.tok.pos)
        return [Card(r, s, up) for s, up in chunks for r in ranks]

    def group(self):
        open_tok = self.take(LPAREN)
        rank_items, cards = [], []
        while True:
            if self.tok.type == LPAREN:
                raise ParseError("parentheses cannot be nested", self.tok.pos)
            if self.tok.type == RPAREN:
                break
            item_pos = self.tok.pos
            ranks = self.rank_spec()
            if self.tok.type == SUIT:
                chunks = self.suit_chunks()
                cards.extend(Card(r, s, up) for s, up in chunks for r in ranks)
            else:
                rank_items.append(_RankItem(ranks, self.accept(TICK) is not None))
            if rank_items and cards:
                raise ParseError(
                    "a group can hold bare ranks (suit after the ')') or full cards, not both",
                    item_pos,
                )
            if not self.accept(COMMA):
                break
        self.take(RPAREN)
        if not rank_items and not cards:
            raise ParseError("empty group '()'", open_tok.pos)
        group_up = self.accept(TICK) is not None
        chunks = self.suit_chunks()
        if cards:
            if chunks:
                raise ParseError(
                    "cards in this group already have suits; no suit letter after ')'",
                    open_tok.pos,
                )
            return [c.with_face_up(c.face_up or group_up) for c in cards]
        if not chunks:
            raise ParseError(
                f"expected a suit letter after the group, found {self._found(self.tok)}",
                self.tok.pos,
            )
        return [
            Card(r, suit, group_up or chunk_up or item.face_up)
            for suit, chunk_up in chunks
            for item in rank_items
            for r in item.ranks
        ]


def parse_cards(text):
    """Expand shorthand text into a list of Cards (no completeness check)."""
    return _Parser(text).parse()


# --- formatting -----------------------------------------------------------------------


def format_cards(cards, compress=True):
    """Shorthand for a card list. With ``compress``, runs of three or more
    consecutive same-suit, same-facing ranks become ranges (e.g. ``A-KC``).
    ``parse_cards(format_cards(x)) == x`` always holds."""
    parts = []
    i = 0
    while i < len(cards):
        c = cards[i]
        j = i + 1
        if compress and j < len(cards):
            step = _rank_step(c, cards[j])
            if step:
                while j < len(cards) and _rank_step(cards[j - 1], cards[j]) == step:
                    j += 1
        if j - i >= 3:
            last = cards[j - 1]
            parts.append(f"{c.rank}-{last.rank}{c.suit}" + ("`" if c.face_up else ""))
        else:
            j = i + 1
            parts.append(str(c))
        i = j
    return ", ".join(parts)


def _rank_step(a, b):
    if a.suit != b.suit or a.face_up != b.face_up:
        return 0
    d = RANKS.index(b.rank) - RANKS.index(a.rank)
    return d if d in (1, -1) else 0


def format_numbered(cards):
    """One card per line with its position (1 = top), for use at the table."""
    return "\n".join(f"{n:>2}. {c.pretty():<5} {c.name()}" for n, c in enumerate(cards, 1))


# --- validation -------------------------------------------------------------------------


@dataclass(frozen=True)
class DeckReport:
    count: int
    duplicates: list  # card keys appearing more than once, in first-seen order
    missing: list  # card keys absent, in new-deck (suit, rank) order

    @property
    def ok(self):
        return self.count == 52 and not self.duplicates and not self.missing

    def messages(self):
        out = []
        if self.count != 52:
            out.append(f"{self.count} cards entered; a full deck needs exactly 52.")
        if self.duplicates:
            out.append("Duplicated: " + ", ".join(self.duplicates))
        if self.missing:
            out.append("Missing: " + ", ".join(self.missing))
        return out


def validate_deck(cards):
    seen, dups = set(), []
    for c in cards:
        if c.key in seen and c.key not in dups:
            dups.append(c.key)
        seen.add(c.key)
    missing = [k for k in FULL_DECK_KEYS if k not in seen]
    return DeckReport(count=len(cards), duplicates=dups, missing=missing)


def parse_deck(text):
    """Parse shorthand and validate it as a full deck. Returns (cards, report)."""
    cards = parse_cards(text)
    return cards, validate_deck(cards)


# --- presets ------------------------------------------------------------------------------


def _from_keys(text):
    return [Card(k[0], k[1]) for k in text.split()]


def _si_stebbins():
    # CHaSeD suit cycle, each card three ranks above the last, starting AC.
    return [Card(RANKS[(3 * k) % 13], SUITS[k % 4]) for k in range(52)]


PRESETS = {
    # Bicycle-style new deck order: AH..KH, AC..KC, KD..AD, KS..AS.
    "New deck order": parse_cards("A-KH, A-KC, K-AD, K-AS"),
    "Si Stebbins (CHaSeD, +3)": _si_stebbins(),
    "Aronson stack": _from_keys(
        "JS KC 5C 2H 9S AS 3H 6C 8D AC TS 5H 2D KD 7D 8C 3S AD 7S 5S QD AH 8S 3D 7H QH "
        "5D 7C 4H KH 4D TD JC JH TC JD 4S TH 6H 3C 2S 9H KS 6S 4C 8H 9C QS 6D QC 2C 9D"
    ),
    "Mnemonica (Tamariz)": _from_keys(
        "4C 2H 7D 3C 4H 6D AS 5H 9S 2S QH 3D QC 8H 6S 5S 9H KC 2D JH 3S 8S 6H TC 5D KD "
        "2C 3H 8D 5C KS JD 8C TS KH JC 7S TH AD 4S 7H 4D AC 9C JS QD 7C QS TD 6C AH 9D"
    ),
}
