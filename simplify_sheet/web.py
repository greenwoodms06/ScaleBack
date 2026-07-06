"""Optional local web UI.

Run with:
    pip install flask
    python -m simplify_sheet.web          # then open http://127.0.0.1:5757

Upload an image/PDF/MusicXML/MIDI/audio file, pick instrument + level, get:
  - side-by-side comparison with the original scan
  - in-browser preview (OpenSheetMusicDisplay) with cursor-based quick fixes
  - practice player (tempo slider, measure looping, count-in)
  - play-along mode: microphone pitch detection scores your notes & timing
"""

import shutil
import subprocess
import tempfile
import uuid
from pathlib import Path

from flask import Flask, jsonify, render_template, request, send_from_directory
from music21 import converter, note as m21note

from .omr import recognize
from .instruments import get_profile
from .simplify import SimplifySettings, simplify_score
from .playability import apply_playability
from .guitar_tab import add_tab_part
from .events import extract_events

app = Flask(__name__)
JOBS_ROOT = Path(tempfile.mkdtemp(prefix="simplify_sheet_web_"))
IMAGE = {".png", ".jpg", ".jpeg", ".bmp", ".tif", ".tiff"}
ALLOWED = IMAGE | {".pdf", ".xml", ".musicxml", ".mxl", ".mid", ".midi",
                   ".mp3", ".wav", ".m4a", ".ogg", ".flac", ".aac"}
MAX_MB = 60
app.config["MAX_CONTENT_LENGTH"] = MAX_MB * 1024 * 1024

# clarinet is written a major 2nd above sounding pitch
SOUNDING_OFFSET = {"clarinet": -2, "piano": 0, "guitar": 0}


def _musescore_available() -> bool:
    """True when music21 is configured with a MusicXML renderer (PDF export)."""
    try:
        from music21 import environment
        p = environment.Environment()["musicxmlPath"]
        return bool(p) and Path(str(p)).exists()
    except Exception:
        return False


PDF_AVAILABLE = _musescore_available()


@app.get("/")
def index():
    return render_template("index.html", pdf_available=PDF_AVAILABLE)


def _source_preview(src: Path, job_dir: Path):
    """A viewable image of the original, for side-by-side comparison."""
    ext = src.suffix.lower()
    if ext in IMAGE:
        prev = job_dir / ("source" + ext)
        shutil.copy(src, prev)
        return prev.name
    if ext == ".pdf" and shutil.which("pdftoppm"):
        subprocess.run(["pdftoppm", "-png", "-r", "120", "-f", "1", "-l", "1",
                        str(src), str(job_dir / "source")], check=False)
        hits = sorted(job_dir.glob("source*.png"))
        if hits:
            return hits[0].name
    return None


def _render_outputs(job_id: str, instrument: str, level: int, score=None,
                    want_pdf: bool = False):
    """(Re)write musicxml/midi/events for the job's current score.

    Pass the in-memory score when available (part ids like 'melody'/'tab'
    do NOT survive a MusicXML round-trip; indices do, which is why events
    carry a stable part index `pi`)."""
    job_dir = JOBS_ROOT / job_id
    if score is None:
        score = converter.parse(str(job_dir / "current.musicxml"))
    base = f"simplified_{instrument}_L{level}"
    out_xml = job_dir / f"{base}.musicxml"
    score.write("musicxml", fp=str(out_xml))
    files = {"musicxml": f"/files/{job_id}/{out_xml.name}"}
    try:
        from .guitar_tab import without_tab
        out_mid = job_dir / f"{base}.mid"
        without_tab(score).write("midi", fp=str(out_mid))
        files["midi"] = f"/files/{job_id}/{out_mid.name}"
    except Exception:
        pass
    if want_pdf and PDF_AVAILABLE:
        try:
            out_pdf = job_dir / f"{base}.pdf"
            score.write("musicxml.pdf", fp=str(out_pdf))
            if not out_pdf.exists():   # some music21 versions add suffixes
                hits = sorted(job_dir.glob(f"{base}*.pdf"))
                out_pdf = hits[-1] if hits else out_pdf
            if out_pdf.exists():
                files["pdf"] = f"/files/{job_id}/{out_pdf.name}"
        except Exception:
            pass  # PDF is best-effort; MusicXML/MIDI stay authoritative
    ev = extract_events(score, SOUNDING_OFFSET.get(instrument, 0))
    return files, ev


@app.post("/simplify")
def simplify_endpoint():
    f = request.files.get("score")
    if f is None or not f.filename:
        return jsonify(error="No file received. Choose a score to upload."), 400
    ext = Path(f.filename).suffix.lower()
    if ext not in ALLOWED:
        return jsonify(error=f"Unsupported file type '{ext}'. Use an image, "
                             "PDF, MusicXML, MIDI, or audio file."), 400

    instrument = request.form.get("instrument", "piano")
    try:
        level = max(1, min(5, int(request.form.get("level", 1))))
    except (TypeError, ValueError):
        return jsonify(error="Level must be a number from 1 to 5."), 400
    want_pdf = request.form.get("pdf", "0") == "1"
    job_id = uuid.uuid4().hex[:12]
    job_dir = JOBS_ROOT / job_id
    job_dir.mkdir(parents=True)
    src = job_dir / ("input" + ext)
    f.save(src)

    try:
        xml_path = recognize(src)
        score = converter.parse(str(xml_path))
    except Exception as e:
        return jsonify(error=f"Could not read the score: {e}. Cleaner scans, "
                             "solo recordings, and MusicXML work best."), 422

    profile = get_profile(instrument)
    settings = SimplifySettings.for_level(level)
    settings.transpose_to_easy_key = request.form.get("transpose", "1") == "1"
    try:
        result = simplify_score(score, profile, settings)
        report = None
        if request.form.get("fingering", "1") == "1":
            report = apply_playability(result, profile, level)
        if instrument == "guitar":
            add_tab_part(result)
    except Exception as e:
        return jsonify(error=f"Simplification failed: {e}"), 500

    result.write("musicxml", fp=str(job_dir / "current.musicxml"))
    (job_dir / "meta.txt").write_text(f"{instrument}\n{level}\n{int(want_pdf)}\n")
    files, ev = _render_outputs(job_id, instrument, level, score=result,
                                want_pdf=want_pdf)

    return jsonify(
        job=job_id,
        instrument=instrument,
        level=level,
        files=files,
        source=(f"/files/{job_id}/{name}"
                if (name := _source_preview(src, job_dir)) else None),
        adjustments=getattr(report, "adjustments", []) if report else [],
        warnings=(getattr(report, "warnings", []) +
                  getattr(report, "unplayable", [])) if report else [],
        **ev,
    )


@app.post("/edit")
def edit_endpoint():
    """Quick fixes: nudge or delete the note at (part, measure, offset)."""
    d = request.get_json(silent=True)
    if not isinstance(d, dict):
        return jsonify(error="Bad request body."), 400
    job_id = Path(str(d.get("job", ""))).name
    job_dir = JOBS_ROOT / job_id
    cur = job_dir / "current.musicxml"
    if not cur.exists() or not (job_dir / "meta.txt").exists():
        return jsonify(error="Session expired — simplify the score again."), 404
    op = d.get("op")
    if op not in {"up1", "down1", "up12", "down12", "delete"}:
        return jsonify(error="Unknown edit."), 400
    try:
        pi = int(d.get("pi", 0))
        measure = int(d.get("measure", -1))
        t = float(d.get("t", -99))
    except (TypeError, ValueError):
        return jsonify(error="Bad note reference."), 400

    score = converter.parse(str(cur))
    target, best_gap = None, 0.26
    parts = list(score.parts)
    if 0 <= pi < len(parts):
        for n in parts[pi].flatten().notes:
            if n.measureNumber != measure:
                continue
            gap = abs(float(n.offset) - t)
            if gap < best_gap:
                target, best_gap = n, gap
    if target is None:
        return jsonify(error="Couldn't find that note — it may have been edited."), 404

    if op == "delete":
        r = m21note.Rest()
        r.duration = target.duration
        target.activeSite.replace(target, r)
    else:
        semis = {"up1": 1, "down1": -1, "up12": 12, "down12": -12}[op]
        for p in (target.pitches if hasattr(target, "pitches") else [target.pitch]):
            p.midi += semis

    score.write("musicxml", fp=str(cur))
    meta = (job_dir / "meta.txt").read_text().split()
    instrument, level = meta[0], int(meta[1])
    want_pdf = len(meta) > 2 and meta[2] == "1"
    files, ev = _render_outputs(job_id, instrument, level, want_pdf=want_pdf)
    return jsonify(job=job_id, files=files, **ev)


@app.get("/files/<job_id>/<path:name>")
def files(job_id, name):
    return send_from_directory(JOBS_ROOT / Path(job_id).name, name,
                               as_attachment=False)


def main():
    print("Simplify Sheet — open http://127.0.0.1:5757 in your browser")
    app.run(host="127.0.0.1", port=5757, debug=False)


if __name__ == "__main__":
    main()
