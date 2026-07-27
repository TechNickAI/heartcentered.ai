"""Tests for eqbench_watch.py — the upstream new-row detector.

Run: python -m unittest discover -s model-benchmarks/tests

The watcher's whole value is that it tells a human when EQ-Bench publishes a
row we've been waiting on. So the tests that matter are the ones proving it
(a) actually notices a new key, (b) notices a WITHDRAWN key rather than
silently dropping it, and (c) never invents a mapping on its own.
"""

import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path

_SRC = Path(__file__).resolve().parent.parent / "scripts" / "fetch-model.py"
_spec = importlib.util.spec_from_file_location("fetch_model", _SRC)
fm = importlib.util.module_from_spec(_spec)
sys.modules["fetch_model"] = fm
_spec.loader.exec_module(fm)

import eqbench_public as eqp  # noqa: E402  (path set up by fetch-model.py import)
import eqbench_watch as ew  # noqa: E402


class TestSnapshotRoundTrip(unittest.TestCase):
    def test_missing_snapshot_is_empty_not_an_error(self):
        """No prior observation must read as 'nothing seen', never as a crash."""
        with tempfile.TemporaryDirectory() as d:
            self.assertEqual(ew.load_snapshot(Path(d) / "absent.json"), set())

    def test_save_then_load_round_trips(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "keys.json"
            ew.save_snapshot({"gpt-5.4", "claude-opus-4-6"}, p)
            self.assertEqual(ew.load_snapshot(p), {"gpt-5.4", "claude-opus-4-6"})

    def test_snapshot_is_sorted_for_stable_git_diffs(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "keys.json"
            ew.save_snapshot({"zzz", "aaa", "mmm"}, p)
            payload = json.loads(p.read_text())
            self.assertEqual(payload["keys"], ["aaa", "mmm", "zzz"])
            self.assertEqual(payload["count"], 3)


class TestDiff(unittest.TestCase):
    def test_detects_a_newly_published_row(self):
        """The core job: upstream gained claude-opus-5, we must say so."""
        delta = ew.diff_upstream({"gpt-5.4", "claude-opus-5"}, {"gpt-5.4"})
        self.assertEqual(delta["new"], ["claude-opus-5"])
        self.assertEqual(delta["disappeared"], [])

    def test_detects_a_withdrawn_row(self):
        """A vanished upstream row is the D-001 delisting shape. Never silent."""
        delta = ew.diff_upstream({"gpt-5.4"}, {"gpt-5.4", "mimo-v2-pro"})
        self.assertEqual(delta["disappeared"], ["mimo-v2-pro"])
        self.assertEqual(delta["new"], [])

    def test_no_change_reports_nothing(self):
        delta = ew.diff_upstream({"gpt-5.4"}, {"gpt-5.4"})
        self.assertEqual(delta, {"new": [], "disappeared": []})


class TestWatchlist(unittest.TestCase):
    def test_mapped_and_published_is_actionable(self):
        model_id, key = next(iter(eqp.EQBENCH_PUBLIC_MAP.items()))
        status = ew.watchlist_status({key}, [model_id])
        self.assertEqual(status["actionable"], [model_id])

    def test_mapped_but_unpublished_stays_blocked(self):
        model_id = next(iter(eqp.EQBENCH_PUBLIC_MAP))
        status = ew.watchlist_status(set(), [model_id])
        self.assertEqual(status["still_blocked"], [model_id])

    def test_unmapped_model_is_never_actionable(self):
        """The anti-fabrication guarantee: no map entry, no score, no exceptions.

        Even if upstream publishes a row whose name looks exactly like the
        model id, the watcher must not treat it as scoreable. Identity is a
        human decision (see fuzzy-match failures in eqbench_public.py).
        """
        self.assertNotIn("anthropic/claude-opus-5", eqp.EQBENCH_PUBLIC_MAP)
        status = ew.watchlist_status(
            {"claude-opus-5", "anthropic/claude-opus-5"}, ["anthropic/claude-opus-5"]
        )
        self.assertEqual(status["actionable"], [])
        self.assertEqual(status["still_blocked"], ["anthropic/claude-opus-5"])

    def test_unmapped_keys_excludes_already_mapped_ones(self):
        known = next(iter(eqp.EQBENCH_PUBLIC_MAP.values()))
        out = ew.unmapped_keys({known, "brand-new-key"})
        self.assertEqual(out, ["brand-new-key"])


class TestReportFormatting(unittest.TestCase):
    def _report(self, **over):
        base = {
            "upstream_total": 79,
            "snapshot_total": 79,
            "new_upstream_keys": [],
            "disappeared_upstream_keys": [],
            "unmapped_upstream_keys": [],
            "actionable": [],
            "still_blocked": [],
        }
        base.update(over)
        return base

    def test_quiet_run_says_so_explicitly(self):
        """Silence must be stated, not implied by an empty report."""
        self.assertIn("No upstream change", ew.format_report(self._report()))

    def test_new_row_is_surfaced_by_name(self):
        text = ew.format_report(self._report(new_upstream_keys=["claude-opus-5"]))
        self.assertIn("claude-opus-5", text)
        self.assertIn("NEW upstream rows", text)

    def test_withdrawn_row_warns_against_silent_drop(self):
        text = ew.format_report(self._report(disappeared_upstream_keys=["mimo-v2-pro"]))
        self.assertIn("DISAPPEARED", text)
        self.assertIn("D-001", text)


class TestNoDataMutation(unittest.TestCase):
    def test_run_watch_leaves_model_data_byte_identical(self):
        """Behavioural proof, not a grep: run the watcher, dataset unchanged.

        D-002 was a refresh path that destroyed real scores. So this test runs
        the real code path against a stubbed upstream and asserts the shipped
        dataset is byte-for-byte identical afterwards.
        """
        data_path = (
            Path(ew.__file__).resolve().parent.parent / "data" / "model-data.json"
        )
        before = data_path.read_bytes()

        real_fetch = ew.fetch_public_leaderboard
        ew.fetch_public_leaderboard = lambda: {
            "claude-opus-5": {"rubric_0_100": 99.9},
            "gpt-5.4": {"rubric_0_100": 82.4},
        }
        try:
            with tempfile.TemporaryDirectory() as d:
                real_snap = ew.SNAPSHOT_PATH
                ew.SNAPSHOT_PATH = Path(d) / "keys.json"
                try:
                    report = ew.run_watch(["anthropic/claude-opus-5"])
                finally:
                    ew.SNAPSHOT_PATH = real_snap
        finally:
            ew.fetch_public_leaderboard = real_fetch

        self.assertEqual(data_path.read_bytes(), before)
        # And even with a juicy-looking upstream row, it refused to map it.
        self.assertEqual(report["actionable"], [])
        self.assertIn("claude-opus-5", report["new_upstream_keys"])

    def test_report_contains_no_score_values(self):
        """It reports names only — never a rubric or Elo number it could leak."""
        real_fetch = ew.fetch_public_leaderboard
        ew.fetch_public_leaderboard = lambda: {"gpt-5.4": {"rubric_0_100": 82.4}}
        try:
            with tempfile.TemporaryDirectory() as d:
                real_snap = ew.SNAPSHOT_PATH
                ew.SNAPSHOT_PATH = Path(d) / "keys.json"
                try:
                    report = ew.run_watch([])
                finally:
                    ew.SNAPSHOT_PATH = real_snap
        finally:
            ew.fetch_public_leaderboard = real_fetch

        blob = json.dumps(report)
        self.assertNotIn("82.4", blob)
        for banned in ("v3_score", "v3_traits", "public_rubric_0_100", "elo"):
            self.assertNotIn(banned, blob)


if __name__ == "__main__":
    unittest.main()
