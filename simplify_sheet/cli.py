"""Command-line interface.

Examples:
    # PDF of a song -> level-1 clarinet part
    python -m simplify_sheet song.pdf --instrument clarinet --level 1

    # photo of sheet music -> level-3 guitar arrangement with chords
    python -m simplify_sheet photo.jpg --instrument guitar --level 3

    # already have MusicXML? skip OMR entirely
    python -m simplify_sheet song.musicxml --instrument piano --level 2 -o easy_piano
"""

import argparse
import sys
from pathlib import Path

from music21 import converter

from .omr import recognize
from .instruments import get_profile
from .simplify import SimplifySettings, simplify_score
from .playability import apply_playability, print_report


def main(argv=None):
    ap = argparse.ArgumentParser(
        prog="simplify_sheet",
        description="Simplify sheet music (image/PDF/MusicXML) to a chosen skill level.",
    )
    ap.add_argument("input", help="image, .pdf, MusicXML, MIDI, or audio (.mp3/.wav) file")
    ap.add_argument("--instrument", "-i", required=True,
                    choices=["guitar", "piano", "clarinet"])
    ap.add_argument("--level", "-l", type=int, default=1, choices=[1, 2, 3, 4, 5],
                    help="1 = absolute beginner ... 5 = light cleanup only")
    ap.add_argument("--output", "-o", default=None,
                    help="output basename (default: <input>_<instrument>_L<level>)")
    ap.add_argument("--formats", default="musicxml,midi",
                    help="comma list of outputs: musicxml, midi, pdf "
                         "(pdf needs MuseScore/LilyPond)")
    ap.add_argument("--engine", default="auto", choices=["auto", "oemer", "audiveris"],
                    help="OMR engine preference")
    ap.add_argument("--no-transpose", action="store_true",
                    help="keep the original key even if it's hard for the level")
    ap.add_argument("--keep-rhythm", action="store_true",
                    help="don't quantize/merge short notes")
    ap.add_argument("--no-fingering", action="store_true",
                    help="skip the playability/fingering pass")
    args = ap.parse_args(argv)

    src = Path(args.input)
    print(f"[1/4] Reading {src.name} ...")
    xml_path = recognize(src, engine=args.engine)
    score = converter.parse(str(xml_path))

    print(f"[2/4] Simplifying for {args.instrument}, level {args.level} ...")
    profile = get_profile(args.instrument)
    settings = SimplifySettings.for_level(args.level)
    if args.no_transpose:
        settings.transpose_to_easy_key = False
    if args.keep_rhythm:
        settings.min_duration_ql = 0.0625
    result = simplify_score(score, profile, settings)

    if not args.no_fingering:
        print("[3/4] Checking playability / assigning fingerings ...")
        report = apply_playability(result, profile, args.level)
        print_report(report)
        if args.instrument == "guitar":
            from .guitar_tab import add_tab_part
            if add_tab_part(result):
                print("  added TAB staff")

    base = args.output or f"{src.stem}_{args.instrument}_L{args.level}"
    print("[4/4] Writing output ...")
    written = []
    for fmt in [f.strip().lower() for f in args.formats.split(",") if f.strip()]:
        try:
            if fmt == "musicxml":
                fp = result.write("musicxml", fp=f"{base}.musicxml")
            elif fmt == "midi":
                from .guitar_tab import without_tab
                fp = without_tab(result).write("midi", fp=f"{base}.mid")
            elif fmt == "pdf":
                fp = result.write("musicxml.pdf", fp=f"{base}.pdf")
            else:
                print(f"  ! unknown format '{fmt}', skipping")
                continue
            written.append(fp)
            print(f"  wrote {fp}")
        except Exception as e:  # e.g. no MuseScore installed for pdf
            print(f"  ! could not write {fmt}: {e}")

    if not written:
        sys.exit("No output produced.")
    print("Done. Open the .musicxml in MuseScore (free) to view/print, "
          "or play the .mid to hear it.")


if __name__ == "__main__":
    main()
