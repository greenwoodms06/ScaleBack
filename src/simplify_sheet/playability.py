"""Playability dispatcher: routes to the instrument-specific engine.

Runs AFTER simplify_score(). For clarinet the score is already in written
pitch, which is what the clarinet engine expects.
"""

from .instruments import InstrumentProfile
from . import guitar_playability, piano_playability, clarinet_playability


def apply_playability(score, profile: InstrumentProfile, level: int):
    """Mutates the score in place; returns a report object with
    .adjustments (what was changed) and, where present, .warnings/.unplayable."""
    if profile.name == "acoustic guitar":
        return guitar_playability.apply(score, level)
    if profile.name == "piano":
        return piano_playability.apply(score, level)
    if profile.name == "clarinet":
        return clarinet_playability.apply(score, level)
    return None


def print_report(report):
    if report is None:
        return
    for msg in getattr(report, "adjustments", []):
        print(f"  ~ {msg}")
    for msg in getattr(report, "warnings", []):
        print(f"  ! {msg}")
    for msg in getattr(report, "unplayable", []):
        print(f"  ! unplayable: {msg}")
