# Faro/Overhand Shuffle Solver

A desktop app that answers the inverse shuffle question: *given the deck order
I want to end up with, and the exact shuffles I'm going to do, what order must
the deck start in?*

Supported shuffles (in any mix and order):

| Shuffle | Position rule (N = 52, 0 = top) | X |
|---|---|---|
| Out-faro | i < 26 → 2i; i ≥ 26 → 2(i−26)+1 | — |
| In-faro | i < 26 → 2i+1; i ≥ 26 → 2(i−26) | — |
| Overhand run of X singles | i ≥ X → i−X; i < X → N−1−i | 1–52 (52 reverses the deck) |
| Cut X | i ≥ X → i−X; i < X → i+(N−X) | 1–51 |

The solver walks each starting position m forward through the sequence to find
its final position Π(m), then sets `start[m] = final[Π(m)]`. Every result is
then forward-simulated and checked against the desired final order; the
PASS/FAIL badge shows that round-trip check.

## Running

Requires Python 3.10+ with Tkinter (on Debian/Ubuntu: `apt install python3-tk`).

```sh
python -m shuffle_solver      # or: python run_app.py
```

Package a single executable with PyInstaller if you like:

```sh
pip install pyinstaller
pyinstaller --onefile --windowed --name ShuffleSolver run_app.py
```

## Using it

1. **Final deck** – pick a preset (new deck order, Si Stebbins, Aronson,
   Mnemonica), type shorthand, or set cards slot by slot. Duplicates are
   highlighted in red and missing cards are listed.
2. **Shuffle sequence** – add out-faros, in-faros, overhand runs and cuts;
   reorder, duplicate, delete, or change X of the selected step.
3. **Starting order** – recomputed on every change. Copy it as shorthand or a
   numbered list, export it to a text file, or open the step-by-step preview.

File → Save/Open setup stores the final deck and sequence as JSON.

## Card shorthand

Cards are RANK+SUIT: ranks `A 2-9 T J Q K` (`10` also works), suits `C H S D`.
Entries are comma-separated; whitespace and case don't matter.

| Input | Meaning |
|---|---|
| `AC` | ace of clubs |
| ``AC` `` | ace of clubs, face up (a backtick flags the card on its left) |
| `A-KC`, `K-AC` | ace to king of clubs; king down to ace |
| ``A-KC` `` | the whole range face up (a bare range is one entry) |
| `(A-8, 9-K)C` | one suit shared by several ranks/ranges |
| ``(A-8, 9-K)`C`` | ...all face up (backtick right after the `)`) |
| `ACHSD` | AC, AH, AS, AD, in the order typed |
| ``ACHSD` `` / ``AC`HSD`` | only AD / only AC face up |
| ``(ACHSD)` `` | all four aces face up |
| `A-KCHSD` | clubs A–K, then hearts, spades, diamonds |

Face-up is a display flag only; it never affects the shuffle math.

## Layout

```
shuffle_solver/
  shuffle_ops.py   pure position functions for each shuffle
  solver.py        composition, solve, forward simulation, round-trip verify
  deck.py          Card, shorthand parser/formatter, validation, presets
  ui/model.py      toolkit-free app state (tested without a display)
  ui/app.py        Tkinter window
tests/             pytest + hypothesis
```

## Tests

```sh
pip install -r requirements-dev.txt
pytest                 # Tk window tests skip without a display
xvfb-run -a pytest     # include them on a headless Linux box
```
