import importlib.util
import sys
from pathlib import Path


def _load_audit_module():
    repo_root = Path(__file__).resolve().parents[1]
    module_path = repo_root / "tools" / "audit_large_assets.py"
    spec = importlib.util.spec_from_file_location("audit_large_assets", module_path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_build_duplicate_groups_merges_same_size_and_hash_records():
    audit = _load_audit_module()
    records = [
        audit.AssetRecord(path="examples/a.pgm", size_bytes=10, sha256="same", top_level="examples"),
        audit.AssetRecord(path="tests/b.pgm", size_bytes=10, sha256="same", top_level="tests"),
        audit.AssetRecord(path="examples/c.pgm", size_bytes=8, sha256="other", top_level="examples"),
    ]

    duplicate_groups = audit.build_duplicate_groups(records)

    assert duplicate_groups == [
        {
            "size_bytes": 10,
            "sha256": "same",
            "count": 2,
            "paths": ["examples/a.pgm", "tests/b.pgm"],
            "top_levels": ["examples", "tests"],
        }
    ]
