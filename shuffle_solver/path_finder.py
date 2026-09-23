"""Find a shuffle sequence that turns one deck order into another.

Two stages:

1. A meet-in-the-middle search over every supported shuffle (full and partial
   faros, overhand runs, cuts). Each side stores everything two shuffles away,
   plus everything reachable by up to ``FARO_DEPTH`` full faros and then one
   more shuffle; one more forward layer is streamed past the backward side.
   That finds a *shortest* sequence whenever one of ``SHORTEST_DEPTH`` or
   fewer shuffles exists, and also finds longer
   faro-heavy routes such as "4 out-faros, run 26, partial faro of 18, cut".
   Optional stepping stones (known stacks) are also tried as a midpoint:
   start -> stone -> target, each leg found by the same search.
2. Otherwise a constructive fallback that always succeeds, but is long. Read the deck as a
   circle: a cut only turns the circle, and an overhand run of X reverses the
   arc made of the top X cards in place. So "cut s, overhand run L" reverses
   any arc, and the fallback sorts the circle by arc reversals, then fixes the
   direction and turns it into place with a final cut.

Decks are handled as lists of target positions (the card that must finish on
top is 0), so the goal is always ``[0, 1, ..., n-1]``. Face-up flags are
ignored when matching cards.
"""

from dataclasses import dataclass

from . import shuffle_ops as ops
from .solver import Step, simulate

SHORTEST_DEPTH = 5  # any route this short is found, so a hit this short is optimal
FARO_DEPTH = 6  # full faros tried in a row at each end of the search
PREFIX = 6  # top cards compared before a full-deck match in the streamed layer


@dataclass(frozen=True)
class PathResult:
    steps: list
    shortest: bool  # True when the search proved nothing shorter exists


def all_steps(n=ops.DECK_SIZE):
    """Every distinct single shuffle on an n-card deck."""
    steps = _faro_steps(n)
    for kind in ops.KINDS_WITH_X:
        lo, hi = ops.x_bounds(kind, n)
        steps += [Step(kind, x) for x in range(lo, hi + 1)]
    return steps


def _faro_steps(n):
    return [Step(ops.OUT_FARO), Step(ops.IN_FARO)] if n % 2 == 0 else []


def target_positions(start, target):
    """``v[i]`` = where the card now at position i must finish. Cards match by key."""
    keys = [c.key for c in start]
    where = {c.key: i for i, c in enumerate(target)}
    if len(start) != len(target) or len(where) != len(target) or sorted(keys) != sorted(where):
        raise ValueError("the two orders must contain exactly the same cards")
    return [where[k] for k in keys]


def find_path(start, target, stones=()):
    """A list of Steps that turns ``start`` into ``target`` (same cards, any order).

    ``stones`` are other orders of the same cards that routes may pass through.
    """
    v = target_positions(start, target)
    n = len(v)
    moves = _moves(all_steps(n), n)
    faro_moves = _moves(_faro_steps(n), n)
    fwd = _side(tuple(v), moves, faro_moves, True)
    bwd = _side(tuple(range(n)), moves, faro_moves, False)
    found = _meet(fwd, bwd)
    if found is None or len(found) > 4:
        found = _meet_streamed(fwd, bwd, moves) or found
    if found is not None and len(found) <= SHORTEST_DEPTH:
        return PathResult(found, True)

    candidates = [found] if found is not None else []
    for stone in stones:
        w = tuple(target_positions(stone, target))
        if w in (tuple(v), tuple(range(n))):
            continue
        first = _meet(fwd, _side(w, moves, faro_moves, False))
        if first is None:
            continue
        second = _meet(_side(w, moves, faro_moves, True), bwd)
        if second is not None:
            candidates.append(_merge_cuts(first + second, n))
    candidates.append(_constructive(v))
    return PathResult(min(candidates, key=len), False)


# --- search ------------------------------------------------------------------------


def _moves(steps, n):
    moves = []
    for step in steps:
        perm = ops.permutation(step.kind, step.x, n)
        inv = [0] * n
        for i, p in enumerate(perm):
            inv[p] = i
        moves.append((step, tuple(perm), tuple(inv)))
    return moves


def _grow(frontier, moves, forward, depth):
    """Every state within ``depth`` moves of ``frontier`` (a state -> path dict).

    Forward paths lead from the start to the state; backward paths lead from
    the state to the goal. Each state keeps the first (shortest) path found.
    """
    found = dict(frontier)
    layer = frontier
    for _ in range(depth):
        nxt = {}
        for state, path in layer.items():
            get = state.__getitem__
            for step, perm, inv in moves:
                # Applying perm moves the card at i to perm[i], i.e. out[j] = state[inv[j]].
                new = tuple(map(get, inv if forward else perm))
                if new not in found:
                    found[new] = nxt[new] = path + [step] if forward else [step] + path
        layer = nxt
    return found


def _side(origin, moves, faro_moves, forward):
    """Everything two moves from ``origin``, plus runs of full faros then one move."""
    near = _grow({origin: []}, moves, forward, 2)
    faros = _grow({origin: []}, faro_moves, forward, FARO_DEPTH)
    for state, path in _grow(faros, moves, forward, 1).items():
        if state not in near or len(path) < len(near[state]):
            near[state] = path
    return near


def _meet(fwd, bwd):
    """The shortest route through a state both sides reached, or None."""
    small, large = (fwd, bwd) if len(fwd) <= len(bwd) else (bwd, fwd)
    best = None
    for state in small:
        if state in large:
            total = len(fwd[state]) + len(bwd[state])
            if best is None or total < len(best):
                best = fwd[state] + bwd[state]
    return best


def _meet_streamed(fwd, bwd, moves):
    """Take every state two moves from the start one move further, without storing them.

    With the backward side's two moves this covers every route of 5 moves.
    Candidates are matched on their top few cards first, which is much
    cheaper than building every full deck.
    """
    k = PREFIX
    by_prefix = {}
    for state in bwd:
        by_prefix.setdefault(state[:k], []).append(state)
    short = [(step, inv, inv[:k]) for step, _perm, inv in moves]
    best = None
    for state, path in fwd.items():
        if len(path) != 2:
            continue
        get = state.__getitem__
        for step, inv, inv_k in short:
            hits = by_prefix.get(tuple(map(get, inv_k)))
            if hits is None:
                continue
            new = tuple(map(get, inv))
            if new in bwd and (best is None or 3 + len(bwd[new]) < len(best)):
                best = path + [step] + bwd[new]
    return best


# --- constructive fallback ------------------------------------------------------------


def _adjacent(a, b, n):
    return (a - b) % n in (1, n - 1)


def _reverse_arc(deck, s, length, out):
    """Reverse the circular arc of ``length`` cards starting at position s."""
    n = len(deck)
    if s % n:
        out.append(Step(ops.CUT, s % n))
        deck = deck[s % n:] + deck[:s % n]
    out.append(Step(ops.OVERHAND_RUN, length))
    return deck[length:] + deck[:length][::-1]


def _finish(deck, out):
    """Deck is 0..n-1 around the circle in some direction: straighten and align it."""
    n = len(deck)
    p = deck.index(0)
    if n > 1 and deck[(p + 1) % n] != 1:
        out.append(Step(ops.OVERHAND_RUN, n))  # reverse the whole deck
        deck = deck[::-1]
        p = deck.index(0)
    if p:
        out.append(Step(ops.CUT, p))
        deck = deck[p:] + deck[:p]
    return deck


def _greedy_reversals(v):
    """Breakpoint-greedy sorting by arc reversals. Usually well under 2 moves per card."""
    n = len(v)
    deck, out = list(v), []
    for _ in range(3 * n):
        adj = [_adjacent(deck[g - 1], deck[g], n) for g in range(n)]  # gap g sits above card g
        if all(adj):
            break
        best = None
        for g1 in range(n):
            for g2 in range(g1 + 1, n):
                gain = (_adjacent(deck[g1 - 1], deck[g2 - 1], n) + _adjacent(deck[g1], deck[g2], n)
                        - adj[g1] - adj[g2])
                # Reversing the arc [g1, g2) and its complement are mirror images, so
                # prefer whichever starts at the top (a single overhand run, no cut).
                s, length = (0, g2) if g1 == 0 else (g1, g2 - g1)
                cost = 1 if s == 0 else 2
                key = (gain, -cost)
                if best is None or key > best[0]:
                    best = (key, s, length)
        (gain, _), s, length = best
        if gain <= 0:
            # Every run points the same way: flip one run so the next move gains.
            s, length = _one_run(deck, adj)
        deck = _reverse_arc(deck, s, length, out)
    else:
        return None
    _finish(deck, out)
    return out


def _one_run(deck, adj):
    """(start, length) of a run of already-adjacent cards, not the whole deck."""
    n = len(deck)
    s = next(g for g in range(n) if not adj[g])
    length = 1
    while length < n and adj[(s + length) % n]:
        length += 1
    return s, max(length, 2) if length < n else 2


def _selection(v):
    """Simple guaranteed method: bring each next card right after the previous one."""
    n = len(v)
    deck, out = list(v), []
    for i in range(1, n):
        p, q = deck.index(i - 1), deck.index(i)
        s = (p + 1) % n
        if q != s:
            deck = _reverse_arc(deck, s, (q - s) % n + 1, out)
    _finish(deck, out)
    return out


def _merge_cuts(steps, n):
    out = []
    for step in steps:
        if step.kind == ops.CUT and out and out[-1].kind == ops.CUT:
            x = (out.pop().x + step.x) % n
            if x:
                out.append(Step(ops.CUT, x))
        else:
            out.append(step)
    return out


def _constructive(v):
    n = len(v)
    goal = list(range(n))
    candidates = [c for c in (_greedy_reversals(v), _selection(v)) if c is not None]
    candidates = [_merge_cuts(c, n) for c in candidates]
    candidates = [c for c in candidates if simulate(v, c) == goal]
    if not candidates:  # the selection method is always correct; this is a safety net
        raise RuntimeError("could not construct a shuffle sequence")
    return min(candidates, key=len)
