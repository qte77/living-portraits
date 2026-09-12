"""test_clip_player.py -- clip_frames' asset-decode fail-open path (runtime/clip_player.py).

numpy-only under test. Covers issue #9's remaining swallow: a bad/missing asset used
to fall back to synthetic frames with no trace, indistinguishable from "this clip has
no asset at all". Fail-open stays -- the show must never go black -- but the reason
must now surface (same pattern PR #38 established for the provenance path).
"""
from __future__ import annotations

import pytest

from conftest import HAVE_NUMPY

pytestmark = pytest.mark.skipif(not HAVE_NUMPY, reason="clip_player tests need numpy")

import clip_player as cp
from clip_graph import Clip
import stage_render as sr


def _boom(clip, width, height):
    raise RuntimeError("decode exploded")
    yield  # pragma: no cover -- unreachable; keeps this a generator function


def test_clip_frames_reports_asset_decode_failure_and_falls_back(monkeypatch, capsys):
    monkeypatch.setattr(cp, "_iter_asset", _boom)
    clip = Clip(from_node="idle", to_node="lean_in",
                asset="clips/phineas/a2g/v0.mp4", frames=4)
    frames = list(cp.clip_frames(clip, 64, 64, sr.PANEL_THEME["A"]))
    assert frames, "a decode failure must still fall back to synthetic frames, never go black"
    out = capsys.readouterr().out
    assert "decode exploded" in out and "falling back to synthetic" in out


def test_clip_frames_says_nothing_on_a_clean_decode(monkeypatch, capsys):
    """An error line on the happy path would train everyone to ignore it."""
    def _ok(clip, width, height):
        yield from ()  # produces nothing, but does not raise either

    monkeypatch.setattr(cp, "_iter_asset", _ok)
    clip = Clip(from_node="idle", to_node="lean_in",
                asset="clips/phineas/a2g/v0.mp4", frames=4)
    frames = list(cp.clip_frames(clip, 64, 64, sr.PANEL_THEME["A"]))
    assert frames  # still falls back (nothing produced), but silently
    assert capsys.readouterr().out == ""
