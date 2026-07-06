"""Unit-test the pure JS timing helpers in templates/index.html with node.

The functions are extracted from the template by name so the test always runs
against the shipped code, not a copy that could drift.
"""

import re
import shutil
import subprocess
from pathlib import Path

import pytest

TEMPLATE = (Path(__file__).resolve().parents[1]
            / "src" / "simplify_sheet" / "templates" / "index.html")

pytestmark = pytest.mark.skipif(shutil.which("node") is None,
                                reason="node not installed")


def _extract(name: str) -> str:
    src = TEMPLATE.read_text(encoding="utf-8")
    m = re.search(rf"function {name}\([^)]*\)\{{.*?\n\}}", src, re.S)
    assert m, f"function {name} not found in index.html"
    return m.group(0)


JS_ASSERTS = r"""
function assert(cond, msg){ if(!cond){ console.error("FAIL: "+msg); process.exit(1); } }

// 120 bpm at 100% -> bs = 0.5 s/beat
var bs = 0.5;

// window opens 180 ms (=0.36 beats) before the onset
var w = noteWindow(4.0, 1.0, bs);
assert(Math.abs((4.0 - w.a)*bs - 0.18) < 1e-9, "early margin must be 180 ms, got "+((4.0-w.a)*bs));

// long note: window closes at 75% of the duration
assert(Math.abs(w.b - (4.0 + 0.75)) < 1e-9, "late edge = onset+0.75 beats for a 1-beat note");

// short note at fast tempo: the 300 ms floor wins over 75% duration
var fast = 60/(180*1.4);          // 180 bpm at 140% -> ~0.238 s/beat
var w2 = noteWindow(0.0, 0.25, fast);
assert(Math.abs((w2.b - 0.0)*fast - 0.30) < 1e-9, "late edge floor must be 300 ms");

// slow tempo: early margin shrinks in beats but stays 180 ms in seconds
var slow = 60/(120*0.4);          // 120 bpm at 40% -> 1.25 s/beat
var w3 = noteWindow(2.0, 1.0, slow);
assert(Math.abs((2.0 - w3.a)*slow - 0.18) < 1e-9, "early margin tempo-invariant in seconds");

// windows are ordered and contain the onset
[w, w2, w3].forEach(function(x){ assert(x.a < x.b, "a<b"); });
assert(w.a < 4.0 && 4.0 < w.b, "onset inside window");

// timingLabel: sign conventions and dead zone
assert(timingLabel(-0.12) === "120 ms early", "early label, got "+timingLabel(-0.12));
assert(timingLabel(0.2) === "200 ms late", "late label");
assert(timingLabel(0.01) === "on time", "dead zone +");
assert(timingLabel(-0.049) === "on time", "dead zone -");

console.log("ok");
"""


def test_timing_helpers_with_node(tmp_path):
    js = _extract("noteWindow") + "\n" + _extract("timingLabel") + "\n" + JS_ASSERTS
    script = tmp_path / "timing.test.js"
    script.write_text(js, encoding="utf-8")
    proc = subprocess.run(["node", str(script)], capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr or proc.stdout
    assert proc.stdout.strip() == "ok"
