"""Optical Music Recognition front-end.

Turns an image (png/jpg) or PDF of printed sheet music into MusicXML.

Two engines are supported, tried in this order:
  1. oemer     (pip install oemer)  -- pure Python, works on single images
  2. Audiveris (https://audiveris.github.io/audiveris/) -- Java app, best
     accuracy, handles multi-page PDFs natively. Set AUDIVERIS env var or
     have `audiveris` on PATH.

If the input is already MusicXML (.xml/.musicxml/.mxl), it is passed through.
"""

import os
import shutil
import subprocess
import tempfile
from pathlib import Path

IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".bmp", ".tiff", ".tif"}
XML_EXTS = {".xml", ".musicxml", ".mxl"}
MIDI_EXTS = {".mid", ".midi"}


def pdf_to_images(pdf_path: Path, out_dir: Path, dpi: int = 300) -> list[Path]:
    """Rasterize each PDF page to PNG using poppler's pdftoppm."""
    if shutil.which("pdftoppm") is None:
        raise RuntimeError(
            "pdftoppm not found. Install poppler-utils "
            "(apt: poppler-utils, brew: poppler) to read PDFs."
        )
    prefix = out_dir / "page"
    subprocess.run(
        ["pdftoppm", "-png", "-r", str(dpi), str(pdf_path), str(prefix)],
        check=True,
    )
    return sorted(out_dir.glob("page-*.png")) or sorted(out_dir.glob("page*.png"))


def _run_oemer(image: Path, out_dir: Path) -> Path:
    """Run oemer on one image; returns path to the produced MusicXML."""
    subprocess.run(
        ["oemer", str(image), "-o", str(out_dir)],
        check=True,
    )
    produced = sorted(out_dir.glob("*.musicxml")) + sorted(out_dir.glob("*.xml"))
    if not produced:
        raise RuntimeError(f"oemer produced no MusicXML for {image}")
    return produced[-1]


def _run_audiveris(source: Path, out_dir: Path) -> Path:
    exe = os.environ.get("AUDIVERIS") or shutil.which("audiveris") or shutil.which("Audiveris")
    if not exe:
        raise RuntimeError("Audiveris not found (set AUDIVERIS env var or add to PATH).")
    subprocess.run(
        [exe, "-batch", "-export", "-output", str(out_dir), str(source)],
        check=True,
    )
    produced = sorted(out_dir.rglob("*.mxl")) + sorted(out_dir.rglob("*.xml"))
    if not produced:
        raise RuntimeError("Audiveris produced no MusicXML output.")
    return produced[-1]


def recognize(source: str | Path, engine: str = "auto") -> Path:
    """Convert an image/PDF of sheet music to a MusicXML file.

    Returns the path to the recognized MusicXML (in a temp directory).
    """
    source = Path(source)
    if not source.exists():
        raise FileNotFoundError(source)

    ext = source.suffix.lower()
    if ext in XML_EXTS or ext in MIDI_EXTS:
        return source  # already symbolic notation, nothing to recognize

    from .audio_input import AUDIO_EXTS, transcribe_audio
    if ext in AUDIO_EXTS:
        return transcribe_audio(source)

    work = Path(tempfile.mkdtemp(prefix="omr_"))

    # Audiveris is the most accurate engine and handles images AND PDFs
    # natively: prefer it whenever it is installed (or explicitly requested).
    audiveris = (os.environ.get("AUDIVERIS") or shutil.which("audiveris")
                 or shutil.which("Audiveris"))
    if engine == "audiveris":
        return _run_audiveris(source, work)
    if engine == "auto" and audiveris and (ext == ".pdf" or ext in IMAGE_EXTS):
        return _run_audiveris(source, work)

    if ext == ".pdf":
        pages = pdf_to_images(source, work)
    elif ext in IMAGE_EXTS:
        pages = [source]
    else:
        raise ValueError(f"Unsupported input type: {ext}")

    if shutil.which("oemer") is None:
        raise RuntimeError(
            "No OMR engine available. Install one of:\n"
            "  pip install oemer            (lightweight, image-based)\n"
            "  Audiveris                    (best accuracy, reads PDFs)\n"
            "or supply a MusicXML file directly."
        )

    if len(pages) == 1:
        return _run_oemer(pages[0], work)

    # Multi-page: recognize each page, then stitch measures together.
    from music21 import converter, stream
    combined = None
    for i, page in enumerate(pages):
        page_dir = work / f"p{i}"
        page_dir.mkdir(exist_ok=True)
        xml = _run_oemer(page, page_dir)
        part_score = converter.parse(str(xml))
        if combined is None:
            combined = part_score
        else:
            if len(combined.parts) != len(part_score.parts):
                print(f"  ! page {i + 1} recognized {len(part_score.parts)} part(s), "
                      f"expected {len(combined.parts)} — extra parts are dropped")
            for a, b in zip(combined.parts, part_score.parts):
                for m in b.getElementsByClass(stream.Measure):
                    a.append(m)
    out = work / "combined.musicxml"
    combined.write("musicxml", fp=str(out))
    return out
