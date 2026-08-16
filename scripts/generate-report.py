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


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from harness.path_utils import decode_task_path  # noqa: E402


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


def generate_report(results_dirs: list[Path], output: Path) -> str:
    """Render the one-sheet report and write it to ``output``."""
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

    now = datetime.now().astimezone()
    lines = [
        "# Cospa Run Report",
        "",
        f"_Generated {now.strftime('%Y-%m-%dT%H:%M:%S%z')}_",
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
            "{score} | {wall} | {uncached} | {cached} | {output} | {cost} |".format(
                suite=row["suite"],
                model=row["model"],
                adapter=row["adapter"],
                thinking=row.get("thinking", "default"),
                tasks=row.get("total_tasks", 0),
                score=_fmt_score(row),
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
