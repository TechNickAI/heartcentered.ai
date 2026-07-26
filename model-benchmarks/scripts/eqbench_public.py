#!/usr/bin/env python3
"""
EQ-Bench v3 PUBLIC leaderboard client.

WHY THIS IS A SEPARATE METRIC (read before touching anything)
-------------------------------------------------------------
`benchmarks.eq_bench.v3_score` in model-data.json comes from Nick's OWN local
EQ-Bench v3 runs (~$6/model). Those runs emit a **22-trait** breakdown, five of
which do not exist on the public site at all: correctness,
intellectual_grounding, subtext_identification, sycophantic, theory_of_mind.

eqbench.com publishes a **17-trait** rubric under the name `rubric_0_100`.
For the five models present in both, the public number is consistently HIGHER:

    model                     local v3_score   public rubric_0_100   delta
    openai/gpt-5.4                    73.20                  82.4   +9.20
    anthropic/claude-sonnet-4.6       71.70                  80.0   +8.30
    anthropic/claude-opus-4.6         71.85                  79.2   +7.35
    google/gemini-3.1-pro-...         68.95                  74.3   +5.35
    google/gemma-4-31b-it             66.10                  70.8   +4.70

The gap is not noise and not a constant offset — it is a different rubric over a
different trait set. Writing a public `rubric_0_100` into `v3_score` would
silently inflate every new model by 5-9 points against Nick's locally-run rows
and make the leaderboard's ordering meaningless. So the public number is stored
in its own field, `public_rubric_0_100`, and NEVER into `v3_score`.

The public Elo (`elo_norm`) is likewise a different quantity from the stored
`elo` (site claude-sonnet-4.6 elo=1876.8, public elo_norm=1714.1). It is stored
as `public_elo_norm`, never into `elo`.

MAPPING IS EXPLICIT AND NEVER FUZZY
-----------------------------------
EQ-Bench keys are not derivable from OpenRouter ids. Substring matching against
the live leaderboard actively mis-assigns:

    openai/gpt-5.4-mini  --fuzzy-->  gpt-5.4        (WRONG: different model)
    z-ai/glm-5-turbo     --fuzzy-->  zai-org/GLM-5  (WRONG: different model)
    x-ai/grok-4.20-...   --fuzzy-->  grok-4         (WRONG: different model)

So EQBENCH_PUBLIC_MAP below is hand-verified, and a model absent from it simply
gets no public score. An empty cell is honest; a fuzzy match is a lie that
looks like data.
"""

from __future__ import annotations

import json
import re
import urllib.request

EQBENCH_LEADERBOARD_URL = "https://eqbench.com/eqbench3.js?v=1.0.4"
EQBENCH_CHARTDATA_URL = "https://eqbench.com/eqbench3_chartdata.js?v=1.0.4"

# Browser-ish UA: eqbench.com and OpenRouter both reject the default urllib UA.
_UA = "curl/8.7.1"

# OpenRouter model id -> EQ-Bench leaderboard key. HAND-VERIFIED ONLY.
# Never add an entry you have not confirmed refers to the same model.
# A missing entry means "no public score", which is a correct outcome.
EQBENCH_PUBLIC_MAP: dict[str, str] = {
    # --- already tracked on the site ---
    "anthropic/claude-opus-4.6": "claude-opus-4-6",
    "anthropic/claude-sonnet-4.6": "claude-sonnet-4-6",
    "openai/gpt-5.4": "gpt-5.4",
    "google/gemini-3.1-pro-preview-20260219": "gemini-3.1-pro-preview",
    "google/gemma-4-31b-it": "google/gemma-4-31B-it",
    "x-ai/grok-4.20-20260309": "grok-4.20-beta",
    # --- untracked frontier models that DO have public EQ-Bench results ---
    "anthropic/claude-opus-4.8": "claude-opus-4-8",
    "anthropic/claude-fable-5": "claude-fable-5",
    "openai/gpt-5.5": "gpt-5.5",
    "z-ai/glm-5.2": "zai-org/GLM-5.2",
    "z-ai/glm-5.1": "zai-org/GLM-5.1",
    "z-ai/glm-4.7": "zai-org/GLM-4.7",
    "z-ai/glm-4.7-flash": "zai-org/GLM-4.7-Flash",
    "deepseek/deepseek-v4-pro": "deepseek-ai/DeepSeek-V4-Pro",
    "deepseek/deepseek-v4-flash": "deepseek-ai/DeepSeek-V4-Flash",
    "moonshotai/kimi-k2.6": "moonshotai/Kimi-K2.6",
    "moonshotai/kimi-k2.5": "moonshotai/Kimi-K2.5",
    "google/gemma-4-26b-a4b-it": "google/gemma-4-26B-A4B-it",
    "qwen/qwen3.5-397b-a17b": "Qwen/Qwen3.5-397B-A17B",
    # --- added 2026-07-26: each confirmed live on OpenRouter AND present
    # upstream. Verified pairwise by name + canonical_slug, never by substring.
    #   eqbench key                -> openrouter canonical_slug
    #   claude-opus-4-7            -> anthropic/claude-4.7-opus-20260416
    #   gpt-5.2                    -> openai/gpt-5.2-20251211
    #   claude-opus-4-5-20251101   -> anthropic/claude-4.5-opus-20251124
    #   zai-org/GLM-5              -> z-ai/glm-5-20260211
    #   claude-sonnet-4.5          -> anthropic/claude-4.5-sonnet-20250929
    #   gpt-5.3-chat               -> openai/gpt-5.3-chat-20260303
    #   gpt-5.1-2025-11-13         -> openai/gpt-5.1-20251113
    #   moonshotai/Kimi-K2-Instruct-> moonshotai/kimi-k2 ("Kimi K2 0711")
    #   NousResearch/Hermes-4-405B -> nousresearch/hermes-4-405b
    "anthropic/claude-opus-4.7": "claude-opus-4-7",
    "openai/gpt-5.2": "gpt-5.2",
    "anthropic/claude-opus-4.5": "claude-opus-4-5-20251101",
    "z-ai/glm-5": "zai-org/GLM-5",
    "anthropic/claude-sonnet-4.5": "claude-sonnet-4.5",
    "openai/gpt-5.3-chat": "gpt-5.3-chat",
    "openai/gpt-5.1": "gpt-5.1-2025-11-13",
    "moonshotai/kimi-k2": "moonshotai/Kimi-K2-Instruct",
    "nousresearch/hermes-4-405b": "NousResearch/Hermes-4-405B",
    # NOTE deliberately absent, verified NOT live on OpenRouter (2026-07-26),
    # so there is no row to attach a real score to:
    #   grok-4, grok-4.1-fast, google/gemma-4-12B-it,
    #   HiveLabsAI/hivemind-32b-preview, openrouter/horizon-alpha
    # NOTE deliberately absent, verified as NOT on the public leaderboard:
    #   anthropic/claude-opus-5, anthropic/claude-opus-5-fast, x-ai/grok-4.5,
    #   moonshotai/kimi-k3, openai/gpt-5.6-*, google/gemini-3.6-flash
    # NOTE deliberately absent, because fuzzy matching would mis-assign them:
    #   openai/gpt-5.4-mini, z-ai/glm-5-turbo, minimax/minimax-m2.7,
    #   stepfun/step-3.5-flash, xiaomi/mimo-v2-pro, qwen/qwen3.6-plus:free,
    #   anthropic/claude-haiku-4.5
}

_LEADERBOARD_RE = re.compile(r"leaderboardDataEQBench3\s*=\s*`(.*?)`", re.DOTALL)


def _get(url: str) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": _UA})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return resp.read().decode("utf-8")


def fetch_public_leaderboard() -> dict[str, dict]:
    """Return {eqbench_key: {column: float}} from the public v3 leaderboard.

    Raises on failure — a silent empty result would let a caller conclude
    "no models have scores" and quietly write nothing, which is exactly the
    green-checkmark-over-zero-work failure mode.
    """
    body = _get(EQBENCH_LEADERBOARD_URL)
    m = _LEADERBOARD_RE.search(body)
    if not m:
        raise RuntimeError(
            f"leaderboardDataEQBench3 block not found at {EQBENCH_LEADERBOARD_URL} "
            "— upstream format changed, refusing to guess"
        )
    rows = [r for r in m.group(1).strip().split("\n") if r.strip()]
    header = rows[0].split(",")
    out: dict[str, dict] = {}
    for row in rows[1:]:
        parts = row.split(",")
        if len(parts) != len(header):
            print(f"  WARNING: skipping malformed EQ-Bench row: {row[:60]!r}")
            continue
        # A leading '*' marks a recently-added entry on eqbench.com; not part
        # of the model name.
        name = parts[0].lstrip("*")
        vals = {}
        for col, raw in zip(header[1:], parts[1:]):
            try:
                vals[col] = float(raw)
            except ValueError:
                print(f"  WARNING: non-numeric {col}={raw!r} for {name}, skipping cell")
        out[name] = vals
    if not out:
        raise RuntimeError("EQ-Bench leaderboard parsed to zero rows — refusing")
    return out


def fetch_public_traits() -> dict[str, dict[str, float]]:
    """Return {eqbench_key: {trait: value}} — the public 17-trait radar."""
    body = _get(EQBENCH_CHARTDATA_URL)
    start = body.index("{")
    payload = json.loads(body[start:].strip().rstrip(";"))
    out: dict[str, dict[str, float]] = {}
    for key, entry in payload.items():
        radar = (entry or {}).get("absoluteRadar") or {}
        labels, values = radar.get("labels"), radar.get("values")
        if not labels or not values or len(labels) != len(values):
            print(f"  WARNING: no usable absoluteRadar for {key}, skipping traits")
            continue
        out[key] = dict(zip(labels, values))
    if not out:
        raise RuntimeError("EQ-Bench chartdata parsed to zero rows — refusing")
    return out


def public_eq_block(model_id: str, leaderboard: dict, traits: dict) -> dict | None:
    """Build the public-EQ fields for one model, or None if it has no entry.

    Returns ONLY `public_*` keys. It must never emit `v3_score`, `v3_traits`,
    or `elo` — those belong to Nick's local runs and are a different rubric.
    """
    key = EQBENCH_PUBLIC_MAP.get(model_id)
    if key is None:
        return None
    row = leaderboard.get(key)
    if row is None:
        print(
            f"  WARNING: {model_id} mapped to '{key}' which is not on the leaderboard"
        )
        return None
    block: dict = {"public_source_key": key}
    if (rubric := row.get("rubric_0_100")) is not None:
        block["public_rubric_0_100"] = rubric
    if (elo := row.get("elo_norm")) is not None:
        block["public_elo_norm"] = elo
    if key in traits:
        block["public_traits_17"] = traits[key]
    return block


# Fields this module owns. Anything else in eq_bench is local-run data and must
# survive untouched.
PUBLIC_EQ_FIELDS = (
    "public_source_key",
    "public_rubric_0_100",
    "public_elo_norm",
    "public_traits_17",
)
