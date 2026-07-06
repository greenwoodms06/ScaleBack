"""Instrument profiles used to constrain the simplified arrangement.

Each profile defines:
  - full sounding range (what the instrument can physically play)
  - comfortable range per skill level (what a student at that level should see)
  - keys that are friendly at each skill level
  - transposition (clarinet in Bb reads a major 2nd above sounding pitch)
"""

from dataclasses import dataclass, field
from music21 import pitch, interval


@dataclass
class InstrumentProfile:
    name: str
    music21_instrument: str            # class name in music21.instrument
    low: str                           # lowest sounding pitch
    high: str                          # highest sounding pitch
    # comfortable SOUNDING range by skill level 1..5 -> (low, high)
    level_ranges: dict = field(default_factory=dict)
    # preferred concert keys (number of sharps(+)/flats(-)) by skill level
    level_keys: dict = field(default_factory=dict)
    # written pitch = sounding pitch transposed by this interval ("M2" for Bb clarinet)
    written_transposition: str | None = None
    # can the instrument play chords?
    polyphonic: bool = False

    def sounding_range(self, level: int):
        lo, hi = self.level_ranges.get(level, (self.low, self.high))
        return pitch.Pitch(lo), pitch.Pitch(hi)

    def allowed_key_signatures(self, level: int):
        """Return the set of key signatures (as sharp counts) OK at this level."""
        return self.level_keys.get(level, list(range(-7, 8)))

    def written(self, p: pitch.Pitch) -> pitch.Pitch:
        if not self.written_transposition:
            return p
        return p.transpose(interval.Interval(self.written_transposition))


GUITAR = InstrumentProfile(
    name="acoustic guitar",
    music21_instrument="AcousticGuitar",
    low="E2", high="B5",
    level_ranges={
        1: ("E3", "G4"),   # first position, mostly strings 1-3
        2: ("A2", "A4"),
        3: ("E2", "C5"),
        4: ("E2", "E5"),
        5: ("E2", "B5"),
    },
    # sharp keys sit best on guitar (open strings): C, G, D, A, E, and relative minors
    level_keys={
        1: [0, 1],            # C, G
        2: [0, 1, 2, -1],     # + D, F
        3: [0, 1, 2, 3, -1],  # + A
        4: list(range(-2, 5)),
        5: list(range(-7, 8)),
    },
    polyphonic=True,
)

PIANO = InstrumentProfile(
    name="piano",
    music21_instrument="Piano",
    low="A0", high="C8",
    level_ranges={
        1: ("C3", "G5"),   # both hands near middle C
        2: ("G2", "C6"),
        3: ("C2", "C7"),
        4: ("A0", "C8"),
        5: ("A0", "C8"),
    },
    level_keys={
        1: [0, 1, -1],           # C, G, F
        2: [0, 1, 2, -1, -2],
        3: list(range(-3, 4)),
        4: list(range(-5, 6)),
        5: list(range(-7, 8)),
    },
    polyphonic=True,
)

CLARINET = InstrumentProfile(
    name="clarinet",
    music21_instrument="Clarinet",
    low="D3", high="B-6",          # sounding range of a Bb clarinet
    level_ranges={
        1: ("E3", "F4"),   # below the break (written G3..G4-ish)
        2: ("D3", "B-4"),  # up to just over the break
        3: ("D3", "F5"),
        4: ("D3", "C6"),
        5: ("D3", "B-6"),
    },
    # keys chosen so the WRITTEN key (concert + M2) is friendly:
    # concert Bb -> written C, concert Eb -> written F, concert F -> written G
    level_keys={
        1: [-2, -1],              # concert Bb, F  (written C, G)
        2: [-3, -2, -1, 0],       # + Eb, C        (written F, D)
        3: list(range(-4, 2)),
        4: list(range(-5, 4)),
        5: list(range(-7, 8)),
    },
    written_transposition="M2",
    polyphonic=False,
)

PROFILES = {
    "guitar": GUITAR,
    "acoustic-guitar": GUITAR,
    "piano": PIANO,
    "clarinet": CLARINET,
}


def get_profile(name: str) -> InstrumentProfile:
    key = name.strip().lower().replace("_", "-").replace(" ", "-")
    if key not in PROFILES:
        raise ValueError(f"Unknown instrument '{name}'. Choose from: guitar, piano, clarinet")
    return PROFILES[key]
