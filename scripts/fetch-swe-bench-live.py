#!/usr/bin/env python3
"""Extract cospa's pinned SWE-bench-Live canary rows from HF parquet.

The runtime harness intentionally has no parquet dependency. setup.sh downloads
all eight immutable split files to a temporary directory, invokes this script
through an isolated pyarrow environment, and retains only the 24 selected rows
under vendor/.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_MANIFEST = (
    PROJECT_ROOT / "configs" / "swe_bench_live_multilang_canary24.json"
)
DEFAULT_VENDOR_DIR = PROJECT_ROOT / "vendor" / "swe-bench-live-multilang"


def canonical_row_hash(row: dict) -> str:
    payload = json.dumps(
        row,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode()
    return hashlib.sha256(payload).hexdigest()


def load_manifest(path: Path) -> dict:
    with open(path, encoding="utf-8") as handle:
        manifest = json.load(handle)
    if not isinstance(manifest, dict):
        raise ValueError(f"Canary manifest must be an object: {path}")
    return manifest


def validate_rows(manifest: dict, rows: list[dict]) -> list[str]:
    tasks = manifest.get("tasks")
    if not isinstance(tasks, list) or not tasks:
        return ["manifest has no tasks"]

    errors: list[str] = []
    expected_ids = [str(task.get("id")) for task in tasks]
    row_ids = [str(row.get("instance_id")) for row in rows]
    if row_ids != expected_ids:
        errors.append("vendor rows do not match manifest task order")
        return errors

    for task, row in zip(tasks, rows, strict=True):
        task_id = str(task["id"])
        expected = {
            "repo": task.get("repository"),
            "base_commit": task.get("base_commit"),
            "created_at": task.get("created_at"),
            "docker_image": task.get("source_image"),
        }
        for field, value in expected.items():
            if row.get(field) != value:
                errors.append(f"{task_id}: {field} does not match manifest")
        actual_hash = canonical_row_hash(row)
        if actual_hash != task.get("row_sha256"):
            errors.append(f"{task_id}: row SHA-256 mismatch")
        for field in (
            "problem_statement",
            "patch",
            "test_patch",
            "log_parser",
            "FAIL_TO_PASS",
            "PASS_TO_PASS",
            "rebuild_cmds",
            "test_cmds",
            "print_cmds",
        ):
            if field not in row:
                errors.append(f"{task_id}: missing required field {field}")
    return errors


def read_vendor_rows(vendor_dir: Path) -> list[dict]:
    rows = []
    with open(vendor_dir / "canary24.jsonl", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, 1):
            if not line.strip():
                continue
            row = json.loads(line)
            if not isinstance(row, dict):
                raise ValueError(f"vendor row {line_number} is not an object")
            rows.append(row)
    return rows


def check_vendor(manifest: dict, vendor_dir: Path) -> list[str]:
    revision_path = vendor_dir / "REVISION"
    data_path = vendor_dir / "canary24.jsonl"
    if not revision_path.is_file() or not data_path.is_file():
        return [f"missing canary vendor files under {vendor_dir}"]
    revision = revision_path.read_text().strip()
    expected_revision = str(manifest.get("dataset", {}).get("revision", ""))
    if revision != expected_revision:
        return [
            f"dataset revision mismatch: expected {expected_revision}, got {revision}"
        ]
    try:
        rows = read_vendor_rows(vendor_dir)
    except (OSError, ValueError, json.JSONDecodeError) as error:
        return [f"could not read canary rows: {error}"]
    return validate_rows(manifest, rows)


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def extract_rows(manifest: dict, parquet_dir: Path) -> tuple[list[dict], dict]:
    try:
        import pyarrow.parquet as parquet  # type: ignore
    except ImportError as error:
        raise RuntimeError(
            "pyarrow is required for extraction; use setup.sh or "
            "uv run --isolated --with pyarrow"
        ) from error

    selected_ids = {str(task["id"]) for task in manifest["tasks"]}
    rows_by_id: dict[str, dict] = {}
    source_hashes: dict[str, str] = {}
    for split in manifest["dataset"]["splits"]:
        path = parquet_dir / f"{split}.parquet"
        if not path.is_file():
            raise FileNotFoundError(f"Missing pinned parquet split: {path}")
        actual_source_hash = file_sha256(path)
        source_hashes[str(split)] = actual_source_hash
        expected_source_hash = manifest["dataset"].get(
            "parquet_sha256", {}
        ).get(str(split))
        if actual_source_hash != expected_source_hash:
            raise ValueError(
                f"Pinned parquet SHA-256 mismatch for {split}: "
                f"expected {expected_source_hash}, got {actual_source_hash}"
            )
        for row in parquet.read_table(path).to_pylist():
            task_id = str(row.get("instance_id"))
            if task_id in selected_ids:
                if task_id in rows_by_id:
                    raise ValueError(f"Duplicate selected task in parquet: {task_id}")
                rows_by_id[task_id] = row

    missing = selected_ids - set(rows_by_id)
    if missing:
        raise ValueError("Selected tasks missing from parquet: " + ", ".join(sorted(missing)))
    ordered = [rows_by_id[str(task["id"])] for task in manifest["tasks"]]
    errors = validate_rows(manifest, ordered)
    if errors:
        raise ValueError("; ".join(errors))
    return ordered, source_hashes


def write_vendor(
    manifest: dict,
    vendor_dir: Path,
    rows: list[dict],
    source_hashes: dict[str, str],
) -> None:
    vendor_dir.mkdir(parents=True, exist_ok=True)
    revision = str(manifest["dataset"]["revision"])
    (vendor_dir / "REVISION").write_text(revision + "\n")
    (vendor_dir / "canary24.jsonl").write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows)
    )
    source = {
        "dataset": manifest["dataset"]["repository"],
        "revision": revision,
        "parquet_sha256": source_hashes,
    }
    (vendor_dir / "SOURCE.json").write_text(json.dumps(source, indent=2) + "\n")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--vendor-dir", type=Path, default=DEFAULT_VENDOR_DIR)
    parser.add_argument("--parquet-dir", type=Path)
    parser.add_argument("--check", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    manifest = load_manifest(args.manifest)
    if args.check:
        errors = check_vendor(manifest, args.vendor_dir)
        if errors:
            for error in errors:
                print(error, file=sys.stderr)
            return 1
        print(f"validated {len(manifest['tasks'])} pinned canary rows")
        return 0
    if args.parquet_dir is None:
        print("--parquet-dir is required unless --check is used", file=sys.stderr)
        return 2
    rows, source_hashes = extract_rows(manifest, args.parquet_dir)
    write_vendor(manifest, args.vendor_dir, rows, source_hashes)
    print(f"wrote {len(rows)} pinned canary rows to {args.vendor_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
