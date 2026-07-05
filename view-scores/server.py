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
DEFAULT_USE_CACHE = True
DEFAULT_CACHE_PATH = Path(
    os.environ.get(
        "CODING_EVAL_VIEW_CACHE_PATH",
        PROJECT_ROOT / ".cache" / "view-scores.json",
    )
)
SCORE_CACHE_VERSION = 3
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
            "Status",
            "Score",
            "Passed",
            "Done",
            "Runtime",
            "Avg",
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
        pass_rate = float(score["pass_rate"])
        score_text = f"{pass_rate:.1f}%"
        score_text = _ansi(score_text, _score_color(pass_rate), color)
        if verbose:
            completed = int(score.get("completed_tasks", score["total_tasks"]))
            expected = int(score.get("expected_tasks", completed))
            done = f"{completed}/{expected}" if expected != completed else str(completed)
            row = [
                str(score["model"]),
                str(score["adapter"]),
                str(score["suite"]),
                str(score.get("status", "complete")),
                score_text,
                f"{score['passed_tasks']}/{score['total_tasks']}",
                done,
                _format_duration(score.get("total_wall_clock_seconds")),
                _format_duration(score.get("mean_wall_clock_seconds")),
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
        if not include_smoke and "smoke" in run_path.lower():
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

        if adapter not in _known_adapter_names():
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
    ) -> bool:
        """Best-effort fallback for pre-heartbeat live runners."""
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
            "trials": signature,
            "heartbeats": heartbeat_signature,
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
            pass_rate = float(score["pass_rate"])
            score_class = _score_class(pass_rate)
            rows += f"""
            <tr>
                <td>{model}</td>
                <td>{adapter}</td>
                <td>{suite}</td>
                <td class="{score_class}">{pass_rate:.1f}%</td>
                <td>{score['passed_tasks']}/{score['total_tasks']}</td>
                <td>{score['total_tasks']}</td>
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
        }

    @classmethod
    def _pricing_from_manifest(
        cls,
        manifest: dict,
        *,
        prompt_tokens: int | None = None,
        cached_tokens: int = 0,
        cache_creation_tokens: int = 0,
    ) -> tuple[float | None, float | None, float | None, float | None]:
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
    def _estimate_cost_usd(
        cls,
        manifest: dict,
        prompt_tokens: int,
        completion_tokens: int,
        cached_tokens: int = 0,
        cache_creation_tokens: int = 0,
        reasoning_tokens: int = 0,
    ) -> float | None:
        usage = manifest.get("token_usage") or manifest.get("usage") or {}
        if isinstance(usage, dict):
            direct_cost = cls._numeric_value(
                usage,
                "cost_usd",
                "total_cost_usd",
                "cost",
                "total_cost",
            )
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
            if direct_cost is not None and direct_cost > 0:
                return direct_cost
            if direct_cost is not None and not has_tokens:
                return None
        else:
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

        direct_cost = cls._numeric_value(
            manifest,
            "cost_usd",
            "total_cost_usd",
            "estimated_cost_usd",
        )
        if direct_cost is not None and direct_cost > 0:
            return direct_cost
        if direct_cost is not None and not has_tokens:
            return None

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
            return None
        if input_per_million is None and output_per_million is None:
            return direct_cost
        if prompt_tokens and input_per_million is None:
            return direct_cost
        billed_output_tokens = completion_tokens + reasoning_tokens
        if billed_output_tokens and output_per_million is None:
            return direct_cost
        if cached_tokens and cache_read_per_million is None:
            return direct_cost
        if cache_creation_tokens and cache_write_per_million is None:
            return direct_cost

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
    ) -> list:
        """Get aggregated scores from results directory."""
        include_smoke = DEFAULT_INCLUDE_SMOKE if include_smoke is None else include_smoke
        filters = tuple(DEFAULT_FILTERS if filters is None else filters)
        excludes = tuple(DEFAULT_EXCLUDES if excludes is None else excludes)

        grouped_trials = {}
        grouped_times = {}
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
        )
        cached_scores = self._get_cached_scores(cache_key)
        if cached_scores is not None:
            return cached_scores

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

            key = (parts["model_id"], parts["adapter_id"], parts["suite_id"])
            suite_dirs_by_key.setdefault(key, set()).add(parts["suite_dir"])
            run_paths_by_key.setdefault(key, set()).add(parts.get("run_path", ""))
            started_tasks.setdefault(key, set()).add(parts["task_id"])
            if trial is None:
                continue
            grouped_trials.setdefault(key, {}).setdefault(parts["task_id"], []).append(
                trial["verdict"].get("passed", False)
            )
            seconds = trial["manifest"].get("timing", {}).get("wall_clock_seconds")
            if isinstance(seconds, (int, float)):
                grouped_times.setdefault(key, {}).setdefault(parts["task_id"], []).append(
                    float(seconds)
                )
            token_usage = self._token_usage_from_manifest(trial["manifest"])
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
        for (model_id, adapter_id, suite_id), task_trials in sorted(
            grouped_trials.items()
        ):
            # Count tasks that passed (majority of trials)
            total_tasks = len(task_trials)
            passed_tasks = sum(
                1 for trials in task_trials.values()
                if sum(1 for t in trials if t) > len(trials) / 2
            )
            pass_rate = (passed_tasks / total_tasks) * 100 if total_tasks > 0 else 0
            task_times = [
                sum(trial_times)
                for trial_times in grouped_times.get(
                    (model_id, adapter_id, suite_id), {}
                ).values()
                if trial_times
            ]
            total_wall_clock_seconds = sum(task_times)
            mean_wall_clock_seconds = (
                total_wall_clock_seconds / len(task_times) if task_times else 0
            )
            median_wall_clock_seconds = statistics.median(task_times) if task_times else 0
            started_count = len(
                started_tasks.get((model_id, adapter_id, suite_id), set())
                | set(task_trials.keys())
            )
            expected_tasks = self._expected_task_count(suite_id, total_tasks)
            remaining_tasks = max(0, expected_tasks - total_tasks)
            incomplete_started_tasks = max(0, started_count - total_tasks)
            key = (model_id, adapter_id, suite_id)
            live_runner = self._cell_has_live_heartbeat(
                suite_dirs_by_key.get(key, set())
            ) or any(
                self._has_live_runner_process(
                    model_id,
                    adapter_id,
                    suite_id,
                    run_path,
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
                (model_id, adapter_id, suite_id),
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
                (model_id, adapter_id, suite_id),
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
                (model_id, adapter_id, suite_id),
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
                "score": pass_rate,
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
                "method": "pass@k majority",
            })

        self._store_cached_scores(cache_key, scores)
        return scores

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
    global DEFAULT_USE_CACHE

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
        help="Include smoke/probe runs (hidden by default)",
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
        help="Show status, runtime, average task time, and ETA",
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
    DEFAULT_USE_CACHE = getattr(args, "use_cache", True)

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
