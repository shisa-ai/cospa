"""
Path encoding utilities for model IDs and task IDs that contain slashes.

Model IDs like "nvidia/nemotron-3-ultra-550b-a55b" and task IDs like
"python/hello" contain slashes that break directory structures. This module
provides URL-encoding/decoding to safely store them as directory names.
"""

from urllib.parse import quote, unquote


def encode_path_component(s: str) -> str:
    """Encode a string for safe use as a directory name.

    Replaces / with %2F to prevent directory traversal.
    Other special characters are URL-encoded.
    """
    return quote(s, safe="")


def decode_path_component(s: str) -> str:
    """Decode a URL-encoded directory name back to the original string."""
    return unquote(s)


def encode_model_path(model_id: str) -> str:
    """Encode a model ID for use as a directory path component.

    Example: "nvidia/nemotron-3-ultra-550b-a55b" -> "nvidia%2Fnemotron-3-ultra-550b-a55b"
    """
    return encode_path_component(model_id)


def decode_model_path(encoded: str) -> str:
    """Decode a model ID from a directory path component."""
    return decode_path_component(encoded)


def encode_task_path(task_id: str) -> str:
    """Encode a task ID for use as a directory path component.

    Example: "python/hello" -> "python%2Fhello"
    """
    return encode_path_component(task_id)


def decode_task_path(encoded: str) -> str:
    """Decode a task ID from a directory path component."""
    return decode_path_component(encoded)
