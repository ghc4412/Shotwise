"""Project file enumeration shared by the Web UI and agent tools."""

from __future__ import annotations

import hashlib
from collections.abc import Iterable, Iterator
from pathlib import Path
from typing import Any

PROJECT_FILE_BUCKETS: tuple[str, ...] = (
    "source",
    "characters",
    "scenes",
    "props",
    "products",
    "storyboards",
    "videos",
    "output",
)
TEXT_SUFFIXES: frozenset[str] = frozenset({".txt", ".md", ".json"})
TEXT_ROOTS: tuple[str, ...] = ("source", "drafts", "scripts")


def enumerate_project_files(project_dir: Path, project_name: str) -> dict[str, list[dict[str, Any]]]:
    """Return the visible file buckets used by the Web UI.

    The same visible-file walker is used by :func:`enumerate_project_text_files`.
    ``source/raw`` contains byte-for-byte upload backups and is deliberately
    omitted from the public file list.
    """
    files: dict[str, list[dict[str, Any]]] = {bucket: [] for bucket in PROJECT_FILE_BUCKETS}
    for bucket in PROJECT_FILE_BUCKETS:
        raw_by_stem: dict[str, str] = {}
        if bucket == "source":
            raw_by_stem = {raw_file.stem: raw_file.name for raw_file in _iter_source_raw_files(project_dir)}

        for file_path in _iter_visible_files(project_dir, (bucket,), recursive=False):
            try:
                size = file_path.stat().st_size
            except OSError:
                continue
            entry: dict[str, Any] = {
                "name": file_path.name,
                "size": size,
                "url": f"/api/v1/files/{project_name}/{bucket}/{file_path.name}",
            }
            if bucket == "source":
                entry["raw_filename"] = raw_by_stem.get(file_path.stem)
            files[bucket].append(entry)
    return files


def enumerate_project_text_files(project_dir: Path) -> list[dict[str, Any]]:
    """Enumerate readable project text files without loading their contents.

    Entries are ordered by document priority: uploaded ``source/`` documents,
    online drafts, structured scripts, and finally project metadata. Callers
    should treat metadata as auxiliary context rather than a document choice.
    """
    result: list[dict[str, Any]] = []
    for root_name in TEXT_ROOTS:
        for file_path in _iter_visible_files(project_dir, (root_name,), recursive=True):
            if file_path.suffix.lower() not in TEXT_SUFFIXES:
                continue
            _append_text_file(result, file_path, project_dir, category=root_name)

    project_json = project_dir / "project.json"
    if project_json.is_file() and not project_json.name.startswith("."):
        _append_text_file(result, project_json, project_dir, category="metadata")
    return result


def project_text_files_signature(project_dir: Path) -> str:
    """Return a cheap version marker for the readable project text files.

    The marker changes when a visible file is added, removed, resized, or
    modified. It is used to prevent a long-lived agent session from reading a
    file list that was collected before a page upload, edit, or delete.
    """
    entries: list[str] = []
    for item in enumerate_project_text_files(project_dir):
        file_path = project_dir / item["path"]
        try:
            stat = file_path.stat()
        except OSError:
            continue
        entries.append(f"{item['path']}\0{stat.st_size}\0{stat.st_mtime_ns}")
    return hashlib.sha256("\n".join(entries).encode("utf-8")).hexdigest()


def _iter_visible_files(project_dir: Path, roots: Iterable[str], *, recursive: bool) -> Iterator[Path]:
    """Yield visible files under project roots, excluding upload backups."""
    for root_name in roots:
        root = project_dir / root_name
        if not root.is_dir():
            continue
        candidates = root.rglob("*") if recursive else root.iterdir()
        for file_path in sorted(candidates, key=lambda path: path.as_posix()):
            if not file_path.is_file() or _is_hidden_path(file_path, root):
                continue
            if root_name == "source" and _is_source_raw_path(file_path, root):
                continue
            if not _is_inside_project(file_path, project_dir):
                continue
            yield file_path


def _iter_source_raw_files(project_dir: Path) -> Iterator[Path]:
    raw_dir = project_dir / "source" / "raw"
    if not raw_dir.is_dir():
        return
    for file_path in sorted(raw_dir.iterdir(), key=lambda path: path.name):
        if file_path.is_file() and not file_path.name.startswith(".") and _is_inside_project(file_path, project_dir):
            yield file_path


def _is_inside_project(file_path: Path, project_dir: Path) -> bool:
    try:
        file_path.resolve().relative_to(project_dir.resolve())
    except (OSError, ValueError):
        return False
    return True


def _append_text_file(result: list[dict[str, Any]], file_path: Path, project_dir: Path, *, category: str) -> None:
    try:
        stat = file_path.stat()
        relative = file_path.relative_to(project_dir).as_posix()
    except (OSError, ValueError):
        return
    result.append({"path": relative, "category": category, "size": stat.st_size})


def _is_hidden_path(file_path: Path, root: Path) -> bool:
    return any(part.startswith(".") for part in file_path.relative_to(root).parts)


def _is_source_raw_path(file_path: Path, source_root: Path) -> bool:
    try:
        relative_parts = file_path.relative_to(source_root).parts
    except ValueError:
        return False
    return bool(relative_parts) and relative_parts[0].lower() == "raw"
