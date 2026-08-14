#!/usr/bin/env python3
"""Resolve mutable evaluation image tags to linux/amd64 manifest digests."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MANIFEST = ROOT / "configs" / "ornith_runtime_pilot_v1.json"
DEFAULT_OUTPUT = ROOT / "configs" / "ornith_runtime_pilot_images_v1.json"
DIGEST_RE = re.compile(r"^sha256:[0-9a-f]{64}$")


def multi_swe_image_ref(instance_id: str) -> str:
    """Return the public Multi-SWE image name defined by its upstream harness."""
    organization, separator, remainder = str(instance_id).partition("__")
    if not separator or "-" not in remainder:
        raise ValueError(f"Invalid Multi-SWE instance id: {instance_id!r}")
    repository, number = remainder.rsplit("-", 1)
    if not organization or not repository or not number.isdigit():
        raise ValueError(f"Invalid Multi-SWE instance id: {instance_id!r}")
    return f"mswebench/{organization}_m_{repository}:pr-{number}".lower()


def collect_image_requests(pilot: dict[str, Any]) -> dict[str, dict[str, list[str]]]:
    """Collect all selected task and verifier images with their provenance."""
    collected: dict[str, dict[str, set[str]]] = {}

    def add(image_ref: str, suite_name: str, task_id: str) -> None:
        entry = collected.setdefault(
            image_ref,
            {"suites": set(), "task_ids": set()},
        )
        entry["suites"].add(suite_name)
        entry["task_ids"].add(task_id)

    for suite_name, suite in pilot.get("suites", {}).items():
        if not isinstance(suite, dict):
            continue
        verifier_image = suite.get("verifier_image_ref")
        if verifier_image:
            add(str(verifier_image), str(suite_name), "__verifier__")
        for task in suite.get("tasks", []):
            if not isinstance(task, dict) or not task.get("id"):
                continue
            image_ref = task.get("image_ref")
            if not image_ref and suite_name == "multi_swe_bench_flash":
                image_ref = multi_swe_image_ref(str(task["id"]))
            if image_ref:
                add(str(image_ref), str(suite_name), str(task["id"]))

    return {
        image_ref: {
            "suites": sorted(metadata["suites"]),
            "task_ids": sorted(metadata["task_ids"]),
        }
        for image_ref, metadata in sorted(collected.items())
    }


def extract_platform_digest(
    manifest: Any,
    *,
    architecture: str = "amd64",
    operating_system: str = "linux",
) -> str:
    """Extract one exact platform digest from Docker's verbose JSON output."""
    candidates = manifest if isinstance(manifest, list) else [manifest]
    for candidate in candidates:
        if not isinstance(candidate, dict):
            continue
        descriptor = candidate.get("Descriptor")
        if not isinstance(descriptor, dict):
            continue
        platform = descriptor.get("platform")
        if isinstance(manifest, list):
            if not isinstance(platform, dict):
                continue
            if platform.get("architecture") != architecture:
                continue
            if platform.get("os") != operating_system:
                continue
        digest = descriptor.get("digest")
        if isinstance(digest, str) and DIGEST_RE.fullmatch(digest):
            return digest
    raise ValueError(
        f"Manifest has no valid {operating_system}/{architecture} sha256 digest"
    )


def pin_image_reference(image_ref: str, digest: str) -> str:
    """Replace a mutable tag with an immutable platform manifest digest."""
    if not DIGEST_RE.fullmatch(digest):
        raise ValueError(f"Invalid image digest: {digest!r}")
    unpinned = image_ref.split("@", 1)[0]
    slash = unpinned.rfind("/")
    colon = unpinned.rfind(":")
    if colon > slash:
        unpinned = unpinned[:colon]
    return f"{unpinned}@{digest}"


def resolve_image(
    image_ref: str,
    *,
    timeout: int = 120,
    attempts: int = 3,
) -> dict[str, str]:
    """Resolve one image through Docker, retrying transient registry failures."""
    if attempts < 1:
        raise ValueError("attempts must be positive")

    for attempt in range(1, attempts + 1):
        try:
            result = subprocess.run(
                ["docker", "manifest", "inspect", "--verbose", image_ref],
                check=True,
                capture_output=True,
                text=True,
                timeout=timeout,
            )
            manifest = json.loads(result.stdout)
            digest = extract_platform_digest(manifest)
            return {
                "digest": digest,
                "pinned_ref": pin_image_reference(image_ref, digest),
            }
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
            if attempt == attempts:
                raise
            time.sleep(2 ** (attempt - 1))

    raise AssertionError("unreachable")


def _display_manifest_path(manifest_path: Path) -> str:
    try:
        return str(manifest_path.relative_to(ROOT))
    except ValueError:
        return str(manifest_path)


def reuse_existing_lock(
    manifest_path: Path,
    existing_lock: dict[str, Any],
) -> dict[str, Any]:
    """Refresh manifest metadata without re-resolving an unchanged image set."""
    manifest_path = Path(manifest_path)
    raw = manifest_path.read_bytes()
    pilot = json.loads(raw)
    requests = collect_image_requests(pilot)
    images = existing_lock.get("images")
    if not isinstance(images, dict) or set(images) != set(requests):
        raise ValueError("Existing lock image requests do not match the manifest")
    if existing_lock.get("platform") != {"os": "linux", "architecture": "amd64"}:
        raise ValueError("Existing lock is not for linux/amd64")

    for image_ref, request in requests.items():
        image = images[image_ref]
        if not isinstance(image, dict):
            raise ValueError(f"Invalid existing lock entry for {image_ref}")
        if (
            image.get("suites") != request["suites"]
            or image.get("task_ids") != request["task_ids"]
        ):
            raise ValueError("Existing lock image requests do not match the manifest")
        digest = image.get("digest")
        if not isinstance(digest, str) or not DIGEST_RE.fullmatch(digest):
            raise ValueError(f"Invalid existing digest for {image_ref}")
        if image.get("pinned_ref") != pin_image_reference(image_ref, digest):
            raise ValueError(f"Invalid existing pinned reference for {image_ref}")

    reused = json.loads(json.dumps(existing_lock))
    reused["source_manifest"] = _display_manifest_path(manifest_path)
    reused["source_manifest_sha256"] = hashlib.sha256(raw).hexdigest()
    return reused


def build_lock(
    manifest_path: Path,
    *,
    workers: int = 8,
    timeout: int = 120,
) -> dict[str, Any]:
    manifest_path = Path(manifest_path)
    raw = manifest_path.read_bytes()
    pilot = json.loads(raw)
    requests = collect_image_requests(pilot)
    resolved: dict[str, dict[str, Any]] = {}

    with ThreadPoolExecutor(max_workers=max(1, workers)) as executor:
        futures = {
            executor.submit(resolve_image, image_ref, timeout=timeout): image_ref
            for image_ref in requests
        }
        for future in as_completed(futures):
            image_ref = futures[future]
            image = future.result()
            resolved[image_ref] = {**requests[image_ref], **image}
            print(f"resolved {image_ref} -> {image['digest']}")

    return {
        "name": "ornith_runtime_pilot_images_v1",
        "source_manifest": _display_manifest_path(manifest_path),
        "source_manifest_sha256": hashlib.sha256(raw).hexdigest(),
        "platform": {"os": "linux", "architecture": "amd64"},
        "images": {key: resolved[key] for key in sorted(resolved)},
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--timeout", type=int, default=120)
    parser.add_argument(
        "--reuse-existing",
        action="store_true",
        help=(
            "Reuse an existing output lock after validating that every image "
            "request and pinned digest is unchanged"
        ),
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.workers < 1 or args.timeout < 1:
        raise SystemExit("--workers and --timeout must be positive")
    if args.reuse_existing:
        if not args.output.is_file():
            raise SystemExit(f"Existing lock not found: {args.output}")
        lock = reuse_existing_lock(
            args.manifest,
            json.loads(args.output.read_text()),
        )
    else:
        lock = build_lock(
            args.manifest,
            workers=args.workers,
            timeout=args.timeout,
        )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    temporary = args.output.with_suffix(args.output.suffix + ".tmp")
    temporary.write_text(json.dumps(lock, indent=2) + "\n")
    temporary.replace(args.output)
    print(f"wrote {len(lock['images'])} image pins to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
