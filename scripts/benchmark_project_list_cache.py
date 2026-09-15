#!/usr/bin/env python3
"""Benchmark project-list JSON cache behavior without external services.

The benchmark measures cold-cache and warm-cache request latency, concurrent
warm-cache latency, and the number of JSON loads for distinct project/script
inputs. It is intentionally a standalone developer tool rather than a pytest
benchmark, so it can be run with different synthetic data sizes.

Usage:
    uv run python scripts/benchmark_project_list_cache.py
    uv run python scripts/benchmark_project_list_cache.py --projects 500 --episodes 20 --concurrent-requests 8
"""

from __future__ import annotations

import argparse
import json
import statistics
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Lock
from typing import Any

from server.services.project_list_cache import ProjectListReadCache


class _BenchmarkProjectManager:
    def __init__(self, root: Path):
        self.projects_root = root
        self.project_loads = 0
        self.script_loads = 0
        self._lock = Lock()

    @staticmethod
    def normalize_script_filename(filename: str) -> str:
        return filename.removeprefix("scripts/")

    def load_project(self, name: str) -> dict[str, Any]:
        with self._lock:
            self.project_loads += 1
        path = self.projects_root / name / "project.json"
        return json.loads(path.read_text(encoding="utf-8"))

    def load_script(self, name: str, filename: str) -> dict[str, Any]:
        with self._lock:
            self.script_loads += 1
        path = self.projects_root / name / "scripts" / self.normalize_script_filename(filename)
        return json.loads(path.read_text(encoding="utf-8"))

    @property
    def json_loads(self) -> int:
        with self._lock:
            return self.project_loads + self.script_loads


def _write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")


def _create_fixture(root: Path, project_count: int, episode_count: int) -> list[str]:
    names: list[str] = []
    for project_index in range(project_count):
        name = f"project-{project_index}"
        names.append(name)
        _write_json(root / name / "project.json", {"name": name})
        for episode_index in range(episode_count):
            _write_json(
                root / name / "scripts" / f"episode_{episode_index}.json",
                {"episode": episode_index, "project": name},
            )
    return names


def _load_project_bundle(
    cache: ProjectListReadCache,
    manager: _BenchmarkProjectManager,
    name: str,
    episode_count: int,
) -> None:
    cache.load_project(manager, name)
    for episode_index in range(episode_count):
        cache.load_script(manager, name, f"scripts/episode_{episode_index}.json")


def _measure_sequential(
    cache: ProjectListReadCache,
    manager: _BenchmarkProjectManager,
    names: list[str],
    episode_count: int,
) -> list[float]:
    durations: list[float] = []
    for name in names:
        started = time.perf_counter()
        _load_project_bundle(cache, manager, name, episode_count)
        durations.append((time.perf_counter() - started) * 1000)
    return durations


def _measure_concurrent(
    cache: ProjectListReadCache,
    manager: _BenchmarkProjectManager,
    names: list[str],
    episode_count: int,
    request_count: int,
) -> list[float]:
    with ThreadPoolExecutor(max_workers=request_count) as executor:
        futures = []
        for _ in range(request_count):
            for name in names:
                futures.append(executor.submit(_timed_bundle, cache, manager, name, episode_count))
        return [future.result() for future in futures]


def _timed_bundle(
    cache: ProjectListReadCache,
    manager: _BenchmarkProjectManager,
    name: str,
    episode_count: int,
) -> float:
    started = time.perf_counter()
    _load_project_bundle(cache, manager, name, episode_count)
    return (time.perf_counter() - started) * 1000


def _percentile(values: list[float], percentile: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    rank = (len(ordered) - 1) * percentile
    lower = int(rank)
    upper = min(lower + 1, len(ordered) - 1)
    fraction = rank - lower
    return ordered[lower] + (ordered[upper] - ordered[lower]) * fraction


def _summary(values: list[float]) -> dict[str, float]:
    return {
        "count": float(len(values)),
        "mean_ms": statistics.fmean(values) if values else 0.0,
        "p50_ms": _percentile(values, 0.50),
        "p95_ms": _percentile(values, 0.95),
        "max_ms": max(values, default=0.0),
    }


def run_benchmark(
    *,
    project_count: int,
    episode_count: int,
    concurrent_requests: int,
) -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="shotwise-project-list-benchmark-") as temporary_root:
        names = _create_fixture(Path(temporary_root), project_count, episode_count)
        manager = _BenchmarkProjectManager(Path(temporary_root))
        cache = ProjectListReadCache()
        cold = _measure_sequential(cache, manager, names, episode_count)
        reads_after_cold = manager.json_loads
        warm = _measure_sequential(cache, manager, names, episode_count)
        reads_after_warm = manager.json_loads
        concurrent_warm = _measure_concurrent(cache, manager, names, episode_count, concurrent_requests)
        reads_after_concurrent = manager.json_loads

    distinct_inputs = project_count * (episode_count + 1)
    return {
        "fixture": {
            "projects": project_count,
            "episodes_per_project": episode_count,
            "distinct_json_inputs": distinct_inputs,
        },
        "cold_sequential": _summary(cold),
        "warm_sequential": _summary(warm),
        "warm_concurrent": {
            **_summary(concurrent_warm),
            "concurrent_requests": concurrent_requests,
        },
        "json_loads": {
            "after_cold": reads_after_cold,
            "after_warm": reads_after_warm,
            "after_concurrent_warm": reads_after_concurrent,
            "cold_loads_per_distinct_input": reads_after_cold / distinct_inputs,
            "warm_additional_loads": reads_after_warm - reads_after_cold,
            "concurrent_warm_additional_loads": reads_after_concurrent - reads_after_warm,
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--projects", type=int, default=100, help="Synthetic project count")
    parser.add_argument("--episodes", type=int, default=10, help="Episodes per project")
    parser.add_argument(
        "--concurrent-requests",
        type=int,
        default=8,
        help="Number of concurrent warm-cache request waves",
    )
    args = parser.parse_args()
    if args.projects < 1 or args.episodes < 1 or args.concurrent_requests < 1:
        parser.error("--projects, --episodes and --concurrent-requests must be positive")
    print(
        json.dumps(
            run_benchmark(
                project_count=args.projects, episode_count=args.episodes, concurrent_requests=args.concurrent_requests
            ),
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
