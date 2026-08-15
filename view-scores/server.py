"""
Score viewer — terminal/web/API views over the durable results tree.

Rows = (model, adapter, suite), cells = task-level pass@k-majority score,
drill-down to per-task verdicts.

Usage:
  ./view
  ./view serve
"""

import html
import hashlib
import json
import os
import sys
import argparse
import re
import statistics
import time
from pathlib import Path
from http.server import HTTPServer, SimpleHTTPRequestHandler
from urllib.parse import urlparse, parse_qs, urlencode

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
RESULTS_DIR = PROJECT_ROOT / "results"
ANSI_RE = re.compile(r"\033\[[0-9;]*m")
DEFAULT_INCLUDE_SMOKE = False
DEFAULT_FILTERS: tuple[str, ...] = ()
DEFAULT_EXCLUDES: tuple[str, ...] = ()
DEFAULT_SORT_BY: tuple[str, ...] = ()
DEFAULT_USE_CACHE = True
DEFAULT_MODELS_CONFIG_PATH = PROJECT_ROOT / "configs" / "models.yaml"
DEFAULT_PRICING_PROFILE = os.environ.get("CODING_EVAL_PRICING_PROFILE") or None
DEFAULT_CACHE_PATH = Path(
    os.environ.get(
        "CODING_EVAL_VIEW_CACHE_PATH",
        PROJECT_ROOT / ".cache" / "view-scores.json",
    )
)
SCORE_CACHE_VERSION = 5
RUN_HEARTBEAT_FILE = ".runner-heartbeat.json"
RUN_HEARTBEAT_STALE_SECONDS = 90


def _ansi(text: str, code: str, enabled: bool) -> str:
    if not enabled:
        return text
    return f"\033[{code}m{text}\033[0m"


def _color_enabled(mode: str) -> bool:
    if mode == "always":
        return True
    if mode == "never":
        return False
    return sys.stdout.isatty()


def _score_color(pass_rate: float) -> str:
    if pass_rate >= 80:
        return "32"
    if pass_rate >= 50:
        return "33"
    return "31"


def _score_class(pass_rate: float) -> str:
    if pass_rate >= 80:
        return "score-good"
    if pass_rate >= 50:
        return "score-mid"
    return "score-low"


def _score_display(row: dict) -> tuple[float, str]:
    value = float(row.get("score", row.get("pass_rate", 0.0)))
    if row.get("score_type") == "continuous_non_coding":
        metric = str(row.get("headline_metric") or "diagnostic")
        label = {
            "weighted_core_coverage": "WCC",
        }.get(metric, metric)
        return value, f"{value:.1f}% {label}"
    return value, f"{value:.1f}%"


def _format_duration(seconds: float | int | None) -> str:
    if seconds is None:
        return "-"
    try:
        total = int(round(float(seconds)))
    except (TypeError, ValueError):
        return "-"
    if total <= 0:
        return "-"
    hours, rem = divmod(total, 3600)
    minutes, secs = divmod(rem, 60)
    if hours:
        return f"{hours}h{minutes:02d}m"
    if minutes:
        return f"{minutes}m{secs:02d}s"
    return f"{secs}s"


def _format_tokens(value: float | int | None) -> str:
    if value is None:
        return "-"
    try:
        total = int(value)
    except (TypeError, ValueError):
        return "-"
    if total <= 0:
        return "-"
    return f"{total:,}"


def _format_turns(value: float | int | None) -> str:
    if value is None:
        return "-"
    try:
        turns = float(value)
    except (TypeError, ValueError):
        return "-"
    if turns <= 0:
        return "-"
    return f"{turns:.1f}"


def _format_percent(value: float | int | None) -> str:
    if value is None:
        return "-"
    try:
        percent = float(value)
    except (TypeError, ValueError):
        return "-"
    return f"{percent:.1f}%"


def _format_cost(value: float | int | None) -> str:
    if value is None:
        return "-"
    try:
        amount = float(value)
    except (TypeError, ValueError):
        return "-"
    if amount < 0:
        return "-"
    if amount == 0:
        return "$0"
    if amount < 1:
        return f"${amount:.4f}"
    return f"${amount:,.2f}"


def _format_rate(value: float | int | None) -> str:
    if value is None:
        return "-"
    try:
        amount = float(value)
    except (TypeError, ValueError):
        return "-"
    if amount < 0:
        return "-"
    if amount >= 100:
        return f"{amount:,.0f}"
    if amount >= 10:
        return f"{amount:,.1f}"
    return f"{amount:,.2f}"


def _matches_any(patterns: tuple[str, ...] | list[str], text: str) -> bool:
    for pattern in patterns:
        try:
            if re.search(pattern, text, flags=re.IGNORECASE):
                return True
        except re.error:
            if pattern.lower() in text.lower():
                return True
    return False


SORT_ALIASES = {
    "pass": "pass_rate",
    "score": "score",
    "pass_rate": "pass_rate",
    "passed": "passed_tasks",
    "passed_tasks": "passed_tasks",
    "cost": "estimated_cost_usd",
    "total_cost": "estimated_cost_usd",
    "estimated_cost": "estimated_cost_usd",
    "estimated_cost_usd": "estimated_cost_usd",
    "task": "cost_per_completed_task_usd",
    "cost_task": "cost_per_completed_task_usd",
    "cost_per_task": "cost_per_completed_task_usd",
    "cost_per_completed_task": "cost_per_completed_task_usd",
    "cost_per_completed_task_usd": "cost_per_completed_task_usd",
    "$/task": "cost_per_completed_task_usd",
    "cospa": "passed_tasks_per_usd",
    "pass_dollar": "passed_tasks_per_usd",
    "pass_per_dollar": "passed_tasks_per_usd",
    "passed_per_dollar": "passed_tasks_per_usd",
    "passed_tasks_per_usd": "passed_tasks_per_usd",
    "pass/$": "passed_tasks_per_usd",
    "model": "model",
    "adapter": "adapter",
    "suite": "suite",
    "thinking": "thinking",
    "provider": "provider",
    "status": "status",
    "runtime": "total_wall_clock_seconds",
    "total_wall_clock_seconds": "total_wall_clock_seconds",
    "avg": "mean_wall_clock_seconds",
    "mean_wall_clock_seconds": "mean_wall_clock_seconds",
    "eta": "estimated_remaining_seconds",
    "estimated_remaining_seconds": "estimated_remaining_seconds",
    "llm": "inference_percent",
    "llm_percent": "inference_percent",
    "inference_percent": "inference_percent",
    "tool_percent": "tool_percent",
    "calls": "mean_tool_calls",
    "mean_tool_calls": "mean_tool_calls",
    "search": "mean_search_calls",
    "mean_search_calls": "mean_search_calls",
}

SORT_DEFAULT_DIRECTIONS = {
    "score": "desc",
    "pass_rate": "desc",
    "passed_tasks": "desc",
    "passed_tasks_per_usd": "desc",
    "estimated_cost_usd": "asc",
    "cost_per_completed_task_usd": "asc",
    "total_wall_clock_seconds": "asc",
    "mean_wall_clock_seconds": "asc",
    "estimated_remaining_seconds": "asc",
    "inference_percent": "desc",
    "tool_percent": "asc",
    "mean_tool_calls": "asc",
    "mean_search_calls": "asc",
}


def _normalize_sort_alias(value: str) -> str:
    return value.strip().lower().replace(" ", "_").replace("-", "_")


def _split_sort_specs(sort_by: str | list[str] | tuple[str, ...] | None) -> list[str]:
    if not sort_by:
        return []
    raw_specs = [sort_by] if isinstance(sort_by, str) else list(sort_by)
    specs: list[str] = []
    for raw_spec in raw_specs:
        specs.extend(
            spec.strip()
            for spec in str(raw_spec).split(",")
            if spec.strip()
        )
    return specs


def _parse_sort_spec(spec: str) -> tuple[str, str]:
    direction = None
    field = spec.strip()
    if ":" in field:
        field, suffix = field.rsplit(":", 1)
        suffix = suffix.strip().lower()
        if suffix not in {"asc", "desc"}:
            raise ValueError(
                f"unknown sort direction {suffix!r}; use asc or desc"
            )
        direction = suffix
    if field.startswith("-"):
        direction = "desc"
        field = field[1:]
    elif field.startswith("+"):
        direction = "asc"
        field = field[1:]

    alias = _normalize_sort_alias(field)
    field_name = SORT_ALIASES.get(alias)
    if field_name is None:
        allowed = ", ".join(sorted(set(SORT_ALIASES)))
        raise ValueError(f"unknown sort field {field!r}; expected one of: {allowed}")
    return field_name, direction or SORT_DEFAULT_DIRECTIONS.get(field_name, "asc")


def _sort_component(row: dict, field: str, direction: str) -> tuple:
    value = row.get(field)
    if value is None:
        return (1, 0, 0)
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        amount = float(value)
        if direction == "desc":
            amount = -amount
        return (0, 0, amount)
    text = str(value).lower()
    if direction == "desc":
        return (0, 1, tuple(-ord(char) for char in text))
    return (0, 1, text)


def sort_scores(
    scores: list[dict],
    sort_by: str | list[str] | tuple[str, ...] | None,
) -> list[dict]:
    """Return scores sorted by terminal/table aliases.

    Missing values sort last. Multiple comma-separated specs are supported,
    e.g. ``pass,cost`` sorts by score first and total cost second.
    """
    specs = [_parse_sort_spec(spec) for spec in _split_sort_specs(sort_by)]
    if not specs:
        return list(scores)

    def key(row: dict) -> tuple:
        tie_breaker = (
            str(row.get("model", "")),
            str(row.get("adapter", "")),
            str(row.get("suite", "")),
            str(row.get("thinking", "")),
            str(row.get("provider", "")),
        )
        return tuple(
            _sort_component(row, field, direction)
            for field, direction in specs
        ) + tie_breaker

    return sorted(scores, key=key)


def _known_adapter_names() -> set[str]:
    from harness.adapters import ADAPTERS

    return set(ADAPTERS)


def _known_suite_names() -> set[str]:
    from harness.suites import SUITES

    return set(SUITES)


def _visible_len(value: str) -> int:
    return len(ANSI_RE.sub("", value))


def _format_warnings_terminal(warnings: list[dict] | None) -> str:
    if not warnings:
        return ""
    lines = ["Warnings:"]
    for warning in warnings[:5]:
        lines.append(f"- {warning.get('message', warning)}")
    if len(warnings) > 5:
        lines.append(f"- ... {len(warnings) - 5} more warning(s)")
    return "\n".join(lines)


def _format_table(headers: list[str], rows: list[list[str]]) -> str:
    widths = [
        max(_visible_len(str(cell)) for cell in column)
        for column in zip(headers, *rows, strict=False)
    ]

    def render_row(cells: list[str]) -> str:
        padded = []
        for cell, width in zip(cells, widths):
            text = str(cell)
            padded.append(text + (" " * (width - _visible_len(text))))
        return "  ".join(padded)

    divider = "  ".join("-" * width for width in widths)
    return "\n".join([render_row(headers), divider, *(render_row(row) for row in rows)])


def format_scores_terminal(
    scores: list[dict],
    *,
    results_dir: Path = RESULTS_DIR,
    color: bool = False,
    show_ci: bool = False,
    verbose: bool = False,
    warnings: list[dict] | None = None,
) -> str:
    """Return a compact terminal score table.

    The default view is operational: task-level score and passed/total counts.
    Confidence intervals are available on request, but they are intentionally
    hidden by default because tiny smoke runs produce very wide intervals.
    """
    warning_text = _format_warnings_terminal(warnings)
    if not scores:
        output = f"No scores found in {results_dir}"
        return f"{output}\n\n{warning_text}" if warning_text else output

    if verbose:
        headers = [
            "Model",
            "Adapter",
            "Suite",
            "Thinking",
            "Provider",
            "Status",
            "Score",
            "Passed",
            "Done",
            "Runtime",
            "Avg",
            "Turns",
            "LLM%",
            "Tool%",
            "Calls",
            "Search",
            "Tok In",
            "Tok Out",
            "$/M In",
            "$/M Out",
            "Reason",
            "Cached",
            "Cost",
            "Costed",
            "$/Task",
            "Pass/$",
            "ETA",
        ]
    else:
        headers = [
            "Model",
            "Adapter",
            "Suite",
            "Thinking",
            "Provider",
            "Score",
            "Passed",
            "Tasks",
            "Cost",
            "$/Task",
            "Pass/$",
        ]
    if show_ci:
        headers.append("95% CI")

    rows = []
    for score in scores:
        display_score, score_text = _score_display(score)
        score_text = _ansi(score_text, _score_color(display_score), color)
        if verbose:
            completed = int(score.get("completed_tasks", score["total_tasks"]))
            expected = int(score.get("expected_tasks", completed))
            done = f"{completed}/{expected}" if expected != completed else str(completed)
            row = [
                str(score["model"]),
                str(score["adapter"]),
                str(score["suite"]),
                str(score.get("thinking", "default")),
                str(score.get("provider", "-")),
                str(score.get("status", "complete")),
                score_text,
                f"{score['passed_tasks']}/{score['total_tasks']}",
                done,
                _format_duration(score.get("total_wall_clock_seconds")),
                _format_duration(score.get("mean_wall_clock_seconds")),
                _format_turns(score.get("mean_turns")),
                _format_percent(score.get("inference_percent")),
                _format_percent(score.get("tool_percent")),
                _format_turns(score.get("mean_tool_calls")),
                _format_turns(score.get("mean_search_calls")),
                _format_tokens(score.get("prompt_tokens")),
                _format_tokens(score.get("completion_tokens")),
                _format_cost(score.get("input_cost_per_million_usd")),
                _format_cost(score.get("output_cost_per_million_usd")),
                _format_tokens(score.get("reasoning_tokens")),
                _format_tokens(score.get("cached_tokens")),
                _format_cost(score.get("estimated_cost_usd")),
                (
                    f"{score.get('costed_trials', 0)}/{score.get('completed_trials', 0)}"
                    if score.get("completed_trials")
                    else "-"
                ),
                _format_cost(score.get("cost_per_completed_task_usd")),
                _format_rate(score.get("passed_tasks_per_usd")),
                _format_duration(score.get("estimated_remaining_seconds")),
            ]
        else:
            row = [
                str(score["model"]),
                str(score["adapter"]),
                str(score["suite"]),
                str(score.get("thinking", "default")),
                str(score.get("provider", "-")),
                score_text,
                f"{score['passed_tasks']}/{score['total_tasks']}",
                str(score["total_tasks"]),
                _format_cost(score.get("estimated_cost_usd")),
                _format_cost(score.get("cost_per_completed_task_usd")),
                _format_rate(score.get("passed_tasks_per_usd")),
            ]
        if show_ci:
            row.append(f"{score['ci_lower']:.1f}-{score['ci_upper']:.1f}%")
        rows.append(row)

    title = _ansi("Coding Eval Scores", "1", color)
    subtitle = f"Results: {results_dir}"
    output = f"{title}\n{subtitle}\n\n{_format_table(headers, rows)}"
    return f"{output}\n\n{warning_text}" if warning_text else output


class ScoreHandler(SimpleHTTPRequestHandler):
    """HTTP handler for the score viewer."""

    @staticmethod
    def _iter_trial_dirs(results_dir: Path):
        """Yield runner trial directories anywhere under results_dir."""
        if not results_dir.exists():
            return
        for verdict_file in results_dir.rglob("verdict.json"):
            trial_dir = verdict_file.parent
            if (
                trial_dir.name.startswith("trial-")
                and (trial_dir / "manifest.json").exists()
            ):
                yield trial_dir

    def _reset_warnings(self) -> None:
        self._warnings = []

    def _warn(self, code: str, message: str, path: Path | None = None) -> None:
        warning = {"code": code, "message": message}
        if path is not None:
            warning["path"] = str(path)
        self._warnings.append(warning)

    def get_warnings(self) -> list[dict]:
        return list(getattr(self, "_warnings", []))

    @staticmethod
    def _iter_started_trial_dirs(results_dir: Path):
        """Yield trial-* directories, including currently incomplete trials."""
        if not results_dir.exists():
            return
        for current, dirnames, _filenames in os.walk(results_dir):
            dirnames[:] = sorted(
                name
                for name in dirnames
                if name not in {".cache", ".git", "__pycache__", ".pytest_cache"}
            )
            current_path = Path(current)
            if re.fullmatch(r"trial-\d+", current_path.name):
                yield current_path
                dirnames[:] = []

    @staticmethod
    def _trial_parts(results_dir: Path, trial_dir: Path) -> dict | None:
        from harness.path_utils import decode_model_path, decode_task_path

        try:
            task_dir = trial_dir.parent
            suite_dir = task_dir.parent
            adapter_dir = suite_dir.parent
            model_dir = adapter_dir.parent
            run_parent = model_dir.parent.relative_to(results_dir)
        except (IndexError, ValueError):
            return None

        run_path = "" if str(run_parent) == "." else run_parent.as_posix()
        return {
            "trial_dir": trial_dir,
            "task_dir": task_dir,
            "suite_dir": suite_dir,
            "adapter_dir": adapter_dir,
            "model_dir": model_dir,
            "run_path": run_path,
            "model_id": decode_model_path(model_dir.name),
            "adapter_id": adapter_dir.name,
            "suite_id": suite_dir.name,
            "task_id": decode_task_path(task_dir.name),
        }

    @staticmethod
    def _trial_search_text(parts: dict) -> str:
        return " ".join(
            str(parts.get(key, ""))
            for key in (
                "run_path",
                "model_id",
                "adapter_id",
                "suite_id",
                "task_id",
                "trial_dir",
            )
        )

    @classmethod
    def _trial_visible(
        cls,
        parts: dict,
        *,
        include_smoke: bool,
        filters: tuple[str, ...],
        excludes: tuple[str, ...],
    ) -> bool:
        run_path = str(parts.get("run_path", ""))
        run_path_lower = run_path.lower()
        run_segments = set(Path(run_path_lower).parts)
        if not include_smoke and (
            "smoke" in run_path_lower
            or "probe" in run_path_lower
            or "preflight" in run_path_lower
            or "qualification" in run_segments
            or "validation" in run_segments
        ):
            return False
        search_text = cls._trial_search_text(parts)
        if filters and not _matches_any(filters, search_text):
            return False
        if excludes and _matches_any(excludes, search_text):
            return False
        return True

    def _trial_parts_valid(self, parts: dict) -> bool:
        adapter = str(parts.get("adapter_id", ""))
        suite = str(parts.get("suite_id", ""))
        trial_dir = parts.get("trial_dir")
        has_durable_artifact = (
            isinstance(trial_dir, Path)
            and (
                (trial_dir / "manifest.json").exists()
                or (trial_dir / "verdict.json").exists()
            )
        )

        if adapter not in _known_adapter_names():
            if has_durable_artifact:
                self._warn(
                    "malformed_result_path",
                    (
                        "malformed result path skipped: "
                        f"unknown adapter {adapter!r} in {trial_dir}"
                    ),
                    trial_dir if isinstance(trial_dir, Path) else None,
                )
            return False
        if suite not in _known_suite_names():
            if has_durable_artifact:
                self._warn(
                    "malformed_result_path",
                    (
                        "malformed result path skipped: "
                        f"unknown suite {suite!r} in {trial_dir}"
                    ),
                    trial_dir if isinstance(trial_dir, Path) else None,
                )
            return False
        return True

    @staticmethod
    def _load_trial(trial_dir: Path) -> dict | None:
        verdict_file = trial_dir / "verdict.json"
        manifest_file = trial_dir / "manifest.json"
        try:
            with open(verdict_file) as f:
                verdict = json.load(f)
            if verdict.get("pending"):
                return None
            with open(manifest_file) as f:
                manifest = json.load(f)
        except Exception:
            return None
        return {"trial_dir": trial_dir, "verdict": verdict, "manifest": manifest}

    @staticmethod
    def _pid_is_running(pid: int) -> bool:
        if pid <= 0:
            return False
        try:
            os.kill(pid, 0)
            return True
        except OSError:
            return False

    @classmethod
    def _heartbeat_is_live(cls, heartbeat: dict, *, now: float | None = None) -> bool:
        if not isinstance(heartbeat, dict) or heartbeat.get("state") != "running":
            return False
        updated_at = heartbeat.get("updated_at_epoch")
        try:
            updated_at = float(updated_at)
        except (TypeError, ValueError):
            return False
        now = time.time() if now is None else now
        if now - updated_at > RUN_HEARTBEAT_STALE_SECONDS:
            return False
        pid = heartbeat.get("pid")
        try:
            pid = int(pid)
        except (TypeError, ValueError):
            return False
        return cls._pid_is_running(pid)

    @classmethod
    def _cell_has_live_heartbeat(cls, suite_dirs: set[Path]) -> bool:
        for suite_dir in suite_dirs:
            heartbeat_path = suite_dir / RUN_HEARTBEAT_FILE
            try:
                heartbeat = json.loads(heartbeat_path.read_text())
            except (OSError, json.JSONDecodeError):
                continue
            if cls._heartbeat_is_live(heartbeat):
                return True
        return False

    @staticmethod
    def _option_value(argv: list[str], name: str) -> str | None:
        for index, arg in enumerate(argv):
            if arg == name and index + 1 < len(argv):
                return argv[index + 1]
            prefix = f"{name}="
            if arg.startswith(prefix):
                return arg[len(prefix):]
        return None

    @classmethod
    def _has_live_runner_process(
        cls,
        model_id: str,
        adapter_id: str,
        suite_id: str,
        run_path: str = "",
        *,
        thinking: str | None = None,
    ) -> bool:
        """Best-effort fallback for pre-heartbeat live runners.

        Matches on (model, adapter, suite) plus, when available, --thinking
        and --run-id so that a dead high-effort run is not mis-attributed to
        a live default-effort runner for the same (model, adapter, suite).
        """
        # Derive expected run-id from the run_path (the leaf directory name
        # of the results root for this run).
        expected_run_id = None
        if run_path:
            from harness.path_utils import encode_model_path
            # run_path is typically "<encoded_model>-<run_id>" — extract run_id
            # by stripping the encoded model prefix.
            leaf = Path(run_path).name
            # The model id is URL-encoded in the path; find the run_id after
            # the last occurrence of the encoded model separator.
            # Example: "aiand%2Fqwen%2Fqwen3.6-27b-full-20260704-high"
            #   -> run_id = "full-20260704-high"
            # We match by looking for the encoded model id prefix.
            enc_model = encode_model_path(model_id)
            if leaf.startswith(enc_model + "-"):
                expected_run_id = leaf[len(enc_model) + 1:]
        proc_root = Path("/proc")
        if not proc_root.exists():
            return False
        for cmdline_path in proc_root.glob("[0-9]*/cmdline"):
            try:
                raw = cmdline_path.read_bytes()
            except OSError:
                continue
            if not raw:
                continue
            argv = [part.decode(errors="replace") for part in raw.split(b"\0") if part]
            if not any(part.endswith("runner.py") for part in argv):
                continue
            if cls._option_value(argv, "--model") != model_id:
                continue
            if cls._option_value(argv, "--adapter") != adapter_id:
                continue
            if cls._option_value(argv, "--suite") != suite_id:
                continue
            # Dimensional match: if we know the thinking level, the live
            # process must be at that level too.
            if thinking is not None:
                proc_thinking = cls._option_value(argv, "--thinking") or "default"
                if proc_thinking != thinking:
                    continue
            # Dimensional match: if we derived a run-id from the run_path,
            # the live process must have the same --run-id.
            if expected_run_id:
                proc_run_id = cls._option_value(argv, "--run-id")
                if proc_run_id != expected_run_id:
                    continue
            return True
        return False

    @staticmethod
    def _file_signature(path: Path) -> tuple[bool, int, int]:
        try:
            stat = path.stat()
            return True, stat.st_mtime_ns, stat.st_size
        except OSError:
            return False, 0, 0

    @classmethod
    def _visible_trial_entries(
        cls,
        results_dir: Path,
        *,
        include_smoke: bool,
        filters: tuple[str, ...],
        excludes: tuple[str, ...],
    ) -> list[dict]:
        entries = []
        for trial_dir in cls._iter_started_trial_dirs(results_dir):
            parts = cls._trial_parts(results_dir, trial_dir)
            if parts is None:
                search_text = str(trial_dir)
                if filters and not _matches_any(filters, search_text):
                    continue
                if excludes and _matches_any(excludes, search_text):
                    continue
            elif not cls._trial_visible(
                parts,
                include_smoke=include_smoke,
                filters=filters,
                excludes=excludes,
            ):
                continue
            entries.append({"trial_dir": trial_dir, "parts": parts})
        return entries

    @classmethod
    def _cache_key(
        cls,
        results_dir: Path,
        entries: list[dict],
        *,
        include_smoke: bool,
        filters: tuple[str, ...],
        excludes: tuple[str, ...],
        thinking_filter: str | None = None,
        provider_filter: str | None = None,
    ) -> str:
        signature = []
        heartbeat_paths = set()
        include_liveness_time_bucket = False
        for entry in entries:
            trial_dir = entry["trial_dir"]
            manifest_signature = cls._file_signature(trial_dir / "manifest.json")
            verdict_signature = cls._file_signature(trial_dir / "verdict.json")
            try:
                rel_trial = trial_dir.relative_to(results_dir).as_posix()
            except ValueError:
                rel_trial = str(trial_dir)
            signature.append({
                "trial": rel_trial,
                "manifest": manifest_signature,
                "verdict": verdict_signature,
            })
            if not manifest_signature[0] or not verdict_signature[0]:
                include_liveness_time_bucket = True
            parts = entry.get("parts")
            if parts is not None:
                heartbeat_paths.add(parts["suite_dir"] / RUN_HEARTBEAT_FILE)

        heartbeat_signature = []
        for heartbeat_path in sorted(heartbeat_paths):
            try:
                rel_path = heartbeat_path.relative_to(results_dir).as_posix()
            except ValueError:
                rel_path = str(heartbeat_path)
            file_sig = cls._file_signature(heartbeat_path)
            heartbeat_signature.append({
                "path": rel_path,
                "file": file_sig,
            })
            if file_sig[0]:
                try:
                    heartbeat = json.loads(heartbeat_path.read_text())
                    if heartbeat.get("state") == "running":
                        include_liveness_time_bucket = True
                except (OSError, json.JSONDecodeError):
                    include_liveness_time_bucket = True

        payload = {
            "version": SCORE_CACHE_VERSION,
            "results_dir": str(results_dir.resolve()),
            "include_smoke": include_smoke,
            "filters": list(filters),
            "excludes": list(excludes),
            "thinking_filter": thinking_filter,
            "provider_filter": provider_filter,
            "trials": signature,
            "heartbeats": heartbeat_signature,
            "models_config": cls._file_signature(DEFAULT_MODELS_CONFIG_PATH),
            "pricing_profile": DEFAULT_PRICING_PROFILE,
            "liveness_bucket": (
                int(time.time() // RUN_HEARTBEAT_STALE_SECONDS)
                if include_liveness_time_bucket
                else None
            ),
        }
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        return hashlib.sha256(encoded).hexdigest()

    @staticmethod
    def _cache_enabled() -> bool:
        disabled = os.environ.get("CODING_EVAL_VIEW_NO_CACHE", "").lower()
        return DEFAULT_USE_CACHE and disabled not in {"1", "true", "yes"}

    @staticmethod
    def _read_score_cache() -> dict:
        try:
            data = json.loads(DEFAULT_CACHE_PATH.read_text())
        except (OSError, json.JSONDecodeError):
            return {"version": SCORE_CACHE_VERSION, "entries": {}}
        if not isinstance(data, dict) or data.get("version") != SCORE_CACHE_VERSION:
            return {"version": SCORE_CACHE_VERSION, "entries": {}}
        entries = data.get("entries")
        if not isinstance(entries, dict):
            return {"version": SCORE_CACHE_VERSION, "entries": {}}
        return {"version": SCORE_CACHE_VERSION, "entries": entries}

    @staticmethod
    def _write_score_cache(cache: dict) -> None:
        try:
            DEFAULT_CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
            temp_path = DEFAULT_CACHE_PATH.with_suffix(DEFAULT_CACHE_PATH.suffix + ".tmp")
            temp_path.write_text(json.dumps(cache, separators=(",", ":")) + "\n")
            temp_path.replace(DEFAULT_CACHE_PATH)
        except OSError:
            return

    def _get_cached_scores(self, cache_key: str) -> list[dict] | None:
        if not self._cache_enabled():
            return None
        cache = self._read_score_cache()
        entry = cache.get("entries", {}).get(cache_key)
        if not isinstance(entry, dict):
            return None
        scores = entry.get("scores")
        warnings = entry.get("warnings", [])
        if not isinstance(scores, list) or not isinstance(warnings, list):
            return None
        self._warnings = warnings
        return scores

    def _store_cached_scores(self, cache_key: str, scores: list[dict]) -> None:
        if not self._cache_enabled():
            return
        cache = self._read_score_cache()
        entries = cache.setdefault("entries", {})
        if not isinstance(entries, dict):
            entries = {}
            cache["entries"] = entries
        entries[cache_key] = {
            "created_at": time.time(),
            "scores": scores,
            "warnings": self.get_warnings(),
        }
        if len(entries) > 64:
            oldest = sorted(
                entries.items(),
                key=lambda item: item[1].get("created_at", 0)
                if isinstance(item[1], dict)
                else 0,
            )
            for key, _entry in oldest[: len(entries) - 64]:
                entries.pop(key, None)
        self._write_score_cache(cache)

    def do_GET(self):
        """Handle GET requests."""
        parsed = urlparse(self.path)

        if parsed.path == "/" or parsed.path == "/index.html":
            self.serve_html(self.generate_html())
        elif parsed.path == "/api/scores":
            self.serve_json(self.get_scores())
        elif parsed.path == "/api/warnings":
            self.get_scores()
            self.serve_json(self.get_warnings())
        elif parsed.path == "/api/tasks":
            params = parse_qs(parsed.query)
            model = params.get("model", [""])[0]
            adapter = params.get("adapter", [""])[0]
            suite = params.get("suite", [""])[0]
            self.serve_json(self.get_task_details(model, adapter, suite))
        else:
            self.send_error(404)

    def serve_html(self, html: str):
        """Serve HTML response."""
        self.send_response(200)
        self.send_header("Content-Type", "text/html")
        self.end_headers()
        self.wfile.write(html.encode())

    def serve_json(self, data: dict):
        """Serve JSON response."""
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(data, indent=2).encode())

    def generate_html(self) -> str:
        """Generate the HTML page."""
        scores = self.get_scores()
        warnings = self.get_warnings()
        rows = ""
        warning_rows = ""

        for warning in warnings:
            warning_rows += (
                '<li><code>'
                + html.escape(str(warning.get("code", "warning")))
                + "</code>: "
                + html.escape(str(warning.get("message", warning)))
                + "</li>"
            )

        warnings_html = (
            f'<section class="warnings"><h2>Warnings</h2><ul>{warning_rows}</ul></section>'
            if warning_rows
            else ""
        )

        for score in scores:
            model = html.escape(str(score["model"]))
            adapter = html.escape(str(score["adapter"]))
            suite = html.escape(str(score["suite"]))
            details_href = "/?" + urlencode(
                {
                    "model": str(score["model"]),
                    "adapter": str(score["adapter"]),
                    "suite": str(score["suite"]),
                }
            )
            display_score, score_text = _score_display(score)
            score_class = _score_class(display_score)
            rows += f"""
            <tr>
                <td>{model}</td>
                <td>{adapter}</td>
                <td>{suite}</td>
                <td class="{score_class}">{html.escape(score_text)}</td>
                <td>{score['passed_tasks']}/{score['total_tasks']}</td>
                <td>{score['total_tasks']}</td>
                <td>{html.escape(_format_percent(score.get("inference_percent")))}</td>
                <td>{html.escape(_format_percent(score.get("tool_percent")))}</td>
                <td>{html.escape(_format_turns(score.get("mean_tool_calls")))}</td>
                <td>{html.escape(_format_turns(score.get("mean_search_calls")))}</td>
                <td>{html.escape(_format_cost(score.get("estimated_cost_usd")))}</td>
                <td>{html.escape(_format_cost(score.get("cost_per_completed_task_usd")))}</td>
                <td>{html.escape(_format_rate(score.get("passed_tasks_per_usd")))}</td>
                <td><a href="{html.escape(details_href, quote=True)}">Details</a></td>
            </tr>
            """

        return f"""<!DOCTYPE html>
<html>
<head>
    <title>Coding Eval Score Viewer</title>
    <style>
        body {{ font-family: Arial, sans-serif; margin: 20px; }}
        table {{ border-collapse: collapse; width: 100%; }}
        th, td {{ border: 1px solid #ddd; padding: 8px; text-align: left; }}
        th {{ background-color: #f2f2f2; }}
        tr:nth-child(even) {{ background-color: #f9f9f9; }}
        .passed {{ color: green; }}
        .failed {{ color: red; }}
        .score-good {{ color: #087f23; font-weight: 700; }}
        .score-mid {{ color: #9a6700; font-weight: 700; }}
        .score-low {{ color: #b42318; font-weight: 700; }}
        .note {{ color: #666; margin: 0 0 16px 0; }}
        .warnings {{ background: #fff7ed; border: 1px solid #fed7aa; padding: 12px; margin: 0 0 16px 0; }}
        .warnings h2 {{ margin: 0 0 8px 0; font-size: 16px; color: #9a3412; }}
        .warnings ul {{ margin: 0; padding-left: 20px; }}
    </style>
</head>
<body>
    <h1>Coding Eval Score Viewer</h1>
    <p class="note">Score is task-level pass@k majority. Confidence intervals are available from <code>/api/scores</code> and <code>./view --show-ci</code>.</p>
    {warnings_html}
    <table>
        <thead>
            <tr>
                <th>Model</th>
                <th>Adapter</th>
                <th>Suite</th>
                <th>Score</th>
                <th>Passed</th>
                <th>Tasks</th>
                <th>LLM%</th>
                <th>Tool%</th>
                <th>Calls</th>
                <th>Search</th>
                <th>Cost</th>
                <th>$/Task</th>
                <th>Pass/$</th>
                <th>Details</th>
            </tr>
        </thead>
        <tbody>
            {rows}
        </tbody>
    </table>
</body>
</html>"""

    @staticmethod
    def _expected_task_count(suite_id: str, observed: int) -> int:
        """Return known suite size for default project results, else observed."""
        try:
            if not RESULTS_DIR.resolve().is_relative_to((PROJECT_ROOT / "results").resolve()):
                return observed
            from harness.suites import load_suite

            suite = load_suite(suite_id)
            task_ids = suite.get_task_ids(vendor_dir=PROJECT_ROOT / "vendor")
            return max(observed, len(task_ids)) if task_ids else observed
        except Exception:
            return observed

    @staticmethod
    def _numeric_value(data: dict, *keys: str) -> float | None:
        for key in keys:
            value = data.get(key)
            if value is None or isinstance(value, bool):
                continue
            try:
                return float(value)
            except (TypeError, ValueError):
                continue
        return None

    @classmethod
    def _token_usage_from_manifest(cls, manifest: dict) -> dict:
        usage = manifest.get("token_usage") or manifest.get("usage") or {}
        if not isinstance(usage, dict):
            usage = {}

        prompt_tokens = cls._numeric_value(
            usage,
            "prompt_tokens",
            "input_tokens",
            "tokens_in",
            "prompt",
        )
        completion_tokens = cls._numeric_value(
            usage,
            "completion_tokens",
            "output_tokens",
            "tokens_out",
            "completion",
        )
        total_tokens = cls._numeric_value(
            usage,
            "total_tokens",
            "tokens_total",
            "total",
        )
        cached_tokens = cls._numeric_value(
            usage,
            "cached_tokens",
            "cache_read_tokens",
            "cacheRead",
            "cache_read",
        )
        cache_creation_tokens = cls._numeric_value(
            usage,
            "cache_creation_tokens",
            "cache_write_tokens",
            "cacheWrite",
            "cache_write",
        )
        reasoning_tokens = cls._numeric_value(
            usage,
            "reasoning_tokens",
            "reasoning",
        )
        response_count = cls._numeric_value(
            usage,
            "response_count",
            "turn_count",
            "turns",
        )

        prompt = int(prompt_tokens or 0)
        completion = int(completion_tokens or 0)
        cached = int(cached_tokens or 0)
        cache_creation = int(cache_creation_tokens or 0)
        reasoning = int(reasoning_tokens or 0)
        total = int(total_tokens or 0)
        if not total and (prompt or completion or cached or cache_creation or reasoning):
            total = prompt + completion + cached + cache_creation + reasoning

        return {
            "prompt_tokens": prompt,
            "completion_tokens": completion,
            "cached_tokens": cached,
            "cache_creation_tokens": cache_creation,
            "reasoning_tokens": reasoning,
            "total_tokens": total,
            # Each usage-bearing assistant response in a pi trace is one
            # model turn, including responses that end in tool calls.
            "response_count": int(response_count or 0),
        }

    @staticmethod
    def _manifest_model_id(manifest: dict) -> str | None:
        model = manifest.get("model", {})
        if isinstance(model, dict) and isinstance(model.get("id"), str):
            return model["id"]
        return None

    @classmethod
    def _pricing_from_pricing_dict(
        cls,
        pricing: dict,
        *,
        prompt_tokens: int | None = None,
        cached_tokens: int = 0,
        cache_creation_tokens: int = 0,
    ) -> tuple[float | None, float | None, float | None, float | None]:
        input_per_million = cls._numeric_value(
            pricing,
            "input",
            "prompt",
            "input_per_million",
            "prompt_per_million",
            "input_per_1m",
            "prompt_per_1m",
        )
        output_per_million = cls._numeric_value(
            pricing,
            "output",
            "completion",
            "output_per_million",
            "completion_per_million",
            "output_per_1m",
            "completion_per_1m",
        )
        cache_read_per_million = cls._numeric_value(
            pricing,
            "cacheRead",
            "cache_read",
            "cached",
            "cache_read_per_million",
            "cached_per_million",
            "cache_read_per_1m",
            "cached_per_1m",
        )
        cache_write_per_million = cls._numeric_value(
            pricing,
            "cacheWrite",
            "cache_write",
            "cache_creation",
            "cache_write_per_million",
            "cache_creation_per_million",
            "cache_write_per_1m",
            "cache_creation_per_1m",
        )
        threshold = cls._numeric_value(
            pricing,
            "longContextInputThreshold",
            "long_context_input_threshold",
            "long_context_threshold",
        )
        if prompt_tokens is not None and threshold is not None:
            input_token_count = (
                int(prompt_tokens or 0)
                + int(cached_tokens or 0)
                + int(cache_creation_tokens or 0)
            )
            if input_token_count > threshold:
                def first_present(*values):
                    for value in values:
                        if value is not None:
                            return value
                    return None

                long_context = pricing.get("longContext") or pricing.get("long_context")
                if not isinstance(long_context, dict):
                    long_context = {}
                input_per_million = first_present(
                    cls._numeric_value(
                        pricing,
                        "longContextInput",
                        "long_context_input",
                    ),
                    cls._numeric_value(long_context, "input"),
                    input_per_million,
                )
                output_per_million = first_present(
                    cls._numeric_value(
                        pricing,
                        "longContextOutput",
                        "long_context_output",
                    ),
                    cls._numeric_value(long_context, "output"),
                    output_per_million,
                )
                cache_read_per_million = first_present(
                    cls._numeric_value(
                        pricing,
                        "longContextCacheRead",
                        "long_context_cache_read",
                    ),
                    cls._numeric_value(long_context, "cacheRead", "cache_read"),
                    cache_read_per_million,
                )
                cache_write_per_million = first_present(
                    cls._numeric_value(
                        pricing,
                        "longContextCacheWrite",
                        "long_context_cache_write",
                    ),
                    cls._numeric_value(long_context, "cacheWrite", "cache_write"),
                    cache_write_per_million,
                )
        return (
            input_per_million,
            output_per_million,
            cache_read_per_million,
            cache_write_per_million,
        )

    @classmethod
    def _pricing_from_repo_config(
        cls,
        manifest: dict,
        *,
        prompt_tokens: int | None = None,
        cached_tokens: int = 0,
        cache_creation_tokens: int = 0,
    ) -> tuple[float | None, float | None, float | None, float | None]:
        model_id = cls._manifest_model_id(manifest)
        if not model_id:
            return None, None, None, None
        try:
            from harness.telemetry import load_model_metadata

            metadata = load_model_metadata(
                model_id,
                models_json_path=Path("/nonexistent-coding-eval-models.json"),
                models_config_path=DEFAULT_MODELS_CONFIG_PATH,
                pricing_profile=DEFAULT_PRICING_PROFILE,
                strict_config_id=True,
            )
        except Exception:
            return None, None, None, None
        pricing = metadata.get("cost")
        if not isinstance(pricing, dict):
            return None, None, None, None
        return cls._pricing_from_pricing_dict(
            pricing,
            prompt_tokens=prompt_tokens,
            cached_tokens=cached_tokens,
            cache_creation_tokens=cache_creation_tokens,
        )

    @classmethod
    def _pricing_from_manifest(
        cls,
        manifest: dict,
        *,
        prompt_tokens: int | None = None,
        cached_tokens: int = 0,
        cache_creation_tokens: int = 0,
    ) -> tuple[float | None, float | None, float | None, float | None]:
        repo_pricing = cls._pricing_from_repo_config(
            manifest,
            prompt_tokens=prompt_tokens,
            cached_tokens=cached_tokens,
            cache_creation_tokens=cache_creation_tokens,
        )
        if any(value is not None for value in repo_pricing):
            return repo_pricing

        model = manifest.get("model", {})
        if not isinstance(model, dict):
            model = {}

        pricing = (
            model.get("cost")
            or model.get("pricing")
            or manifest.get("cost")
            or manifest.get("pricing")
            or {}
        )
        if not isinstance(pricing, dict):
            return None, None, None, None
        return cls._pricing_from_pricing_dict(
            pricing,
            prompt_tokens=prompt_tokens,
            cached_tokens=cached_tokens,
            cache_creation_tokens=cache_creation_tokens,
        )

    @classmethod
    def _estimate_cost_usd(
        cls,
        manifest: dict,
        prompt_tokens: int,
        completion_tokens: int,
        cached_tokens: int = 0,
        cache_creation_tokens: int = 0,
        reasoning_tokens: int = 0,
    ) -> float | None:
        has_tokens = any(
            value > 0
            for value in (
                prompt_tokens,
                completion_tokens,
                cached_tokens,
                cache_creation_tokens,
                reasoning_tokens,
            )
        )
        usage = manifest.get("token_usage") or manifest.get("usage") or {}
        direct_cost = None
        if isinstance(usage, dict):
            direct_cost = cls._numeric_value(
                usage,
                "cost_usd",
                "total_cost_usd",
                "cost",
                "total_cost",
            )

        manifest_direct_cost = cls._numeric_value(
            manifest,
            "cost_usd",
            "total_cost_usd",
            "estimated_cost_usd",
        )
        if direct_cost is None:
            direct_cost = manifest_direct_cost

        (
            input_per_million,
            output_per_million,
            cache_read_per_million,
            cache_write_per_million,
        ) = cls._pricing_from_manifest(
            manifest,
            prompt_tokens=prompt_tokens,
            cached_tokens=cached_tokens,
            cache_creation_tokens=cache_creation_tokens,
        )
        if not has_tokens:
            if direct_cost is not None:
                if direct_cost > 0:
                    return direct_cost
                usage_status = ""
                if isinstance(usage, dict):
                    usage_status = str(usage.get("status", "")).lower()
                if direct_cost == 0 and usage_status == "observed":
                    return 0.0
            return None
        if input_per_million is None and output_per_million is None:
            return direct_cost if direct_cost is not None and direct_cost > 0 else None
        if prompt_tokens and input_per_million is None:
            return direct_cost if direct_cost is not None and direct_cost > 0 else None
        billed_output_tokens = completion_tokens + reasoning_tokens
        if billed_output_tokens and output_per_million is None:
            return direct_cost if direct_cost is not None and direct_cost > 0 else None
        if cached_tokens and cache_read_per_million is None:
            return direct_cost if direct_cost is not None and direct_cost > 0 else None
        if cache_creation_tokens and cache_write_per_million is None:
            return direct_cost if direct_cost is not None and direct_cost > 0 else None

        return (
            (prompt_tokens / 1_000_000) * (input_per_million or 0)
            + (billed_output_tokens / 1_000_000) * (output_per_million or 0)
            + (cached_tokens / 1_000_000) * (cache_read_per_million or 0)
            + (cache_creation_tokens / 1_000_000) * (cache_write_per_million or 0)
        )

    def get_scores(
        self,
        *,
        include_smoke: bool | None = None,
        filters: list[str] | tuple[str, ...] | None = None,
        excludes: list[str] | tuple[str, ...] | None = None,
        thinking_filter: str | None = None,
        provider_filter: str | None = None,
        sort_by: str | list[str] | tuple[str, ...] | None = None,
    ) -> list:
        """Get aggregated scores from results directory."""
        include_smoke = DEFAULT_INCLUDE_SMOKE if include_smoke is None else include_smoke
        filters = tuple(DEFAULT_FILTERS if filters is None else filters)
        excludes = tuple(DEFAULT_EXCLUDES if excludes is None else excludes)
        sort_by = DEFAULT_SORT_BY if sort_by is None else sort_by

        grouped_trials = {}
        grouped_continuous_scores = {}
        grouped_score_metadata = {}
        grouped_times = {}
        grouped_turns = {}
        grouped_behavior = {}
        grouped_tokens = {}
        grouped_pricing = {}
        grouped_cost_coverage = {}
        started_tasks = {}
        suite_dirs_by_key = {}
        run_paths_by_key = {}
        self._reset_warnings()
        trial_entries = self._visible_trial_entries(
            RESULTS_DIR,
            include_smoke=include_smoke,
            filters=filters,
            excludes=excludes,
        )
        cache_key = self._cache_key(
            RESULTS_DIR,
            trial_entries,
            include_smoke=include_smoke,
            filters=filters,
            excludes=excludes,
            thinking_filter=thinking_filter,
            provider_filter=provider_filter,
        )
        cached_scores = self._get_cached_scores(cache_key)
        if cached_scores is not None:
            return sort_scores(cached_scores, sort_by)

        for entry in trial_entries:
            trial_dir = entry["trial_dir"]
            parts = entry["parts"]
            if parts is None:
                self._warn(
                    "malformed_result_path",
                    f"malformed result path skipped: unable to parse {trial_dir}",
                    trial_dir,
                )
                continue
            if not self._trial_parts_valid(parts):
                continue

            trial = self._load_trial(trial_dir)
            if trial is not None:
                manifest_model = trial["manifest"].get("model", {}).get("id")
                if manifest_model and manifest_model != parts["model_id"]:
                    self._warn(
                        "malformed_result_path",
                        (
                            "malformed result path skipped: manifest model "
                            f"{manifest_model!r} does not match path model "
                            f"{parts['model_id']!r} in {trial_dir}"
                        ),
                        trial_dir,
                    )
                    continue

            # Multi-dimensional grouping: the same (model, adapter, suite)
            # can be run at multiple effort levels (thinking) and served by
            # multiple providers (aiand quant vs local nvfp4 vs hosted).
            # These MUST be part of the key or runs silently merge and
            # corrupt each other's scores.
            # When trial is None (pending/incomplete), we can't read the manifest
            # so fall back to defaults — the trial won't be counted in scoring
            # but the task will still be tracked in started_tasks.
            if trial is not None:
                manifest_model_block = trial["manifest"].get("model", {})
                manifest_sampling_block = trial["manifest"].get("sampling", {})
                thinking = manifest_sampling_block.get("thinking") or "default"
                provider = (
                    manifest_model_block.get("provider")
                    or parts["model_id"].split("/")[0]
                )
            else:
                thinking = "default"
                provider = parts["model_id"].split("/")[0]
            key = (
                parts["model_id"],
                parts["adapter_id"],
                parts["suite_id"],
                thinking,
                provider,
            )
            suite_dirs_by_key.setdefault(key, set()).add(parts["suite_dir"])
            run_paths_by_key.setdefault(key, set()).add(parts.get("run_path", ""))
            started_tasks.setdefault(key, set()).add(parts["task_id"])
            if trial is None:
                continue
            verdict = trial["verdict"]
            grouped_trials.setdefault(key, {}).setdefault(parts["task_id"], []).append(
                verdict.get("passed", False)
            )
            suite_metadata = trial["manifest"].get("suite", {})
            score_type = verdict.get("score_type") or suite_metadata.get("score_type")
            headline_metric = verdict.get("headline_metric") or suite_metadata.get(
                "headline_metric"
            )
            continuous_score = verdict.get("score")
            if (
                score_type == "continuous_non_coding"
                and continuous_score is None
                and verdict.get("failure_class") == "invalid_output"
                and not verdict.get("verifier_failed")
                and not verdict.get("adapter_failed")
            ):
                # Older diagnostic verdicts omitted a numeric score for malformed
                # agent answers. They are capability misses, not missing data.
                continuous_score = 0.0
            if (
                score_type == "continuous_non_coding"
                and isinstance(continuous_score, (int, float))
                and not isinstance(continuous_score, bool)
                and isinstance(headline_metric, str)
                and headline_metric
            ):
                metadata = grouped_score_metadata.setdefault(
                    key,
                    {
                        "score_type": score_type,
                        "headline_metric": headline_metric,
                    },
                )
                if metadata == {
                    "score_type": score_type,
                    "headline_metric": headline_metric,
                }:
                    grouped_continuous_scores.setdefault(key, {}).setdefault(
                        parts["task_id"], []
                    ).append(float(continuous_score))
            seconds = trial["manifest"].get("timing", {}).get("wall_clock_seconds")
            if isinstance(seconds, (int, float)):
                grouped_times.setdefault(key, {}).setdefault(parts["task_id"], []).append(
                    float(seconds)
                )
            token_usage = self._token_usage_from_manifest(trial["manifest"])
            if token_usage["response_count"] > 0:
                grouped_turns.setdefault(key, []).append(token_usage["response_count"])

            behavior = trial["manifest"].get("behavior")
            if isinstance(behavior, dict) and behavior.get("status") in {
                "observed",
                "partial",
                "counts_only",
            }:
                behavior_totals = grouped_behavior.setdefault(
                    key,
                    {
                        "trials": 0,
                        "timing_trials": 0,
                        "partial_trials": 0,
                        "agent_seconds": 0.0,
                        "inference_seconds": 0.0,
                        "tool_seconds": 0.0,
                        "other_seconds": 0.0,
                        "tool_calls": 0,
                        "tool_errors": 0,
                        "incomplete_tool_calls": 0,
                        "search_calls": 0,
                        "search_seconds": 0.0,
                        "external_lookup_calls": 0,
                        "external_lookup_seconds": 0.0,
                        "long_tool_calls": 0,
                        "tool_counts": {},
                        "category_counts": {},
                        "tool_seconds_by_name": {},
                        "category_seconds": {},
                        "longest_tools": [],
                    },
                )
                behavior_totals["trials"] += 1
                agent_value = behavior.get("agent_seconds")
                if (
                    isinstance(agent_value, (int, float))
                    and not isinstance(agent_value, bool)
                    and agent_value > 0
                ):
                    behavior_totals["timing_trials"] += 1
                if behavior.get("status") == "partial":
                    behavior_totals["partial_trials"] += 1
                for field in (
                    "agent_seconds",
                    "inference_seconds",
                    "tool_seconds",
                    "other_seconds",
                    "search_seconds",
                    "external_lookup_seconds",
                ):
                    value = behavior.get(field)
                    if isinstance(value, (int, float)) and not isinstance(value, bool):
                        behavior_totals[field] += float(value)
                for field in (
                    "tool_calls",
                    "tool_errors",
                    "incomplete_tool_calls",
                    "search_calls",
                    "external_lookup_calls",
                    "long_tool_calls",
                ):
                    value = behavior.get(field)
                    if isinstance(value, (int, float)) and not isinstance(value, bool):
                        behavior_totals[field] += int(value)
                for field in (
                    "tool_counts",
                    "category_counts",
                    "tool_seconds_by_name",
                    "category_seconds",
                ):
                    values = behavior.get(field)
                    if not isinstance(values, dict):
                        continue
                    target = behavior_totals[field]
                    for name, value in values.items():
                        if isinstance(value, (int, float)) and not isinstance(value, bool):
                            target[name] = target.get(name, 0) + value
                longest = behavior.get("longest_tools")
                if isinstance(longest, list):
                    for item in longest:
                        if isinstance(item, dict):
                            behavior_totals["longest_tools"].append(
                                {
                                    **item,
                                    "task_id": parts["task_id"],
                                    "trial": trial_dir.name,
                                }
                            )
            pricing = self._pricing_from_manifest(
                trial["manifest"],
                prompt_tokens=token_usage["prompt_tokens"],
                cached_tokens=token_usage["cached_tokens"],
                cache_creation_tokens=token_usage["cache_creation_tokens"],
            )
            if any(value is not None for value in pricing):
                existing_pricing = grouped_pricing.get(key)
                if existing_pricing is None:
                    grouped_pricing[key] = pricing
                else:
                    grouped_pricing[key] = tuple(
                        old if old is not None else new
                        for old, new in zip(existing_pricing, pricing)
                    )
            coverage = grouped_cost_coverage.setdefault(
                key,
                {"completed_trials": 0, "costed_trials": 0},
            )
            coverage["completed_trials"] += 1
            token_totals = grouped_tokens.setdefault(
                key,
                {
                    "prompt_tokens": 0,
                    "completion_tokens": 0,
                    "cached_tokens": 0,
                    "cache_creation_tokens": 0,
                    "reasoning_tokens": 0,
                    "total_tokens": 0,
                    "estimated_cost_usd": 0.0,
                    "has_estimated_cost": False,
                },
            )
            token_totals["prompt_tokens"] += token_usage["prompt_tokens"]
            token_totals["completion_tokens"] += token_usage["completion_tokens"]
            token_totals["cached_tokens"] += token_usage["cached_tokens"]
            token_totals["cache_creation_tokens"] += token_usage["cache_creation_tokens"]
            token_totals["reasoning_tokens"] += token_usage["reasoning_tokens"]
            token_totals["total_tokens"] += token_usage["total_tokens"]
            estimated_cost = self._estimate_cost_usd(
                trial["manifest"],
                token_usage["prompt_tokens"],
                token_usage["completion_tokens"],
                token_usage["cached_tokens"],
                token_usage["cache_creation_tokens"],
                token_usage["reasoning_tokens"],
            )
            if estimated_cost is not None:
                token_totals["estimated_cost_usd"] += estimated_cost
                token_totals["has_estimated_cost"] = True
                coverage["costed_trials"] += 1

        scores = []
        for (model_id, adapter_id, suite_id, thinking, provider), task_trials in sorted(
            grouped_trials.items()
        ):
            key5 = (model_id, adapter_id, suite_id, thinking, provider)
            # Count tasks that passed (majority of trials)
            total_tasks = len(task_trials)
            passed_tasks = sum(
                1 for trials in task_trials.values()
                if sum(1 for t in trials if t) > len(trials) / 2
            )
            pass_rate = (passed_tasks / total_tasks) * 100 if total_tasks > 0 else 0
            score_metadata = grouped_score_metadata.get(key5)
            continuous_task_scores = grouped_continuous_scores.get(key5, {})
            if score_metadata and continuous_task_scores:
                task_macro_scores = [
                    statistics.fmean(trials)
                    for trials in continuous_task_scores.values()
                    if trials
                ]
                headline_score = (
                    statistics.fmean(task_macro_scores)
                    if task_macro_scores
                    else None
                )
                display_score = (
                    headline_score * 100 if headline_score is not None else 0.0
                )
                score_type = score_metadata["score_type"]
                headline_metric = score_metadata["headline_metric"]
                score_method = f"task-macro mean {headline_metric}"
                scored_tasks = len(task_macro_scores)
            else:
                headline_score = None
                display_score = pass_rate
                score_type = "binary_resolution"
                headline_metric = "pass_rate"
                score_method = "pass@k majority"
                scored_tasks = 0
            task_times = [
                sum(trial_times)
                for trial_times in grouped_times.get(
                    key5, {}
                ).values()
                if trial_times
            ]
            total_wall_clock_seconds = sum(task_times)
            mean_wall_clock_seconds = (
                total_wall_clock_seconds / len(task_times) if task_times else 0
            )
            median_wall_clock_seconds = statistics.median(task_times) if task_times else 0
            turn_counts = grouped_turns.get(key5, [])
            mean_turns = statistics.fmean(turn_counts) if turn_counts else None
            behavior_totals = grouped_behavior.get(key5)
            if behavior_totals:
                behavior_counted_trials = behavior_totals["trials"]
                agent_seconds = behavior_totals["agent_seconds"]
                inference_percent = (
                    behavior_totals["inference_seconds"] / agent_seconds * 100
                    if agent_seconds > 0
                    else None
                )
                tool_percent = (
                    behavior_totals["tool_seconds"] / agent_seconds * 100
                    if agent_seconds > 0
                    else None
                )
                other_percent = (
                    behavior_totals["other_seconds"] / agent_seconds * 100
                    if agent_seconds > 0
                    else None
                )
                mean_tool_calls = (
                    behavior_totals["tool_calls"] / behavior_counted_trials
                )
                mean_search_calls = (
                    behavior_totals["search_calls"] / behavior_counted_trials
                )
                slowest_tools = sorted(
                    behavior_totals["longest_tools"],
                    key=lambda item: float(item.get("seconds", 0)),
                    reverse=True,
                )[:10]
            else:
                behavior_counted_trials = 0
                inference_percent = tool_percent = other_percent = None
                mean_tool_calls = mean_search_calls = None
                slowest_tools = []
            started_count = len(
                started_tasks.get(key5, set())
                | set(task_trials.keys())
            )
            expected_tasks = self._expected_task_count(suite_id, total_tasks)
            remaining_tasks = max(0, expected_tasks - total_tasks)
            incomplete_started_tasks = max(0, started_count - total_tasks)
            key = key5
            live_runner = self._cell_has_live_heartbeat(
                suite_dirs_by_key.get(key, set())
            ) or any(
                self._has_live_runner_process(
                    model_id,
                    adapter_id,
                    suite_id,
                    run_path,
                    thinking=thinking,
                )
                for run_path in run_paths_by_key.get(key, {""})
            )
            if remaining_tasks == 0 and not incomplete_started_tasks:
                status = "complete"
            elif live_runner:
                status = "running"
            elif incomplete_started_tasks:
                status = "stalled"
            else:
                status = "partial"
            estimated_remaining_seconds = (
                mean_wall_clock_seconds * remaining_tasks
                if remaining_tasks and mean_wall_clock_seconds
                else 0
            )
            token_totals = grouped_tokens.get(
                key5,
                {
                    "prompt_tokens": 0,
                    "completion_tokens": 0,
                    "cached_tokens": 0,
                    "cache_creation_tokens": 0,
                    "reasoning_tokens": 0,
                    "total_tokens": 0,
                    "estimated_cost_usd": 0.0,
                    "has_estimated_cost": False,
                },
            )
            estimated_cost_usd = (
                token_totals["estimated_cost_usd"]
                if token_totals["has_estimated_cost"]
                else None
            )
            coverage = grouped_cost_coverage.get(
                key5,
                {"completed_trials": 0, "costed_trials": 0},
            )
            completed_trials = coverage["completed_trials"]
            costed_trials = coverage["costed_trials"]
            has_complete_cost = (
                estimated_cost_usd is not None
                and completed_trials > 0
                and costed_trials == completed_trials
            )
            has_partial_cost = (
                estimated_cost_usd is not None
                and 0 < costed_trials < completed_trials
            )
            cost_per_completed_task_usd = (
                estimated_cost_usd / total_tasks
                if has_complete_cost and total_tasks
                else None
            )
            passed_tasks_per_usd = (
                passed_tasks / estimated_cost_usd
                if has_complete_cost and estimated_cost_usd and estimated_cost_usd > 0
                else None
            )
            (
                input_cost_per_million_usd,
                output_cost_per_million_usd,
                cache_read_cost_per_million_usd,
                cache_write_cost_per_million_usd,
            ) = grouped_pricing.get(
                key5,
                (None, None, None, None),
            )

            # Calculate 95% CI (Wilson score interval approximation) at task level
            if total_tasks > 0:
                p = pass_rate / 100
                n = total_tasks
                z = 1.96  # 95% CI
                denominator = 1 + z**2 / n
                center = (p + z**2 / (2 * n)) / denominator
                margin = z * ((p * (1 - p) + z**2 / (4 * n)) / n) ** 0.5 / denominator
                ci_lower = max(0, (center - margin) * 100)
                ci_upper = min(100, (center + margin) * 100)
            else:
                ci_lower = ci_upper = 0

            scores.append({
                "model": model_id,
                "adapter": adapter_id,
                "suite": suite_id,
                # Multi-dimensional axes: the same (model, adapter, suite) can
                # be served at multiple effort levels and by multiple providers.
                # These let the viewer distinguish rows that would otherwise merge.
                "thinking": thinking,
                "provider": provider,
                "score": display_score,
                "score_type": score_type,
                "headline_metric": headline_metric,
                "headline_score": headline_score,
                "scored_tasks": scored_tasks,
                "score_missing_tasks": (
                    total_tasks - scored_tasks if headline_score is not None else 0
                ),
                "pass_rate": pass_rate,
                "ci_lower": ci_lower,
                "ci_upper": ci_upper,
                "total_tasks": total_tasks,
                "completed_tasks": total_tasks,
                "expected_tasks": expected_tasks,
                "remaining_tasks": remaining_tasks,
                "started_tasks": started_count,
                "incomplete_started_tasks": incomplete_started_tasks,
                "passed_tasks": passed_tasks,
                "status": status,
                "total_wall_clock_seconds": total_wall_clock_seconds,
                "mean_wall_clock_seconds": mean_wall_clock_seconds,
                "median_wall_clock_seconds": median_wall_clock_seconds,
                "estimated_remaining_seconds": estimated_remaining_seconds,
                "mean_turns": mean_turns,
                "turn_counted_trials": len(turn_counts),
                "behavior_counted_trials": behavior_counted_trials,
                "behavior_timing_trials": (
                    behavior_totals["timing_trials"] if behavior_totals else 0
                ),
                "behavior_partial_trials": (
                    behavior_totals["partial_trials"] if behavior_totals else 0
                ),
                "inference_percent": inference_percent,
                "tool_percent": tool_percent,
                "other_percent": other_percent,
                "mean_tool_calls": mean_tool_calls,
                "mean_search_calls": mean_search_calls,
                "agent_seconds": behavior_totals["agent_seconds"] if behavior_totals else 0,
                "inference_seconds": behavior_totals["inference_seconds"] if behavior_totals else 0,
                "tool_seconds": behavior_totals["tool_seconds"] if behavior_totals else 0,
                "search_seconds": behavior_totals["search_seconds"] if behavior_totals else 0,
                "tool_calls": behavior_totals["tool_calls"] if behavior_totals else 0,
                "tool_errors": behavior_totals["tool_errors"] if behavior_totals else 0,
                "incomplete_tool_calls": behavior_totals["incomplete_tool_calls"] if behavior_totals else 0,
                "search_calls": behavior_totals["search_calls"] if behavior_totals else 0,
                "external_lookup_calls": behavior_totals["external_lookup_calls"] if behavior_totals else 0,
                "long_tool_calls": behavior_totals["long_tool_calls"] if behavior_totals else 0,
                "tool_counts": dict(sorted(behavior_totals["tool_counts"].items())) if behavior_totals else {},
                "category_counts": dict(sorted(behavior_totals["category_counts"].items())) if behavior_totals else {},
                "tool_seconds_by_name": dict(sorted(behavior_totals["tool_seconds_by_name"].items())) if behavior_totals else {},
                "category_seconds": dict(sorted(behavior_totals["category_seconds"].items())) if behavior_totals else {},
                "slowest_tools": slowest_tools,
                "prompt_tokens": token_totals["prompt_tokens"],
                "completion_tokens": token_totals["completion_tokens"],
                "cached_tokens": token_totals["cached_tokens"],
                "cache_creation_tokens": token_totals["cache_creation_tokens"],
                "reasoning_tokens": token_totals["reasoning_tokens"],
                "total_tokens": token_totals["total_tokens"],
                "estimated_cost_usd": estimated_cost_usd,
                "cost_per_completed_task_usd": cost_per_completed_task_usd,
                "passed_tasks_per_usd": passed_tasks_per_usd,
                "completed_trials": completed_trials,
                "costed_trials": costed_trials,
                "has_partial_cost": has_partial_cost,
                "input_cost_per_million_usd": input_cost_per_million_usd,
                "output_cost_per_million_usd": output_cost_per_million_usd,
                "cache_read_cost_per_million_usd": cache_read_cost_per_million_usd,
                "cache_write_cost_per_million_usd": cache_write_cost_per_million_usd,
                "method": score_method,
            })

        # Apply dimensional filters (thinking, provider). These are
        # first-class axes for cospa and are applied post-grouping so they
        # don't interfere with path-text filters/excludes.
        if thinking_filter and thinking_filter.lower() != "all":
            scores = [
                s for s in scores
                if str(s.get("thinking", "default")).lower() == thinking_filter.lower()
            ]
        if provider_filter and provider_filter.lower() != "all":
            scores = [
                s for s in scores
                if str(s.get("provider", "")).lower() == provider_filter.lower()
            ]

        self._store_cached_scores(cache_key, scores)
        return sort_scores(scores, sort_by)

    def get_task_details(self, model: str, adapter: str, suite: str) -> dict:
        """Get per-task details for a specific run.

        `model` arrives URL-encoded from the query string (because the
        runner writes encoded directory names). We keep it encoded for the
        filesystem lookup and only decode it for display.
        """
        from harness.path_utils import decode_model_path, decode_task_path, encode_model_path

        # The query string may carry either the decoded model id (from a
        # /api/scores row) or the encoded one. Normalize to encoded for FS use.
        encoded_model = encode_model_path(decode_model_path(model))
        decoded_model = decode_model_path(model)

        task_trials = {}
        for trial_dir in self._iter_trial_dirs(RESULTS_DIR):
            try:
                task_dir = trial_dir.parent
                suite_dir = task_dir.parent
                adapter_dir = suite_dir.parent
                model_dir = adapter_dir.parent
            except IndexError:
                continue
            if (
                model_dir.name != encoded_model
                or adapter_dir.name != adapter
                or suite_dir.name != suite
            ):
                continue
            trial = self._load_trial(trial_dir)
            if trial is None:
                continue
            manifest_model = trial["manifest"].get("model", {}).get("id")
            if manifest_model and manifest_model != decoded_model:
                continue
            task_id = decode_task_path(task_dir.name)
            verdict = trial["verdict"]
            manifest = trial["manifest"]
            task_trials.setdefault(task_id, []).append({
                "trial": trial_dir.name,
                "passed": verdict.get("passed", False),
                "test_count": verdict.get("test_count", 0),
                "wall_clock_seconds": manifest.get("timing", {}).get("wall_clock_seconds", 0),
                "behavior": manifest.get("behavior"),
            })

        if not task_trials:
            return {"error": "Not found", "tasks": []}

        details = []
        for task_id, trials in sorted(task_trials.items()):
            trials = sorted(trials, key=lambda item: item["trial"])

            n_trials = len(trials)
            n_passed = sum(1 for t in trials if t["passed"])
            task_passed = n_passed > n_trials / 2

            details.append({
                "task_id": task_id,
                "trials": trials,
                "passed": task_passed,
                "pass_at_k": f"{n_passed}/{n_trials}",
                "test_count": trials[0]["test_count"],
                "wall_clock_seconds": trials[0]["wall_clock_seconds"],
            })

        return {"model": decoded_model, "adapter": adapter, "suite": suite, "tasks": details}


def _handler() -> ScoreHandler:
    return ScoreHandler.__new__(ScoreHandler)


def _start_server(host: str, port: int) -> None:
    server = HTTPServer((host, port), ScoreHandler)
    print(f"Score viewer running at http://{host}:{port}")
    print(f"Results directory: {RESULTS_DIR}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down...")
        server.shutdown()


def main(argv: list[str] | None = None) -> int:
    """Run the score viewer CLI."""
    global RESULTS_DIR, DEFAULT_INCLUDE_SMOKE, DEFAULT_FILTERS, DEFAULT_EXCLUDES
    global DEFAULT_SORT_BY, DEFAULT_USE_CACHE, DEFAULT_PRICING_PROFILE

    common = argparse.ArgumentParser(add_help=False)
    common.add_argument(
        "--results-dir",
        type=Path,
        default=argparse.SUPPRESS,
        help="Results directory to read (default: results)",
    )
    common.add_argument(
        "--all",
        dest="include_smoke",
        action="store_true",
        default=False,
        help=(
            "Include smoke/probe/preflight/qualification/validation runs "
            "(hidden by default)"
        ),
    )
    common.add_argument(
        "--filter",
        dest="filters",
        action="append",
        default=[],
        metavar="PATTERN",
        help="Only include trials whose run/model/adapter/suite/task text matches PATTERN",
    )
    common.add_argument(
        "--exclude",
        dest="excludes",
        action="append",
        default=[],
        metavar="PATTERN",
        help="Exclude trials whose run/model/adapter/suite/task text matches PATTERN",
    )
    common.add_argument(
        "--no-cache",
        dest="use_cache",
        action="store_false",
        default=True,
        help="Disable the persistent score cache",
    )
    common.add_argument(
        "--thinking",
        dest="thinking_filter",
        default=None,
        metavar="LEVEL",
        help=(
            "Only include rows at this thinking/effort level "
            "(e.g. default, high, xhigh). Use --thinking all to include "
            "every level (default)."
        ),
    )
    common.add_argument(
        "--provider",
        dest="provider_filter",
        default=None,
        metavar="NAME",
        help=(
            "Only include rows served by this provider "
            "(e.g. aiand, local, nvidia). Use --provider all to include "
            "every provider (default)."
        ),
    )
    common.add_argument(
        "--sort",
        dest="sort_by",
        action="append",
        default=[],
        metavar="FIELD",
        help=(
            "Sort rows by FIELD. Common aliases: pass (score desc), "
            "cost (total cost asc), task ($/task asc), cospa/pass-dollar "
            "(Pass/$ desc). Supports comma lists and :asc/:desc overrides."
        ),
    )
    common.add_argument(
        "--pricing-profile",
        default=None,
        help=(
            "Use cost_profiles.<name> from configs/models.yaml for pricing "
            "(default: use each model's cost block)"
        ),
    )
    parser = argparse.ArgumentParser(
        description="View coding-eval scores",
        parents=[common],
    )
    subparsers = parser.add_subparsers(dest="command")

    table_parser = subparsers.add_parser(
        "table",
        parents=[common],
        help="Print terminal score table",
    )
    table_parser.add_argument(
        "--color",
        choices=("auto", "always", "never"),
        default="auto",
        help="Color terminal output (default: auto)",
    )
    table_parser.add_argument(
        "--show-ci",
        action="store_true",
        help="Show Wilson 95% confidence intervals",
    )
    table_parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Show status, runtime, average task time/turns, and ETA",
    )

    json_parser = subparsers.add_parser(
        "json",
        parents=[common],
        help="Print score rows as JSON",
    )
    json_parser.add_argument("--pretty", action="store_true", help="Pretty-print JSON")

    serve_parser = subparsers.add_parser(
        "serve",
        parents=[common],
        help="Start the web score viewer",
    )
    serve_parser.add_argument("--host", default="localhost", help="Bind host")
    serve_parser.add_argument("--port", type=int, default=8000, help="Bind port")

    args = parser.parse_args(argv)
    RESULTS_DIR = getattr(args, "results_dir", RESULTS_DIR)
    DEFAULT_INCLUDE_SMOKE = getattr(args, "include_smoke", False)
    DEFAULT_FILTERS = tuple(getattr(args, "filters", []) or [])
    DEFAULT_EXCLUDES = tuple(getattr(args, "excludes", []) or [])
    DEFAULT_SORT_BY = tuple(getattr(args, "sort_by", []) or [])
    DEFAULT_USE_CACHE = getattr(args, "use_cache", True)
    DEFAULT_PRICING_PROFILE = getattr(args, "pricing_profile", None)
    try:
        sort_scores([], DEFAULT_SORT_BY)
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2

    # Preserve the old direct-launch behavior: `python view-scores/server.py`
    # starts the web viewer. The root `./view` wrapper defaults to table mode.
    if args.command is None:
        _start_server("localhost", 8000)
        return 0

    handler = _handler()
    if args.command == "table":
        scores = handler.get_scores(
            include_smoke=args.include_smoke,
            filters=args.filters,
            excludes=args.excludes,
            thinking_filter=getattr(args, "thinking_filter", None),
            provider_filter=getattr(args, "provider_filter", None),
            sort_by=getattr(args, "sort_by", None),
        )
        warnings = handler.get_warnings()
        print(
            format_scores_terminal(
                scores,
                results_dir=RESULTS_DIR,
                color=_color_enabled(args.color),
                show_ci=args.show_ci,
                verbose=args.verbose,
                warnings=warnings,
            )
        )
        return 0
    if args.command == "json":
        indent = 2 if args.pretty else None
        scores = handler.get_scores(
            include_smoke=args.include_smoke,
            filters=args.filters,
            excludes=args.excludes,
            thinking_filter=getattr(args, "thinking_filter", None),
            provider_filter=getattr(args, "provider_filter", None),
            sort_by=getattr(args, "sort_by", None),
        )
        warning_text = _format_warnings_terminal(handler.get_warnings())
        if warning_text:
            print(warning_text, file=sys.stderr)
        print(
            json.dumps(
                scores,
                indent=indent,
            )
        )
        return 0
    if args.command == "serve":
        _start_server(args.host, args.port)
        return 0

    return 1


if __name__ == "__main__":
    raise SystemExit(main())
