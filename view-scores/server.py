"""
Score viewer — static HTML + server.py that walks results/ and renders a table.

Rows = (model, adapter, suite), cells = pass-rate with CI,
drill-down to per-task verdicts.

Usage:
  python view-scores/server.py
"""

import html
import json
import sys
from pathlib import Path
from http.server import HTTPServer, SimpleHTTPRequestHandler
from urllib.parse import urlparse, parse_qs, urlencode

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
RESULTS_DIR = PROJECT_ROOT / "results"


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
            rows += f"""
            <tr>
                <td>{model}</td>
                <td>{adapter}</td>
                <td>{suite}</td>
                <td>{score['pass_rate']:.1f}%</td>
                <td>{score['ci_lower']:.1f}% - {score['ci_upper']:.1f}%</td>
                <td>{score['total_tasks']}</td>
                <td>{score['passed_tasks']}</td>
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
    </style>
</head>
<body>
    <h1>Coding Eval Score Viewer</h1>
    <table>
        <thead>
            <tr>
                <th>Model</th>
                <th>Adapter</th>
                <th>Suite</th>
                <th>Pass Rate</th>
                <th>95% CI</th>
                <th>Total</th>
                <th>Passed</th>
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


def main():
    """Start the score viewer server."""
    port = 8000
    server = HTTPServer(("localhost", port), ScoreHandler)
    print(f"Score viewer running at http://localhost:{port}")
    print(f"Results directory: {RESULTS_DIR}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down...")
        server.shutdown()


if __name__ == "__main__":
    main()
