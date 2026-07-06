"""Core simplification engine.

Takes a music21 Score and an InstrumentProfile + skill level (1-5) and
produces a simplified arrangement:

  Level 1  melody only, half/quarter notes, easiest keys, tiny range
  Level 2  melody only, eighth notes allowed, easy keys
  Level 3  melody + simple accompaniment (piano/guitar), dotted rhythms
  Level 4  light reduction: thinner chords, sixteenths allowed
  Level 5  cleanup only (re-notation, range check)

All transformations are individually overridable via SimplifySettings.
"""

from dataclasses import dataclass
from fractions import Fraction

from music21 import (
    stream, note, chord, key, meter, pitch, interval,
    instrument as m21instrument, expressions, articulations, tempo,
)

from .instruments import InstrumentProfile


# ---------------------------------------------------------------- settings

@dataclass
class SimplifySettings:
    level: int = 1
    melody_only: bool = True           # keep only the top line
    min_duration_ql: float = 1.0       # shortest allowed note (quarterLength)
    keep_accompaniment: bool = False   # add a reduced accompaniment part
    max_chord_notes: int = 1           # chord thinning
    strip_ornaments: bool = True
    transpose_to_easy_key: bool = True
    slow_tempo_ratio: float = 1.0      # suggested practice tempo multiplier

    @classmethod
    def for_level(cls, level: int) -> "SimplifySettings":
        level = max(1, min(5, int(level)))
        table = {
            1: cls(level=1, melody_only=True,  min_duration_ql=1.0,
                   keep_accompaniment=False, max_chord_notes=1,
                   strip_ornaments=True, slow_tempo_ratio=0.7),
            2: cls(level=2, melody_only=True,  min_duration_ql=0.5,
                   keep_accompaniment=False, max_chord_notes=1,
                   strip_ornaments=True, slow_tempo_ratio=0.8),
            3: cls(level=3, melody_only=False, min_duration_ql=0.5,
                   keep_accompaniment=True,  max_chord_notes=3,
                   strip_ornaments=True, slow_tempo_ratio=0.9),
            4: cls(level=4, melody_only=False, min_duration_ql=0.25,
                   keep_accompaniment=True,  max_chord_notes=4,
                   strip_ornaments=False, slow_tempo_ratio=1.0),
            5: cls(level=5, melody_only=False, min_duration_ql=0.25,
                   keep_accompaniment=True,  max_chord_notes=6,
                   strip_ornaments=False, slow_tempo_ratio=1.0),
        }
        return table[level]


# ---------------------------------------------------------------- helpers

def _analyzed_key(score: stream.Score) -> key.Key:
    try:
        ks = score.recurse().getElementsByClass(key.KeySignature).first()
        if ks is not None and isinstance(ks, key.Key):
            return ks
        return score.analyze("key")
    except Exception:
        return key.Key("C")


def choose_target_key(current: key.Key, profile: InstrumentProfile,
                      level: int) -> tuple[key.Key, interval.Interval]:
    """Pick the closest allowed key (by semitone shift) for the level."""
    allowed = profile.allowed_key_signatures(level)
    current_sharps = current.sharps
    if current_sharps in allowed:
        return current, interval.Interval(0)

    best = None
    for sharps in allowed:
        target = key.KeySignature(sharps).asKey(current.mode or "major")
        semis = (target.tonic.pitchClass - current.tonic.pitchClass) % 12
        if semis > 6:
            semis -= 12  # prefer the smaller direction
        cand = interval.Interval(semis)
        score_ = (abs(semis), abs(sharps))
        if best is None or score_ < best[0]:
            best = (score_, target, cand)
    _, target, itv = best
    return target, itv


def extract_melody(part: stream.Part) -> stream.Part:
    """Reduce a part to its top voice / top note of each chord."""
    flat = part.flatten().notesAndRests
    out = stream.Part()
    out.id = "melody"
    seen_offsets = {}
    for el in flat:
        off = el.offset
        if isinstance(el, chord.Chord):
            n = note.Note(max(el.pitches))
            n.duration = el.duration
        elif isinstance(el, note.Note):
            n = note.Note(el.pitch)
            n.duration = el.duration
        else:  # rest
            n = note.Rest()
            n.duration = el.duration
        # if two voices share an offset keep the higher pitch
        prev = seen_offsets.get(off)
        if prev is not None and isinstance(prev, note.Note) and isinstance(n, note.Note):
            if n.pitch <= prev.pitch:
                continue
            out.remove(prev)
        seen_offsets[off] = n
        out.insert(off, n)
    return out


def quantize_rhythm(part: stream.Part, min_ql: float) -> stream.Part:
    """Quantize to a min_ql grid, guaranteeing monophonic non-overlapping output.

    The timeline is cut into grid cells; each cell is won by the note that
    dominates it (a fresh attack beats a held-over note, then longest overlap,
    then the earlier onset). Cells won by the same source note merge into one
    longer note; empty cells become rests, so pickup measures stay aligned.
    """
    grid = Fraction(min_ql).limit_denominator(16)
    out = stream.Part()
    elements = list(part.flatten().notesAndRests)
    sounding = [(el,
                 Fraction(el.offset).limit_denominator(64),
                 Fraction(el.offset).limit_denominator(64)
                 + Fraction(el.duration.quarterLength).limit_denominator(64))
                for el in elements if not el.isRest]
    if not elements:
        return out
    total = max(end for _, _, end in sounding) if sounding else \
        max(Fraction(el.offset).limit_denominator(64)
            + Fraction(el.duration.quarterLength).limit_denominator(64)
            for el in elements)
    n_cells = int(-(-total // grid))  # ceil

    winners = []
    for k in range(n_cells):
        c0, c1 = k * grid, (k + 1) * grid
        best, best_key = None, None
        for el, on, end in sounding:
            overlap = min(end, c1) - max(on, c0)
            if overlap <= 0:
                continue
            attacks_here = c0 <= on < c1
            cand_key = (attacks_here, overlap, -on)
            if best is None or cand_key > best_key:
                best, best_key = el, cand_key
        winners.append(best)

    def emit(el, cell_start, n_won):
        if isinstance(el, chord.Chord):
            n = chord.Chord(el.pitches)
        else:
            n = note.Note(el.pitch)
        n.duration.quarterLength = float(n_won * grid)
        out.insert(float(cell_start * grid), n)

    run_el, run_start = None, 0
    for k, el in enumerate(winners):
        if el is run_el:
            continue
        # a distinct attack of the same pitch stays a separate note; only
        # cells sustained by the same source note merge
        if run_el is not None:
            emit(run_el, run_start, k - run_start)
        elif k > run_start:
            r = note.Rest()
            r.duration.quarterLength = float((k - run_start) * grid)
            out.insert(float(run_start * grid), r)
        run_el, run_start = el, k
    if run_el is not None:
        emit(run_el, run_start, n_cells - run_start)
    elif n_cells > run_start:
        r = note.Rest()
        r.duration.quarterLength = float((n_cells - run_start) * grid)
        out.insert(float(run_start * grid), r)
    return out


def fold_into_range(part: stream.Part, lo: pitch.Pitch, hi: pitch.Pitch) -> None:
    """Octave-displace notes so everything fits the comfortable range."""
    for el in part.recurse().notes:
        pitches = el.pitches if isinstance(el, chord.Chord) else [el.pitch]
        for p in pitches:
            while p > hi:
                p.octave -= 1
            while p < lo:
                p.octave += 1


def strip_decorations(part: stream.Part) -> None:
    for n in part.recurse().notes:
        n.expressions = [e for e in n.expressions
                         if not isinstance(e, (expressions.Trill,
                                               expressions.Turn,
                                               expressions.Mordent,
                                               expressions.Tremolo))]
        n.articulations = [a for a in n.articulations
                           if isinstance(a, (articulations.Staccato,
                                             articulations.Accent))]
    # remove grace notes
    for n in list(part.recurse().notes):
        if n.duration.isGrace:
            part.remove(n, recurse=True)


def thin_chords(part: stream.Part, max_notes: int) -> None:
    """Keep at most max_notes per chord: bass note + top notes (the money notes)."""
    for c in list(part.recurse().getElementsByClass(chord.Chord)):
        if len(c.pitches) <= max_notes:
            continue
        ps = sorted(c.pitches)
        keep = [ps[0]] + ps[-(max_notes - 1):] if max_notes > 1 else [ps[-1]]
        for p in list(c.pitches):
            if p not in keep:
                c.remove(p)


def make_accompaniment(score: stream.Score, target_key: key.Key,
                       profile: InstrumentProfile, level: int) -> stream.Part | None:
    """Very simple accompaniment: one chord per measure from chordify()."""
    if not profile.polyphonic:
        return None
    try:
        chords = score.chordify()
    except Exception:
        return None
    acc = stream.Part()
    acc.id = "accompaniment"
    for m in chords.getElementsByClass(stream.Measure):
        best = None
        for c in m.recurse().getElementsByClass(chord.Chord):
            if best is None or c.duration.quarterLength > best.duration.quarterLength:
                best = c
        new_m = stream.Measure(number=m.number)
        if best is not None and best.pitches:
            root = best.root() or min(best.pitches)
            if level <= 3:
                # root + fifth, held for the bar
                c2 = chord.Chord([root, root.transpose("P5")])
            else:
                c2 = chord.Chord(sorted(best.pitches)[:3])
            c2.duration.quarterLength = m.barDuration.quarterLength
            new_m.append(c2)
        else:
            r = note.Rest()
            r.duration.quarterLength = m.barDuration.quarterLength
            new_m.append(r)
        acc.append(new_m)
    lo = pitch.Pitch("E2" if profile.name == "acoustic guitar" else "C2")
    fold_into_range(acc, lo, pitch.Pitch("C4"))
    return acc


# ---------------------------------------------------------------- main entry

def simplify_score(score: stream.Score, profile: InstrumentProfile,
                   settings: SimplifySettings) -> stream.Score:
    level = settings.level

    # 1. key -----------------------------------------------------------
    current_key = _analyzed_key(score)
    if settings.transpose_to_easy_key:
        target_key, shift = choose_target_key(current_key, profile, level)
        if shift.semitones != 0:
            score = score.transpose(shift)
    else:
        target_key = current_key

    # 2. melody / part selection ----------------------------------------
    src_part = score.parts[0] if score.parts else score
    melody = extract_melody(src_part)

    # 3. decorations -----------------------------------------------------
    if settings.strip_ornaments:
        strip_decorations(melody)

    # 4. rhythm ----------------------------------------------------------
    melody = quantize_rhythm(melody, settings.min_duration_ql)
    melody.id = "melody"   # quantize_rhythm returns a fresh Part; the id is
                           # what the playability/TAB passes use to find us

    # 5. range -----------------------------------------------------------
    lo, hi = profile.sounding_range(level)
    fold_into_range(melody, lo, hi)

    # 6. assemble --------------------------------------------------------
    out = stream.Score()
    ts = (score.recurse().getElementsByClass(meter.TimeSignature).first()
          or meter.TimeSignature("4/4"))

    inst = getattr(m21instrument, profile.music21_instrument)()
    melody.insert(0, inst)
    melody.insert(0, key.KeySignature(target_key.sharps))
    melody.insert(0, meter.TimeSignature(ts.ratioString))

    # practice tempo suggestion
    mm = score.recurse().getElementsByClass(tempo.MetronomeMark).first()
    base = mm.number if (mm and mm.number) else 100
    melody.insert(0, tempo.MetronomeMark(number=round(base * settings.slow_tempo_ratio)))

    melody.makeMeasures(inPlace=True)
    melody.makeTies(inPlace=True)      # split cross-barline notes now, so the
    melody.makeAccidentals(inPlace=True)  # in-memory score matches its MusicXML
    out.insert(0, melody)

    if settings.keep_accompaniment and not settings.melody_only:
        acc = make_accompaniment(score, target_key, profile, level)
        if acc is not None:
            if settings.max_chord_notes:
                thin_chords(acc, settings.max_chord_notes)
            acc.insert(0, key.KeySignature(target_key.sharps))
            acc.insert(0, meter.TimeSignature(ts.ratioString))
            out.insert(0, acc)

    # 7. clarinet: write the transposed (written) part --------------------
    if profile.written_transposition:
        out = out.transpose(interval.Interval(profile.written_transposition))
        for p in out.parts:
            ks = p.recurse().getElementsByClass(key.KeySignature).first()
            if ks:
                written_key = key.KeySignature(target_key.sharps).asKey().transpose("M2")
                ks.sharps = written_key.sharps

    out.metadata = score.metadata
    return out
