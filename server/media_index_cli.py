"""Operational MediaAsset scanner and reconciliation command."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from server.services.media_indexing import (
    audit_project_media_assets,
    retry_project_media_reconciliation,
    scan_project_media_assets,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Scan a SHOTWISE project without changing physical media files.")
    parser.add_argument("--project-root", required=True, type=Path)
    parser.add_argument("--project-id")
    parser.add_argument("--dry-run", action="store_true", help="inspect candidates without writing the index")
    parser.add_argument("--report", type=Path, help="also write the JSON report to this path")
    parser.add_argument("--retry", action="store_true", help="retry unresolved registration and binding records")
    args = parser.parse_args(argv)
    project_root = args.project_root.resolve()
    project_id = args.project_id or project_root.name
    scan = (
        audit_project_media_assets(project_id, project_root)
        if args.dry_run
        else scan_project_media_assets(project_id, project_root)
    )
    result: dict[str, object] = {"scan": scan}
    if args.retry and args.dry_run:
        parser.error("--retry cannot be combined with --dry-run")
    if args.retry:
        result["retry"] = retry_project_media_reconciliation(project_id, project_root)
    payload = json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True)
    if args.report is not None:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(payload, encoding="utf-8")
    print(payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
