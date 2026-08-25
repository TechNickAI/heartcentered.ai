#!/usr/bin/env python3
"""Tests for AA slug resolution.

Guards two properties:
  1. Derivation reproduces the hand-maintained map (except the one reordered
     entry, which the hand map must keep winning).
  2. Resolution NEVER returns a slug absent from the AA payload, so a derived
     near-miss can never attach one model's scores to another.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

import importlib.util

_spec = importlib.util.spec_from_file_location(
    "fetch_model", Path(__file__).parent.parent / "scripts" / "fetch-model.py"
)
fetch_model = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(fetch_model)

AA_SLUG_MAP = fetch_model.AA_SLUG_MAP
derive_aa_slug = fetch_model.derive_aa_slug
resolve_aa_slug = fetch_model.resolve_aa_slug

# The one entry derivation cannot produce: AA reorders the name components.
KNOWN_UNDERIVABLE = {"anthropic/claude-haiku-4.5"}


def test_derive_reproduces_hand_map():
    misses = {
        mid: (derive_aa_slug(mid), slug)
        for mid, slug in AA_SLUG_MAP.items()
        if derive_aa_slug(mid) != slug
    }
    assert set(misses) == KNOWN_UNDERIVABLE, f"unexpected derivation misses: {misses}"


def test_hand_map_wins_over_derivation():
    mid = "anthropic/claude-haiku-4.5"
    aa = {"claude-4-5-haiku": {}, "claude-haiku-4-5": {}}
    assert resolve_aa_slug(mid, aa) == "claude-4-5-haiku"


def test_derivation_adds_coverage():
    # A model absent from the hand map but present in AA now resolves.
    mid = "openai/gpt-5.5"
    assert mid not in AA_SLUG_MAP
    assert resolve_aa_slug(mid, {"gpt-5-5": {}}) == "gpt-5-5"


def test_near_miss_returns_none_not_a_guess():
    # THE LOAD-BEARING CASE. AA holds a similar-but-different slug; we must
    # return None rather than attach the wrong model's scores.
    mid = "openai/gpt-5.5"
    assert resolve_aa_slug(mid, {"gpt-5-5-preview": {}, "gpt-5-4": {}}) is None
    assert resolve_aa_slug(mid, {}) is None


def test_gate_varies_with_its_subject():
    # Proves the guard above is not vacuous: same model id, two payloads,
    # opposite answers.
    mid = "z-ai/glm-5.2"
    assert resolve_aa_slug(mid, {"glm-5-2": {}}) == "glm-5-2"
    assert resolve_aa_slug(mid, {"glm-5-3": {}}) is None


if __name__ == "__main__":
    failed = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print(f"PASS {name}")
            except AssertionError as e:
                failed += 1
                print(f"FAIL {name}: {e}")
    print(f"\n{'FAILED' if failed else 'all tests passed'}")
    sys.exit(1 if failed else 0)
