#!/usr/bin/env python3
"""
Fetch model data from OpenRouter API and merge into model-data.json.

Usage:
    # Fetch a single model by OpenRouter ID
    python fetch-model.py anthropic/claude-sonnet-4.6

    # Fetch multiple models
    python fetch-model.py anthropic/claude-sonnet-4.6 xiaomi/mimo-v2-pro

    # Fetch all models in the curated list
    python fetch-model.py --curated

    # Refresh all models already in model-data.json
    python fetch-model.py --refresh

    # Dry run (print what would be written, don't save)
    python fetch-model.py --dry-run anthropic/claude-sonnet-4.6

Designed to be run by parallel agents — each invocation locks the JSON file
briefly during the merge step to avoid conflicts.
"""

import argparse
import json
import os
import sys
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).parent
DATA_DIR = SCRIPT_DIR.parent / "data"
MODEL_DATA_PATH = DATA_DIR / "model-data.json"
LLMS_TXT_PATH = SCRIPT_DIR.parent / "llms.txt"

OPENROUTER_MODELS_URL = "https://openrouter.ai/api/v1/models"
OPENROUTER_ENDPOINTS_URL = "https://openrouter.ai/api/v1/models/{slug}/endpoints"
AA_MODELS_URL = "https://artificialanalysis.ai/api/v2/data/llms/models"

# Current-generation models we track
CURATED_MODELS = [
    "stepfun/step-3.5-flash",
    "xiaomi/mimo-v2-pro",
    "z-ai/glm-5-turbo",
    "anthropic/claude-sonnet-4.6",
    "minimax/minimax-m2.7",
    "qwen/qwen3.6-plus:free",
    "anthropic/claude-opus-4.6",
    "arcee-ai/trinity-large-preview:free",
]

# Maps OpenRouter model IDs to Artificial Analysis slugs.
# AA often has multiple variants (reasoning/non-reasoning, effort levels).
# We pick the "default" variant — non-reasoning or standard effort.
AA_SLUG_MAP = {
    "anthropic/claude-sonnet-4.6": "claude-sonnet-4-6",
    "anthropic/claude-opus-4.6": "claude-opus-4-6",
    "stepfun/step-3.5-flash": "step-3-5-flash",
    "xiaomi/mimo-v2-pro": "mimo-v2-pro",
    "z-ai/glm-5-turbo": "glm-5-turbo",
    "minimax/minimax-m2.7": "minimax-m2-7",
}

# PinchBench scores — manually maintained from pinchbench.com
# Last updated: 2026-03-31
PINCHBENCH_DATA = {
    "anthropic/claude-opus-4.6": {"best_score": 93.3, "avg_score": 83.1, "runs": 19},
    "anthropic/claude-sonnet-4.6": {"best_score": 88.0, "avg_score": 81.1, "runs": 19},
    "stepfun/step-3.5-flash": {"best_score": 85.3, "avg_score": 76.9, "runs": 18},
    "xiaomi/mimo-v2-pro": {"best_score": 83.95, "avg_score": 80.7, "runs": 15},
    "z-ai/glm-5-turbo": {"best_score": 86.5, "avg_score": 81.6, "runs": 11},
    "minimax/minimax-m2.7": {"best_score": 89.8, "avg_score": 83.2, "runs": 11},
    "qwen/qwen3.6-plus:free": {"best_score": 88.6, "avg_score": 84.0, "runs": 5},
    "arcee-ai/trinity-large-preview:free": {"best_score": 80.6, "avg_score": 69.4, "runs": 8},
}


def load_aa_api_key() -> str | None:
    """Load Artificial Analysis API key from env.local or environment."""
    if key := os.environ.get("AA_API_KEY"):
        return key
    env_local = SCRIPT_DIR.parent.parent / "env.local"
    if not env_local.exists():
        return None
    for line in env_local.read_text().splitlines():
        line = line.strip()
        if line.startswith("AA_API_KEY="):
            return line.split("=", 1)[1].strip()
    return None


def fetch_openrouter_models() -> list[dict]:
    """Fetch all models from OpenRouter API."""
    req = urllib.request.Request(OPENROUTER_MODELS_URL)
    with urllib.request.urlopen(req, timeout=30) as resp:
        data = json.loads(resp.read())
    return data.get("data", [])


def fetch_endpoints(canonical_slug: str) -> dict | None:
    """Fetch endpoint details (uptime, latency, throughput) for a model."""
    url = OPENROUTER_ENDPOINTS_URL.format(slug=canonical_slug)
    try:
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read())
    except Exception:
        return None


def fetch_aa_models(api_key: str) -> dict[str, dict]:
    """Fetch all models from Artificial Analysis API. Returns dict keyed by slug."""
    req = urllib.request.Request(AA_MODELS_URL)
    req.add_header("x-api-key", api_key)
    with urllib.request.urlopen(req, timeout=30) as resp:
        data = json.loads(resp.read())
    return {m["slug"]: m for m in data.get("data", [])}


def _weighted_avg(components: list[tuple[float, float]]) -> float | None:
    """Weighted average from [(value, weight), ...]. Returns None if empty."""
    if not components:
        return None
    total = sum(v * w for v, w in components)
    return round(total / sum(w for _, w in components), 1)


def compute_reasoning_score(evals: dict) -> float | None:
    """Reasoning score: how well does it think? Scale 0-100."""
    parts = []
    # AA intelligence index (0-100 scale)
    if (v := evals.get("artificial_analysis_intelligence_index")) is not None:
        parts.append((v, 3.0))
    # Graduate-level reasoning
    if (v := evals.get("gpqa")) is not None:
        parts.append((v * 100, 2.5))
    # Broad knowledge
    if (v := evals.get("mmlu_pro")) is not None:
        parts.append((v * 100, 2.0))
    # Frontier difficulty (Humanity's Last Exam)
    if (v := evals.get("hle")) is not None:
        parts.append((v * 100, 1.5))
    # Math competition
    if (v := evals.get("aime_25")) is not None:
        parts.append((v * 100, 1.0))
    return _weighted_avg(parts)


def compute_coding_score(evals: dict) -> float | None:
    """Coding score: how well does it write code? Scale 0-100."""
    parts = []
    # AA coding index (0-100 scale)
    if (v := evals.get("artificial_analysis_coding_index")) is not None:
        parts.append((v, 3.0))
    # Live coding benchmark
    if (v := evals.get("livecodebench")) is not None:
        parts.append((v * 100, 2.0))
    # Terminal/systems coding
    if (v := evals.get("terminalbench_hard")) is not None:
        parts.append((v * 100, 2.0))
    # Science coding
    if (v := evals.get("scicode")) is not None:
        parts.append((v * 100, 1.0))
    return _weighted_avg(parts)


def compute_agentic_score(evals: dict, pinchbench: dict | None = None) -> float | None:
    """Agentic score: how well does it follow instructions and use tools? Scale 0-100."""
    parts = []
    # PinchBench — the gold standard for agent performance
    if pinchbench and (v := pinchbench.get("best_score")) is not None:
        parts.append((v, 4.0))
    # Instruction following — critical for tool-using agents
    if (v := evals.get("ifbench")) is not None:
        parts.append((v * 100, 3.0))
    # PinchBench average (consistency matters for agents)
    if pinchbench and (v := pinchbench.get("avg_score")) is not None:
        parts.append((v, 2.0))
    return _weighted_avg(parts)


def compute_smart_score(
    reasoning: float | None,
    coding: float | None,
    agentic: float | None,
) -> float | None:
    """Composite 'smart' score. Weighted toward reasoning and agentic performance
    since the primary use case is conversational AI + tool use, not coding."""
    parts = []
    if reasoning is not None:
        parts.append((reasoning, 3.0))
    if agentic is not None:
        parts.append((agentic, 3.0))
    if coding is not None:
        parts.append((coding, 1.0))
    return _weighted_avg(parts)


def compute_blended_cost(pricing: dict) -> float | None:
    """Blended cost per 1M tokens using 3:1 input-to-output ratio."""
    inp = pricing.get("input_per_m")
    out = pricing.get("output_per_m")
    if inp is None or out is None:
        return None
    return round((3 * inp + out) / 4, 4)


def enrich_with_aa(model: dict, aa_model: dict) -> dict:
    """Merge Artificial Analysis benchmark and speed data into a model record."""
    evals = aa_model.get("evaluations", {})

    model["benchmarks"]["artificial_analysis"] = {
        "intelligence_index": evals.get("artificial_analysis_intelligence_index"),
        "coding_index": evals.get("artificial_analysis_coding_index"),
        "math_index": evals.get("artificial_analysis_math_index"),
        "mmlu_pro": evals.get("mmlu_pro"),
        "gpqa": evals.get("gpqa"),
        "hle": evals.get("hle"),
        "livecodebench": evals.get("livecodebench"),
        "scicode": evals.get("scicode"),
        "aime_25": evals.get("aime_25"),
        "ifbench": evals.get("ifbench"),
        "terminalbench_hard": evals.get("terminalbench_hard"),
    }

    # Compute dimension scores
    pinchbench = model["benchmarks"].get("pinchbench")
    reasoning = compute_reasoning_score(evals)
    coding = compute_coding_score(evals)
    agentic = compute_agentic_score(evals, pinchbench if pinchbench else None)
    smart = compute_smart_score(reasoning, coding, agentic)

    model["scores"] = {
        "reasoning": reasoning,
        "coding": coding,
        "agentic": agentic,
        "smart": smart,
    }

    # Speed metrics from AA (more reliable than OpenRouter's often-null values)
    tps = aa_model.get("median_output_tokens_per_second")
    ttft = aa_model.get("median_time_to_first_token_seconds")
    ttfa = aa_model.get("median_time_to_first_answer_token")
    if tps and tps > 0:
        model["speed"] = {
            "output_tokens_per_sec": round(tps, 1),
            "ttft_seconds": round(ttft, 3) if ttft else None,
            "ttfa_seconds": round(ttfa, 3) if ttfa else None,
            "source": "artificial_analysis",
        }

    model["sources"]["artificial_analysis"] = True
    return model


def extract_capabilities(raw: dict) -> dict[str, bool]:
    """Derive capability flags from supported_parameters and architecture."""
    params = set(raw.get("supported_parameters", []))
    input_modalities = raw.get("architecture", {}).get("input_modalities", [])

    return {
        "tool_use": "tools" in params,
        "reasoning": "reasoning" in params or "include_reasoning" in params,
        "vision": "image" in input_modalities,
        "audio_input": "audio" in input_modalities,
        "web_search": raw.get("pricing", {}).get("web_search") is not None
            and raw["pricing"]["web_search"] != "0",
        "structured_output": "structured_outputs" in params or "response_format" in params,
    }


def pricing_per_million(price_per_token: str | None) -> float | None:
    """Convert per-token price string to per-million-tokens float."""
    if price_per_token is None:
        return None
    val = float(price_per_token) * 1_000_000
    return round(val, 4) if val > 0 else 0.0


def aggregate_endpoints(endpoints_data: dict | None) -> dict[str, Any]:
    """Extract best uptime, latency, throughput across providers."""
    if not endpoints_data or "data" not in endpoints_data:
        return {"providers": [], "uptime_24h": None, "latency_ms": None, "throughput_tps": None}

    endpoints = endpoints_data["data"].get("endpoints", [])
    providers = []
    uptimes = []
    latencies = []
    throughputs = []

    for ep in endpoints:
        providers.append(ep.get("provider_name", "unknown"))
        if ep.get("uptime_last_1d") is not None:
            uptimes.append(ep["uptime_last_1d"])
        if ep.get("latency_last_30m") is not None:
            latencies.append(ep["latency_last_30m"])
        if ep.get("throughput_last_30m") is not None:
            throughputs.append(ep["throughput_last_30m"])

    return {
        "providers": sorted(set(providers)),
        "uptime_24h": round(max(uptimes), 2) if uptimes else None,
        "latency_ms": round(min(latencies), 1) if latencies else None,
        "throughput_tps": round(max(throughputs), 1) if throughputs else None,
    }


def transform_model(raw: dict, endpoints_data: dict | None = None) -> dict:
    """Transform raw OpenRouter model data into our schema."""
    pricing = raw.get("pricing", {})
    arch = raw.get("architecture", {})
    top = raw.get("top_provider", {})

    endpoint_stats = aggregate_endpoints(endpoints_data)

    pricing_data = {
        "input_per_m": pricing_per_million(pricing.get("prompt")),
        "output_per_m": pricing_per_million(pricing.get("completion")),
        "cache_read_per_m": pricing_per_million(pricing.get("input_cache_read")),
        "cache_write_per_m": pricing_per_million(pricing.get("input_cache_write")),
        "web_search_per_req": float(pricing["web_search"]) if pricing.get("web_search") else None,
    }
    pricing_data["blended_per_m"] = compute_blended_cost(pricing_data)

    # Inject PinchBench data if available
    pinchbench = PINCHBENCH_DATA.get(raw["id"], {})

    return {
        "id": raw["id"],
        "canonical_slug": raw.get("canonical_slug", raw["id"]),
        "name": clean_name(raw.get("name", raw["id"])),
        "provider": extract_provider(raw.get("name", "")),
        "description": raw.get("description", ""),
        "context_window": raw.get("context_length"),
        "max_output": top.get("max_completion_tokens"),
        "modalities": {
            "input": arch.get("input_modalities", ["text"]),
            "output": arch.get("output_modalities", ["text"]),
        },
        "tokenizer": arch.get("tokenizer"),
        "pricing": pricing_data,
        "capabilities": extract_capabilities(raw),
        "endpoint_stats": endpoint_stats,
        "scores": {},
        "benchmarks": {
            "artificial_analysis": {},
            "eq_bench": {},
            "pinchbench": pinchbench,
        },
        "sources": {
            "openrouter": True,
            "artificial_analysis": False,
            "eq_bench": False,
            "pinchbench": bool(pinchbench),
        },
        "created": raw.get("created"),
        "last_updated": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }


def clean_name(name: str) -> str:
    """Strip provider prefix from model name. 'Anthropic: Claude Sonnet 4.6' -> 'Claude Sonnet 4.6'"""
    if ": " in name:
        return name.split(": ", 1)[1]
    return name


def extract_provider(name: str) -> str:
    """Extract provider from 'Provider: Model Name' format."""
    if ": " in name:
        return name.split(": ", 1)[0]
    return "Unknown"


def load_model_data() -> dict:
    """Load existing model-data.json or create empty structure."""
    if MODEL_DATA_PATH.exists():
        with open(MODEL_DATA_PATH) as f:
            return json.load(f)
    return {
        "generated": None,
        "schema_version": "1.0",
        "sources": {
            "openrouter": "https://openrouter.ai/api/v1/models",
            "artificial_analysis": "https://artificialanalysis.ai/api",
            "eq_bench": "https://eqbench.com",
        },
        "models": [],
    }


def merge_model(existing_data: dict, new_model: dict) -> dict:
    """Merge a new/updated model into the dataset. Preserves manually-added data."""
    models = existing_data["models"]
    for i, m in enumerate(models):
        if m["id"] == new_model["id"]:
            # Preserve manually-entered benchmark data (don't overwrite with empty)
            for bench_key in ("eq_bench",):
                existing_bench = m.get("benchmarks", {}).get(bench_key, {})
                if existing_bench and not new_model["benchmarks"].get(bench_key):
                    new_model["benchmarks"][bench_key] = existing_bench
            # Preserve speed data if new model doesn't have it
            if not new_model.get("speed") and m.get("speed"):
                new_model["speed"] = m["speed"]
            # Preserve source flags for non-openrouter sources
            for src_key in ("artificial_analysis", "eq_bench"):
                if m.get("sources", {}).get(src_key) and not new_model["sources"].get(src_key):
                    new_model["sources"][src_key] = True
            models[i] = new_model
            return existing_data

    models.append(new_model)
    return existing_data


def save_model_data(data: dict) -> None:
    """Write model-data.json with updated timestamp."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    data["generated"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    # Sort models by provider then name for stable output
    data["models"].sort(key=lambda m: (m["provider"], m["name"]))
    with open(MODEL_DATA_PATH, "w") as f:
        json.dump(data, f, indent=2)
    print(f"Saved {len(data['models'])} models to {MODEL_DATA_PATH}")


def generate_llms_txt(data: dict) -> None:
    """Generate llms.txt — plain text model summary for LLM consumption."""
    lines = [
        "# HeartCentered AI — LLM Model Benchmarks",
        f"# Generated: {data['generated']}",
        f"# Full data: https://heartcentered.ai/model-benchmarks/data/model-data.json",
        f"# Web UI: https://heartcentered.ai/model-benchmarks/",
        "",
        "# Current-generation LLM models ranked by community usage on OpenRouter.",
        "# Pricing is per million tokens. Capabilities derived from API metadata.",
        "",
    ]

    for m in data["models"]:
        p = m["pricing"]
        caps = [k for k, v in m["capabilities"].items() if v]
        lines.append(f"## {m['name']}")
        lines.append(f"Provider: {m['provider']}")
        lines.append(f"ID: {m['id']}")
        lines.append(f"Context: {m['context_window']:,} tokens" if m["context_window"] else "Context: unknown")
        if m["max_output"]:
            lines.append(f"Max output: {m['max_output']:,} tokens")

        inp = p.get("input_per_m")
        out = p.get("output_per_m")
        if inp is not None and out is not None and inp == 0 and out == 0:
            lines.append("Pricing: FREE")
        elif inp is not None and out is not None:
            blended = p.get("blended_per_m")
            price_str = f"Pricing: ${inp:.2f} input / ${out:.2f} output per 1M tokens"
            if blended is not None:
                price_str += f" (blended: ${blended:.2f})"
            lines.append(price_str)
        else:
            lines.append("Pricing: not available")

        if caps:
            lines.append(f"Capabilities: {', '.join(c.replace('_', ' ') for c in caps)}")

        scores = m.get("scores", {})
        score_parts = []
        if scores.get("smart") is not None:
            score_parts.append(f"Smart: {scores['smart']}")
        if scores.get("reasoning") is not None:
            score_parts.append(f"Reasoning: {scores['reasoning']}")
        if scores.get("coding") is not None:
            score_parts.append(f"Coding: {scores['coding']}")
        if scores.get("agentic") is not None:
            score_parts.append(f"Agentic: {scores['agentic']}")
        if score_parts:
            lines.append(f"Scores (0-100): {', '.join(score_parts)}")

        speed = m.get("speed", {})
        if speed.get("output_tokens_per_sec"):
            speed_parts = [f"{speed['output_tokens_per_sec']} tokens/sec"]
            if speed.get("ttft_seconds"):
                speed_parts.append(f"TTFT {speed['ttft_seconds']}s")
            lines.append(f"Speed: {', '.join(speed_parts)}")

        ep = m.get("endpoint_stats", {})
        if ep.get("providers"):
            lines.append(f"Available via: {', '.join(ep['providers'])}")

        # Include any benchmark data present
        benchmarks = m.get("benchmarks", {})
        aa = benchmarks.get("artificial_analysis", {})
        if aa:
            aa_parts = [f"{k}: {v}" for k, v in aa.items() if v is not None]
            if aa_parts:
                lines.append(f"Benchmarks (Artificial Analysis): {', '.join(aa_parts)}")

        eq = benchmarks.get("eq_bench", {})
        if eq.get("elo"):
            lines.append(f"EQ-Bench Elo: {eq['elo']}")

        pb = benchmarks.get("pinchbench", {})
        if pb.get("best_score"):
            lines.append(f"PinchBench: {pb['best_score']}% best, {pb.get('avg_score', 'N/A')}% avg ({pb.get('runs', '?')} runs)")

        lines.append(f"Description: {m['description'][:200]}")
        lines.append("")

    lines.append("---")
    lines.append("Source: https://heartcentered.ai/model-benchmarks/")
    lines.append("Data: https://heartcentered.ai/model-benchmarks/data/model-data.json")

    with open(LLMS_TXT_PATH, "w") as f:
        f.write("\n".join(lines))
    print(f"Generated {LLMS_TXT_PATH}")


def main():
    parser = argparse.ArgumentParser(description="Fetch model data from OpenRouter + Artificial Analysis")
    parser.add_argument("model_ids", nargs="*", help="OpenRouter model IDs to fetch")
    parser.add_argument("--curated", action="store_true", help="Fetch all curated models")
    parser.add_argument("--refresh", action="store_true", help="Refresh all models in model-data.json")
    parser.add_argument("--dry-run", action="store_true", help="Print results without saving")
    parser.add_argument("--no-llms-txt", action="store_true", help="Skip llms.txt generation")
    parser.add_argument("--no-aa", action="store_true", help="Skip Artificial Analysis enrichment")
    args = parser.parse_args()

    if args.curated:
        target_ids = CURATED_MODELS
    elif args.refresh:
        existing = load_model_data()
        target_ids = [m["id"] for m in existing["models"]]
        if not target_ids:
            print("No models in model-data.json to refresh. Use --curated for initial fetch.")
            sys.exit(1)
    elif args.model_ids:
        target_ids = args.model_ids
    else:
        parser.print_help()
        sys.exit(1)

    # Fetch OpenRouter data
    print(f"Fetching {len(target_ids)} model(s) from OpenRouter...")
    all_models = fetch_openrouter_models()
    models_by_id = {m["id"]: m for m in all_models}

    # Fetch Artificial Analysis data if available
    aa_models = {}
    if not args.no_aa:
        aa_key = load_aa_api_key()
        if aa_key:
            print("Fetching Artificial Analysis benchmark data...")
            try:
                aa_models = fetch_aa_models(aa_key)
                print(f"  Loaded {len(aa_models)} models from Artificial Analysis")
            except Exception as e:
                print(f"  WARNING: Failed to fetch AA data: {e}")
        else:
            print("  No AA API key found (set AA_API_KEY or add to env.local)")

    data = load_model_data()
    fetched = 0

    for model_id in target_ids:
        raw = models_by_id.get(model_id)
        if not raw:
            print(f"  WARNING: {model_id} not found on OpenRouter, skipping")
            continue

        slug = raw.get("canonical_slug", model_id)
        print(f"  Fetching {model_id} (endpoints: {slug})...")
        endpoints_data = fetch_endpoints(slug)

        transformed = transform_model(raw, endpoints_data)

        # Enrich with Artificial Analysis data if available
        aa_slug = AA_SLUG_MAP.get(model_id)
        if aa_slug and aa_slug in aa_models:
            transformed = enrich_with_aa(transformed, aa_models[aa_slug])
            print(f"    + Enriched with Artificial Analysis data (slug: {aa_slug})")
        elif aa_slug and aa_models:
            print(f"    - AA slug '{aa_slug}' not found in AA data")

        if args.dry_run:
            print(json.dumps(transformed, indent=2))
        else:
            data = merge_model(data, transformed)
        fetched += 1

    if not args.dry_run:
        save_model_data(data)
        if not args.no_llms_txt:
            generate_llms_txt(data)

    print(f"Done. Fetched {fetched}/{len(target_ids)} models.")


if __name__ == "__main__":
    main()
