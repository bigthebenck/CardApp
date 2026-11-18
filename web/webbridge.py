"""JSON bridge between the phone web app (in a Web Worker) and the Qt-free model.

The page sends ``handle(op, args_json)`` calls; each returns a JSON string:
``{"state": ...}`` (the whole Starting Order state after the change), or for
the Free Tracking ops (named ``t_...``) ``{"tracker": ...}``, or another
payload for read-only ops. All shuffle math stays in ``shuffle_solver``;
this module only translates between it and plain JSON.

Cards travel as their shorthand text (``"AC"``, ``"TH`"``, ``"X"``), or None
for an empty slot.
"""

import json
import re

from shuffle_solver import __version__, deck, solver, tracking
from shuffle_solver import shuffle_ops as ops
from shuffle_solver.ui.model import (AppModel, TrackerModel, format_instructions, format_splits,
                                     split_note)

model = AppModel()
tracker = TrackerModel()


def _card(c):
    return None if c is None else str(c)


def _cards(cards):
    return [_card(c) for c in cards]


def _parse_one(text):
    cards = deck.parse_cards(text, allow_indifferent=True)
    if len(cards) != 1:
        raise ValueError("one card per slot")
    return cards[0]


def meta():
    kinds = []
    for kind in ops.SHUFFLE_KINDS:
        entry = {"kind": kind, "label": solver.kind_label(kind),
                 "hasX": kind in ops.KINDS_WITH_X, "hasY": kind in ops.KINDS_WITH_Y}
        if kind in ops.KINDS_WITH_X:
            entry["min"], entry["max"] = ops.x_bounds(kind)
        if kind in ops.PARTIAL_FAROS:
            source, dest, out = ops.PARTIAL_FAROS[kind]
            entry.update(source=source, dest=dest, out=out)
        kinds.append(entry)
    return {"version": __version__, "presets": list(deck.PRESETS), "kinds": kinds}


def state():
    m = model
    res = m.result
    report = m.deck_report()
    if report.ok:
        x = report.indifferent
        deck_status = ("Full 52-card deck, no duplicates." if not x else
                       f"52 cards, no duplicates; {x} indifferent ({report.counts_text()}).")
    else:
        deck_status = "\n".join(report.messages())
    states = res.states if res.has_answer else None
    steps = [{"kind": s.kind, "x": s.x, "y": s.y, "label": s.label(),
              "split": split_note(s, states[k]) if states else ""}
             for k, s in enumerate(m.steps)]
    result = {"status": res.status, "messages": res.messages, "verified": res.verified,
              "start": _cards(res.start) if res.has_answer else None,
              "states": [_cards(s) for s in states] if states else None}
    return {"slots": _cards(m.slots), "text": m.final_text(), "inputError": m.input_error,
            "dups": sorted(m.duplicate_slots()), "deckOk": report.ok,
            "deckStatus": deck_status, "steps": steps, "result": result,
            "setup": m.to_dict()}


def export_text(notes=""):
    """The same text the desktop Export writes: steps, starting order, shorthand."""
    res = model.result
    if not (res.has_answer and res.verified):
        raise ValueError("there is no verified starting order yet")
    steps = format_instructions(model.steps, res.states) or "(none)"
    if any(ops.split_point(s.kind, s.x) is not None for s in model.steps):
        steps += ("\n\n(split A|B): split the deck so A is the card you see on the bottom "
                  "of the upper packet and B is the top card of the rest.")
    text = (f"Shuffle sequence:\n{steps}\n\nStarting order (top first):\n"
            + deck.format_numbered(res.start) + "\n\nShorthand:\n"
            + deck.format_cards(res.start) + "\n")
    if notes:
        text += f"\nNotes:\n{notes}\n"
    return text


def _start_text(kind):
    res = model.result
    if not res.has_answer:
        raise ValueError("there is no starting order yet")
    if kind == "shorthand":
        if not res.verified:
            raise ValueError("the starting order failed its check")
        return deck.format_cards(res.start)
    return deck.format_numbered(res.start)


def _make_step(kind, x=None, y=None):
    step = solver.Step(kind, x, None if y == x else y)
    step.validate(ops.DECK_SIZE)
    return step


# --- Free Tracking ------------------------------------------------------------------------


def _card_list(text):
    """Cards typed for a step; spaces separate cards as well as commas ("AC AH")."""
    text = (text or "").strip()
    if not text:
        raise ValueError("type the cards first")
    return tuple(deck.parse_cards(", ".join(re.split(r"[\s,]+", text)), allow_indifferent=True))


def _tracker_step(d):
    """A tracking step from the form the page sends (see ``_step_form``)."""
    kind = d["kind"]
    if kind in ops.SHUFFLE_KINDS:
        x, y = d.get("x"), d.get("y")
        return tracking.Shuffle(solver.Step(kind, x, None if y == x else y),
                                d.get("pile") or tracking.START_PILE)
    if kind == "take_out":
        return tracking.TakeOut(_card_list(d.get("cards")), d.get("mode", "pile"))
    if kind == "add_cards":
        return tracking.AddCards(_card_list(d.get("cards")), d.get("pile"),
                                 int(d.get("position", 1)))
    if kind == "name_cards":
        return tracking.NameCards(_card_list(d.get("cards")), d["pile"],
                                  int(d.get("position", 1)))
    if kind == "split":
        try:
            sizes = tuple(int(n) for n in re.split(r"[\s,;]+", d.get("sizes", "").strip()))
        except ValueError:
            raise ValueError("packet sizes are whole numbers, e.g. 1,1,1,1,12,12,12,12") from None
        return tracking.Split(d["pile"], sizes)
    if kind == "place":
        return tracking.Place(d["pile"], d["onto"], bool(d.get("top", True)))
    if kind == "gather":
        return tracking.Gather(tuple(d.get("names", ())))
    if kind == "rearrange":
        return tracking.Rearrange(d.get("title", "").strip(), tracking.parse_piles(d["text"]))
    raise ValueError(f"unknown step {kind!r}")


def _step_form(step):
    """A step as the page's forms show it, to edit it (the inverse of ``_tracker_step``)."""
    kind = step.kind
    cards = " ".join(str(c) for c in getattr(step, "cards", ()))
    if isinstance(step, tracking.Shuffle):
        return {"kind": kind, "x": step.x, "y": step.y, "pile": step.pile}
    if isinstance(step, tracking.TakeOut):
        return {"kind": kind, "cards": cards, "mode": step.mode}
    if isinstance(step, (tracking.AddCards, tracking.NameCards)):
        return {"kind": kind, "cards": cards, "pile": step.pile, "position": step.position}
    if isinstance(step, tracking.Split):
        return {"kind": kind, "pile": step.pile, "sizes": ", ".join(map(str, step.sizes))}
    if isinstance(step, tracking.Place):
        return {"kind": kind, "pile": step.pile, "onto": step.onto, "top": step.top}
    if isinstance(step, tracking.Gather):
        return {"kind": kind, "names": list(step.names)}
    return {"kind": kind, "title": step.title, "text": step.text()}


def _piles(table):
    return [{"name": p.name, "size": len(p)} for p in table.piles]


def tracker_state():
    m = tracker
    problems = m.deck_problems()
    if problems:
        status = "\n".join(problems)
    else:
        n = len(m.cards)
        full = " (a full deck)" if deck.validate_deck(m.cards).ok else ""
        status = f"{n} card{'s' if n != 1 else ''}{full}, each once."
    decks = m.step_decks() if m.states is not None else [None] * len(m.steps)
    steps = []
    for i, s in enumerate(m.steps):
        entry = {"kind": s.kind, "label": s.label(), "form": _step_form(s),
                 "problem": m.step_problem(i), "shuffle": isinstance(s, tracking.Shuffle),
                 "split": ""}
        if entry["shuffle"]:
            if decks[i] is not None:
                entry["split"] = split_note(s.step, decks[i])
            if s.kind in ops.KINDS_WITH_X:
                size = m.size_at(i, s.pile)
                entry["min"], entry["max"] = ops.x_bounds(s.kind, size or ops.DECK_SIZE)
        steps.append(entry)
    piles_at = []
    for i in range(len(m.steps) + 1):
        table = m.table_before(i)
        piles_at.append(_piles(table) if table is not None
                        else [{"name": tracking.START_PILE, "size": None}])
    tables = None if m.states is None else [
        [{"name": p.name, "cards": _cards(p.cards)} for p in t.piles] for t in m.states]
    return {"text": deck.format_cards(m.cards), "error": m.error, "count": len(m.cards),
            "deckOk": not problems, "deckStatus": status, "targetPile": m.target_pile,
            "steps": steps, "pilesAt": piles_at, "tables": tables,
            "missing": m.missing_reason(), "problem": list(m.problem) if m.problem else None,
            "groups": [{"id": g.id, "title": g.title, "color": g.color, "first": g.first,
                        "last": g.last} for g in m.groups],
            "setup": m.to_dict()}


def _t_add(step, index=None):
    if isinstance(step, tracking.Shuffle):
        tracker.target_pile = step.pile
    tracker.add_step(step, index)


def _t_bounds(index, pile):
    """X range of each shuffle for pile ``pile`` as a step at ``index`` would find it."""
    size = tracker.size_at(index, pile)
    n = size or ops.DECK_SIZE
    return {"size": size, "bounds": {k: ops.x_bounds(k, n) for k in ops.KINDS_WITH_X}}


def _check_replacement(index, step):
    """Raise ValueError unless ``step`` can take the place of step ``index``.

    The steps are replayed with it in place, rather than ``step`` being tried
    on the table before ``index``: that table already shows the cards the old
    step named (``NameCards`` names X cards in earlier tables too), so naming
    them differently would look like naming cards that are already in play.
    """
    if tracker.states is None:  # no usable deck: only the step itself can be checked
        if isinstance(step, tracking.Shuffle):
            step.step.validate(ops.DECK_SIZE)
        return
    steps = list(tracker.steps)
    steps[index] = step
    _tables, error = tracking.replay(tracker.cards, steps)
    if error is not None and error[0] == index:
        raise ValueError(error[1])


def _t_replace(index, form):
    step = _tracker_step(form)
    _check_replacement(index, step)
    if step != tracker.steps[index]:
        tracker.steps[index] = step
        tracker._changed()


def _t_check(step, index, edit=False):
    """Whether ``step`` (a form) can be done at ``index`` (or, with ``edit``, take the
    place of step ``index``), without adding it."""
    try:
        built = _tracker_step(step)
        if edit:
            _check_replacement(index, built)
        else:
            table = tracker.table_before(index)
            if table is not None:
                built.apply(table)
    except (ValueError, TypeError, KeyError) as exc:
        return {"ok": False, "message": str(exc)}
    if isinstance(built, tracking.Rearrange):
        n = sum(len(cards) for _name, cards in built.piles)
        piles = len(built.piles)
        return {"ok": True, "message": f"{n} card{'s' if n != 1 else ''}"
                + (f" in {piles} piles" if piles != 1 else "")}
    return {"ok": True, "message": ""}


def _t_table_text(index):
    table = tracker.table_before(index)
    if table is None or not table.piles:
        return {"text": ""}
    return {"text": tracking.format_piles(table.piles)}


def _t_remove_range(first, last):
    for index in range(last, first - 1, -1):
        tracker.remove_step(index)


def _t_set_pile(name):
    tracker.target_pile = name


def _none(_value):
    """Drop a return value so the op answers with the new state."""


# op -> function(**args); the ones returning None answer with the new state.
OPS = {
    "meta": meta,
    "state": lambda: None,
    "set_text": lambda text: _none(model.set_final_from_text(text)),
    "set_slot": lambda index, card: model.set_slot(index, None if card is None
                                                   else _parse_one(card)),
    "preset": lambda name: model.load_preset(name),
    "clear_final": lambda: model.clear_final(),
    "add_step": lambda kind, x=None, y=None, index=None:
        model.add_step(_make_step(kind, x, y), index),
    "remove_step": lambda index: model.remove_step(index),
    "move_step": lambda index, delta: _none(model.move_step(index, delta)),
    "duplicate_step": lambda index: model.duplicate_step(index),
    "set_x": lambda index, x: model.set_step_x(index, x),
    "set_y": lambda index, y: model.set_step_y(index, y),
    "clear_steps": lambda: model.clear_steps(),
    "load": lambda setup: model.load_dict(setup),
    "export_text": lambda notes="": {"text": export_text(notes)},
    "start_text": lambda kind: {"text": _start_text(kind)},
    "splits": lambda: {"text": format_splits(model.steps, model.result.states)
                       if model.result.has_answer else ""},
    # Free Tracking
    "t_state": lambda: None,
    "t_set_text": lambda text: _none(tracker.set_from_text(text)),
    "t_preset": lambda name: tracker.load_preset(name),
    "t_clear": lambda: tracker.set_cards([]),
    "t_set_pile": _t_set_pile,
    "t_add": lambda step, index=None: _t_add(_tracker_step(step), index),
    "t_replace": lambda index, step: _t_replace(index, step),
    "t_check": _t_check,
    "t_bounds": _t_bounds,
    "t_remove": lambda index: tracker.remove_step(index),
    "t_remove_range": _t_remove_range,
    "t_move": lambda index, delta: _none(tracker.move_step(index, delta)),
    "t_duplicate": lambda first, last: _none(tracker.duplicate_steps(first, last)),
    "t_set_x": lambda index, x: tracker.set_step_x(index, x),
    "t_set_y": lambda index, y: tracker.set_step_y(index, y),
    "t_clear_steps": lambda: tracker.clear_steps(),
    "t_group_add": lambda first, last, title, color:
        _none(tracker.add_group(first, last, title, color)),
    "t_group_edit": lambda id, title, color: tracker.edit_group(id, title, color),
    "t_group_remove": lambda id: tracker.remove_group(id),
    "t_load": lambda setup: tracker.load_dict(setup),
    "t_table_text": _t_table_text,
}


def handle(op, args_json="{}"):
    """Run one op; returns JSON with the new state, a payload, or ``error``."""
    key, current = ("tracker", tracker_state) if op.startswith("t_") else ("state", state)
    try:
        out = OPS[op](**json.loads(args_json))
    except (ValueError, TypeError, KeyError, StopIteration) as exc:
        return json.dumps({"error": str(exc) or type(exc).__name__, key: current()})
    if out is None:
        return json.dumps({key: current()})
    return json.dumps(out)
