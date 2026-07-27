# Proposal: render the public EQ-Bench score as its own column

**Status:** DRAFT — needs Nick's approval before it reaches `main`.
**Branch:** `benchmark/eq-public-display` · **Scope:** display logic only, zero data changes.
**Date:** 2026-07-26

## The problem

`model-data.json` holds 35 models. 28 of them carry a real, upstream-verified public EQ-Bench
v3 score. The page rendered only 12 of them, because the EQ column read a single field,
`v3_score`, which is Nick's locally-run 22-trait metric. Everything else showed an em-dash.

Measured on the live page before this change: **23 of 35 EQ cells rendered "—"** while the
data behind them existed and was verified. Every pass that added coverage widened that gap.

## What this change does

Splits one EQ column into two clearly-labelled ones.

| | Reads | Rubric | Renders |
|---|---|---|---|
| **EQ (local)** | `v3_score` | 22 traits, our own run (~$6/model) | 12 of 35 |
| **EQ (public)** | `public_rubric_0_100` | 17 traits, eqbench.com leaderboard | 28 of 35 |

Both are sortable. Blank cells sort to the bottom. Mobile cards gained a matching
"EQ (public)" tile and the old ambiguous "EQ" label became "EQ (local)".

## What it deliberately does NOT do

- **Does not merge, average, or convert between the two metrics.** They are different rubrics
  and the offset is not even consistent in sign (Grok 4.20 is 68.55 local, 55.8 public).
  Each column shows only its own source.
- **Does not fall back.** A model with no local score shows blank in the local column
  forever, not the public number wearing a local label.
- **Does not touch `model-data.json`.** `git diff --name-only` covers exactly two files:
  `js/app.js` and `index.html`.

Both column tooltips say in plain words that the rubrics differ and are not directly
comparable. The public tooltip names eqbench.com as the source. Trait values in the public
tooltip are shown as `x/20` because upstream traits are on a 0-20 scale, not 0-100.

## Evidence actually verified

Headless Chromium against a local server, reading the rendered DOM:

- Before: 35 rows, **23 EQ cells empty**, 12 rendered.
- After: 35 rows, **28 public scores rendered**, 12 local scores rendered.
- Every rendered number cross-checked cell-by-cell against `model-data.json`:
  **0 mismatches across all 35 rows and both columns.**
- Sorting by EQ (public) verified descending (83.3, 82.6, 82.6, 82.4, 82.4 ...) with all
  blanks at the bottom.
- Header row reads: Model, Reasoning, Coding, Agentic, EQ (local), EQ (public), Chat, Speed,
  Cost, Context. `colspan` updated 9 → 10 in all three placeholder states.
- Test suite: 26/26 pass. Pre-commit hooks pass including Prettier.

Screenshots (tracked with this proposal):

- [Before: one EQ column, 23 blanks](assets/eq-public-before.png)
- [After: separate local and public EQ columns](assets/eq-public-after.png)

## Open question for Nick

The top of the page by public score is Claude Opus 4.8 at 83.3, and the local column's top is
GPT-5.4 at 73.2. Two different models lead depending on the column. That is honest and it is
also a story worth telling in prose. Want a short explainer under the table saying why two EQ
columns exist and why they disagree? That is prose, so it is not in this diff.
