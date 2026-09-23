"""Find a shuffle sequence that turns one deck order into another.

Two stages:

1. A meet-in-the-middle search over every supported shuffle (full and partial
   faros, overhand runs, cuts). Each side stores everything up to two
   shuffles away, plus everything reachable by up to ``FARO_DEPTH`` full faros
   and then one more shuffle. For a search depth above 4 the remaining
   forward layers are streamed past the backward side without being stored.
   That finds a *shortest* sequence whenever one of ``depth`` (default
   ``SHORTEST_DEPTH``) or fewer shuffles exists, and also finds longer
   faro-heavy routes such as "4 out-faros, run 26, partial faro of 18, cut".
   Each streamed layer multiplies the time by the number of distinct
   shuffles (about 300): depth 5 takes seconds, 6 tens of minutes.
   Optional stepping stones (known stacks) are also tried as a midpoint:
   start -> stone -> target, each leg found by the same search.
2. Otherwise a constructive fallback that always succeeds, but is long. Read the deck as a
   circle: a cut only turns the circle, and an overhand run of X reverses the
   arc made of the top X cards in place. So "cut s, overhand run L" reverses
   any arc, and the fallback sorts the circle by arc reversals, then fixes the
   direction and turns it into place with a final cut.

Decks are handled as lists of target positions (the card that must finish on
top is 0), so the goal is always ``[0, 1, ..., n-1]``. Face-up flags are
ignored when matching cards. Inside the search a deck is stored the other way
round, as bytes giving each card's position, so a shuffle is one
``bytes.translate`` (it moves every card from position p to perm[p]).
"""

import time
from dataclasses import dataclass

from . import shuffle_ops as ops
from .solver import Step, simulate

SHORTEST_DEPTH = 5  # default depth: any route this short is found, so such a hit is optimal
MAX_DEPTH = 7  # 7 already means hundreds of billions of decks to check
STORED_DEPTH = 2  # layers kept in memory on each side; deeper ones are streamed
FARO_DEPTH = 6  # full faros tried in a row at each end of the search


class SearchCancelled(Exception):
    """Raised by ``find_path`` when its ``cancel`` callback returns True."""


@dataclass(frozen=True)
class PathResult:
    steps: list
    shortest: bool  # True when the search proved nothing shorter exists


def all_steps(n=ops.DECK_SIZE):
    """Every distinct single shuffle on an n-card deck.

    Shuffles that move the cards the same way as an earlier one are left out
    (a partial faro of n/2 is a full faro; "out-faro of top 1 into bottom" is
    cut 1), so the simpler name is the one reported.
    """
    steps = _faro_steps(n)
    for kind in ops.KINDS_WITH_X:
        lo, hi = ops.x_bounds(kind, n)
        steps += [Step(kind, x) for x in range(lo, hi + 1)]
    seen, distinct = set(), []
    for step in steps:
        perm = tuple(ops.permutation(step.kind, step.x, n))
        if perm not in seen:
            seen.add(perm)
            distinct.append(step)
    return distinct


def _faro_steps(n):
    return [Step(ops.OUT_FARO), Step(ops.IN_FARO)] if n % 2 == 0 else []


def target_positions(start, target):
    """``v[i]`` = where the card now at position i must finish. Cards match by key."""
    keys = [c.key for c in start]
    where = {c.key: i for i, c in enumerate(target)}
    if len(start) != len(target) or len(where) != len(target) or sorted(keys) != sorted(where):
        raise ValueError("the two orders must contain exactly the same cards")
    return [where[k] for k in keys]


def find_path(start, target, stones=(), depth=SHORTEST_DEPTH, cancel=None, progress=None,
              improved=None):
    """A list of Steps that turns ``start`` into ``target`` (same cards, any order).

    ``stones`` are other orders of the same cards that routes may pass through.
    Every route of up to ``depth`` shuffles is searched, so a result that short
    is a shortest one. ``cancel()`` is polled, and SearchCancelled is raised
    once it returns True. ``progress(fraction, text)`` is called now and then,
    with fraction None while the amount of work is unknown. ``improved(steps)``
    is called with each route shorter than any before it while the slow
    exhaustive layers run, starting with the fallback route, so a caller can
    show the best answer so far. All three are called on the thread running
    the search.
    """
    if not 1 <= depth <= MAX_DEPTH:
        raise ValueError(f"search depth must be between 1 and {MAX_DEPTH}, got {depth}")
    v = target_positions(start, target)
    n = len(v)
    if n > 256:
        raise ValueError("decks of more than 256 cards are not supported")
    report = _Reporter(cancel, progress)
    report(None, "Building search tables…", force=True)
    moves = _moves(all_steps(n), n)
    faro_moves = _moves(_faro_steps(n), n)
    near_f = min(STORED_DEPTH, (depth + 1) // 2)
    near_b = min(STORED_DEPTH, depth // 2)
    origin, goal = _state(v), _state(range(n))
    fwd = _side(origin, moves, faro_moves, True, near_f, report)
    bwd = _side(goal, moves, faro_moves, False, near_b, report)
    found = _meet(fwd, bwd)
    covered = near_f + near_b  # every route this short has been checked
    best = _Best(improved)

    def fallback():
        """The best route that is not from the exhaustive search (stones, constructive)."""
        candidates = []
        for k, stone in enumerate(stones):
            report(k / len(stones), "Trying known stacks as a midpoint…", force=True)
            w = _state(target_positions(stone, target))
            if w in (origin, goal):
                continue
            first = _meet(fwd, _side(w, moves, faro_moves, False, near_b, report))
            if first is None:
                continue
            second = _meet(_side(w, moves, faro_moves, True, near_f, report), bwd)
            if second is not None:
                candidates.append(_merge_cuts(first + second, n))
        candidates.append(_constructive(v))
        return min(candidates, key=len)

    stones = list(stones)
    backup = None
    layers = range(1, depth - covered + 1)
    if improved is not None and layers:
        # The streamed layers are slow; have an answer to show while they run.
        best.offer(found)
        if found is None or len(found) > depth:  # else the fallback could not win anyway
            backup = fallback()
            best.offer(backup)
    for extra in layers:
        if found is not None and len(found) < covered + extra:
            break  # this layer only adds routes of exactly covered + extra shuffles
        hit = _meet_streamed(fwd, bwd, moves, near_f, extra, report,
                             f"Checking routes of {covered + extra} shuffles…", best.offer)
        if hit is not None and (found is None or len(hit) < len(found)):
            found = hit
    if found is not None and len(found) <= depth:
        return PathResult(found, True)

    if backup is None:
        backup = fallback()
    candidates = [found, backup] if found is not None else [backup]
    return PathResult(min(candidates, key=len), False)


# --- search ------------------------------------------------------------------------


class _Reporter:
    """Polls ``cancel`` on every call; passes progress on at most ten times a second."""

    def __init__(self, cancel, progress):
        self.cancel, self.progress = cancel, progress
        self._last = 0.0

    def __call__(self, fraction, text, force=False):
        if self.cancel is not None and self.cancel():
            raise SearchCancelled()
        if self.progress is not None:
            now = time.monotonic()
            if force or now - self._last >= 0.1:
                self._last = now
                self.progress(fraction, text)


class _Best:
    """The shortest route known so far; passes each improvement on to ``improved``."""

    def __init__(self, improved):
        self.improved = improved
        self.steps = None

    def offer(self, steps):
        if steps is None or (self.steps is not None and len(steps) >= len(self.steps)):
            return
        self.steps = steps
        if self.improved is not None:
            self.improved(list(steps))


def _state(v):
    """Search form of a deck: ``state[c]`` is the position of card c (``v[i]`` = card at i)."""
    pos = bytearray(len(v))
    for i, c in enumerate(v):
        pos[c] = i
    return bytes(pos)


def _moves(steps, n):
    """(step, forward table, backward table) for ``bytes.translate`` on search states."""
    moves = []
    for step in steps:
        perm = ops.permutation(step.kind, step.x, n)
        inv = [0] * n
        for i, p in enumerate(perm):
            inv[p] = i
        pad = bytes(256 - n)
        moves.append((step, bytes(perm) + pad, bytes(inv) + pad))
    return moves


def _grow(frontier, moves, forward, depth, report):
    """Every state within ``depth`` moves of ``frontier`` (a state -> path dict).

    Forward paths lead from the start to the state; backward paths lead from
    the state to the goal. Each state keeps the first (shortest) path found.
    """
    steps = [step for step, _f, _b in moves]
    tables = [f if forward else b for _s, f, b in moves]
    found = dict(frontier)
    layer = frontier
    for _ in range(depth):
        nxt = {}
        for state, path in layer.items():
            report(None, "Building search tables…")
            for step, new in zip(steps, map(state.translate, tables)):
                if new not in found:
                    found[new] = nxt[new] = path + [step] if forward else [step] + path
        layer = nxt
    return found


def _side(origin, moves, faro_moves, forward, depth, report):
    """Everything ``depth`` moves from ``origin``, plus runs of full faros then one move."""
    near = _grow({origin: []}, moves, forward, depth, report)
    faros = _grow({origin: []}, faro_moves, forward, FARO_DEPTH, report)
    for state, path in _grow(faros, moves, forward, 1, report).items():
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


def _meet_streamed(fwd, bwd, moves, root_len, layers, report, text, on_hit=None):
    """Take every forward state ``root_len`` moves out ``layers`` moves further.

    Nothing is stored; each deck is only matched against the backward side,
    so this adds every route of root_len + layers + (backward depth) moves.
    On the last layer a state's whole set of next decks is checked in one
    C-level ``isdisjoint`` call; only a hit is looked at move by move, and
    each new best hit is passed to ``on_hit`` straight away.
    """
    steps = [step for step, _f, _b in moves]
    tables = [f for _s, f, _b in moves]
    targets = bwd.keys()
    roots = [(state, path) for state, path in fwd.items() if len(path) == root_len]
    best = None
    trail = []  # moves taken below the current root

    def walk(state, root_path, left):
        nonlocal best
        if left == 1:
            news = list(map(state.translate, tables))
            if targets.isdisjoint(news):
                return
            for step, new in zip(steps, news):
                if new in bwd:
                    route = root_path + trail + [step] + bwd[new]
                    if best is None or len(route) < len(best):
                        best = route
                        if on_hit is not None:
                            on_hit(best)
            return
        if left >= 3:
            report(done / len(roots), text)  # this deep, a single root takes seconds
        for step, new in zip(steps, map(state.translate, tables)):
            trail.append(step)
            walk(new, root_path, left - 1)
            trail.pop()

    for done, (state, path) in enumerate(roots):
        report(done / len(roots), text)
        walk(state, path, layers)
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
