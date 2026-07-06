"""Guitar TAB: build a tablature staff from the playability pass's
string/fret annotations and append it below the notation part.

MusicXML represents TAB as a part with a TAB clef, staff tuning details,
and <technical><string>/<fret> marks on each note. MuseScore and most
notation apps render this as real tablature. music21 covers the clef and
technicals; staff-details tuning is best-effort (MuseScore infers standard
tuning when absent).
"""

import copy

from music21 import clef, stream, articulations, note


def _string_fret(n):
    s = f = None
    for a in n.articulations:
        if isinstance(a, articulations.StringIndication):
            s = a.number
        elif isinstance(a, articulations.FretIndication):
            f = a.number
    return s, f


def add_tab_part(score) -> bool:
    """Clone the melody part into a TAB staff. Returns True if added."""
    src = None
    for p in score.parts:
        if p.id == "melody":
            src = p
            break
    if src is None and len(score.parts):
        src = score.parts[0]
    if src is None:
        return False

    # only worthwhile if the playability pass annotated positions
    annotated = any(_string_fret(n) != (None, None)
                    for n in src.recurse().notes if isinstance(n, note.Note))
    if not annotated:
        return False

    tab = copy.deepcopy(src)
    tab.id = "tab"
    if tab.partName:
        tab.partName = f"{tab.partName} (TAB)"
    else:
        tab.partName = "TAB"

    # swap the clef; keep the technical marks (they carry the fret numbers)
    for c in list(tab.recurse().getElementsByClass(clef.Clef)):
        tab.remove(c, recurse=True)
    first_measure = tab.getElementsByClass(stream.Measure).first()
    (first_measure or tab).insert(0, clef.TabClef())

    # drop fingering numbers on the TAB staff to avoid clutter
    for n in tab.recurse().notes:
        n.articulations = [a for a in n.articulations
                           if isinstance(a, (articulations.StringIndication,
                                             articulations.FretIndication))]

    score.append(tab)
    return True


def without_tab(score):
    """A copy of the score with TAB parts removed (for MIDI export --
    otherwise every guitar note sounds twice)."""
    new = copy.deepcopy(score)
    for p in list(new.parts):
        if (getattr(p, "id", "") == "tab" or
                p.recurse().getElementsByClass(clef.TabClef).first() is not None):
            new.remove(p)
    return new
