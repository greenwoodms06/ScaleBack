# ScaleBack — details

The long-form documentation. For the short version, see the [README](../README.md).

## Skill levels

| Level | Rhythm | Content | Keys (concert) | Range |
|---|---|---|---|---|
| 1 | quarter/half notes only, 70% tempo | melody only, no ornaments | guitar C,G · piano C,G,F · clarinet Bb,F (written C,G) | very narrow (e.g. clarinet stays below the break) |
| 2 | eighths allowed | melody only | + one more sharp/flat | narrow |
| 3 | dotted rhythms | melody + one-chord-per-bar accompaniment (root+5th) | moderate | moderate |
| 4 | sixteenths | fuller chords (≤4 notes), ornaments kept | most keys | wide |
| 5 | untouched | chord thinning + range check only | any | full instrument range |

Instrument-specific handling:
- **Clarinet** — output is the *written* Bb part (transposed up a major 2nd) and target
  keys are chosen so the *written* key is easy; level 1 avoids crossing the break.
- **Guitar** — favors open-string keys (C/G/D/A); level 1 fits first position.
- **Piano** — level ≤2 keeps everything near middle C; accompaniment becomes a simple
  left-hand part.

## Playability & fingering engines

After simplification, an instrument-specific engine verifies the result is physically
playable and annotates fingerings (skip with `--no-fingering`):

- **Guitar** (`guitar_playability.py`) — every melody note gets a string/fret via a
  Viterbi search minimizing position shifts and string hops (level caps the max fret:
  3/5/7/12/15). Every chord is checked against a backtracking shape-finder with a
  fret-span limit (2–4 frets) and a no-barre rule below level 3; chords with no valid
  grip are thinned (bass+top kept) or re-voiced, and the change is logged.
- **Piano** (`piano_playability.py`) — chords wider than the level's hand span
  (5th → 10th) are thinned; fast leaps beyond the level's reach are octave-folded.
  A Parncutt-style dynamic program then assigns fingers 1–5 using a finger-pair
  stretch-cost table, with thumb-crossings heavily penalized at levels 1–2.
- **Clarinet** (`clarinet_playability.py`) — a written-pitch difficulty table
  (chalumeau 0 → altissimo 5) caps note difficulty per level via octave folding;
  measures with too many *fast* break crossings (written B♭4↔B4) get the minority
  side folded across; any remaining crossings are marked "break!" in the score.

Each engine returns a report of every adjustment, printed by the CLI and shown in the
web app:

```
[3/4] Checking playability / assigning fingerings ...
  ~ re-voiced chord C3-E3-G3-B3-E4 -> C3-G3-B3-E4
  ~ m12: folded 3 note(s) to avoid 2 fast break crossings
  ! m20: fast break crossing kept
```

## Inputs and OMR engines

| Input | Path |
|---|---|
| `.musicxml` `.xml` `.mxl` | used directly |
| `.mid` `.midi` | parsed directly |
| `.png` `.jpg` etc. | OMR: Audiveris (preferred when installed) or oemer |
| `.pdf` | Audiveris natively, or rasterized via poppler for oemer |
| `.mp3` `.wav` etc. | transcribed by basic-pitch (`uv sync --extra audio`) |

- **Audiveris** ([install](https://github.com/audiveris/audiveris/releases)) is
  auto-detected via PATH or the `AUDIVERIS` env var and is strongly recommended:
  ~8× faster than oemer on CPU and more accurate. If a page contains no readable
  music (cover pages, tip sheets), it is skipped automatically and reported.
- **oemer** (`uv sync --extra omr`) is the pip-installable fallback (~4 min/page on
  CPU). The project pins CPU onnxruntime because oemer's GPU build hard-requires CUDA.
- The pipeline defends against messy OMR output: the melody source part is chosen by
  a musical sanity score (not blindly `parts[0]`), leading dead bars are trimmed, and
  junk parts (e.g. misread TAB staves) are excluded from the accompaniment.

## Web app

`uv run scaleback-web` → http://127.0.0.1:5757

- **Compare & fix** — the original scan beside the simplified preview
  (OpenSheetMusicDisplay). A Fix Notes toolbar steps through notes with one-tap edits
  (±semitone, ±octave, remove); edits apply server-side so downloads stay in sync.
- **Practice player** — WebAudio synth at *sounding* pitch, 40–140% tempo slider,
  bar-range looping, count-in, cursor following the score.
- **Play-along** — an autocorrelation pitch detector scores each melody note (±60
  cents) in a timing window (180 ms early grace, ≥300 ms to react); per-note
  early/late feedback, average timing offset, and best/last scores kept in
  localStorage per instrument and level. Monophonic: for piano it scores the
  melody's top line only. Use headphones so the mic doesn't hear the backing.
- **PDF export** — if music21 is configured with a MuseScore path, an
  "Also export a PDF" checkbox appears.
- Accessibility: keyboard-operable throughout, live-region status updates, visible
  focus, reduced-motion support.

## Using it as a library

```python
from music21 import converter
from simplify_sheet import recognize, get_profile, simplify_score, SimplifySettings

xml = recognize("song.pdf")                       # OMR step
score = converter.parse(str(xml))
settings = SimplifySettings.for_level(2)
settings.slow_tempo_ratio = 0.6                   # every knob is overridable
easy = simplify_score(score, get_profile("clarinet"), settings)
easy.write("musicxml", fp="easy_clarinet.musicxml")
```

## Optional system tools

- **MuseScore** — enables PDF export and is the best way to view/print results.
  Point music21 at it once:
  `from music21 import environment; environment.set("musicxmlPath", "/path/to/MuseScore4")`
- **poppler** (`pdftoppm`) — only needed to rasterize PDFs for oemer
  (Ubuntu: `apt install poppler-utils`, macOS: `brew install poppler`).

## Honest limitations & verification status

Verified by execution (July 2026): the full MusicXML/MIDI pipeline for all three
instruments, the CLI level matrix, web simplify/edit round-trips, both OMR engines on
a real scan, TAB export, and the browser timing math (node-tested). See CLAUDE.md for
the running verification log.

- OMR recognition errors are normal on real scans — always eyeball the side-by-side
  view. Handwritten music won't work. Repeats/voltas are played through linearly.
- The level-3+ accompaniment is deliberately naive (one chord per bar).
- Audio input (basic-pitch) has never been exercised here — treat as beta.
- The mic play-along has not yet been tested against a live instrument in a real room.
- Multi-page oemer stitching assumes consistent parts across pages.
- Copyright: only arrange music you have the right to arrange.
