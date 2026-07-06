"""Test suite for simplify_sheet.

Run:  pip install -r requirements.txt pytest && pytest -v

NOTE: written in a sandbox without music21 installed, so these tests have
NOT been executed. Expect a few assertion/API mismatches on first run —
fix the code (or the test if the test's expectation is wrong) and re-run.
"""

import io
import pytest

music21 = pytest.importorskip("music21")
from music21 import (stream, note, chord, key, meter, tempo, pitch,
                     articulations, clef, converter)

from simplify_sheet.instruments import get_profile, GUITAR, PIANO, CLARINET
from simplify_sheet.simplify import (SimplifySettings, simplify_score,
                                     choose_target_key, quantize_rhythm,
                                     fold_into_range)
from simplify_sheet import (guitar_playability as gp,
                            piano_playability as pp,
                            clarinet_playability as cp)
from simplify_sheet.guitar_tab import add_tab_part, without_tab
from simplify_sheet.events import extract_events


# ------------------------------------------------------------ fixtures

def make_score(key_sharps=4, with_chords=True):
    """4 bars in E major: melody with sixteenths + block chords."""
    s = stream.Score()
    p = stream.Part()
    p.insert(0, key.KeySignature(key_sharps))
    p.insert(0, meter.TimeSignature("4/4"))
    p.insert(0, tempo.MetronomeMark(number=120))
    melody_pitches = ["E4", "F#4", "G#4", "A4", "B4", "C#5", "D#5", "E5"]
    off = 0.0
    for name in melody_pitches:          # eighths
        n = note.Note(name); n.duration.quarterLength = 0.5
        p.insert(off, n); off += 0.5
    for i in range(8):                   # sixteenth run
        n = note.Note(melody_pitches[i % 8])
        n.duration.quarterLength = 0.25
        p.insert(off, n); off += 0.25
    while off < 16.0:                    # pad with halves
        n = note.Note("B4"); n.duration.quarterLength = 2.0
        p.insert(off, n); off += 2.0
    p.makeMeasures(inPlace=True)
    s.insert(0, p)
    if with_chords:
        acc = stream.Part()
        for m in range(4):
            c = chord.Chord(["E2", "B2", "E3", "G#3", "B3"])
            c.duration.quarterLength = 4.0
            acc.insert(m * 4.0, c)
        acc.makeMeasures(inPlace=True)
        s.insert(0, acc)
    return s


# ------------------------------------------------------------ key choice

def test_key_choice_guitar_level1_lands_on_easy_key():
    target, itv = choose_target_key(key.Key("E"), GUITAR, 1)
    assert target.sharps in GUITAR.allowed_key_signatures(1)

def test_key_choice_noop_when_already_easy():
    target, itv = choose_target_key(key.Key("C"), PIANO, 1)
    assert itv.semitones == 0

def test_clarinet_level1_keys_give_easy_written_keys():
    for sharps in CLARINET.allowed_key_signatures(1):
        written = key.KeySignature(sharps).asKey().transpose("M2")
        assert abs(written.sharps) <= 1


# ------------------------------------------------------------ rhythm & range

def test_quantize_removes_short_notes():
    p = stream.Part()
    for i in range(8):
        n = note.Note("C4"); n.duration.quarterLength = 0.25
        p.insert(i * 0.25, n)
    q = quantize_rhythm(p, 1.0)
    for n in q.recurse().notes:
        assert n.duration.quarterLength >= 1.0 - 1e-6

def test_fold_into_range():
    p = stream.Part()
    p.insert(0, note.Note("C7")); p.insert(1, note.Note("C1"))
    fold_into_range(p, pitch.Pitch("C3"), pitch.Pitch("C5"))
    for n in p.recurse().notes:
        assert pitch.Pitch("C3") <= n.pitch <= pitch.Pitch("C5")

def test_quantize_never_overlaps_mixed_pitches():
    """Regression: eighths of different pitches used to stack at offset 0."""
    p = stream.Part()
    for i, nm in enumerate(["E4", "F#4", "G#4", "A4"]):
        n = note.Note(nm); n.duration.quarterLength = 0.5
        p.insert(i * 0.5, n)
    q = quantize_rhythm(p, 1.0)
    evts = sorted((float(n.offset), float(n.duration.quarterLength))
                  for n in q.flatten().notes)
    for (t1, d1), (t2, _) in zip(evts, evts[1:]):
        assert t1 + d1 <= t2 + 1e-6, f"overlap: note at {t1} d{d1} vs {t2}"

def test_quantize_preserves_pickup_rest():
    p = stream.Part()
    r = note.Rest(); r.duration.quarterLength = 1.0; p.insert(0, r)
    n = note.Note("C4"); n.duration.quarterLength = 0.5; p.insert(1.0, n)
    q = quantize_rhythm(p, 1.0)
    first = q.flatten().notesAndRests.first()
    assert first.isRest and float(first.offset) == 0.0
    assert float(q.flatten().notes.first().offset) >= 1.0


# ------------------------------------------------------------ full pipeline

@pytest.mark.parametrize("inst", ["guitar", "piano", "clarinet"])
def test_simplify_level1_end_to_end(inst):
    profile = get_profile(inst)
    out = simplify_score(make_score(), profile, SimplifySettings.for_level(1))
    melody = out.parts[0]
    lo, hi = profile.sounding_range(1)
    if profile.written_transposition:      # score is written pitch
        lo, hi = profile.written(lo), profile.written(hi)
    for n in melody.recurse().notes:
        assert n.duration.quarterLength >= 1.0 - 1e-6, "level 1 rhythm"
        for p in (n.pitches if hasattr(n, "pitches") else [n.pitch]):
            assert lo <= p <= hi, f"{p} outside level-1 range for {inst}"
    ks = melody.recurse().getElementsByClass(key.KeySignature).first()
    assert ks is not None

def test_level3_has_accompaniment_for_polyphonic():
    out = simplify_score(make_score(), PIANO, SimplifySettings.for_level(3))
    assert len(out.parts) >= 2

def test_clarinet_is_monophonic_output():
    out = simplify_score(make_score(), CLARINET, SimplifySettings.for_level(3))
    assert len(out.parts) == 1


# ------------------------------------------------------------ guitar

def test_guitar_candidates_middle_c():
    c = gp.candidates(pitch.Pitch("C4"), 5)
    assert (3, 5) in c and (4, 1) in c

def test_guitar_open_c_major_shape_exists():
    ps = [pitch.Pitch(x) for x in ("C3", "E3", "G3", "C4", "E4")]
    assert gp.find_chord_shape(ps, 3) is not None

def test_guitar_playability_annotates_and_fixes():
    out = simplify_score(make_score(), GUITAR, SimplifySettings.for_level(2))
    gp.apply(out, 2)
    annotated = [n for n in out.parts[0].recurse().notes
                 if any(isinstance(a, articulations.FretIndication)
                        for a in n.articulations)]
    assert annotated, "melody notes should carry fret indications"
    for n in annotated:
        for a in n.articulations:
            if isinstance(a, articulations.FretIndication):
                assert 0 <= a.number <= gp.MAX_FRET[2]

def test_guitar_tab_survives_accompaniment_levels():
    """Regression: quantize_rhythm dropped the 'melody' part id, so levels
    with an accompaniment part never got fret assignments or a TAB staff."""
    out = simplify_score(make_score(), GUITAR, SimplifySettings.for_level(3))
    assert out.parts[0].id == "melody"
    gp.apply(out, 3)
    assert add_tab_part(out) is True
    ev = extract_events(out)
    assert any("fret" in e for e in ev["events"])

def test_tab_part_added_and_stripped_for_midi():
    out = simplify_score(make_score(), GUITAR, SimplifySettings.for_level(2))
    gp.apply(out, 2)
    assert add_tab_part(out) is True
    assert any(p.recurse().getElementsByClass(clef.TabClef).first()
               for p in out.parts)
    clean = without_tab(out)
    assert len(clean.parts) == len(out.parts) - 1


# ------------------------------------------------------------ piano

def test_piano_span_enforced():
    p = stream.Part()
    c = chord.Chord(["C3", "E3", "G3", "E5"])   # far beyond a level-1 hand
    c.duration.quarterLength = 4.0
    p.insert(0, c); p.makeMeasures(inPlace=True)
    s = stream.Score(); s.insert(0, p)
    pp.apply(s, 1)
    for c2 in s.recurse().getElementsByClass(chord.Chord):
        ps = sorted(x.midi for x in c2.pitches)
        assert ps[-1] - ps[0] <= pp.CHORD_SPAN[1]

def test_piano_fingering_annotated_low_levels():
    out = simplify_score(make_score(), PIANO, SimplifySettings.for_level(1))
    pp.apply(out, 1)
    fingered = [n for n in out.parts[0].recurse().notes
                if any(isinstance(a, articulations.Fingering)
                       for a in n.articulations)]
    assert fingered


# ------------------------------------------------------------ clarinet

def test_clarinet_difficulty_table():
    assert cp.base_difficulty(60) == 0
    assert cp.base_difficulty(72) == 2
    assert cp.base_difficulty(86) == 4

def test_clarinet_level1_no_notes_above_break():
    out = simplify_score(make_score(), CLARINET, SimplifySettings.for_level(1))
    cp.apply(out, 1)
    for n in out.parts[0].recurse().notes:
        assert cp.base_difficulty(n.pitch.midi) <= cp.LEVEL_BUDGET[1][0]


# ------------------------------------------------------------ events

def test_events_have_indices_and_sounding_offset():
    out = simplify_score(make_score(), CLARINET, SimplifySettings.for_level(2))
    ev = extract_events(out, sounding_offset=-2)
    assert ev["events"], "no events extracted"
    assert ev["melody_pi"] == 0
    for e in ev["events"]:
        assert e["sounding"] == e["midi"] - 2
        assert "pi" in e and "t" in e and "d" in e

def test_events_skip_tab_part():
    out = simplify_score(make_score(), GUITAR, SimplifySettings.for_level(2))
    gp.apply(out, 2); add_tab_part(out)
    ev = extract_events(out)
    tab_pi = len(list(out.parts)) - 1
    assert all(e["pi"] != tab_pi for e in ev["events"])

def test_events_identical_after_musicxml_roundtrip(tmp_path):
    """Regression: tie splits at barlines used to double-count notes, and
    quantize overlaps used to shift offsets after write->parse (breaking /edit)."""
    out = simplify_score(make_score(), GUITAR, SimplifySettings.for_level(2))
    gp.apply(out, 2); add_tab_part(out)
    fp = tmp_path / "rt.musicxml"
    out.write("musicxml", fp=str(fp))
    reparsed = converter.parse(str(fp))
    key_of = lambda ev: [(e["t"], e["d"], e["midi"]) for e in ev["events"]]
    assert key_of(extract_events(out)) == key_of(extract_events(reparsed))

def test_events_merge_tied_notes(tmp_path):
    p = stream.Part()
    p.insert(0, meter.TimeSignature("4/4"))
    n = note.Note("C4"); n.duration.quarterLength = 6.0  # spans a barline
    p.insert(0, n)
    p.makeMeasures(inPlace=True)
    p.makeTies(inPlace=True)
    s = stream.Score(); s.insert(0, p)
    fp = tmp_path / "tie.musicxml"
    s.write("musicxml", fp=str(fp))
    ev = extract_events(converter.parse(str(fp)))["events"]
    assert len(ev) == 1
    assert abs(ev[0]["d"] - 6.0) < 1e-6

def test_clarinet_output_key_is_written_key():
    """Concert F (easiest for E-major source at L1) must appear as written G."""
    out = simplify_score(make_score(), CLARINET, SimplifySettings.for_level(1))
    ks = out.parts[0].recurse().getElementsByClass(key.KeySignature).first()
    concert = CLARINET.allowed_key_signatures(1)
    written_allowed = {key.KeySignature(s).asKey().transpose("M2").sharps
                       for s in concert}
    assert ks.sharps in written_allowed


# ------------------------------------------------------------ web (end-to-end)

@pytest.fixture
def client(tmp_path):
    pytest.importorskip("flask")
    from simplify_sheet import web
    web.app.config["TESTING"] = True
    return web.app.test_client()

def _upload_xml(client, instrument="piano", level="1"):
    s = make_score()
    import tempfile, os
    fp = tempfile.mktemp(suffix=".musicxml")
    s.write("musicxml", fp=fp)
    data = open(fp, "rb").read(); os.unlink(fp)
    return client.post("/simplify", data={
        "score": (io.BytesIO(data), "test.musicxml"),
        "instrument": instrument, "level": level,
    }, content_type="multipart/form-data")

def test_web_simplify_roundtrip(client):
    r = _upload_xml(client)
    assert r.status_code == 200, r.get_json()
    j = r.get_json()
    assert j["files"]["musicxml"] and j["events"]
    # the served musicxml must parse
    x = client.get(j["files"]["musicxml"])
    assert x.status_code == 200 and b"score-partwise" in x.data

def test_web_edit_changes_pitch(client):
    j = _upload_xml(client).get_json()
    first = [e for e in j["events"] if e["pi"] == j["melody_pi"]][0]
    r = client.post("/edit", json={"job": j["job"], "op": "up1",
                                   "pi": first["pi"],
                                   "measure": first["measure"], "t": first["t"]})
    assert r.status_code == 200, r.get_json()
    j2 = r.get_json()
    first2 = [e for e in j2["events"]
              if e["pi"] == j["melody_pi"] and abs(e["t"] - first["t"]) < 1e-3][0]
    assert first2["midi"] == first["midi"] + 1

def test_web_rejects_bad_extension(client):
    r = client.post("/simplify", data={"score": (io.BytesIO(b"x"), "a.docx")},
                    content_type="multipart/form-data")
    assert r.status_code == 400

def test_web_rejects_garbage_level(client):
    r = client.post("/simplify", data={
        "score": (io.BytesIO(b"<xml/>"), "a.musicxml"),
        "instrument": "piano", "level": "banana",
    }, content_type="multipart/form-data")
    assert r.status_code == 400
    assert "error" in r.get_json()

def test_web_rejects_corrupt_musicxml(client):
    r = client.post("/simplify", data={
        "score": (io.BytesIO(b"this is not music"), "a.musicxml"),
        "instrument": "piano", "level": "1",
    }, content_type="multipart/form-data")
    assert r.status_code == 422
    assert "error" in r.get_json()

def test_web_edit_rejects_bad_json(client):
    r = client.post("/edit", data="not json", content_type="application/json")
    assert r.status_code == 400
    assert "error" in r.get_json()

def test_web_edit_delete_removes_note(client):
    j = _upload_xml(client).get_json()
    first = [e for e in j["events"] if e["pi"] == j["melody_pi"]][0]
    n_before = len(j["events"])
    r = client.post("/edit", json={"job": j["job"], "op": "delete",
                                   "pi": first["pi"],
                                   "measure": first["measure"], "t": first["t"]})
    assert r.status_code == 200, r.get_json()
    assert len(r.get_json()["events"]) == n_before - 1

def test_web_second_edit_after_roundtrip(client):
    """The first edit re-parses current.musicxml; a second edit must still
    find its note (offsets/measures must survive the write->parse cycle)."""
    j = _upload_xml(client, instrument="guitar", level="2").get_json()
    melody = [e for e in j["events"] if e["pi"] == j["melody_pi"]]
    r1 = client.post("/edit", json={"job": j["job"], "op": "up1",
                                    "pi": melody[0]["pi"],
                                    "measure": melody[0]["measure"], "t": melody[0]["t"]})
    assert r1.status_code == 200, r1.get_json()
    j2 = r1.get_json()
    target = [e for e in j2["events"] if e["pi"] == j["melody_pi"]][-1]
    r2 = client.post("/edit", json={"job": j["job"], "op": "down1",
                                    "pi": target["pi"],
                                    "measure": target["measure"], "t": target["t"]})
    assert r2.status_code == 200, r2.get_json()
    after = [e for e in r2.get_json()["events"]
             if e["pi"] == j["melody_pi"] and abs(e["t"] - target["t"]) < 1e-3][0]
    assert after["midi"] == target["midi"] - 1
