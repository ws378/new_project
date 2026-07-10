#!/usr/bin/env python3
"""Audit tracked large assets and detect duplicate content groups."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from dataclasses import asdict, dataclass
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]


@dataclass(frozen=True)
class AssetRecord:
    path: str
    size_bytes: int
    sha256: str
    top_level: str


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--min-size-bytes",
        type=int,
        default=200_000,
        help="Only audit tracked files whose size is at least this many bytes.",
    )
    parser.add_argument(
        "--top-level",
        action="append",
        default=[],
        help="Restrict to one or more top-level directories. May be repeated.",
    )
    parser.add_argument(
        "--output-json",
        type=Path,
        default=None,
        help="Optional path to write the full audit result as JSON.",
    )
    return parser.parse_args()


def tracked_files() -> list[Path]:
    output = subprocess.check_output(["git", "ls-files"], cwd=REPO_ROOT, text=True)
    return [REPO_ROOT / line for line in output.splitlines() if line]


def compute_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def build_asset_records(*, min_size_bytes: int, allowed_top_levels: set[str]) -> list[AssetRecord]:
    records: list[AssetRecord] = []
    for path in tracked_files():
        if not path.is_file():
            continue
        rel = path.relative_to(REPO_ROOT)
        top_level = rel.parts[0] if rel.parts else "(root)"
        if allowed_top_levels and top_level not in allowed_top_levels:
            continue
        size_bytes = int(path.stat().st_size)
        if size_bytes < min_size_bytes:
            continue
        records.append(
            AssetRecord(
                path=rel.as_posix(),
                size_bytes=size_bytes,
                sha256=compute_sha256(path),
                top_level=top_level,
            )
        )
    return records


def build_duplicate_groups(records: list[AssetRecord]) -> list[dict]:
    grouped: dict[tuple[int, str], list[AssetRecord]] = {}
    for record in records:
        grouped.setdefault((record.size_bytes, record.sha256), []).append(record)

    duplicates: list[dict] = []
    for (size_bytes, sha256), group in sorted(grouped.items(), key=lambda item: (-len(item[1]), -item[0][0], item[0][1])):
        if len(group) < 2:
            continue
        duplicates.append(
            {
                "size_bytes": size_bytes,
                "sha256": sha256,
                "count": len(group),
                "paths": [record.path for record in sorted(group, key=lambda item: item.path)],
                "top_levels": sorted({record.top_level for record in group}),
            }
        )
    return duplicates


def print_summary(records: list[AssetRecord], duplicate_groups: list[dict]) -> None:
    print(f"tracked_large_asset_count={len(records)}")
    print(f"duplicate_group_count={len(duplicate_groups)}")
    for group in duplicate_groups:
        print(
            "duplicate"
            f" count={group['count']}"
            f" size_bytes={group['size_bytes']}"
            f" sha256={group['sha256'][:12]}"
            f" top_levels={','.join(group['top_levels'])}"
        )
        for path in group["paths"]:
            print(f"  {path}")


def main() -> int:
    args = parse_args()
    allowed_top_levels = set(args.top_level)
    records = build_asset_records(
        min_size_bytes=int(args.min_size_bytes),
        allowed_top_levels=allowed_top_levels,
    )
    duplicate_groups = build_duplicate_groups(records)
    print_summary(records, duplicate_groups)

    if args.output_json is not None:
        payload = {
            "version": 1,
            "min_size_bytes": int(args.min_size_bytes),
            "top_levels": sorted(allowed_top_levels),
            "asset_count": len(records),
            "duplicate_group_count": len(duplicate_groups),
            "assets": [asdict(record) for record in records],
            "duplicate_groups": duplicate_groups,
        }
        output_path = args.output_json.resolve()
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"output_json={output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
