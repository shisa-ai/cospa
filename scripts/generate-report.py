#!/usr/bin/env python3
"""Generate a human-readable one-sheet Markdown report for result runs.

The report summarizes every (model, adapter, suite, thinking) cell found in
the given results directories, then drills into per-task verdicts with
relative links to trial directories and pi-session traces so an agent (or
human) can navigate from headline numbers to raw rollouts.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Any
import math


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from harness.path_utils import decode_task_path  # noqa: E402
from harness.suites import load_suite  # noqa: E402


def _canonical_suite_size(suite: str) -> int | None:
    """Best-effort canonical task count for a suite (None if unknown).

    Used to decide whether a cell is complete. Suites whose task list needs
    absent vendor data resolve to None; callers then fall back to the largest
    observed cell for that suite key.
    """
    try:
        return len(load_suite(suite).get_task_ids())
    except Exception:
        return None


def _cell_latest_mtime(results_dir: Path, row: dict) -> float:
    """Newest verdict mtime under a cell directory (0 when unreadable)."""
    cell_dir = _cell_dir(Path(results_dir), row)
    latest = 0.0
    try:
        for verdict in cell_dir.rglob("verdict.json"):
            try:
                latest = max(latest, verdict.stat().st_mtime)
            except OSError:
                continue
    except OSError:
        pass
    return latest


def _load_viewer():
    server_path = ROOT / "view-scores" / "server.py"
    spec = importlib.util.spec_from_file_location(
        "cospa_report_viewer", server_path
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _fmt_tokens(value: float | int | None) -> str:
    if value is None:
        return "-"
    try:
        total = float(value)
    except (TypeError, ValueError):
        return "-"
    if total <= 0:
        return "0"
    if total >= 1_000_000:
        return f"{total / 1_000_000:.1f}M"
    if total >= 1_000:
        return f"{total / 1_000:.0f}K"
    return f"{total:.0f}"


def _fmt_duration(seconds: float | int | None) -> str:
    if seconds is None or seconds <= 0:
        return "-"
    total = int(round(float(seconds)))
    hours, rem = divmod(total, 3600)
    minutes, secs = divmod(rem, 60)
    if hours:
        return f"{hours}h{minutes:02d}m"
    if minutes:
        return f"{minutes}m{secs:02d}s"
    return f"{secs}s"


def _fmt_cost(value: float | None) -> str:
    if value is None or value < 0:
        return "-"
    if value == 0:
        return "$0"
    if value < 1:
        return f"${value:.4f}"
    return f"${value:,.2f}"


def _fmt_percent(value: float | None) -> str:
    if value is None:
        return "-"
    try:
        percent = float(value)
    except (TypeError, ValueError):
        return "-"
    return f"{percent:.1f}%"


def _fmt_count(value: float | None) -> str:
    if value is None:
        return "-"
    try:
        count = float(value)
    except (TypeError, ValueError):
        return "-"
    if count <= 0:
        return "-"
    return f"{count:.1f}"


def _geomean_rate(row: dict) -> float | None:
    """Extract a 0-1 rate for geomean aggregation from a score row.

    Continuous diagnostics (e.g. SWE-Explore WCC) contribute their headline
    ``score``; their ``pass_rate`` is an any-hit binary rate that would
    inflate the aggregate. Values on a 0-100 scale are normalized.
    """
    value = row.get("score") if row.get("score_type") == "continuous_non_coding" else row.get("pass_rate")
    if value is None:
        return None
    rate = float(value)
    return rate / 100.0 if rate > 1.0 else rate


def _smoothed_rate(row: dict) -> float | None:
    """Laplace-smoothed rate (passed+1)/(total+2) for ranking aggregates.

    Zero components stop annihilating the geometric mean; continuous rows
    keep their rate but are floored at the same Laplace floor.
    """
    total = row.get("total_tasks") or 0
    if total <= 0:
        return None
    if row.get("score_type") == "continuous_non_coding":
        base = _geomean_rate(row) or 0.0
        return max(base, 1.0 / (total + 2))
    passed = row.get("passed_tasks") or 0
    return (passed + 1) / (total + 2)


def _fmt_score(row: dict) -> str:
    if row.get("score_type") == "continuous_non_coding":
        return f"{row.get('score', 0.0):.1f}% {row.get('headline_metric', 'diag')}"
    return f"{row.get('passed_tasks', 0)}/{row.get('total_tasks', 0)} ({row.get('pass_rate', 0.0):.1f}%)"


def _cell_dir(results_dir: Path, row: dict) -> Path:
    from harness.path_utils import encode_model_path

    return (
        Path(results_dir)
        / encode_model_path(row["model"])
        / row["adapter"]
        / row["suite"]
    )


def _iter_task_trials(cell_dir: Path):
    """Yield (task_id, [trial_dir, ...]) with trials sorted numerically."""
    if not cell_dir.is_dir():
        return
    for task_dir in sorted(cell_dir.iterdir()):
        if not task_dir.is_dir() or task_dir.name.startswith("."):
            continue
        trials = sorted(
            (
                entry
                for entry in task_dir.iterdir()
                if entry.is_dir() and entry.name.startswith("trial-")
            ),
            key=lambda entry: entry.name,
        )
        if trials:
            try:
                task_id = decode_task_path(task_dir.name)
            except Exception:
                task_id = task_dir.name
            yield task_id, trials


def _trial_row(trial_dir: Path) -> dict:
    verdict_path = trial_dir / "verdict.json"
    manifest_path = trial_dir / "manifest.json"
    row = {
        "dir": trial_dir,
        "verdict": None,
        "manifest": None,
        "wall": None,
        "trace": None,
    }
    try:
        row["verdict"] = json.loads(verdict_path.read_text())
    except (OSError, json.JSONDecodeError):
        pass
    try:
        row["manifest"] = json.loads(manifest_path.read_text())
    except (OSError, json.JSONDecodeError):
        pass
    if row["manifest"]:
        seconds = row["manifest"].get("timing", {}).get("wall_clock_seconds")
        if isinstance(seconds, (int, float)):
            row["wall"] = float(seconds)
    trace = trial_dir / "out" / "pi_session.jsonl"
    if trace.is_file():
        row["trace"] = trace
    return row


def _campaign_elapsed_seconds(trial_infos: list[dict]) -> float | None:
    starts: list[datetime] = []
    ends: list[datetime] = []
    for info in trial_infos:
        manifest = info.get("manifest")
        if not manifest:
            continue
        for key, bucket in (("created_at", starts), ("run_end_time", ends)):
            raw = manifest.get(key)
            if not raw:
                continue
            try:
                bucket.append(datetime.fromisoformat(raw))
            except (TypeError, ValueError):
                continue
    if not starts or not ends:
        return None
    elapsed = (max(ends) - min(starts)).total_seconds()
    return elapsed if elapsed > 0 else None


def _rel(target: Path, base: Path) -> str:
    return Path(os.path.relpath(target, base)).as_posix()


def _render_cell_section(
    results_dir: Path,
    row: dict,
    report_dir: Path,
) -> str:
    cell_dir = _cell_dir(results_dir, row)
    lines = [
        f"### {row['suite']} — {row['model']} / {row['adapter']} / "
        f"{row.get('thinking', 'default')}",
        "",
        f"Results root: `{cell_dir}`",
        "",
    ]

    trial_infos: list[dict] = []
    task_lines: list[str] = []
    failure_counts: dict[str, int] = {}
    for task_id, trials in _iter_task_trials(cell_dir):
        rendered_trials = []
        rendered_traces = []
        wall_sum = 0.0
        for trial_dir in trials:
            info = _trial_row(trial_dir)
            trial_infos.append(info)
            verdict = info["verdict"]
            label = trial_dir.name.replace("trial-", "t")
            if verdict is None:
                symbol = "?"
            elif verdict.get("passed"):
                symbol = "✓"
            else:
                symbol = "✗"
                failure_class = verdict.get("failure_class") or "incorrect"
                failure_counts[failure_class] = (
                    failure_counts.get(failure_class, 0) + 1
                )
            rendered_trials.append(
                f"[{label} {symbol}]({_rel(trial_dir, report_dir)})"
            )
            if info["trace"] is not None:
                rendered_traces.append(
                    f"[{label}]({_rel(info['trace'], report_dir)})"
                )
            if info["wall"] is not None:
                wall_sum += info["wall"]
        wall_text = _fmt_duration(wall_sum) if wall_sum else "-"
        task_lines.append(
            f"| {task_id} | {' '.join(rendered_trials) or '-'} | "
            f"{wall_text} | {' '.join(rendered_traces) or '-'} |"
        )

    if task_lines:
        lines.extend(
            [
                "| Task | Trials | Task wall | Traces |",
                "| --- | --- | ---: | --- |",
                *task_lines,
                "",
            ]
        )

    if failure_counts:
        taxonomy = ", ".join(
            f"{count} {name}"
            for name, count in sorted(
                failure_counts.items(), key=lambda item: -item[1]
            )
        )
        lines.extend([f"Failed-trial taxonomy: {taxonomy}.", ""])

    elapsed = _campaign_elapsed_seconds(trial_infos)
    if elapsed is not None:
        lines.extend([f"Campaign elapsed (c=8 scheduling included): {_fmt_duration(elapsed)}.", ""])

    trace_count = sum(1 for info in trial_infos if info["trace"] is not None)
    lines.append(
        f"Traces: {trace_count}/{len(trial_infos)} trials expose "
        "`out/pi_session.jsonl`."
    )
    lines.append("")
    return "\n".join(lines)


def _pi_version() -> str:
    """Best-effort pi CLI version for the harness header."""
    import subprocess

    for argv in (["pi", "--version"],):
        try:
            result = subprocess.run(
                argv, capture_output=True, text=True, timeout=10
            )
        except (OSError, subprocess.TimeoutExpired):
            continue
        output = (result.stdout or result.stderr or "").strip()
        if result.returncode == 0 and output:
            return output.splitlines()[0]
    return "unknown"


def generate_report(
    results_dirs: list[Path],
    output: Path,
    canonical_suite_size=None,
) -> str:
    """Render the one-sheet report and write it to ``output``.

    ``canonical_suite_size`` overrides the default suite-size lookup (a
    ``suite_name -> expected task count | None`` callable); used by tests.
    """
    size_of = canonical_suite_size or _canonical_suite_size
    viewer = _load_viewer()
    output = Path(output)
    report_dir = output.parent

    all_rows: list[tuple[Path, dict]] = []
    for results_dir in results_dirs:
        results_dir = Path(results_dir)
        viewer.RESULTS_DIR = results_dir
        viewer.DEFAULT_USE_CACHE = False
        handler = viewer.ScoreHandler.__new__(viewer.ScoreHandler)
        rows = handler.get_scores(include_smoke=True)
        all_rows.extend((results_dir, row) for row in rows)

    # Deduplicate suite keys across roots: prefer the latest COMPLETE cell;
    # only when no complete cell exists fall back to the latest partial,
    # prominently marked. Excluded partials are footnoted, never silent.
    groups: dict[tuple, list[tuple[Path, dict]]] = {}
    for entry in all_rows:
        row = entry[1]
        key = (
            row["model"],
            row["adapter"],
            row["suite"],
            row.get("thinking", "default"),
        )
        groups.setdefault(key, []).append(entry)

    primary: list[tuple[Path, dict]] = []
    excluded: list[tuple[Path, dict]] = []
    for key, entries in groups.items():
        suite = key[2]
        canonical = size_of(suite)
        observed = [e[1].get("total_tasks", 0) for e in entries] or [0]
        expected = canonical if canonical else max(observed)

        def _is_complete(entry: tuple[Path, dict]) -> bool:
            return expected > 0 and entry[1].get("total_tasks", 0) >= expected

        candidates = [e for e in entries if _is_complete(e)] or entries
        chosen = max(candidates, key=lambda e: _cell_latest_mtime(e[0], e[1]))
        if not _is_complete(chosen) and expected > 0:
            chosen[1]["_partial_marker"] = (
                f"**PARTIAL {chosen[1].get('total_tasks', 0)}/{expected}**"
            )
        primary.append(chosen)
        excluded.extend(e for e in entries if e is not chosen)
    all_rows = primary

    now = datetime.now().astimezone()
    lines = [
        "# Cospa Run Report",
        "",
        f"_Generated {now.strftime('%Y-%m-%dT%H:%M:%S%z')} · "
        f"harness pi {_pi_version()} (pi_vanilla, --no-extensions)_",
        "",
        "## Summary",
        "",
        "| Suite | Model | Adapter | Thinking | Tasks | Score | "
        "Task wall | Uncached | Cached | Output | Cost |",
        "| --- | --- | --- | --- | ---: | --- | ---: | ---: | ---: | ---: | ---: |",
    ]
    totals = {
        "tasks": 0,
        "wall": 0.0,
        "prompt": 0,
        "cached": 0,
        "completion": 0,
        "cost": 0.0,
    }
    any_cost = False
    for results_dir, row in all_rows:
        totals["tasks"] += row.get("total_tasks", 0)
        totals["wall"] += row.get("total_wall_clock_seconds") or 0.0
        totals["prompt"] += row.get("prompt_tokens") or 0
        totals["cached"] += row.get("cached_tokens") or 0
        totals["completion"] += row.get("completion_tokens") or 0
        cost = row.get("estimated_cost_usd")
        if cost is not None:
            totals["cost"] += cost
            any_cost = True
        lines.append(
            "| {suite} | {model} | {adapter} | {thinking} | {tasks} | "
            "{score}{partial} | {wall} | {uncached} | {cached} | {output} | {cost} |".format(
                suite=row["suite"],
                model=row["model"],
                adapter=row["adapter"],
                thinking=row.get("thinking", "default"),
                tasks=row.get("total_tasks", 0),
                score=_fmt_score(row),
                partial=(
                    " " + row["_partial_marker"]
                    if row.get("_partial_marker")
                    else ""
                ),
                wall=_fmt_duration(row.get("total_wall_clock_seconds")),
                uncached=_fmt_tokens(row.get("prompt_tokens")),
                cached=_fmt_tokens(row.get("cached_tokens")),
                output=_fmt_tokens(row.get("completion_tokens")),
                cost=_fmt_cost(cost),
            )
        )
    if all_rows:
        lines.append(
            "| **All cells** | | | | **{tasks}** | — | **{wall}** | "
            "**{uncached}** | **{cached}** | **{output}** | **{cost}** |".format(
                tasks=totals["tasks"],
                wall=_fmt_duration(totals["wall"]),
                uncached=_fmt_tokens(totals["prompt"]),
                cached=_fmt_tokens(totals["cached"]),
                output=_fmt_tokens(totals["completion"]),
                cost=_fmt_cost(totals["cost"]) if any_cost else "-",
            )
        )
    # Headline geomean per model configuration (the "actual score").
    import math

    geomean_groups: dict[tuple, list[dict]] = {}
    for _results_dir, row in all_rows:
        if row.get("_partial_marker"):
            continue
        key = (row["model"], row["adapter"], row.get("thinking", "default"))
        geomean_groups.setdefault(key, []).append(row)
    if geomean_groups:
        lines.extend(
            [
                "",
                "## Headline geomean",
                "",
                "Geometric mean of per-suite rates per model configuration, "
                "across primary complete cells only (partials excluded; "
                "continuous diagnostics contribute their rate; any 0% "
                "component floors the strict geomean at 0). The smoothed "
                "column applies Laplace (passed+1)/(total+2) so zero "
                "components rank instead of annihilating. Macro mean is the "
                "unweighted average of per-suite rates; micro pooled is "
                "total passed / total tasks (larger panels weigh more; "
                "SWE-Explore contributes its any-hit count).",
                "",
                "| Model | Adapter | Thinking | Cells | Geomean | Geomean (smoothed) | Macro mean | Micro pooled |",
                "| --- | --- | --- | ---: | ---: | ---: | ---: | ---: |",
            ]
        )
        for key in sorted(geomean_groups):
            rates: list[float] = []
            for row in geomean_groups[key]:
                rate = _geomean_rate(row)
                if rate is not None:
                    rates.append(rate)
            if not rates:
                continue
            if any(rate <= 0.0 for rate in rates):
                geomean = 0.0
            else:
                geomean = math.exp(
                    sum(math.log(rate) for rate in rates) / len(rates)
                )
            smoothed = [
                _smoothed_rate(row)
                for row in geomean_groups[key]
            ]
            smoothed = [s for s in smoothed if s is not None]
            if smoothed:
                smoothed_geomean = math.exp(
                    sum(math.log(s) for s in smoothed) / len(smoothed)
                )
            else:
                smoothed_geomean = 0.0
            macro = sum(rates) / len(rates) if rates else 0.0
            passed_sum = sum(
                row.get("passed_tasks") or 0
                for row in geomean_groups[key]
                if row.get("total_tasks")
            )
            total_sum = sum(
                row.get("total_tasks") or 0
                for row in geomean_groups[key]
                if row.get("total_tasks")
            )
            micro = passed_sum / total_sum if total_sum else 0.0
            lines.append(
                f"| {key[0]} | {key[1]} | {key[2]} | {len(rates)} | "
                f"{100.0 * geomean:.1f}% | {100.0 * smoothed_geomean:.1f}% | "
                f"{100.0 * macro:.1f}% | {100.0 * micro:.1f}% |"
            )
        lines.append("")

    lines.extend(["", "## Speed & behavior", ""])
    lines.append(
        "| Suite | Model | Thinking | Tasks | Task wall | Avg/task | Turns | "
        "LLM% | Tool% | Tool calls | Search calls | Behavior trials |"
    )
    lines.append(
        "| --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |"
    )
    for _results_dir, row in all_rows:
        turns = row.get("mean_turns")
        behavior_trials = row.get("behavior_counted_trials") or 0
        lines.append(
            "| {suite} | {model} | {thinking} | {tasks} | {wall} | {avg} | "
            "{turns} | {llm} | {tool} | {calls} | {search} | {btrial} |".format(
                suite=row["suite"],
                model=row["model"],
                thinking=row.get("thinking", "default"),
                tasks=row.get("total_tasks", 0),
                wall=_fmt_duration(row.get("total_wall_clock_seconds")),
                avg=_fmt_duration(row.get("mean_wall_clock_seconds")),
                turns=f"{turns:.1f}" if turns else "-",
                llm=_fmt_percent(row.get("inference_percent")),
                tool=_fmt_percent(row.get("tool_percent")),
                calls=_fmt_count(row.get("mean_tool_calls")),
                search=_fmt_count(row.get("mean_search_calls")),
                btrial=behavior_trials or "-",
            )
        )
    if excluded:
        lines.extend(
            [
                "## Excluded partial cells",
                "",
                "Duplicate suite keys where a complete cell existed; shown for "
                "provenance, excluded from all totals above.",
                "",
                "| Suite | Model | Thinking | Tasks | Results root |",
                "| --- | --- | --- | ---: | --- |",
            ]
        )
        for results_dir, row in excluded:
            lines.append(
                "| {suite} | {model} | {thinking} | {tasks} | `{root}` |".format(
                    suite=row["suite"],
                    model=row["model"],
                    thinking=row.get("thinking", "default"),
                    tasks=row.get("total_tasks", 0),
                    root=results_dir,
                )
            )
        lines.append("")

    lines.extend(["", "## Per-cell detail", ""])

    for results_dir, row in all_rows:
        lines.append(_render_cell_section(results_dir, row, report_dir))

    lines.extend(
        [
            "## Navigating raw data",
            "",
            "Each trial link above resolves to a directory containing "
            "`manifest.json` (model, sampling, timing, token usage), "
            "`verdict.json` (pass/fail, failure class, grader output), "
            "`out/` (adapter logs and `pi_session.jsonl` rollout trace), "
            "and for Harbor suites `jobs/` plus `workdir/`.",
            "",
        ]
    )

    markdown = "\n".join(lines)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(markdown)
    return markdown


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--results-dir",
        action="append",
        required=True,
        type=Path,
        help="Results directory to include (repeatable).",
    )
    parser.add_argument(
        "--output",
        type=Path,
        required=True,
        help="Markdown output path; links are relative to this file.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    markdown = generate_report(args.results_dir, args.output)
    print(f"wrote {len(markdown.splitlines())} lines to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
