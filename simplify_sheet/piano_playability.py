"""Piano playability pass.

1. Hand-span check   -> thin any chord wider than the level's reach.
2. Leap check        -> fold fast, huge melodic leaps back toward the hand.
3. Fingering         -> Parncutt-style dynamic program assigning fingers 1-5
                        to the melody (RH) and accompaniment (LH), annotated
                        on the score.

Level limits (semitones):
    level:        1    2    3    4    5
    chord span:   7    9   12   14   16    (5th, 6th, 8ve, 9th, 10th)
    fast leap:    7   12   16   24   24    (max leap when note < 0.5 beat)
"""

from dataclasses import dataclass, field
from music21 import note, chord, articulations

CHORD_SPAN = {1: 7, 2: 9, 3: 12, 4: 14, 5: 16}
FAST_LEAP = {1: 7, 2: 12, 3: 16, 4: 24, 5: 24}

# Parncutt-lite: comfortable / max stretch (in semitones) between finger pairs.
# (finger_a, finger_b) with a < b, for the RIGHT hand ascending.
SPAN = {
    (1, 2): (5, 10), (1, 3): (7, 12), (1, 4): (9, 13), (1, 5): (10, 15),
    (2, 3): (3, 5),  (2, 4): (5, 7),  (2, 5): (7, 10),
    (3, 4): (2, 4),  (3, 5): (5, 7),
    (4, 5): (2, 4),
}


@dataclass
class PianoReport:
    adjustments: list = field(default_factory=list)

    def log(self, msg):
        self.adjustments.append(msg)


# ------------------------------------------------------------- chords/leaps

def enforce_spans(part, level: int, report: PianoReport):
    limit = CHORD_SPAN[level]
    for c in list(part.recurse().getElementsByClass(chord.Chord)):
        ps = sorted(c.pitches, key=lambda p: p.midi)
        while len(ps) > 1 and ps[-1].midi - ps[0].midi > limit:
            # drop the note whose removal shrinks the span most while
            # keeping the outer voices if possible: drop 2nd-from-bottom
            victim = ps[1] if len(ps) > 2 else ps[0]
            c.remove(victim)
            ps = sorted(c.pitches, key=lambda p: p.midi)
            report.log(f"m{c.measureNumber}: thinned chord to fit "
                       f"{limit}-semitone hand span")


def fix_fast_leaps(part, level: int, report: PianoReport):
    limit = FAST_LEAP[level]
    prev = None
    for n in part.recurse().notes:
        if isinstance(n, note.Note):
            if (prev is not None and n.duration.quarterLength < 0.5
                    and abs(n.pitch.midi - prev.midi) > limit):
                direction = 12 if n.pitch.midi < prev.midi else -12
                n.pitch.midi += direction
                report.log(f"m{n.measureNumber}: folded fast leap "
                           f"({abs(n.pitch.midi - direction - prev.midi)} semis) "
                           f"by an octave")
            prev = n.pitch
        elif isinstance(n, chord.Chord):
            prev = max(n.pitches)


# ------------------------------------------------------------- fingering DP

def _pair_cost(f1, f2, semis, right_hand=True):
    """Cost of playing an interval of `semis` semitones with fingers f1->f2."""
    if semis == 0:
        return 0.0 if f1 == f2 else 1.0
    ascending = semis > 0
    if not right_hand:
        ascending = not ascending  # LH mirror
    a, b = (f1, f2) if ascending else (f2, f1)

    if a == b:
        return 3.0 + abs(semis) * 0.2          # same-finger jump: avoid
    if a < b:
        comfy, mx = SPAN.get((a, b), (1, 5))
        s = abs(semis)
        if s > mx:
            return 8.0                          # over-stretch
        return 0.0 if s <= comfy else (s - comfy) * 1.0
    # a > b while pitch ascends => crossing (thumb-under is the only good one)
    if b == 1:
        return 1.5 + max(0, abs(semis) - 2) * 0.3   # finger-over-thumb
    if a == 1:
        return 1.0 + max(0, abs(semis) - 4) * 0.5   # thumb-under: fine
    return 6.0                                       # 3-over-4 etc: bad


def assign_fingering(part, right_hand: bool, level: int):
    """DP over finger choices 1-5 for single-note lines; annotates Fingering."""
    notes = [n for n in part.recurse().notes if isinstance(n, note.Note)]
    if not notes:
        return
    FINGERS = (1, 2, 3, 4, 5)
    # beginners live in five-finger positions: discourage thumb crossings
    crossing_penalty = {1: 4.0, 2: 2.0, 3: 0.5, 4: 0.0, 5: 0.0}[level]

    best = [{f: (0.0, None) for f in FINGERS}]
    for i in range(1, len(notes)):
        semis = notes[i].pitch.midi - notes[i - 1].pitch.midi
        row = {}
        for f in FINGERS:
            opts = []
            for pf, (pc, _) in best[i - 1].items():
                c = _pair_cost(pf, f, semis, right_hand)
                is_crossing = (semis > 0) == right_hand and pf > f or \
                              (semis > 0) != right_hand and pf < f
                if semis != 0 and is_crossing:
                    c += crossing_penalty
                opts.append((pc + c, pf))
            row[f] = min(opts)
        best.append(row)

    path = [min(best[-1], key=lambda f: best[-1][f][0])]
    for i in range(len(best) - 1, 0, -1):
        path.append(best[i][path[-1]][1])
    path.reverse()

    for n, f in zip(notes, path):
        n.articulations.append(articulations.Fingering(f))


def apply(score, level: int) -> PianoReport:
    report = PianoReport()
    for part in score.parts:
        right_hand = (part.id != "accompaniment")
        enforce_spans(part, level, report)
        fix_fast_leaps(part, level, report)
        if level <= 3:                       # fingerings help most early on
            assign_fingering(part, right_hand, level)
    return report
