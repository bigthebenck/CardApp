"""Poker deals: where each dealt card comes from in the deck, and the stack for a deal.

Cards are dealt from the top, one at a time, going round the table. Player 1
sits on the dealer's left and gets the first card; the last player is the
dealer. Five-card poker deals five rounds. Texas hold'em deals two rounds of
hole cards, then the flop (3 cards), the turn and the river, each after a
burn card unless burns are turned off.

``build_stack`` turns the cards wanted in each hand into a 52-card starting
order; ``deal`` deals a deck out again, so a stack can be checked.
"""

from dataclasses import dataclass

from . import deck

FIVE_CARD, HOLDEM = "five_card", "holdem"
GAMES = {FIVE_CARD: "5-card poker", HOLDEM: "Texas hold'em"}
MIN_PLAYERS, MAX_PLAYERS = 2, 10
DECK_SIZE = 52

BURN = "Burn"
BOARD = (("Flop", 3), ("Turn", 1), ("River", 1))  # hold'em community cards, in deal order
HAND_SIZES = {FIVE_CARD: 5, HOLDEM: 2}


def player_name(p):
    """1 -> "Player 1"."""
    return f"Player {p}"


@dataclass(frozen=True)
class Spot:
    """Where one dealt card goes: card ``index`` (0-based) of ``hand``."""

    hand: str  # a player's name, a BOARD name, or BURN
    index: int


def hands(game, players):
    """(name, size) of each hand that can be chosen, players first."""
    _check(game, players)
    out = [(player_name(p), HAND_SIZES[game]) for p in range(1, players + 1)]
    if game == HOLDEM:
        out += list(BOARD)
    return out


def layout(game, players, burns=True):
    """The Spot each card goes to, top of the deck first."""
    _check(game, players)
    spots = [Spot(player_name(p), r)
             for r in range(HAND_SIZES[game]) for p in range(1, players + 1)]
    if game == HOLDEM:
        for n, (name, size) in enumerate(BOARD):
            if burns:
                spots.append(Spot(BURN, n))
            spots += [Spot(name, i) for i in range(size)]
    return spots


def _check(game, players):
    if game not in GAMES:
        raise ValueError(f"unknown game {game!r}")
    if not MIN_PLAYERS <= players <= MAX_PLAYERS:
        raise ValueError(f"pick {MIN_PLAYERS} to {MAX_PLAYERS} players")


def build_stack(game, players, wanted, burns=True, fill=False):
    """The 52-card starting order that deals ``wanted`` (hand name -> cards).

    A hand may list fewer cards than it holds, and X stands for a card that
    doesn't matter; both leave an indifferent card in that spot. Every other
    position is indifferent too, unless ``fill`` puts the unused cards there
    in new deck order. Raises ValueError for an unknown hand, a hand with too
    many cards, or a card wanted twice.
    """
    sizes = dict(hands(game, players))
    for name, cards in wanted.items():
        if name not in sizes:
            raise ValueError(f"no hand called {name!r}")
        if len(cards) > sizes[name]:
            raise ValueError(f"{name} holds {sizes[name]} card"
                             f"{'s' if sizes[name] != 1 else ''}, not {len(cards)}")
    where = {}  # card key -> the hands it is wanted in, once per time
    for name, cards in wanted.items():
        for c in cards:
            if not c.indifferent:
                where.setdefault(c.key, []).append(name)
    twice = [f"{deck.Card(k[0], k[1]).pretty()} ("
             + (f"twice in {names[0]}" if len(set(names)) == 1 else " and ".join(names)) + ")"
             for k, names in where.items() if len(names) > 1]
    if twice:
        raise ValueError("Wanted twice: " + "; ".join(twice))

    stack = [deck.indifferent_card()] * DECK_SIZE
    for i, spot in enumerate(layout(game, players, burns)):
        cards = wanted.get(spot.hand, [])
        if spot.index < len(cards):
            stack[i] = cards[spot.index].with_face_up(False)
    if fill:
        spare = iter(c for c in deck.PRESETS["New deck order"]
                     if c.key not in {s.key for s in stack})
        stack = [next(spare) if c.indifferent else c for c in stack]
    return stack


def deal(stack, game, players, burns=True):
    """Deal ``stack`` (top first): hand name -> the cards it gets, burns included."""
    dealt = {}
    for card, spot in zip(stack, layout(game, players, burns)):
        dealt.setdefault(spot.hand, []).append(card)
    return dealt
