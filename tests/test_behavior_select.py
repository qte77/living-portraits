"""test_behavior_select.py -- _iter_clips' fail-open normalisation (runtime/behavior_select.py).

Pure stdlib under test. Covers issue #9's remaining swallow: `_iter_clips` is
documented "Never raises; an object we can't interpret yields []", but its two
`except Exception: return []` handlers used to swallow a REAL bug in a
ClipGraph-like source's `.edges()` (or in iterating a plain iterable) the same
way they swallow "this is not a shape I understand" -- indistinguishable from
here. Fail-open stays; the reason must now surface (same pattern PR #38
established for the provenance path).
"""
from __future__ import annotations

from behavior_select import _iter_clips


class _BrokenEdges:
    """Duck-types a ClipGraph: has a callable `.edges` that raises."""

    def edges(self):
        raise RuntimeError("edges exploded")


class _BrokenIterable:
    """Not a ClipGraph, not a single clip (no .tags) -- falls to the plain-iterable
    branch, whose __iter__ raises when consumed."""

    def __iter__(self):
        raise RuntimeError("iteration exploded")


def test_iter_clips_reports_a_broken_edges_method(capsys):
    assert _iter_clips(_BrokenEdges()) == []
    out = capsys.readouterr().out
    assert "edges exploded" in out and "_iter_clips" in out


def test_iter_clips_reports_a_broken_iterable(capsys):
    assert _iter_clips(_BrokenIterable()) == []
    out = capsys.readouterr().out
    assert "iteration exploded" in out and "_iter_clips" in out


def test_iter_clips_says_nothing_for_a_genuinely_unrecognised_shape(capsys):
    """An error line for the ordinary 'None' / 'not a shape we know' cases would
    train everyone to ignore it."""
    assert _iter_clips(object()) == []
    assert capsys.readouterr().out == ""
    assert _iter_clips(None) == []
    assert capsys.readouterr().out == ""


def test_iter_clips_still_works_on_the_happy_paths():
    class Ok:
        def edges(self):
            return ["a", "b"]

    assert _iter_clips(Ok()) == ["a", "b"]
    assert _iter_clips(["x", "y"]) == ["x", "y"]

    class SingleClip:
        tags = ("idle",)

    single = SingleClip()
    assert _iter_clips(single) == [single]
