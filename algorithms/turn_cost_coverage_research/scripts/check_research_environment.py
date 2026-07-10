"""检查带转角代价覆盖规划研究环境。"""

from __future__ import annotations

import importlib
import json
import os
import sys
from dataclasses import dataclass


REQUIRED_MODULES = (
    "numpy",
    "scipy",
    "shapely",
    "networkx",
    "matplotlib",
    "cv2",
    "yaml",
    "pytest",
)

OPTIONAL_MODULES = (
    "gmsh",
    "pygmsh",
    "skimage",
    "gurobipy",
)


@dataclass(frozen=True)
class ModuleStatus:
    name: str
    available: bool
    version: str
    error: str

    def to_dict(self) -> dict[str, object]:
        return {
            "name": self.name,
            "available": self.available,
            "version": self.version,
            "error": self.error,
        }


def check_module(name: str) -> ModuleStatus:
    try:
        module = importlib.import_module(name)
    except Exception as exc:  # pragma: no cover - command-line diagnostics
        return ModuleStatus(name=name, available=False, version="", error=f"{type(exc).__name__}: {exc}")
    version = str(getattr(module, "__version__", ""))
    return ModuleStatus(name=name, available=True, version=version, error="")


def main() -> int:
    required = [check_module(name) for name in REQUIRED_MODULES]
    optional = [check_module(name) for name in OPTIONAL_MODULES]
    payload = {
        "python": {
            "executable": sys.executable,
            "version": sys.version.replace("\n", " "),
            "prefix": sys.prefix,
            "base_prefix": sys.base_prefix,
            "pythonpath": os.environ.get("PYTHONPATH", ""),
        },
        "required": [status.to_dict() for status in required],
        "optional": [status.to_dict() for status in optional],
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    missing_required = [status.name for status in required if not status.available]
    if missing_required:
        print("缺少必需依赖: " + ", ".join(missing_required), file=sys.stderr)
        return 1
    missing_optional = [status.name for status in optional if not status.available]
    if missing_optional:
        print("缺少可选依赖: " + ", ".join(missing_optional), file=sys.stderr)
    if os.environ.get("PYTHONPATH"):
        print("检测到 PYTHONPATH，研究命令建议使用 env -u PYTHONPATH 运行。", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
