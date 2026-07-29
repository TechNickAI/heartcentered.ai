"""Tests for the fetch-model.py data pipeline.

Run: python -m unittest discover -s model-benchmarks/tests

Focus is merge_model(), which guards manually-curated benchmark data against
being clobbered by an automated refresh. Artificial Analysis is the subtle
case: it is only fetched when AA_API_KEY is set, so a keyless refresh yields
an all-null block that must not overwrite real scores.
"""

import importlib.util
import json
import sys
import unittest
from pathlib import Path

_SRC = Path(__file__).resolve().parent.parent / "scripts" / "fetch-model.py"
_spec = importlib.util.spec_from_file_location("fetch_model", _SRC)
fm = importlib.util.module_from_spec(_spec)
sys.modules["fetch_model"] = fm
_spec.loader.exec_module(fm)

import eqbench_public as eqp  # noqa: E402  (path set up by fetch-model.py import)

REAL = {"intelligence_index": 46.5, "coding_index": 47.6, "gpqa": 0.84}
NULLED = dict.fromkeys(REAL)


def stored(aa):
    """A dataset holding one model with curated benchmark data."""
    return {
        "models": [
            {
                "id": "acme/model-1",
                "provider": "acme",
                "name": "Model 1",
                "benchmarks": {
                    "artificial_analysis": aa,
                    "eq_bench": {"score": 77.7},
                    "arena": {},
                    "pinchbench": {},
                },
                "scores": {"reasoning": 5, "coding": 6, "agentic": 7},
                "sources": {"artificial_analysis": True, "eq_bench": True},
                "notes": "hand-written note",
                "speed": {"tps": 100},
            }
        ]
    }


def refreshed(aa, model_id="acme/model-1"):
    """What a bare OpenRouter refresh produces: no curated data of its own."""
    return {
        "id": model_id,
        "provider": "acme",
        "name": "Model 1",
        "benchmarks": {"artificial_analysis": aa, "eq_bench": {}},
        "scores": dict.fromkeys(("reasoning", "coding", "agentic")),
        "sources": {"artificial_analysis": False, "eq_bench": False},
    }


def merge(aa_stored, aa_new):
    return fm.merge_model(stored(aa_stored), refreshed(aa_new))["models"][0]


class ArtificialAnalysisPreservation(unittest.TestCase):
    """A keyless refresh must never destroy previously-fetched AA scores."""

    def test_keyless_refresh_preserves_scores(self):
        self.assertEqual(merge(REAL, NULLED)["benchmarks"]["artificial_analysis"], REAL)

    def test_fresh_value_overwrites_stale(self):
        aa = merge(REAL, {**NULLED, "intelligence_index": 51.0})["benchmarks"][
            "artificial_analysis"
        ]
        self.assertEqual(aa["intelligence_index"], 51.0)
        self.assertEqual(aa["coding_index"], 47.6, "partial update dropped a field")

    def test_repeated_refreshes_are_idempotent(self):
        data = stored(REAL)
        for _ in range(3):
            data = fm.merge_model(data, refreshed(NULLED))
        self.assertEqual(data["models"][0]["benchmarks"]["artificial_analysis"], REAL)

    def test_model_without_prior_scores_accepts_incoming(self):
        self.assertEqual(merge({}, REAL)["benchmarks"]["artificial_analysis"], REAL)


class CuratedDataPreservation(unittest.TestCase):
    """The guarantees AGENTS.md documents for merge_model()."""

    def setUp(self):
        self.model = merge(REAL, NULLED)

    def test_manual_benchmarks_survive(self):
        self.assertEqual(self.model["benchmarks"]["eq_bench"], {"score": 77.7})

    def test_scores_survive(self):
        self.assertEqual(self.model["scores"]["reasoning"], 5)

    def test_notes_and_speed_survive(self):
        self.assertEqual(self.model["notes"], "hand-written note")
        self.assertEqual(self.model["speed"], {"tps": 100})

    def test_source_flags_survive(self):
        self.assertIs(self.model["sources"]["artificial_analysis"], True)

    def test_new_model_is_appended(self):
        data = fm.merge_model(stored(REAL), refreshed(REAL, "acme/model-2"))
        self.assertEqual(
            {m["id"] for m in data["models"]}, {"acme/model-1", "acme/model-2"}
        )


class UnknownProvenanceFlagPreservation(unittest.TestCase):
    """Regression guard for the 72b7149 provenance wipe.

    The weekly CI metadata refresh deleted `sources.eq_bench_public` from all 28
    rows carrying real public EQ-Bench scores, because merge_model() preserved a
    hardcoded whitelist of source keys ("artificial_analysis", "eq_bench") and
    silently dropped everything else. The scores survived; the provenance did
    not. A refresh must preserve source keys it has never heard of.
    """

    def _merge_with_sources(self, stored_sources):
        data = stored(REAL)
        data["models"][0]["sources"] = stored_sources
        return fm.merge_model(data, refreshed(NULLED))["models"][0]["sources"]

    def test_eq_bench_public_survives_a_metadata_refresh(self):
        out = self._merge_with_sources(
            {"openrouter": True, "eq_bench": True, "eq_bench_public": True}
        )
        self.assertIs(
            out.get("eq_bench_public"),
            True,
            "eq_bench_public was dropped by a metadata refresh (regression of 72b7149)",
        )

    def test_arbitrary_future_source_key_survives(self):
        """The bug was the whitelist itself, not the one missing key."""
        out = self._merge_with_sources(
            {"openrouter": True, "some_source_invented_next_year": True}
        )
        self.assertIs(out.get("some_source_invented_next_year"), True)

    def test_falsy_flags_do_not_resurrect(self):
        out = self._merge_with_sources({"openrouter": True, "eq_bench_public": False})
        self.assertFalse(out.get("eq_bench_public"))

    def test_incoming_truthy_value_is_not_downgraded(self):
        data = stored(REAL)
        data["models"][0]["sources"] = {"eq_bench_public": True}
        new = refreshed(NULLED)
        new["sources"]["eq_bench_public"] = True
        out = fm.merge_model(data, new)["models"][0]["sources"]
        self.assertIs(out["eq_bench_public"], True)

    def test_repeated_refreshes_do_not_erode_provenance(self):
        data = stored(REAL)
        data["models"][0]["sources"] = {"openrouter": True, "eq_bench_public": True}
        for _ in range(3):
            data = fm.merge_model(data, refreshed(NULLED))
        self.assertIs(data["models"][0]["sources"]["eq_bench_public"], True)

    def test_model_with_no_sources_block_does_not_crash(self):
        """xiaomi/mimo-v2-pro is delisted and carries no `sources` key at all."""
        data = stored(REAL)
        del data["models"][0]["sources"]
        out = fm.merge_model(data, refreshed(NULLED))["models"][0]["sources"]
        self.assertIsInstance(out, dict)


class AliasMap(unittest.TestCase):
    """OpenRouter renames slugs; aliases keep dataset ids stable."""

    def test_aliases_are_not_self_referential(self):
        for old, new in fm.OPENROUTER_ID_ALIASES.items():
            self.assertNotEqual(old, new)

    def test_noted_models_are_documented(self):
        """Every alias/delisted entry needs a note explaining the divergence."""
        for model_id in fm.MODEL_NOTES:
            self.assertTrue(fm.MODEL_NOTES[model_id].strip())


class PublicEqIsolation(unittest.TestCase):
    """The public EQ-Bench rubric is a DIFFERENT metric from Nick's local runs.

    Public `rubric_0_100` runs 5-9 points higher than local `v3_score` over 17
    traits instead of 22. Leaking it into `v3_score` would silently inflate new
    models against existing rows and corrupt the leaderboard ordering.
    """

    def setUp(self):
        self.leaderboard = {
            "claude-opus-4-6": {"rubric_0_100": 79.2, "elo_norm": 1717.4},
        }
        self.traits = {"claude-opus-4-6": {"warmth": 14.04, "analytical": 17.42}}

    def test_public_block_never_emits_local_fields(self):
        block = eqp.public_eq_block(
            "anthropic/claude-opus-4.6", self.leaderboard, self.traits
        )
        for forbidden in ("v3_score", "v3_traits", "elo"):
            self.assertNotIn(forbidden, block)

    def test_public_block_emits_namespaced_fields(self):
        block = eqp.public_eq_block(
            "anthropic/claude-opus-4.6", self.leaderboard, self.traits
        )
        self.assertEqual(block["public_rubric_0_100"], 79.2)
        self.assertEqual(block["public_elo_norm"], 1717.4)
        self.assertEqual(block["public_source_key"], "claude-opus-4-6")

    def test_unmapped_model_gets_nothing(self):
        """An unmapped model must yield None, never a fuzzy-matched score."""
        self.assertIsNone(
            eqp.public_eq_block("acme/never-heard-of-it", self.leaderboard, self.traits)
        )

    def test_local_v3_score_survives_public_fetch(self):
        data = {
            "models": [
                {
                    "id": "anthropic/claude-opus-4.6",
                    "benchmarks": {
                        "eq_bench": {"v3_score": 71.85, "v3_traits": {"warmth": 13.6}}
                    },
                }
            ]
        }
        eq = data["models"][0]["benchmarks"]["eq_bench"]
        eq.update(
            eqp.public_eq_block(
                "anthropic/claude-opus-4.6", self.leaderboard, self.traits
            )
        )
        self.assertEqual(eq["v3_score"], 71.85, "local v3_score was clobbered")
        self.assertEqual(eq["v3_traits"], {"warmth": 13.6})
        self.assertEqual(eq["public_rubric_0_100"], 79.2)

    def test_map_has_no_fuzzy_lookalikes(self):
        """Models whose names invite a wrong substring match stay unmapped."""
        for risky in (
            "openai/gpt-5.4-mini",
            "z-ai/glm-5-turbo",
            "anthropic/claude-haiku-4.5",
        ):
            self.assertNotIn(risky, eqp.EQBENCH_PUBLIC_MAP)


class PublicMapIsInjective(unittest.TestCase):
    """Two OpenRouter ids must never claim the same upstream EQ-Bench row.

    That is exactly the shape of the inherited-score bug (D-001): one real run
    presented as two models' own results. Cheap to assert, so assert it.
    """

    def test_no_two_models_share_an_eqbench_key(self):
        seen: dict[str, str] = {}
        for model_id, key in eqp.EQBENCH_PUBLIC_MAP.items():
            self.assertNotIn(
                key,
                seen,
                f"{model_id} and {seen.get(key)} both map to upstream {key!r} "
                "— one of them would be showing the other's score",
            )
            seen[key] = model_id


class Glm5TurboProvenance(unittest.TestCase):
    """z-ai/glm-5-turbo and z-ai/glm-5 are DIFFERENT models.

    glm-5-turbo carries a legacy 11-trait EQ block of unknown provenance. It was
    suspected of being GLM-5's data. Checked against upstream 2026-07-26: on the
    shared 0-10 rescaling only 4 of 11 traits agree within rounding (humanlike
    7.20 vs 6.76, social_iq 7.20 vs 6.94), and the stored elo 1631.9 differs from
    GLM-5's public elo_norm 1526.0. So it is NOT a copy of GLM-5 and stays put —
    but glm-5-turbo must never be mapped to the GLM-5 row.
    """

    def test_turbo_is_not_mapped_to_glm5(self):
        self.assertNotIn("z-ai/glm-5-turbo", eqp.EQBENCH_PUBLIC_MAP)

    def test_glm5_maps_to_glm5(self):
        self.assertEqual(eqp.EQBENCH_PUBLIC_MAP.get("z-ai/glm-5"), "zai-org/GLM-5")


class DiscoverNewModels(unittest.TestCase):
    def test_untracked_and_live_is_discovered(self):
        data = {"models": [{"id": "anthropic/claude-opus-4.6"}]}
        live = [
            {"id": "anthropic/claude-opus-4.8"},
            {"id": "anthropic/claude-opus-4.6"},
        ]
        self.assertIn("anthropic/claude-opus-4.8", fm.discover_new_models(data, live))

    def test_already_tracked_is_not_rediscovered(self):
        data = {"models": [{"id": "anthropic/claude-opus-4.8"}]}
        live = [{"id": "anthropic/claude-opus-4.8"}]
        self.assertNotIn(
            "anthropic/claude-opus-4.8", fm.discover_new_models(data, live)
        )

    def test_not_live_on_openrouter_is_skipped(self):
        """EQ-Bench lists models OpenRouter doesn't serve; never invent a row."""
        data = {"models": []}
        self.assertEqual(fm.discover_new_models(data, []), [])


class NoInheritedScores(unittest.TestCase):
    """Charter non-negotiable: never present a predecessor's score as a model's own.

    qwen/qwen3.6-plus:free carried EQ-Bench data copied from Qwen3.5-397B-A17B.
    That predecessor is now tracked as its own row, so the inherited copy was
    removed 2026-07-26 rather than merely footnoted.
    """

    DATA = Path(__file__).resolve().parent.parent / "data" / "model-data.json"

    def setUp(self):
        with open(self.DATA) as f:
            self.models = {m["id"]: m for m in json.load(f)["models"]}

    def test_qwen36_has_no_inherited_eq(self):
        eq = self.models["qwen/qwen3.6-plus:free"]["benchmarks"].get("eq_bench", {})
        for field in ("v3_score", "v3_traits", "elo"):
            self.assertIsNone(
                eq.get(field),
                f"qwen3.6-plus has {field} again — it belongs to Qwen3.5-397B",
            )

    def test_predecessor_is_tracked_separately(self):
        self.assertIn("qwen/qwen3.5-397b-a17b", self.models)

    def test_qwen36_keeps_its_own_pinchbench(self):
        """PinchBench was run on Qwen3.6 directly, so it must survive."""
        pb = self.models["qwen/qwen3.6-plus:free"]["benchmarks"]["pinchbench"]
        self.assertEqual(pb["best_score"], 88.6)

    def test_no_two_models_share_a_public_source_key(self):
        """Two rows citing one EQ-Bench entry means one of them inherited it."""
        seen = {}
        for mid, m in self.models.items():
            key = m["benchmarks"].get("eq_bench", {}).get("public_source_key")
            if key is None:
                continue
            self.assertNotIn(key, seen, f"{mid} and {seen.get(key)} share EQ key {key}")
            seen[key] = mid


if __name__ == "__main__":
    unittest.main()
