"""Read-through cache for the project list's JSON inputs.

The cache is intentionally scoped to project-list reads. Other callers keep the
normal ProjectManager load semantics, while list reads avoid reparsing unchanged
project and script JSON on every request.
"""

from __future__ import annotations

import copy
import threading
from collections import OrderedDict
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast


@dataclass(frozen=True)
class _FileFingerprint:
    exists: bool
    mtime_ns: int | None
    size: int | None


def _fingerprint(path: Path) -> _FileFingerprint:
    try:
        stat = path.stat()
    except OSError:
        return _FileFingerprint(False, None, None)
    return _FileFingerprint(True, stat.st_mtime_ns, stat.st_size)


@dataclass(frozen=True)
class _CacheEntry:
    fingerprint: _FileFingerprint
    value: dict[str, Any]


class ProjectListReadCache:
    """Cache project-list JSON while checking the source file on every read."""

    def __init__(self, *, max_entries: int = 4096):
        self._max_entries = max_entries
        self._projects: OrderedDict[tuple[Path, str], _CacheEntry] = OrderedDict()
        self._scripts: OrderedDict[tuple[Path, str, str], _CacheEntry] = OrderedDict()
        self._lock = threading.RLock()
        self._resolved_roots: dict[Path, Path] = {}

    def _root(self, manager: Any) -> Path | None:
        root = getattr(manager, "projects_root", None)
        if root is None:
            root = getattr(manager, "base", None)
        if root is None:
            return None
        raw_root = Path(root)
        with self._lock:
            resolved = self._resolved_roots.get(raw_root)
            if resolved is None:
                resolved = raw_root.resolve()
                self._resolved_roots[raw_root] = resolved
            return resolved

    def _project_file(self, manager: Any, project_name: str) -> tuple[Path, tuple[Path, str]] | None:
        root = self._root(manager)
        if root is None:
            return None
        return root / project_name / "project.json", (root, project_name)

    def _script_file(self, manager: Any, project_name: str, filename: str) -> tuple[Path, tuple[Path, str, str]] | None:
        root = self._root(manager)
        if root is None:
            return None
        normalizer = cast(Callable[[str], str] | None, getattr(manager, "normalize_script_filename", None))
        normalized = normalizer(filename) if normalizer is not None else filename.removeprefix("scripts/")
        normalized_path = Path(normalized)
        if normalized_path.is_absolute() or ".." in normalized_path.parts:
            return None
        scripts_root = root / project_name / "scripts"
        candidate = scripts_root / normalized_path
        return candidate, (root, project_name, normalized)

    @staticmethod
    def _copy(value: dict[str, Any]) -> dict[str, Any]:
        return copy.deepcopy(value)

    def _get(
        self,
        entries: OrderedDict[Any, _CacheEntry],
        key: Any,
        path: Path,
        fingerprint: _FileFingerprint | None = None,
    ) -> dict[str, Any] | None:
        fingerprint = fingerprint or _fingerprint(path)
        if not fingerprint.exists:
            return None
        with self._lock:
            entry = entries.get(key)
            if entry is None or entry.fingerprint != fingerprint:
                return None
            entries.move_to_end(key)
            return self._copy(entry.value)

    def _put(
        self,
        entries: OrderedDict[Any, _CacheEntry],
        key: Any,
        path: Path,
        value: dict[str, Any],
        fingerprint: _FileFingerprint | None = None,
    ) -> None:
        fingerprint = fingerprint or _fingerprint(path)
        if not fingerprint.exists:
            return
        entry = _CacheEntry(fingerprint, self._copy(value))
        with self._lock:
            entries[key] = entry
            entries.move_to_end(key)
            while len(entries) > self._max_entries:
                entries.popitem(last=False)

    def load_project(self, manager: Any, project_name: str) -> dict[str, Any]:
        location = self._project_file(manager, project_name)
        fingerprint: _FileFingerprint | None = None
        if location is not None:
            path, key = location
            fingerprint = _fingerprint(path)
            cached = self._get(self._projects, key, path, fingerprint)
            if cached is not None:
                return cached
        value = manager.load_project(project_name)
        if location is not None:
            self._put(self._projects, location[1], location[0], value, fingerprint)
        return self._copy(value)

    def load_script(self, manager: Any, project_name: str, filename: str) -> dict[str, Any]:
        location = self._script_file(manager, project_name, filename)
        fingerprint: _FileFingerprint | None = None
        if location is not None:
            path, key = location
            fingerprint = _fingerprint(path)
            cached = self._get(self._scripts, key, path, fingerprint)
            if cached is not None:
                return cached
        value = manager.load_script(project_name, filename)
        if location is not None:
            self._put(self._scripts, location[1], location[0], value, fingerprint)
        return self._copy(value)

    def clear(self) -> None:
        with self._lock:
            self._projects.clear()
            self._scripts.clear()


_project_list_read_cache = ProjectListReadCache()


def get_project_list_read_cache() -> ProjectListReadCache:
    return _project_list_read_cache
