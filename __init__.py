"""Top-level package for Mroya ftrack_inout tools.

This module:
- marks directory as Python package;
- ensures internal dependencies (`ftrack_inout/dependencies`) are added
  to `sys.path` in all environments (Houdini, Maya, Blender, standalone),
  so packages like `fileseq` are available to both `finput` and publisher, etc.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path


def _ensure_local_dependencies_on_path() -> None:
    """Add `ftrack_inout/dependencies` to sys.path if folder exists.

    This is a single point for third-party packages (fileseq, boto3, ftrack_api, etc.) that works
    the same in all DCCs and standalone browser, without requiring installation in
    system site-packages for users.
    """
    try:
        here = Path(__file__).resolve().parent
        # Dependencies are located in ftrack_inout/dependencies
        deps = here / "dependencies"
        if deps.is_dir():
            deps_str = str(deps)
            if deps_str not in sys.path:
                sys.path.insert(0, deps_str)
    except Exception as exc:  # pragma: no cover - defensive log
        print(f"[ftrack_inout] Failed to add local dependencies to sys.path: {exc}")


_ensure_local_dependencies_on_path()