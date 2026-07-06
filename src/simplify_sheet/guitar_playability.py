"""Guitar playability pass.

Two jobs:
1. Melody notes  -> pick a (string, fret) for every note with a Viterbi
   (dynamic-programming) search that minimizes hand movement, then annotate
   the score with string/fret indications.
2. Chords        -> verify each chord has a real, grabbable shape within the
   level's fret-span limit; if not, drop inner notes or re-voice until it does.

Level limits:
    level:        1    2    3    4    5
    max fret:     3    5    7   12   15
    chord span:   2    3    3    4    4   (frets between lowest/highest fretted note)
    barre ok:     no   no  yes  yes  yes
"""

from dataclasses import dataclass, field
from music21 import pitch, note, chord, articulations

STANDARD_TUNING = [pitch.Pitch(p) for p in ("E2", "A2", "D3", "G3", "B3", "E4")]

MAX_FRET = {1: 3, 2: 5, 3: 7, 4: 12, 5: 15}
CHORD_SPAN = {1: 2, 2: 3, 3: 3, 4: 4, 5: 4}
BARRE_OK = {1: False, 2: False, 3: True, 4: True, 5: True}


@dataclass
class GuitarReport:
    adjustments: list = field(default_factory=list)
    unplayable: list = field(default_factory=list)

    def log(self, msg):
        self.adjustments.append(msg)


# ------------------------------------------------------------- candidates

def candidates(p: pitch.Pitch, max_fret: int):
    """All (string_index, fret) positions producing this pitch. 0 = low E."""
    out = []
    for s, open_p in enumerate(STANDARD_TUNING):
        fret = p.midi - open_p.midi
        if 0 <= fret <= max_fret:
            out.append((s, fret))
    return out


# ------------------------------------------------------------- melody DP

def _transition_cost(a, b):
    """Cost of moving from position a=(string,fret) to b."""
    (s1, f1), (s2, f2) = a, b
    # hand position = fret of index finger; open strings don't move the hand
    pos1, pos2 = (f1 or None), (f2 or None)
    cost = 0.0
    if pos1 is not None and pos2 is not None:
        cost += abs(pos2 - pos1) * 2.0          # position shifts are expensive
    cost += abs(s2 - s1) * 0.5                  # string crossings, mildly
    cost += f2 * 0.1                            # slight preference for low frets
    return cost


def assign_melody_positions(part, level: int, report: GuitarReport):
    """Viterbi over the note sequence; annotates string/fret, fixes impossible notes."""
    max_fret = MAX_FRET[level]
    notes = [n for n in part.recurse().notes if isinstance(n, note.Note)]
    if not notes:
        return

    # fold notes with no candidate position into range first
    for n in notes:
        tries = 0
        while not candidates(n.pitch, max_fret) and tries < 4:
            n.pitch.octave += 1 if n.pitch < STANDARD_TUNING[0] else -1
            tries += 1
        if not candidates(n.pitch, max_fret):
            report.unplayable.append(f"{n.pitch} (measure {n.measureNumber})")

    seqs = [candidates(n.pitch, max_fret) or [(0, 0)] for n in notes]

    # DP tables
    best = [{c: (c[1] * 0.1, None) for c in seqs[0]}]
    for i in range(1, len(seqs)):
        row = {}
        for c in seqs[i]:
            options = [(prev_cost + _transition_cost(pc, c), pc)
                       for pc, (prev_cost, _) in best[i - 1].items()]
            row[c] = min(options)
        best.append(row)

    # backtrack
    path = [min(best[-1], key=lambda c: best[-1][c][0])]
    for i in range(len(best) - 1, 0, -1):
        path.append(best[i][path[-1]][1])
    path.reverse()

    for n, (s, f) in zip(notes, path):
        n.articulations.append(articulations.StringIndication(6 - s))  # 1 = high E
        n.articulations.append(articulations.FretIndication(f))


# ------------------------------------------------------------- chords

def find_chord_shape(pitches, level: int):
    """Backtracking search: assign each pitch to a distinct string.

    Returns list of (string, fret) or None. Enforces fret-span limit and,
    below level 3, no duplicate frets across 3+ strings (i.e. no barres).
    """
    max_fret = MAX_FRET[level]
    span = CHORD_SPAN[level]
    ps = sorted(pitches, key=lambda p: p.midi)

    def bt(i, used_strings, placed):
        if i == len(ps):
            fretted = [f for _, f in placed if f > 0]
            if fretted and (max(fretted) - min(fretted)) > span:
                return None
            if not BARRE_OK[level]:
                from collections import Counter
                counts = Counter(f for _, f in placed if f > 0)
                if any(v >= 3 for v in counts.values()):
                    return None
                if len([f for _, f in placed if f > 0]) > 4:
                    return None      # more fretted notes than fingers
            return list(placed)
        for (s, f) in candidates(ps[i], max_fret):
            if s in used_strings:
                continue
            # keep low pitches on low strings for sane voicings
            if placed and s <= placed[-1][0]:
                continue
            got = bt(i + 1, used_strings | {s}, placed + [(s, f)])
            if got:
                return got
        return None

    return bt(0, set(), [])


def fix_chords(part, level: int, report: GuitarReport):
    for c in list(part.recurse().getElementsByClass(chord.Chord)):
        shape = find_chord_shape(c.pitches, level)
        if shape:
            continue
        original = "-".join(p.nameWithOctave for p in c.pitches)
        # strategy 1: drop inner notes (keep bass + top), retry
        ps = sorted(c.pitches, key=lambda p: p.midi)
        while len(ps) > 2 and not shape:
            ps = [ps[0]] + ps[2:] if len(ps) > 2 else ps
            shape = find_chord_shape(ps, level)
        # strategy 2: re-voice — move bass up an octave
        if not shape and len(ps) >= 2:
            ps2 = sorted([ps[0].transpose(12)] + ps[1:], key=lambda p: p.midi)
            shape = find_chord_shape(ps2, level)
            if shape:
                ps = ps2
        if shape:
            for p in list(c.pitches):
                if p not in ps:
                    c.remove(p)
            for p_old, p_new in zip(sorted(c.pitches, key=lambda p: p.midi), ps):
                p_old.midi = p_new.midi
            report.log(f"re-voiced chord {original} -> "
                       + "-".join(p.nameWithOctave for p in c.pitches))
        else:
            top = max(c.pitches)
            for p in list(c.pitches):
                if p is not top:
                    c.remove(p)
            report.log(f"chord {original} had no shape at level {level}; kept top note")


def apply(score, level: int) -> GuitarReport:
    report = GuitarReport()
    for part in score.parts:
        fix_chords(part, level, report)
        if part.id == "melody" or len(score.parts) == 1:
            assign_melody_positions(part, level, report)
    return report
