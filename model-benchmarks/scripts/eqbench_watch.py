#!/usr/bin/env python3
"""
EQ-Bench upstream WATCHER — detects when eqbench.com publishes a new row.

WHY THIS EXISTS (read before touching anything)
-----------------------------------------------
The benchmark's coverage gap is not neglect, it is upstream-blocked. As of
2026-07-27 there are frontier models live on OpenRouter (claude-opus-5,
grok-4.5, kimi-k3, the gpt-5.6 family, gemini-3.6-flash) with NO EQ-Bench
row. Adding them would produce empty rows, so the honest move is to wait.

But "wait" was silently costing us: nothing in the repo noticed when the wait
ended. `--refresh` only updates rows that already exist, and `--discover` only
adds models already present in EQBENCH_PUBLIC_MAP. Both are blind to a brand
new upstream key. So a score could sit published upstream for weeks before a
human happened to look.

This module closes that loop. It snapshots the set of upstream EQ-Bench keys
to `data/eqbench-upstream-keys.json` and, on each run, diffs live upstream
against the snapshot. New keys are REPORTED, never auto-mapped.

WHY IT REPORTS INSTEAD OF AUTO-ADDING
-------------------------------------
Mapping an EQ-Bench key to an OpenRouter id is not derivable and fuzzy
matching demonstrably mis-assigns (gpt-5.4-mini->gpt-5.4, glm-5-turbo->GLM-5,
grok-4.20->grok-4). Each of those would write one model's score into another
model's row — a fabrication that looks like a refresh. So the watcher's output
is a work order for a human: "upstream published X, decide what it maps to."
Detection is automatable. Identity is not.
"""

from __future__ import annotations

import json
from pathlib import Path

from eqbench_public import EQBENCH_PUBLIC_MAP, fetch_public_leaderboard

# Snapshot of every upstream key seen on a previous run. Checked into git so
# the diff is meaningful across machines and across CI runs.
SNAPSHOT_PATH = (
    Path(__file__).resolve().parent.parent / "data" / "eqbench-upstream-keys.json"
)


def load_snapshot(path: Path | None = None) -> set[str]:
    """Return the set of upstream keys recorded on a previous run.

    A missing snapshot returns an empty set, which makes the first run report
    every upstream key as new. That is correct and honest: we genuinely have
    no prior observation to compare against.
    """
    path = SNAPSHOT_PATH if path is None else path
    if not path.exists():
        return set()
    payload = json.loads(path.read_text())
    return set(payload.get("keys", []))


def save_snapshot(keys: set[str], path: Path | None = None) -> None:
    """Record the current upstream key set. Sorted for a stable git diff."""
    path = SNAPSHOT_PATH if path is None else path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"count": len(keys), "keys": sorted(keys)}, indent=2) + "\n"
    )


def diff_upstream(live_keys: set[str], snapshot: set[str]) -> dict[str, list[str]]:
    """Compare live upstream keys against the last snapshot.

    Returns both directions. A DISAPPEARED key matters as much as a new one:
    it means an upstream row we may already be shipping has been withdrawn,
    which is the D-001 delisting shape and needs a human, not a silent drop.
    """
    return {
        "new": sorted(live_keys - snapshot),
        "disappeared": sorted(snapshot - live_keys),
    }


def unmapped_keys(live_keys: set[str]) -> list[str]:
    """Upstream keys that no OpenRouter id currently claims."""
    return sorted(live_keys - set(EQBENCH_PUBLIC_MAP.values()))


def watchlist_status(
    live_keys: set[str], watched_ids: list[str]
) -> dict[str, list[str]]:
    """Split watched OpenRouter ids by whether upstream can score them yet.

    `actionable` means: this id is already hand-mapped AND its upstream row
    now exists, so a real score can be shipped. `still_blocked` means upstream
    has nothing, so the honest state remains an empty cell.
    """
    actionable, still_blocked = [], []
    for model_id in watched_ids:
        key = EQBENCH_PUBLIC_MAP.get(model_id)
        if key is not None and key in live_keys:
            actionable.append(model_id)
        else:
            still_blocked.append(model_id)
    return {"actionable": sorted(actionable), "still_blocked": sorted(still_blocked)}


def run_watch(tracked_ids: list[str], write_snapshot: bool = True) -> dict:
    """Fetch live upstream, diff it against the snapshot, and report.

    Never writes to model-data.json. This function's only side effect is the
    snapshot file, so it is safe to run on every CI pass.
    """
    live_keys = set(fetch_public_leaderboard().keys())
    snapshot = load_snapshot()
    delta = diff_upstream(live_keys, snapshot)
    report = {
        "upstream_total": len(live_keys),
        "snapshot_total": len(snapshot),
        "new_upstream_keys": delta["new"],
        "disappeared_upstream_keys": delta["disappeared"],
        "unmapped_upstream_keys": unmapped_keys(live_keys),
        **watchlist_status(live_keys, tracked_ids),
    }
    if write_snapshot:
        save_snapshot(live_keys)
    return report


def format_report(report: dict) -> str:
    """Human-readable work order. Explicitly says when nothing changed."""
    lines = [
        f"EQ-Bench upstream: {report['upstream_total']} rows "
        f"(previous snapshot: {report['snapshot_total']})",
    ]
    new = report["new_upstream_keys"]
    gone = report["disappeared_upstream_keys"]
    if new:
        lines.append(f"\nNEW upstream rows ({len(new)}) — decide the mapping by hand:")
        lines += [f"  + {k}" for k in new]
    if gone:
        lines.append(
            f"\nDISAPPEARED upstream rows ({len(gone)}) — do NOT silently drop, see D-001:"
        )
        lines += [f"  - {k}" for k in gone]
    if not new and not gone:
        lines.append("\nNo upstream change since last snapshot.")
    if report["actionable"]:
        lines.append("\nACTIONABLE — mapped and now scoreable upstream:")
        lines += [f"  ! {m}" for m in report["actionable"]]
    lines.append(
        f"\n{len(report['still_blocked'])} tracked model(s) still have no upstream row. "
        "Empty cell remains the honest state for them."
    )
    return "\n".join(lines)
