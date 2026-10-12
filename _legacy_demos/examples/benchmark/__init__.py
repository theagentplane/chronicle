"""The Chronicle incident benchmark: recorded agent incidents + an evaluation harness.

Each scenario is a small ``model -> tool -> model`` agent where an unguarded tool
produces an unsafe result and a guarded version corrects it. Every scenario has three
tool variants:

- ``ungated``  the incident (unsafe): the cut-point test must FAIL (fault detected).
- ``gated``    the fix (safe): the cut-point test must PASS.
- ``benign``   an unrelated correct change: the cut-point test must PASS (specificity).

The harness records each incident, replays it, and cut-point tests all three variants,
reporting recording overhead, store growth, replay determinism, and detection /
specificity. See ``harness.py``.
"""
