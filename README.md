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
| Partial out-faro of top X into top | i < X → 2i; X ≤ i < 2X → 2(i−X)+1; else i | 2–26 |
| Partial in-faro of top X into top | i < X → 2i+1; X ≤ i < 2X → 2(i−X); else i | 1–26 |
| Partial out/in-faro of top X into bottom | see below | 1–26 |
| Partial out/in-faro of bottom X into top | see below | 1–26 |
| Partial out-faro of bottom X into bottom | mirror image of top into top | 2–26 |
| Partial in-faro of bottom X into bottom | mirror image of top into top | 1–26 |

A partial faro cuts off X cards from the top or the bottom of the deck, and
weaves them into the top X or the bottom X cards of what is left. The rest of
the deck keeps its order. The out version keeps the packet's outer card on the
outside of the deck: its top card stays on top when woven into the top, and its
bottom card stays on the bottom when woven into the bottom. The in version
tucks that card one place inside. With 1–10 as a small deck and X = 3:

| Partial faro of 3 | Out | In |
|---|---|---|
| top into top | 1 4 2 5 3 6 7 8 9 10 | 4 1 5 2 6 3 7 8 9 10 |
| top into bottom | 4 5 6 7 8 1 9 2 10 3 | 4 5 6 7 1 8 2 9 3 10 |
| bottom into top | 8 1 9 2 10 3 4 5 6 7 | 1 8 2 9 3 10 4 5 6 7 |
| bottom into bottom | 1 2 3 4 5 8 6 9 7 10 | 1 2 3 4 8 5 9 6 10 7 |

Top into top with X = 26 is a full faro.

The solver walks each starting position m forward through the sequence to find
its final position Π(m), then sets `start[m] = final[Π(m)]`. Every result is
then forward-simulated and checked against the desired final order; the
PASS/FAIL badge shows that round-trip check.

## Running

Requires Python 3.10+ with Tkinter (on Debian/Ubuntu: `apt install python3-tk`)
and [ttkbootstrap](https://github.com/israel-dryer/ttkbootstrap) for the themes.

```sh
pip install -r requirements.txt
python -m shuffle_solver      # or: python run_app.py
```

Package a single executable with PyInstaller if you like:

```sh
pip install pyinstaller
pyinstaller --onefile --windowed --name ShuffleSolver   --add-data "shuffle_solver/ui/card_images:shuffle_solver/ui/card_images" run_app.py
```

(On Windows PyInstaller before 6.0, use `;` instead of `:` in `--add-data`.)

## Using it

1. **Final deck** – pick a preset (new deck order, Si Stebbins, Aronson,
   Mnemonica), type shorthand, or set cards slot by slot. Duplicates are
   highlighted in red and missing cards are listed.
2. **Shuffle sequence** – add out-faros, in-faros, overhand runs, cuts and
   partial faros (pick which end the packet comes from and goes into under
   the partial faro buttons); reorder, duplicate, delete, or change X of the
   selected step.
3. **Starting order** – recomputed on every change. Copy it as shorthand or a
   numbered list, export it to a text file, or open the step-by-step preview.

Every shorthand field (final deck, starting order, and X and Y on the next
tab) has a **View cards** button. It opens a window that shows the order as card
pictures in rows of 13, top first. Face-up cards have an orange outline, and
empty slots are dashed. The window stays open and updates as you edit. Card
images are from [MattCain/svg-playing-cards](https://github.com/MattCain/svg-playing-cards)
(MIT).

File → Save/Open setup stores the final deck and sequence as JSON.

View → Theme picks a colour theme (Sandstone by default), and View → Dark mode
(Ctrl+D) switches it between light and dark. The choice is remembered in
`~/.shuffle_solver.json`.

### X to Y tab

Enter a starting order (X) and an ending order (Y) as presets or shorthand,
then press **Find shuffles** to get numbered instructions that turn X into Y.

- A search tries every full and partial faro (all four packet directions),
  overhand run and cut. If some
  sequence of 5 or fewer shuffles works, the app gives a shortest one. It also
  finds longer faro-heavy routes: several full faros plus a few other
  shuffles at either end (e.g. the Mnemonica prep preset → Mnemonica: 4
  out-faros, run 26, partial out-faro of top 18, cut 9).
- It also tries each preset as a midpoint, X → preset → Y. New deck order →
  Mnemonica goes through the Mnemonica prep preset in 11 shuffles.
- Otherwise it builds a long route (usually 60–75 steps) out of cuts and
  overhand runs, which can reach any order. Most pairs of orders have no short
  route: with ~300 possible shuffles per step, reaching an arbitrary one of
  the 52! orders takes at least ~27 shuffles. Read the deck as a circle: a cut
  just turns the circle, and "cut s, then overhand run L" reverses any arc
  of it, so arc reversals can sort the deck.

Every answer is replayed forward and checked against Y (the PASS badge).

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
  path_finder.py   X to Y: shuffles from one order to another
  deck.py          Card, shorthand parser/formatter, validation, presets
  ui/model.py      toolkit-free app state (tested without a display)
  ui/app.py        Tkinter window and tabs
  ui/theme.py      ttkbootstrap theme choice and the app's custom styles
  ui/x_to_y.py     the X to Y tab
  ui/card_viewer.py  "View cards" popups; images in ui/card_images/
tests/             pytest + hypothesis
```

## Tests

```sh
pip install -r requirements-dev.txt
pytest                 # Tk window tests skip without a display
xvfb-run -a pytest     # include them on a headless Linux box
```
