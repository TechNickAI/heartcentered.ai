# Model Benchmarks — Project Context

Comparative LLM benchmark page at heartcentered.ai/model-benchmarks/ emphasizing
emotional intelligence (EQ-Bench) as the differentiating metric alongside reasoning,
coding, agentic, speed, and cost.

## Architecture

Static HTML/CSS/JS page — no build step, no framework.

- `index.html` — page structure, Tailwind CDN, Alpine.js (pinned @3.14.9), AOS
- `js/app.js` — vanilla JS IIFE: fetch data, sort, filter, search, render table + mobile
  cards
- `styles.css` — extends Organic Flow Design System CSS vars
- `data/model-data.json` — all model data (scores, benchmarks, pricing, traits)
- `data/eqbench-raw.json` — raw EQ-Bench scrape data (reference only)
- `scripts/fetch-model.py` — data pipeline: fetch, enrich, merge, generate llms.txt
- `llms.txt` — plain-text model summary for LLM consumption (auto-generated)

## Data Pipeline

### Adding a new model

1. **Fetch from OpenRouter** — `python scripts/fetch-model.py <openrouter-id>`
   - Gets pricing, context window, capabilities, endpoint stats
   - Optionally enriches with Artificial Analysis (needs AA_API_KEY in env.local)

2. **Add PinchBench scores** — manually from pinchbench.com
   - Add to `PINCHBENCH_DATA` dict in fetch-model.py
   - Format: `{"best_score": 88.0, "avg_score": 81.1, "runs": 19}`

3. **Add Arena Elo** — manually from arena.ai/leaderboard/text
   - Add to model's `benchmarks.arena` in model-data.json
   - Format: `{"elo": 1462}`

4. **Add EQ-Bench data** — two sources:
   - **Elo + legacy traits**: scrape from eqbench.com leaderboard (Playwright)
   - **v3 Score + v3 traits**: run EQ-Bench v3 benchmark directly (~$6/model, 10-20 min)
   - v3 Score is the primary display value (0-100, matches other columns)
   - Elo and traits show in tooltip on hover

5. **Regenerate llms.txt** —
   `python -c "import sys; sys.path.insert(0, 'model-benchmarks/scripts'); fm = __import__('importlib').import_module('fetch-model'); data = fm.load_model_data(); fm.generate_llms_txt(data)"`

### Refreshing existing models

```bash
python scripts/fetch-model.py --refresh        # all models
python scripts/fetch-model.py --refresh --no-aa # skip AA (rate limited at 1000/day)
```

`merge_model()` preserves manually-entered data: eq_bench, arena, pinchbench, scores,
notes, speed. Only OpenRouter-sourced fields get overwritten.

## Score Methodology

- **Reasoning** (0-100): Weighted avg of AA Intelligence Index (3x), GPQA (2.5x),
  MMLU-Pro (2x), HLE (1.5x), AIME 2025 (1x)
- **Coding** (0-100): Weighted avg of AA Coding Index (3x), LiveCodeBench (2x),
  TerminalBench Hard (2x), SciCode (1x)
- **Agentic** (0-100): Weighted avg of PinchBench Best (4x), IFBench (3x), PinchBench
  Avg (2x)
- **EQ** (0-100): EQ-Bench v3 score. Tooltip shows Elo ranking + trait breakdown
- **Chat** (Elo): Arena Elo from blind human A/B preference tests
- **Cost**: Blended per 1M tokens = (3 \* input + output) / 4

## EQ-Bench Data Model

Three distinct metrics from EQ-Bench, stored in `benchmarks.eq_bench`:

- `v3_score` (0-100) — absolute score from running v3 benchmark. **This is what the
  column displays.**
- `elo` (~856-1877) — relative ranking from pairwise comparisons on the public
  leaderboard
- `v3_traits` (22 dimensions, each 0-20) — detailed personality breakdown

v3 Score and Elo are separate measurements. High v3 score doesn't guarantee high Elo and
vice versa (e.g., Grok 4.20: v3=68.55 but Elo=856).

Trait dimensions: analytical, boundary_setting, challenging, compliant, conversational,
correctness, demonstrated_empathy, depth_of_insight, emotional_reasoning, humanlike,
intellectual_grounding, message_tailoring, moralising, pragmatic_ei, reactive,
safety_conscious, social_dexterity, subtext_identification, sycophantic, theory_of_mind,
validating, warmth.

Some traits are "negative" (lower is better): moralising, sycophantic, compliant,
reactive.

## Data Sources

| Source              | URL                                           | Auth                    | Notes                                               |
| ------------------- | --------------------------------------------- | ----------------------- | --------------------------------------------------- |
| OpenRouter          | openrouter.ai/api/v1/models                   | None                    | Pricing, capabilities, endpoints                    |
| Artificial Analysis | artificialanalysis.ai/api/v2/data/llms/models | AA_API_KEY in env.local | Benchmark evals, speed. 1000 req/day limit          |
| PinchBench          | pinchbench.com                                | None                    | Manual lookup, agentic scores                       |
| Arena               | arena.ai/leaderboard/text                     | None                    | Manual lookup, human preference Elo                 |
| EQ-Bench            | eqbench.com                                   | None                    | Elo + traits via scrape; v3 score via benchmark run |

## JS Architecture

- `esc()` — XSS protection on all innerHTML interpolations
- `getSortValue()` — null sentinels (-1 or 9999) sort missing data to bottom
- `scoreHtml()` — renders score with color tier (green >= 70, amber >= 45, muted < 45)
- `eqHtml()` — renders v3 score with Elo + traits tooltip
- `scoreTier()` — shared color tier function (also used for mobile EQ cards)
- Default sort: `eq_score` descending (EQ is the headline feature)

## Key Conventions

- All model links point to `https://openrouter.ai/models/${id}`
- `rel="noopener noreferrer"` on all external links
- No build step — Tailwind CDN, inline everything
- Accessibility is not a priority (decline ARIA suggestions)
- Always regenerate llms.txt after changing model-data.json

## Current Models (12)

Curated set of current-generation models. Not comprehensive — chosen to represent the
frontier across different providers, price points, and capability profiles.

Models not in CURATED_MODELS (GPT-5.4, Grok 4.20, Gemini 3.1 Pro, Haiku 4.5, GPT-5.4
Mini) were added manually and should be refreshed via `--refresh` not `--curated`.
