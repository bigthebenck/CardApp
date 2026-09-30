"""Cards on a table: named piles, and the steps that shuffle, split and rebuild them.

The Free Tracking tab follows a deck forward through a list of steps. Besides
shuffles, a step can take cards out, add new ones, split a pile into packets,
put one pile on another, or gather piles back into one. Every step turns one
``Table`` into the next and raises ``ValueError`` (with a message fit to show)
when it can't be done on that table.

Piles are named with letters: the starting deck is "A", and each new pile
takes the next letter. Letters are never reused, so a step keeps pointing at
the same pile however the table changes around it.

Several piles are written in shorthand with ``|`` between them, each pile
optionally named with its letter and a colon: ``A: 2-KC, AC | B: 2-KH, AH``
(see ``parse_piles`` and ``format_piles``).

Indifferent cards (``X``, ``X12``) may be tracked too: each stands in for a card
whose identity doesn't matter. They are never duplicates of one another, and
can't be named to take out, since one is as good as any other. A ``NameCards``
step turns some of them into real cards partway through, e.g. once it matters
which card sits where a faro splits; ``replay`` names them in earlier tables too.
"""

import re
from dataclasses import dataclass

from . import deck
from . import shuffle_ops as ops
from . import solver

START_PILE = "A"


def pile_name(i):
    """0 -> "A", 25 -> "Z", 26 -> "AA", ..."""
    name = ""
    i += 1
    while i:
        i, r = divmod(i - 1, 26)
        name = chr(ord("A") + r) + name
    return name


def pile_index(name):
    """The inverse of ``pile_name``: "A" -> 0, "AA" -> 26."""
    i = 0
    for ch in name:
        i = i * 26 + ord(ch) - ord("A") + 1
    return i - 1


_PILE_START = re.compile(r"^\s*([A-Za-z]{1,3})\s*:(.*)$", re.S)


def parse_piles(text):
    """Shorthand for one or more piles -> ((name or None, cards), ...).

    Piles are separated by ``|``, or by a line starting with a pile name, as in
    ``A: 2-KC, AC | B: 2-KH, AH``. Either every pile is named or none is.
    Raises ValueError (a ``deck.ParseError`` names the pile it is in).
    """
    chunks = []
    for part in text.split("|"):
        lines = re.split(r"\n(?=\s*[A-Za-z]{1,3}\s*:)", part)
        chunks.extend([c for c in lines if c.strip()] or [part])
    piles = []
    for n, chunk in enumerate(chunks, 1):
        m = _PILE_START.match(chunk)
        name, body = (m.group(1).upper(), m.group(2)) if m else (None, chunk)
        where = f"pile {name}" if name else f"pile {n}"
        if not body.strip():
            raise ValueError(f"{where} has no cards" if len(chunks) > 1 else "no cards given")
        try:
            cards = deck.parse_cards(body, allow_indifferent=True)
        except ValueError as exc:
            raise ValueError(f"{where}: {exc}") from exc
        piles.append((name, tuple(cards)))
    named = [name is not None for name, _cards in piles]
    if any(named) and not all(named):
        raise ValueError("name every pile (A: ... | B: ...) or none of them")
    names = [name for name, _cards in piles if name]
    dups = sorted({x for x in names if names.count(x) > 1})
    if dups:
        raise ValueError(f"pile {dups[0]} is named twice")
    return tuple(piles)


def format_piles(piles, names=True):
    """Shorthand for ``piles`` (Piles, or (name, cards) pairs), one per line.

    Several piles get their names and ``|``. A table's single pile is written
    as plain cards, as is an unnamed one; a single (name, cards) pair keeps
    the name it was typed with.
    """
    pairs = [(p.name, p.cards) if isinstance(p, Pile) else p for p in piles]
    lone_plain = pairs and (pairs[0][0] is None or isinstance(piles[0], Pile) or not names)
    if len(pairs) == 1 and lone_plain:
        return deck.format_cards(list(pairs[0][1]))
    return " |\n".join((f"{name}: " if name and names else "") + deck.format_cards(list(cards))
                        for name, cards in pairs)


def _cards(cards):
    return " ".join(c.pretty() for c in cards)


def _count(n):
    return f"{n} card{'s' if n != 1 else ''}"


@dataclass(frozen=True)
class Pile:
    name: str
    cards: tuple

    def __len__(self):
        return len(self.cards)


@dataclass(frozen=True)
class Table:
    piles: tuple  # of Pile, in the order they lie on the table
    next_name: int = 1  # index (see ``pile_name``) of the next new pile

    @classmethod
    def start(cls, cards):
        return cls((Pile(START_PILE, tuple(cards)),), 1)

    @property
    def names(self):
        return [p.name for p in self.piles]

    def pile(self, name):
        for p in self.piles:
            if p.name == name:
                return p
        raise ValueError(f"there is no pile {name} on the table")

    def cards(self):
        return [c for p in self.piles for c in p.cards]

    def keys(self):
        """Keys of the named cards; indifferent cards have no identity to count."""
        return {c.key for c in self.cards() if not c.indifferent}

    def indifferent_count(self):
        return sum(c.indifferent for c in self.cards())

    def _index(self, name):
        return self.names.index(self.pile(name).name)

    def with_pile(self, name, cards):
        """This table with pile ``name`` holding ``cards`` (dropped if they're none)."""
        i = self._index(name)
        rest = self.piles[:i] + self.piles[i + 1:]
        if not cards:
            return Table(rest, self.next_name)
        return Table(rest[:i] + (Pile(name, tuple(cards)),) + rest[i:], self.next_name)

    def with_new_piles(self, packets, after=None):
        """Add each packet as a new pile, after pile ``after`` (or at the end)."""
        new = tuple(Pile(pile_name(self.next_name + k), tuple(cards))
                    for k, cards in enumerate(packets))
        at = len(self.piles) if after is None else self._index(after) + 1
        return Table(self.piles[:at] + new + self.piles[at:], self.next_name + len(new))


# --- steps ---------------------------------------------------------------------------------


@dataclass(frozen=True)
class Shuffle:
    """A shuffle (``solver.Step``) done to one pile."""

    step: solver.Step
    pile: str = START_PILE

    kind = property(lambda self: self.step.kind)
    x = property(lambda self: self.step.x)
    y = property(lambda self: self.step.y)

    def label(self):
        return self.step.label() + ("" if self.pile == START_PILE else f" on pile {self.pile}")

    def apply(self, table):
        cards = list(table.pile(self.pile).cards)
        if self.kind in (ops.OUT_FARO, ops.IN_FARO) and len(cards) % 2:
            raise ValueError(f"pile {self.pile} has {_count(len(cards))}; a full faro needs "
                             "an even number, so use a partial faro")
        try:
            self.step.validate(len(cards))
        except TypeError as exc:
            raise ValueError(str(exc)) from exc
        return table.with_pile(self.pile, solver.apply_step(cards, self.step))


TAKE_OUT_MODES = {"pile": "as a new pile", "each": "each as its own pile", "discard": "and discard"}


@dataclass(frozen=True)
class TakeOut:
    """Take named cards out of whatever piles they are in.

    ``mode`` "pile" puts them together as one new pile, in the order listed;
    "each" makes a pile of every card; "discard" puts them away for good.
    """

    cards: tuple
    mode: str = "pile"
    kind = "take_out"

    def label(self):
        return f"Take out {_cards(self.cards)} {TAKE_OUT_MODES[self.mode]}"

    def apply(self, table):
        if not self.cards:
            raise ValueError("name at least one card to take out")
        if self.mode not in TAKE_OUT_MODES:
            raise ValueError(f"unknown take-out mode {self.mode!r}")
        if any(c.indifferent for c in self.cards):
            raise ValueError("indifferent cards (X) can't be taken out by name; "
                             "split them off instead")
        wanted = [c.key for c in self.cards]
        if len(set(wanted)) != len(wanted):
            raise ValueError("a card is named twice")
        found = {c.key: c for c in table.cards()}  # keeps a face-up card face up
        missing = [c.pretty() for c in self.cards if c.key not in found]
        if missing:
            raise ValueError(f"not on the table: {' '.join(missing)}")
        for p in table.piles:
            table = table.with_pile(p.name, [c for c in p.cards if c.key not in wanted])
        taken = [found[k] for k in wanted]
        if self.mode == "pile":
            return table.with_new_piles([taken])
        if self.mode == "each":
            return table.with_new_piles([[c] for c in taken])
        return table


@dataclass(frozen=True)
class AddCards:
    """Put new cards into a pile, the first at ``position`` (1 = top); no pile: a new pile."""

    cards: tuple
    pile: str | None = START_PILE
    position: int = 1
    kind = "add_cards"

    def label(self):
        if self.pile is None:
            return f"Add {_cards(self.cards)} as a new pile"
        return f"Add {_cards(self.cards)} to pile {self.pile} at {self.position}"

    def apply(self, table):
        if not self.cards:
            raise ValueError("name at least one card to add")
        keys = [c.key for c in self.cards]
        dups = [c.pretty() for c in self.cards if not c.indifferent
                and (c.key in table.keys() or keys.count(c.key) > 1)]
        if dups:
            raise ValueError(f"already in play: {' '.join(dict.fromkeys(dups))}")
        if self.pile is None:
            return table.with_new_piles([self.cards])
        cards = list(table.pile(self.pile).cards)
        if not 1 <= self.position <= len(cards) + 1:
            raise ValueError(f"pile {self.pile} has {_count(len(cards))}; the position must "
                             f"be between 1 and {len(cards) + 1}")
        at = self.position - 1
        return table.with_pile(self.pile, cards[:at] + list(self.cards) + cards[at:])


@dataclass(frozen=True)
class NameCards:
    """Say which cards some indifferent cards are (and were: see ``replay``).

    The X cards at ``position`` (1 = top) and on down pile ``pile`` become
    ``cards``, in order; a face-up X stays face up. Every one of those spots
    must hold an X, and the named cards must not already be on the table.
    """

    cards: tuple
    pile: str = START_PILE
    position: int = 1
    kind = "name_cards"

    def label(self):
        end = self.position + len(self.cards) - 1
        where = f"{self.position}" if end == self.position else f"{self.position}–{end}"
        return f"Name X at {where} of pile {self.pile} as {_cards(self.cards)}"

    def apply(self, table):
        if not self.cards:
            raise ValueError("name at least one card")
        if any(c.indifferent for c in self.cards):
            raise ValueError("give real cards to name the X cards as, not X")
        keys = [c.key for c in self.cards]
        dups = [c.pretty() for c in self.cards if c.key in table.keys() or keys.count(c.key) > 1]
        if dups:
            raise ValueError(f"already in play: {' '.join(dict.fromkeys(dups))}")
        cards = list(table.pile(self.pile).cards)
        at, end = self.position - 1, self.position - 1 + len(self.cards)
        if at < 0 or end > len(cards):
            raise ValueError(f"pile {self.pile} has {_count(len(cards))}; there's no room for "
                             f"{_count(len(self.cards))} from position {self.position}")
        named = [n for n in range(at, end) if not cards[n].indifferent]
        if named:
            raise ValueError("not an X card at position "
                             + ", ".join(f"{n + 1} ({cards[n].pretty()})" for n in named))
        cards[at:end] = [c.with_face_up(c.face_up or old.face_up)
                         for c, old in zip(self.cards, cards[at:end])]
        return table.with_pile(self.pile, cards)


@dataclass(frozen=True)
class Split:
    """Split a pile into packets of ``sizes`` cards, from the top.

    The top packet keeps the pile's name; the others become new piles next to
    it, in order. Cards left over after the last size form one more packet.
    """

    pile: str
    sizes: tuple
    kind = "split"

    def label(self):
        return f"Split pile {self.pile} into {', '.join(map(str, self.sizes))}"

    def apply(self, table):
        cards = list(table.pile(self.pile).cards)
        if not self.sizes or any(not isinstance(s, int) or s < 1 for s in self.sizes):
            raise ValueError("packet sizes must be whole numbers of at least 1")
        if sum(self.sizes) > len(cards):
            raise ValueError(f"packets of {sum(self.sizes)} cards in all, but pile "
                             f"{self.pile} has {_count(len(cards))}")
        packets, at = [], 0
        for size in self.sizes:
            packets.append(cards[at:at + size])
            at += size
        if at < len(cards):
            packets.append(cards[at:])
        if len(packets) < 2:
            raise ValueError("that leaves the pile in one piece")
        table = table.with_pile(self.pile, packets[0])
        return table.with_new_piles(packets[1:], after=self.pile)


@dataclass(frozen=True)
class Place:
    """Put pile ``pile`` on top of (or under) pile ``onto``, which keeps its name."""

    pile: str
    onto: str
    top: bool = True
    kind = "place"

    def label(self):
        return f"Put pile {self.pile} {'on top of' if self.top else 'under'} pile {self.onto}"

    def apply(self, table):
        if self.pile == self.onto:
            raise ValueError("a pile can't go on itself")
        moved, base = table.pile(self.pile).cards, table.pile(self.onto).cards
        table = table.with_pile(self.onto, moved + base if self.top else base + moved)
        return table.with_pile(self.pile, [])


@dataclass(frozen=True)
class Gather:
    """Stack piles into one, the first named on top; no names: every pile, in table order."""

    names: tuple = ()
    kind = "gather"

    def label(self):
        return f"Gather piles {', '.join(self.names)}" if self.names else "Gather all piles"

    def apply(self, table):
        names = list(self.names) or table.names
        if len(set(names)) != len(names):
            raise ValueError("a pile is named twice")
        if len(names) < 2:
            raise ValueError("gathering needs at least two piles")
        stacked = [c for name in names for c in table.pile(name).cards]
        for name in names[1:]:
            table = table.with_pile(name, [])
        return table.with_pile(names[0], stacked)


@dataclass(frozen=True)
class Rearrange:
    """Set the table to a new arrangement of the same cards, e.g. after a trick.

    ``piles`` are (name or None, cards) pairs as from ``parse_piles``. Unnamed
    piles take the names of the piles already on the table, in order, and new
    letters after those. Cards may turn face up or down, but no card may
    appear, vanish or be doubled, and there must be as many indifferent cards (X) as
    before.
    """

    title: str
    piles: tuple
    kind = "rearrange"

    def label(self):
        n = len(self.piles)
        return (f"Rearrange: {self.title or 'new order'}"
                + (f" ({n} piles)" if n != 1 else ""))

    def text(self):
        """The piles back as shorthand, as they were entered."""
        return format_piles(self.piles)

    def apply(self, table):
        if not self.piles:
            raise ValueError("give the new order")
        new = [c for _name, cards in self.piles for c in cards]
        keys = [c.key for c in new if not c.indifferent]
        have = table.keys()
        twice = list(dict.fromkeys(k for k in keys if keys.count(k) > 1))
        extra = [k for k in dict.fromkeys(keys) if k not in have]
        missing = [c.key for c in table.cards()
                   if not c.indifferent and c.key not in set(keys)]
        problems = []
        if missing:
            problems.append("missing " + " ".join(_pretty_keys(missing)))
        if extra:
            problems.append("not on the table " + " ".join(_pretty_keys(extra)))
        if twice:
            problems.append("given twice " + " ".join(_pretty_keys(twice)))
        x_new, x_old = sum(c.indifferent for c in new), table.indifferent_count()
        if x_new != x_old:
            problems.append(f"{x_new} indifferent cards (X) where the table has {x_old}")
        if problems:
            raise ValueError("the new order must hold exactly the cards on the table: "
                             + "; ".join(problems))
        if self.piles[0][0] is not None:
            names = [name for name, _cards in self.piles]
        else:
            old = table.names
            extra_count = max(len(self.piles) - len(old), 0)
            names = old[:len(self.piles)] + [pile_name(table.next_name + k)
                                               for k in range(extra_count)]
        next_name = max([table.next_name] + [pile_index(n) + 1 for n in names])
        return Table(tuple(Pile(n, cards) for n, (_name, cards) in zip(names, self.piles)),
                     next_name)


def _pretty_keys(keys):
    return [deck.parse_cards(k)[0].pretty() for k in keys]


@dataclass(frozen=True)
class _TaggedX(deck.Card):
    """An indifferent card that ``replay`` can follow from table to table."""

    tag: int = 0

    def with_face_up(self, face_up):
        return _TaggedX(self.rank, self.suit, face_up, self.tag)


def _map_cards(table, fn):
    return Table(tuple(Pile(p.name, tuple(fn(c) for c in p.cards)) for p in table.piles),
                 table.next_name)


def replay(cards, steps):
    """([table at start, after step 1, ...], error): tables up to the first step that fails.

    ``error`` is (index of that step, message), or None when every step works.

    Naming X cards (``NameCards``) reaches back as well: an X card was that
    card all along, so every earlier table shows it too, back to where the X
    first appeared (the starting deck, added cards, or a rearrangement). That
    fails if the card was already on the table somewhere in between.
    """
    tags = iter(range(1, 1 << 62))

    def tag_new(table):
        return _map_cards(table, lambda c: _TaggedX(c.rank, c.suit, c.face_up, next(tags))
                          if c.indifferent and not isinstance(c, _TaggedX) else c)

    tables = [tag_new(Table.start(cards))]
    error = None
    for i, step in enumerate(steps):
        try:
            after = step.apply(tables[-1])
            if isinstance(step, NameCards):
                _name_back(tables, step)
        except (ValueError, TypeError) as exc:
            error = (i, str(exc))
            break
        tables.append(tag_new(after))
    untag = (lambda c: deck.indifferent_card(c.face_up) if isinstance(c, _TaggedX) else c)
    return [_map_cards(t, untag) for t in tables], error


def _name_back(tables, step):
    """Put ``step``'s named cards in place of the X cards they were, in every table so far."""
    at = step.position - 1
    xs = tables[-1].pile(step.pile).cards[at:at + len(step.cards)]
    names = {x.tag: card for x, card in zip(xs, step.cards)}
    named = []
    for j, table in enumerate(tables):
        tags_here = {c.tag for c in table.cards() if isinstance(c, _TaggedX)}
        clash = [card.pretty() for tag, card in names.items()
                 if tag in tags_here and card.key in table.keys()]
        if clash:
            where = "in the starting deck" if j == 0 else f"before step {j + 1}"
            raise ValueError(f"{' '.join(clash)} is already on the table {where}, "
                             "where that X card was too")
        named.append(_map_cards(table, lambda c: names[c.tag].with_face_up(
            names[c.tag].face_up or c.face_up) if getattr(c, "tag", None) in names else c))
    tables[:] = named
