"""
Score viewer — terminal/web/API views over the durable results tree.

Rows = (model, adapter, suite), cells = task-level pass@k-majority score,
drill-down to per-task verdicts.

Usage:
  ./view
  ./view serve
"""

import html
import json
import sys
import argparse
import re
from pathlib import Path
from http.server import HTTPServer, SimpleHTTPRequestHandler
from urllib.parse import urlparse, parse_qs, urlencode

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
RESULTS_DIR = PROJECT_ROOT / "results"
ANSI_RE = re.compile(r"\033\[[0-9;]*m")


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


def _visible_len(value: str) -> int:
    return len(ANSI_RE.sub("", value))


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
) -> str:
    """Return a compact terminal score table.

    The default view is operational: task-level score and passed/total counts.
    Confidence intervals are available on request, but they are intentionally
    hidden by default because tiny smoke runs produce very wide intervals.
    """
    if not scores:
        return f"No scores found in {results_dir}"

    headers = ["Model", "Adapter", "Suite", "Score", "Passed", "Tasks"]
    if show_ci:
        headers.append("95% CI")

    rows = []
    for score in scores:
        pass_rate = float(score["pass_rate"])
        score_text = f"{pass_rate:.1f}%"
        score_text = _ansi(score_text, _score_color(pass_rate), color)
        row = [
            str(score["model"]),
            str(score["adapter"]),
            str(score["suite"]),
            score_text,
            f"{score['passed_tasks']}/{score['total_tasks']}",
            str(score["total_tasks"]),
        ]
        if show_ci:
            row.append(f"{score['ci_lower']:.1f}-{score['ci_upper']:.1f}%")
        rows.append(row)

    title = _ansi("Coding Eval Scores", "1", color)
    subtitle = f"Results: {results_dir}"
    return f"{title}\n{subtitle}\n\n{_format_table(headers, rows)}"


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

    def do_GET(self):
        """Handle GET requests."""
        parsed = urlparse(self.path)

        if parsed.path == "/" or parsed.path == "/index.html":
            self.serve_html(self.generate_html())
        elif parsed.path == "/api/scores":
            self.serve_json(self.get_scores())
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
        rows = ""

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
    </style>
</head>
<body>
    <h1>Coding Eval Score Viewer</h1>
    <p class="note">Score is task-level pass@k majority. Confidence intervals are available from <code>/api/scores</code> and <code>./view --show-ci</code>.</p>
    <table>
        <thead>
            <tr>
                <th>Model</th>
                <th>Adapter</th>
                <th>Suite</th>
                <th>Score</th>
                <th>Passed</th>
                <th>Tasks</th>
                <th>Details</th>
            </tr>
        </thead>
        <tbody>
            {rows}
        </tbody>
    </table>
</body>
</html>"""

    def get_scores(self) -> list:
        """Get aggregated scores from results directory."""
        from harness.path_utils import decode_model_path, decode_task_path

        grouped_trials = {}
        for trial_dir in self._iter_trial_dirs(RESULTS_DIR):
            trial = self._load_trial(trial_dir)
            if trial is None:
                continue
            try:
                task_dir = trial_dir.parent
                suite_dir = task_dir.parent
                adapter_dir = suite_dir.parent
                model_dir = adapter_dir.parent
            except IndexError:
                continue

            model_id = decode_model_path(model_dir.name)
            manifest_model = trial["manifest"].get("model", {}).get("id")
            if manifest_model and manifest_model != model_id:
                continue
            adapter_id = adapter_dir.name
            suite_id = suite_dir.name
            task_id = decode_task_path(task_dir.name)
            key = (model_id, adapter_id, suite_id)
            grouped_trials.setdefault(key, {}).setdefault(task_id, []).append(
                trial["verdict"].get("passed", False)
            )

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
                "passed_tasks": passed_tasks,
                "method": "pass@k majority",
            })

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
    global RESULTS_DIR

    common = argparse.ArgumentParser(add_help=False)
    common.add_argument(
        "--results-dir",
        type=Path,
        default=argparse.SUPPRESS,
        help="Results directory to read (default: results)",
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

    # Preserve the old direct-launch behavior: `python view-scores/server.py`
    # starts the web viewer. The root `./view` wrapper defaults to table mode.
    if args.command is None:
        _start_server("localhost", 8000)
        return 0

    handler = _handler()
    if args.command == "table":
        print(
            format_scores_terminal(
                handler.get_scores(),
                results_dir=RESULTS_DIR,
                color=_color_enabled(args.color),
                show_ci=args.show_ci,
            )
        )
        return 0
    if args.command == "json":
        indent = 2 if args.pretty else None
        print(json.dumps(handler.get_scores(), indent=indent))
        return 0
    if args.command == "serve":
        _start_server(args.host, args.port)
        return 0

    return 1


if __name__ == "__main__":
    raise SystemExit(main())
