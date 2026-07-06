# CLAUDE.md — ScaleBack (simplify_sheet)

## What this project is
`simplify_sheet` turns an **image / PDF / MusicXML / MIDI / audio** file of a song into a
**simplified arrangement** tuned to skill level 1–5 for **guitar, piano, or clarinet**, with
playability checks and fingerings, guitar TAB, a local **web UI** (compare-and-fix editor,
practice player, microphone play-along scoring), and a CLI.

Pipeline: `input → recognize() [OMR: oemer/Audiveris | AMT: basic-pitch] → MusicXML →
simplify_score() → apply_playability() → (guitar: add_tab_part) → MusicXML/MIDI + events JSON`

## Layout
```
src/simplify_sheet/
  instruments.py            # per-instrument ranges/keys/transposition (Bb clarinet = M2)
  omr.py                    # image/PDF → MusicXML (oemer or Audiveris); MIDI/audio routing
  audio_input.py            # MP3/WAV → MIDI via basic-pitch
  simplify.py               # core: key choice, melody extraction, quantize, range fold, accomp
  guitar_playability.py     # Viterbi string/fret + chord-shape backtracking
  piano_playability.py      # hand spans, leap folding, Parncutt-lite fingering DP
  clarinet_playability.py   # difficulty table, break-crossing folding
  guitar_tab.py             # TAB staff from string/fret marks; without_tab() for MIDI export
  events.py                 # note-events JSON: powers browser player + mic scoring
  cli.py  web.py  templates/index.html
tests/                      # pytest suite incl. node-driven JS timing tests
```

## Dev environment
- uv project (pyproject.toml + uv.lock; src/ layout, package `simplify_sheet`,
  project/CLI name `scaleback`). Setup: `uv sync --extra web`.
  OMR/audio extras are optional: `uv sync --all-extras`.
- Run tests: `uv run pytest -q` (35 tests, all green).
- Lint: `uv run ruff check .` (config in pyproject.toml [tool.ruff]).
- CLI: `uv run scaleback <file> -i <instrument> -l <level>`.
- Web UI: `uv run scaleback-web` → http://127.0.0.1:5757

## Verification status (2026-07-06)
Verified by execution: full MusicXML/MIDI pipeline for all 3 instruments,
CLI (levels 1/3/5 matrix), web /simplify + /edit round-trips, event parity between
in-memory scores and re-parsed MusicXML, TAB clef export, clarinet written-key handling,
OSMD 1.8.4 cursor API casing (against the package's .d.ts), JS timing helpers (node).
Also verified: both OMR engines end-to-end on a real scan. Audiveris 5.10.2 lives at
~/.local/opt/audiveris (symlinked as ~/.local/bin/audiveris) and is auto-preferred by
recognize() for images and PDFs (~30 s/page vs oemer's ~4 min, and it caught a 6/8 time
signature oemer missed). oemer stays the pip fallback; onnxruntime-gpu is excluded via
a uv override in pyproject.toml because its import hard-requires CUDA.
**Never executed:** basic-pitch audio input, the browser player/mic in a live browser
session (the AudioContext/mic teardown bug was fixed by inspection — see stopPlayback
vs stopAll in index.html).

## Conventions (do not break)
- Playability engines mutate scores in place and return report objects with `.adjustments`
  / `.warnings` — the CLI and web both print them.
- Events JSON contract (the frontend depends on it):
  `{events:[{t,d,midi,sounding,part,pi,measure,string?,fret?,finger?}], bpm,
  beats_per_measure, n_measures, melody_part, melody_pi}` — `pi` is the stable part index
  (part *ids* like "melody" do not survive MusicXML round-trips; indices do).
  Tied continuations are merged into one event (a tie is not a new attack).
- The melody part must keep `id="melody"` through the pipeline — `quantize_rhythm`
  returns a fresh Part, so `simplify_score` re-stamps the id. The guitar playability
  and TAB passes find the melody by that id.
- `quantize_rhythm` guarantees monophonic, non-overlapping, grid-aligned output — this
  is what keeps event offsets identical across MusicXML write→parse (the /edit flow
  depends on that parity).
- `simplify_score` runs makeMeasures **and makeTies** so in-memory scores match their
  exported MusicXML measure-for-measure.
- Clarinet scores are WRITTEN pitch everywhere after simplify_score; `sounding = midi - 2`.
- Keep everything runnable fully offline except the OSMD CDN fetch.
- Timing helpers in index.html (`noteWindow`, `timingLabel`) are pure functions,
  extracted by name and unit-tested via node in tests/test_timing_windows.py — keep them
  dependency-free and top-level.
- To CHECK OUTPUT QUALITY autonomously, render scores to PNG and look at them:
  verovio + cairosvg are dev deps (`tk = verovio.toolkit(); tk.loadFile(xml);
  cairosvg.svg2png(bytestring=tk.renderToSVG(1).encode(), write_to=...)`). This catches
  what green tests can't (e.g. a structurally valid score that opens with 34 empty bars).
- OMR output is hostile: parts may be silent for whole pages or be misread-TAB junk.
  simplify_score picks the melody source via part_melody_score() and trims leading dead
  bars — don't reintroduce a bare parts[0] assumption.
