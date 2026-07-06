"""Audio input: transcribe MP3/WAV/etc. into notation via basic-pitch.

Spotify's basic-pitch (pip install basic-pitch) does automatic music
transcription (AMT): audio -> MIDI. We then parse the MIDI with music21
and hand it to the same simplification pipeline as scanned scores.

Works best on solo, monophonic-ish recordings (a sung melody, one guitar,
one piano). Dense mixes will transcribe messily -- the simplifier's
melody-extraction and rhythm quantization then act as a cleanup stage,
which is genuinely helpful here.
"""

import tempfile
from pathlib import Path

AUDIO_EXTS = {".mp3", ".wav", ".m4a", ".ogg", ".flac", ".aac"}


def transcribe_audio(source: Path) -> Path:
    """Audio file -> MIDI file path (in a temp dir)."""
    try:
        from basic_pitch.inference import predict
        from basic_pitch import ICASSP_2022_MODEL_PATH
    except ImportError as e:
        raise RuntimeError(
            "Audio input needs basic-pitch: pip install basic-pitch"
        ) from e

    work = Path(tempfile.mkdtemp(prefix="amt_"))
    _, midi_data, _ = predict(str(source), ICASSP_2022_MODEL_PATH)
    out = work / (source.stem + ".mid")
    midi_data.write(str(out))
    return out
