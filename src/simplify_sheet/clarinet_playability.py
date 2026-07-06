"""Clarinet playability pass (operates on the WRITTEN Bb part).

Uses a fingering-difficulty table keyed by written pitch plus transition
costs, then repairs passages that exceed the level's budget:

  - fast crossings of the break (written A4/Bb4 <-> B4/C5) at low levels
    -> fold the offending phrase to one side of the break
  - altissimo (written C6+) below level 4 -> drop an octave
  - awkward throat tones in fast passages -> flagged in the report

Difficulty scale: 0 = trivial ... 5 = advanced.
"""

from dataclasses import dataclass, field
from music21 import note, expressions

# written-pitch base difficulty (midi -> difficulty)
def base_difficulty(midi: int) -> int:
    if midi < 52:            # below written E3: doesn't exist
        return 99
    if midi <= 65:           # E3..F4 chalumeau: beginner home turf
        return 0
    if midi <= 68:           # F#4..G#4 throat tones: easy fingerings, tricky tone
        return 1
    if midi <= 70:           # A4, Bb4 (register-key side of the throat)
        return 1
    if midi <= 77:           # B4..F5 clarion: fine once over the break
        return 2
    if midi <= 82:           # F#5..Bb5 upper clarion
        return 3
    if midi <= 88:           # B5..E6 lower altissimo
        return 4
    return 5                 # above E6

BREAK_LOW, BREAK_HIGH = 70, 71     # written Bb4 | B4 boundary

# max allowed: (note difficulty, break crossings per measure at speed)
LEVEL_BUDGET = {1: (0, 0), 2: (2, 1), 3: (3, 2), 4: (4, 99), 5: (5, 99)}
FAST_QL = 0.5   # a crossing is "fast" if either note is shorter than this


@dataclass
class ClarinetReport:
    adjustments: list = field(default_factory=list)
    warnings: list = field(default_factory=list)

    def log(self, msg):
        self.adjustments.append(msg)


def _crosses_break(a: int, b: int) -> bool:
    return (a <= BREAK_LOW < b) or (b <= BREAK_LOW < a)


def fix_register(part, level: int, report: ClarinetReport):
    """Clamp per-note difficulty to the level budget by octave displacement."""
    max_diff, _ = LEVEL_BUDGET[level]
    for n in part.recurse().notes:
        if not isinstance(n, note.Note):
            continue
        moved = 0
        while base_difficulty(n.pitch.midi) > max_diff and n.pitch.midi - 12 >= 52:
            n.pitch.midi -= 12
            moved += 1
        if base_difficulty(n.pitch.midi) > max_diff:
            report.warnings.append(
                f"m{n.measureNumber}: {n.pitch.nameWithOctave} exceeds level "
                f"{level} even after folding")
        elif moved:
            report.log(f"m{n.measureNumber}: dropped note {moved} octave(s) "
                       f"out of the {'altissimo' if moved else ''} register")


def fix_break_crossings(part, level: int, report: ClarinetReport):
    """Fold fast break-crossing phrases to one side of the break."""
    _, max_crossings = LEVEL_BUDGET[level]
    if max_crossings >= 99:
        return
    notes = [n for n in part.recurse().notes if isinstance(n, note.Note)]

    # group notes by measure, count fast crossings
    from collections import defaultdict
    by_measure = defaultdict(list)
    for n in notes:
        by_measure[n.measureNumber].append(n)

    for m_num, ms in by_measure.items():
        crossings = []
        for a, b in zip(ms, ms[1:]):
            fast = min(a.duration.quarterLength, b.duration.quarterLength) < FAST_QL
            if fast and _crosses_break(a.pitch.midi, b.pitch.midi):
                crossings.append((a, b))
        if len(crossings) <= max_crossings:
            continue
        # fold: move the minority side of the measure across the break
        above = [n for n in ms if n.pitch.midi > BREAK_LOW]
        below = [n for n in ms if n.pitch.midi <= BREAK_LOW]
        movers, direction = (above, -12) if len(above) <= len(below) else (below, +12)
        for n in movers:
            target = n.pitch.midi + direction
            if 52 <= target <= 89:
                n.pitch.midi = target
        report.log(f"m{m_num}: folded {len(movers)} note(s) to avoid "
                   f"{len(crossings)} fast break crossings")


def flag_awkward_transitions(part, report: ClarinetReport):
    """Annotate remaining tricky spots so the student/teacher can see them."""
    notes = [n for n in part.recurse().notes if isinstance(n, note.Note)]
    for a, b in zip(notes, notes[1:]):
        fast = min(a.duration.quarterLength, b.duration.quarterLength) < FAST_QL
        if fast and _crosses_break(a.pitch.midi, b.pitch.midi):
            b.expressions.append(expressions.TextExpression("break!"))
            report.warnings.append(f"m{b.measureNumber}: fast break crossing kept")
        # awkward throat Bb -> clarion via register key with several rings
        if fast and a.pitch.midi == 70 and 71 <= b.pitch.midi <= 77:
            b.expressions.append(expressions.TextExpression("Bb->clarion"))


def apply(score, level: int) -> ClarinetReport:
    report = ClarinetReport()
    for part in score.parts:
        fix_register(part, level, report)
        fix_break_crossings(part, level, report)
        flag_awkward_transitions(part, report)
    return report
