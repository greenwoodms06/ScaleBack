# simplify_sheet

Turn an **image or PDF of sheet music** into a **simplified arrangement** tuned to a
skill level (1–5), for **acoustic guitar, piano, or clarinet**.

Pipeline: `image/PDF → OMR (optical music recognition) → MusicXML → simplification → MusicXML / MIDI / PDF`

## Install

This is a [uv](https://docs.astral.sh/uv/) project:

```bash
uv sync --extra web              # core (music21) + the local web UI
uv sync --all-extras             # + OMR (oemer) and audio (basic-pitch) input
# optional but recommended:
#   Audiveris  – far more accurate OMR, reads PDFs directly (https://audiveris.github.io)
#   MuseScore  – free; lets the tool export PDF and lets you view/print the result
#   poppler    – needed only to rasterize PDFs when using oemer
#                (Ubuntu: apt install poppler-utils, macOS: brew install poppler)
```

`uv run <command>` always uses the project environment — no activation needed.

Point music21 at MuseScore once for PDF export:
```python
from music21 import environment
environment.set("musicxmlPath", "/path/to/MuseScore4")
```

## Use

```bash
# absolute-beginner clarinet part from a PDF
uv run scaleback song.pdf -i clarinet -l 1

# level-3 guitar arrangement (melody + simple accompaniment) from a photo
uv run scaleback photo.jpg -i guitar -l 3

# skip OMR if you already have MusicXML (e.g. downloaded from MuseScore.com)
uv run scaleback song.musicxml -i piano -l 2 --formats musicxml,midi,pdf
```

Outputs `<name>_<instrument>_L<level>.musicxml` (+ `.mid`, optionally `.pdf`).

## What each level does

| Level | Rhythm | Content | Keys (concert) | Range |
|---|---|---|---|---|
| 1 | quarter/half notes only, 70% tempo | melody only, no ornaments | guitar C,G · piano C,G,F · clarinet Bb,F (written C,G) | very narrow (e.g. clarinet stays below the break) |
| 2 | eighths allowed | melody only | + one more sharp/flat | narrow |
| 3 | dotted rhythms | melody + one-chord-per-bar accompaniment (root+5th) | moderate | moderate |
| 4 | sixteenths | fuller chords (≤4 notes), ornaments kept | most keys | wide |
| 5 | untouched | chord thinning + range check only | any | full instrument range |

Instrument-specific handling:
- **Clarinet** — output is the *written* Bb part (transposed up a major 2nd) and target keys are chosen so the *written* key is easy; level 1 avoids crossing the break (written A4/B4).
- **Guitar** — favors open-string keys (C/G/D/A); level 1 fits first position.
- **Piano** — level ≤2 keeps everything near middle C; accompaniment becomes a simple left-hand part.

## Use as a library

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

## Playability & fingering pass

After simplification, an instrument-specific engine verifies the result is physically playable and annotates fingerings (skip with `--no-fingering`):

- **Guitar** (`guitar_playability.py`) — every melody note gets a string/fret via a Viterbi search minimizing position shifts and string hops (level caps the max fret: 3/5/7/12/15). Every chord is checked against a backtracking shape-finder with a fret-span limit (2–4 frets) and a no-barre rule below level 3; chords with no valid grip are thinned (bass+top kept) or re-voiced, and the change is logged. Verified: it finds the open x32010 shape for C major and rejects impossible clusters.
- **Piano** (`piano_playability.py`) — chords wider than the level's hand span (5th → 10th) are thinned; fast leaps beyond the level's reach are octave-folded. A Parncutt-style dynamic program then assigns fingers 1–5 using a finger-pair stretch-cost table, with thumb-crossings heavily penalized at levels 1–2 (beginners stay in five-finger positions). Verified: produces 1-2-3-4-5 for five-finger patterns, 1-2-3-5 for arpeggios, 1-5 for broken octaves.
- **Clarinet** (`clarinet_playability.py`) — a written-pitch difficulty table (chalumeau 0 → altissimo 5) caps note difficulty per level via octave folding; measures with too many *fast* break crossings (written B♭4↔B4) get the minority side folded across; any remaining crossings are marked "break!" in the score so the teacher sees them.

Each engine returns a report of every adjustment it made, printed by the CLI:
```
[3/4] Checking playability / assigning fingerings ...
  ~ re-voiced chord C3-E3-G3-B3-E4 -> C3-G3-B3-E4
  ~ m12: folded 3 note(s) to avoid 2 fast break crossings
  ! m20: fast break crossing kept
```

## Web UI (optional)

For anyone who'd rather not touch a terminal:

```bash
uv run scaleback-web               # open http://127.0.0.1:5757
```

One page, four steps: drop a score → pick the instrument → set the level on the **staff slider** (the note climbs the staff as the music gets harder) → simplify. You get an in-browser preview of the result (rendered with OpenSheetMusicDisplay, no MuseScore needed just to look), download buttons for MusicXML/MIDI, and the playability report shown as engraver-style notes. If music21 is configured with a MuseScore path, an "Also export a PDF" checkbox appears and adds a PDF download. Everything runs locally; the only network use is fetching the preview renderer once from a CDN (downloads still work offline).

Accessibility: the whole flow is keyboard-operable (the staff slider is a real range input with spoken level names), status updates are announced via live regions, focus is always visible, and motion is disabled for users who prefer reduced motion.

## Audio input, TAB, editing, practice & play-along

**Audio input** — drop an MP3/WAV (or `.mid`) instead of a scan; Spotify's basic-pitch transcribes it to notes first (`uv sync --extra audio`). Works best on solo recordings; the simplifier's melody extraction doubles as cleanup for messy transcriptions.

**Guitar TAB** — for guitar the output gains a tablature staff built directly from the Viterbi string/fret assignments, exported as standard MusicXML technicals (renders in MuseScore and the web preview).

**Compare & fix (web UI)** — the original scan appears beside the simplified preview. OMR makes mistakes, so a Fix Notes toolbar steps through notes (Prev/Next moves the score cursor) with one-tap edits: ±semitone, ±octave, remove. Edits apply server-side to the real MusicXML, so downloads stay in sync.

**Practice player** — plays the arrangement in the browser (WebAudio synth at *sounding* pitch, so clarinet parts sound correct), with a 40–140% tempo slider, bar-range looping, a count-in, and a cursor that follows along.

**Play-along with microphone** — Yousician-style: hit Start, the count-in plays, and an autocorrelation pitch detector listens as you play. Each melody note gets a timing window (180 ms early grace, at least 300 ms to react); play the right pitch (±60 cents, tested accurate to ~2 cents on clean tones) in the window and its dot turns green. You get live "expected vs heard" feedback with the fingering/fret shown, per-note timing (hover a dot for "45 ms late"), and a final score with your average early/late offset plus tempo advice. Practice results are saved in the browser (localStorage), so students see best/last scores per instrument and level across sessions. Options: melody guide on/off, octave-tolerant matching (handy for guitar). Honest limits: it's monophonic — for piano it scores the melody's top line only, chords aren't judged (the page says so next to the mic button); use headphones so the mic doesn't hear the backing; very noisy rooms will confuse it.

## Honest limitations

What has actually been verified (July 2026): the full MusicXML/MIDI pipeline — simplify,
playability, TAB, events, CLI (3 instruments × levels 1/3/5), and the web endpoints
including edits — runs green under pytest (35 tests) with music21 10.5, and outputs
re-parse cleanly with correct key signatures and a real TAB clef. The browser-side
timing math is unit-tested with node. What has **not** been exercised end-to-end:

- **OMR is the weak link.** The oemer path is now verified end-to-end (its demo scan →
  simplified part, ~4 min/page on CPU; the project pins CPU onnxruntime because
  oemer's GPU build needs CUDA). But recognition quality on *your* scans will vary:
  oemer works best on clean scans; Audiveris is much better on real-world PDFs.
  Handwritten music won't work. Always eyeball the result in MuseScore.
- **Audio input (basic-pitch) has never been run here** — treat it as beta until you've
  fed it a real recording (`uv sync --extra audio`).
- **The mic play-along in a live room.** The pitch detector is verified against clean
  synthesized tones (~2 cents), and a mic-killing AudioContext teardown bug was fixed by
  inspection — but nobody has hummed at it in a real browser session yet.
- The OSMD preview fetches from a CDN once; the TAB staff preview depends on OSMD's
  tablature support and may look rougher than MuseScore's rendering.
- The level-3+ accompaniment is deliberately naive (one chord per bar). It's a practice
  aid, not an arrangement a human arranger would sign.
- Multi-page image stitching assumes consistent parts across pages (pages with a
  different part count are logged and the extra parts dropped).
- Copyright: only run this on music you have the right to arrange (public domain, your
  own, or licensed).
