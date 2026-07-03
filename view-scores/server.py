"""
Score viewer — static HTML + server.py that walks results/ and renders a table.

Rows = (model, adapter, suite), cells = pass-rate with CI,
drill-down to per-task verdicts.

Usage:
  python view-scores/server.py
"""

import json
import statistics
from pathlib import Path
from http.server import HTTPServer, SimpleHTTPRequestHandler
from urllib.parse import urlparse, parse_qs

RESULTS_DIR = Path(__file__).resolve().parent.parent / "results"


class ScoreHandler(SimpleHTTPRequestHandler):
    """HTTP handler for the score viewer."""

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
            rows += f"""
            <tr>
                <td>{score['model']}</td>
                <td>{score['adapter']}</td>
                <td>{score['suite']}</td>
                <td>{score['pass_rate']:.1f}%</td>
                <td>{score['ci_lower']:.1f}% - {score['ci_upper']:.1f}%</td>
                <td>{score['total']}</td>
                <td>{score['passed']}</td>
                <td><a href="/?model={score['model']}&adapter={score['adapter']}&suite={score['suite']}">Details</a></td>
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
        scores = []

        if not RESULTS_DIR.exists():
            return scores

        from harness.path_utils import decode_model_path

        for model_dir in RESULTS_DIR.iterdir():
            if not model_dir.is_dir():
                continue

            model_id = decode_model_path(model_dir.name)

            for adapter_dir in model_dir.iterdir():
                if not adapter_dir.is_dir():
                    continue

                adapter_id = adapter_dir.name

                for suite_dir in adapter_dir.iterdir():
                    if not suite_dir.is_dir():
                        continue

                    suite_id = suite_dir.name

                    # Group trials by task, then apply pass@k (majority) semantics
                    task_trials = {}
                    for task_dir in suite_dir.iterdir():
                        if not task_dir.is_dir():
                            continue
                        for trial_dir in task_dir.iterdir():
                            if trial_dir.is_dir() and trial_dir.name.startswith("trial-"):
                                verdict_file = trial_dir / "verdict.json"
                                if verdict_file.exists():
                                    with open(verdict_file) as f:
                                        verdict = json.load(f)
                                        task_id = decode_task_path(task_dir.name)
                                        if task_id not in task_trials:
                                            task_trials[task_id] = []
                                        task_trials[task_id].append(verdict.get("passed", False))

                    if not task_trials:
                        continue

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
        """Get per-task details for a specific run."""
        from harness.path_utils import decode_model_path, decode_task_path

        details = []

        # Decode URL-encoded model and task IDs
        decoded_model = decode_model_path(model)
        suite_dir = RESULTS_DIR / decoded_model / adapter / suite
        if not suite_dir.exists():
            return {"error": "Not found", "tasks": []}

        # Group trials by task_id (there may be multiple trials per task)
        task_trials = {}
        for trial_dir in suite_dir.iterdir():
            if trial_dir.is_dir() and trial_dir.name.startswith("trial-"):
                verdict_file = trial_dir / "verdict.json"
                manifest_file = trial_dir / "manifest.json"

                verdict = {}
                manifest = {}

                if verdict_file.exists():
                    with open(verdict_file) as f:
                        verdict = json.load(f)

                if manifest_file.exists():
                    with open(manifest_file) as f:
                        manifest = json.load(f)

                # Decode the task_id from the directory name
                encoded_task = trial_dir.parent.name
                task_id = decode_task_path(encoded_task)
                if task_id not in task_trials:
                    task_trials[task_id] = []

                task_trials[task_id].append({
                    "trial": trial_dir.name,
                    "passed": verdict.get("passed", False),
                    "test_count": verdict.get("test_count", 0),
                    "wall_clock_seconds": manifest.get("timing", {}).get("wall_clock_seconds", 0),
                })

        # Build details list using pass@k semantics (majority of trials must pass)
        for task_id, trials in task_trials.items():
            first_trial = trials[0]
            n_trials = len(trials)
            n_passed = sum(1 for t in trials if t["passed"])
            # Task passes if majority of trials pass (pass@k with majority rule)
            task_passed = n_passed > n_trials / 2

            details.append({
                "task_id": task_id,
                "trials": trials,
                "passed": task_passed,
                "pass_at_k": f"{n_passed}/{n_trials}",
                "test_count": first_trial["test_count"],
                "wall_clock_seconds": first_trial["wall_clock_seconds"],
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
