"""Note events: flatten the simplified score into a JSON-friendly list.

One data source powers the whole practice stack in the browser:
  - the WebAudio player (play-along backing, tempo slider, measure looping)
  - the microphone game (expected pitch + timing windows)

Each event: {t, d, midi, sounding, part, measure, string?, fret?, finger?}
  t        onset in beats (quarterLength offset from the start)
  d        duration in beats
  midi     written pitch (matches the displayed score)
  sounding actual pitch to synthesize / listen for (clarinet is written
           a major 2nd above sounding, so sounding = midi - 2 there)
"""

from music21 import chord, tempo, meter, articulations, clef


def extract_events(score, sounding_offset: int = 0) -> dict:
    events = []
    n_measures = 0
    for pi, part in enumerate(score.parts if score.parts else [score]):
        part_id = str(getattr(part, "id", None) or f"part{pi}")
        is_tab = (part_id == "tab" or
                  part.recurse().getElementsByClass(clef.TabClef).first() is not None)
        if is_tab:
            continue  # duplicate of the melody part
        open_ties = {}  # midi -> event dict still awaiting its tie continuation
        for el in part.flatten().notes:
            pitches = el.pitches if isinstance(el, chord.Chord) else [el.pitch]
            base = {
                "t": round(float(el.offset), 4),
                "d": round(float(el.duration.quarterLength), 4),
                "part": part_id,
                "pi": pi,
                "measure": el.measureNumber or 0,
            }
            n_measures = max(n_measures, base["measure"])
            for a in el.articulations:
                if isinstance(a, articulations.Fingering):
                    base["finger"] = a.fingerNumber if hasattr(a, "fingerNumber") else a.number
                elif isinstance(a, articulations.StringIndication):
                    base["string"] = a.number
                elif isinstance(a, articulations.FretIndication):
                    base["fret"] = a.number
            tie_type = el.tie.type if el.tie is not None else None
            for p in pitches:
                # a tie continuation is not a new attack: extend the open event
                prev = open_ties.get(p.midi)
                if (tie_type in ("continue", "stop") and prev is not None
                        and abs(prev["t"] + prev["d"] - base["t"]) < 1e-3):
                    prev["d"] = round(prev["d"] + base["d"], 4)
                    if tie_type == "stop":
                        del open_ties[p.midi]
                    continue
                ev = dict(base)
                ev["midi"] = p.midi
                ev["sounding"] = p.midi + sounding_offset
                events.append(ev)
                if tie_type in ("start", "continue"):
                    open_ties[p.midi] = ev

    events.sort(key=lambda e: (e["t"], e["pi"]))
    mm = score.recurse().getElementsByClass(tempo.MetronomeMark).first()
    ts = score.recurse().getElementsByClass(meter.TimeSignature).first()
    return {
        "events": events,
        "bpm": (mm.number if mm and mm.number else 100),
        "beats_per_measure": (ts.barDuration.quarterLength if ts else 4.0),
        "n_measures": n_measures,
        "melody_part": "melody",
        "melody_pi": 0,
    }
