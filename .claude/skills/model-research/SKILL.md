---
name: model-research
description:
  Use when adding a new LLM model to heartcentered.ai/model-benchmarks, refreshing
  benchmark data, or comparing models for fleet routing decisions — gathers pricing,
  speed, reasoning, coding, agentic, emotional intelligence, and conversational
  preference data from five sources
---

# LLM Model Research

## Overview

Gather comprehensive benchmark data for LLM models from five sources and merge into the
heartcentered.ai model-benchmarks dataset. The goal is a complete profile: pricing,
speed, reasoning, coding, agentic performance, emotional intelligence (EQ-Bench), and
conversational preference (Arena Elo).

## When to Use

- Adding a new model to the benchmarks dataset
- A new model generation drops and needs evaluation
- Refreshing stale data (run `--refresh` on the fetch script)
- Comparing models for OpenClaw fleet routing decisions

## Data Sources

### 1. OpenRouter API (baseline)

`GET https://openrouter.ai/api/v1/models` — pricing, context window, capabilities,
modalities. `GET https://openrouter.ai/api/v1/models/{canonical_slug}/endpoints` —
per-provider uptime. No auth required. Use the model's `canonical_slug` for the
endpoints call, not the `id`.

### 2. Artificial Analysis API (benchmarks + speed)

`GET https://artificialanalysis.ai/api/v2/data/llms/models` — intelligence index, coding
index, GPQA, HLE, IFBench, tokens/sec, TTFT. API key in `env.local` as `AA_API_KEY`,
header `x-api-key`. 1,000 req/day free. Models keyed by `slug` (e.g.,
`claude-sonnet-4-6`). Naming differs from OpenRouter — maintain `AA_SLUG_MAP` in the
fetch script.

### 3. PinchBench (agentic performance)

`https://pinchbench.com` — agent benchmark with best/avg scores and run counts. Data is
JS-rendered. Use WebFetch (it returns JSON from the page source) or Playwright. Look
for: best_score, avg_score, number of runs.

### 4. Arena (conversational preference)

`https://arena.ai/leaderboard/text` — Elo ratings from blind human A/B preference tests.
JS-rendered leaderboard with 300+ models. Use WebFetch to extract scores. Model names
use hyphens (e.g., `claude-sonnet-4-6`).

### 5. EQ-Bench 3 (emotional intelligence)

`https://eqbench.com` — Elo + 11 trait scores (Empathy, Social IQ, Humanlike, Warm,
Insight, etc.). **Requires Playwright** — data is JS-rendered in a table, WebFetch gets
only the skeleton. Use `browser_evaluate` to extract all rows from the table DOM:

```js
const rows = document.querySelectorAll("table tbody tr");
// Each row: model, abilities, humanlike, safety, assertive, social_iq,
//           warm, analytic, insight, empathy, compliant, moralising, pragmatic, elo
```

## Workflow

The fetch script at `model-benchmarks/scripts/fetch-model.py` automates OpenRouter + AA.
PinchBench, Arena, and EQ-Bench data is collected manually and either hardcoded in the
script's `PINCHBENCH_DATA` dict or written directly into `model-data.json`.

For a new model:

1. Find its OpenRouter ID (e.g., `anthropic/claude-sonnet-4.6`)
2. Find its AA slug and add to `AA_SLUG_MAP` in the fetch script
3. Run: `python fetch-model.py <openrouter-id>`
4. Collect PinchBench, Arena, EQ-Bench scores from the web
5. Add PinchBench data to `PINCHBENCH_DATA` in the script
6. Edit `model-data.json` to add arena and eq_bench benchmark entries
7. Regenerate llms.txt (the script does this automatically)

For a full refresh: `python fetch-model.py --refresh`

## Scoring Composites

Scores are 0-100 weighted averages:

- **Reasoning**: AA Intelligence (3x), GPQA (2.5x), MMLU-Pro (2x), HLE (1.5x), AIME (1x)
- **Coding**: AA Coding Index (3x), LiveCodeBench (2x), TerminalBench Hard (2x), SciCode
  (1x)
- **Agentic**: PinchBench Best (4x), IFBench (3x), PinchBench Avg (2x)
- **Blended cost**: (3 \* input_per_m + output_per_m) / 4

## Key Files

- `model-benchmarks/scripts/fetch-model.py` — automated pipeline
- `model-benchmarks/data/model-data.json` — source of truth
- `model-benchmarks/llms.txt` — plain text for LLM consumption
- `model-benchmarks/data/eqbench-raw.json` — cached EQ-Bench scrape
- `env.local` — AA API key (gitignored)

## Common Pitfalls

- AA slugs don't match OpenRouter IDs — always check `AA_SLUG_MAP`
- AA often has multiple variants per model (reasoning/non-reasoning, effort levels) —
  use the default/non-reasoning variant unless specifically comparing reasoning modes
- EQ-Bench data is sparse for newer/smaller providers — proxy from predecessor models
  when needed (note it in the data with a `"note"` field)
- OpenRouter's speed fields (latency_last_30m, throughput_last_30m) are usually null —
  rely on AA for speed data
- The fetch script's `merge_model()` preserves manually-entered benchmark data on
  refresh
