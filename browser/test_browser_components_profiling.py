#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Test script for profiling browser component loading performance.

USE CASE: Identify bottlenecks in get_components_with_paths_for_version flow.
Run this script first, measure timings, test hypotheses. Only after confirming
a fix works here — apply changes to production code.

Usage (from workspace root or ftrack_plugins):
  python ftrack_plugins/ftrack_inout/browser/test_browser_components_profiling.py [VERSION_ID]
  python ftrack_plugins/ftrack_inout/browser/test_browser_components_profiling.py  # auto-discover version

Example:
  python ftrack_plugins/ftrack_inout/browser/test_browser_components_profiling.py df6c9127-c854-471c-b83d-caf9f3f011a2
"""

import sys
import os
import time
import argparse
import types
from pathlib import Path

# Python 3.12+ compat: imp + distutils stubs (ftrack_api deps) - same as run_browser.py
if sys.version_info >= (3, 12):
    if "imp" not in sys.modules:
        imp_stub = types.ModuleType("imp")
        imp_stub.find_module = lambda n, p=None: None
        def _load_module(n, f=None, p=None, d=None):
            raise ImportError("imp.load_module removed in Python 3.12+")
        imp_stub.load_module = _load_module
        imp_stub.new_module = lambda n: types.ModuleType(n)
        imp_stub.get_suffixes = lambda: []
        imp_stub.acquire_lock = imp_stub.release_lock = lambda: None
        sys.modules["imp"] = imp_stub
    if "distutils" not in sys.modules:
        import re
        class _LooseVersion:
            def __init__(self, v): self.v = str(v); self.version = [int(x) if x.isdigit() else x for x in re.findall(r"\d+|[a-zA-Z]+", self.v)]
            def __gt__(self, o): return self.version > (o.version if isinstance(o, _LooseVersion) else _LooseVersion(str(o)).version)
            def __lt__(self, o): return self.version < (o.version if isinstance(o, _LooseVersion) else _LooseVersion(str(o)).version)
            def __eq__(self, o): return self.version == (o.version if isinstance(o, _LooseVersion) else _LooseVersion(str(o)).version)
        dv = types.ModuleType("distutils.version")
        dv.LooseVersion = _LooseVersion
        dm = types.ModuleType("distutils")
        dm.version = dv
        sys.modules["distutils"] = dm
        sys.modules["distutils.version"] = dv

# Bootstrap: same as run_browser.py / test_browser_cache.py (ftrack_api, .env, plugins)
_script_path = Path(__file__).resolve()
_ftrack_inout_root = _script_path.parent.parent
_ftrack_plugins_root = _ftrack_inout_root.parent
_project_root = _ftrack_plugins_root.parent

if str(_ftrack_plugins_root) not in sys.path:
    sys.path.insert(0, str(_ftrack_plugins_root))
for subpath in ("ftrack_inout/dependencies", "multi-site-location-0.2.0/dependencies"):
    deps = _ftrack_plugins_root / subpath
    if deps.is_dir() and str(deps) not in sys.path:
        sys.path.insert(0, str(deps))

os.environ.setdefault("FTRACK_CONNECT_PLUGIN_PATH", str(_ftrack_plugins_root))


def _load_dotenv(path: Path) -> None:
    if not path.is_file():
        return
    try:
        from dotenv import load_dotenv
        load_dotenv(dotenv_path=str(path))
    except Exception:
        try:
            for line in path.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if line and "=" in line and not line.startswith("#"):
                    k, v = line.split("=", 1)
                    os.environ.setdefault(k.strip(), v.strip().strip("'\""))

        except Exception:
            pass


_load_dotenv(_project_root / "config" / ".env")
config_json = _project_root / "config" / "mroya.json"
if config_json.is_file():
    try:
        import json
        for k, v in json.loads(config_json.read_text(encoding="utf-8")).items():
            os.environ.setdefault(str(k), str(v))
    except Exception:
        pass

# Pre-import ftrack_api so session_factory finds it (same order as run_browser)
try:
    import ftrack_api  # noqa: F401
except ImportError as e:
    print(f"[WARN] ftrack_api import failed: {e}")
    print(f"  sys.path[:5] = {sys.path[:5]}")


def _timed(label, fn, *args, **kwargs):
    """Run fn and return (result, elapsed_ms)."""
    start = time.perf_counter()
    try:
        result = fn(*args, **kwargs)
        return result, (time.perf_counter() - start) * 1000
    except Exception as e:
        elapsed = (time.perf_counter() - start) * 1000
        raise RuntimeError(f"{label} failed after {elapsed:.0f}ms: {e}") from e


def run_profiling(version_id: str) -> None:
    """Profile each step of the get_components_with_paths flow."""
    print("=" * 60)
    print("BROWSER COMPONENTS PROFILING TEST")
    print("=" * 60)
    print(f"Version ID: {version_id}")
    print()

    # --- Session ---
    print("[1] Session (shared, cached)")
    from ftrack_inout.common.session_factory import get_shared_session
    session, t1 = _timed("get_shared_session", get_shared_session)
    if not session:
        print("  [FAIL] No session")
        return
    print(f"  Time: {t1:.1f}ms")

    # --- Query component IDs ---
    print("\n[2] Query component IDs")
    def _query():
        q = f'select id, name, file_type, component_locations.location.name, component_locations.location.label from Component where version.id is "{version_id}"'
        return session.query(q).all()
    comps_raw, t2 = _timed("query components", _query)
    print(f"  Time: {t2:.1f}ms")
    print(f"  Count: {len(comps_raw)}")
    if not comps_raw:
        print("  [WARN] No components found")
        return

    comp_ids = [c["id"] for c in comps_raw]

    # --- session.get per component ---
    print("\n[3] session.get('Component', id) per component")
    components = []
    t3_start = time.perf_counter()
    for i, cid in enumerate(comp_ids):
        t0 = time.perf_counter()
        c = session.get("Component", cid)
        elapsed = (time.perf_counter() - t0) * 1000
        if elapsed > 50:
            print(f"  [SLOW] component {i+1}: {elapsed:.0f}ms")
        if c:
            components.append(c)
    t3 = (time.perf_counter() - t3_start) * 1000
    print(f"  Time (total): {t3:.1f}ms")
    print(f"  Time per component: {t3 / len(comp_ids):.1f}ms" if comp_ids else "  N/A")

    # --- populate(sequence_components, 'members') - only when show_sequence_frame_range (browser respects config) ---
    from ftrack_inout.browser.browser_config_loader import get_show_sequence_frame_range
    seq_comps = [c for c in components if getattr(c, "entity_type", None) == "SequenceComponent"]
    t3b = 0.0
    if seq_comps and get_show_sequence_frame_range():
        print("\n[3b] session.populate(sequence_components, 'members') [show_sequence_frame_range=True]")
        t3b_start = time.perf_counter()
        try:
            session.populate(seq_comps, "members")
            t3b = (time.perf_counter() - t3b_start) * 1000
            print(f"  Time: {t3b:.1f}ms, count: {len(seq_comps)}")
            for sc in seq_comps:
                members = sc.get("members") or []
                print(f"  Members: {len(members)}")
        except Exception as e:
            print(f"  [ERROR] {e}")
    else:
        print("\n[3b] SKIP populate(members) (show_sequence_frame_range=False or no SequenceComponents)")

    # --- pick_location ---
    print("\n[4] session.pick_location()")
    location, t4 = _timed("pick_location", session.pick_location)
    print(f"  Time: {t4:.1f}ms")
    if location:
        print(f"  Location: {location.get('name', '?')} / {location.get('label', '?')}")
    else:
        print("  [WARN] No location")

    # --- get_filesystem_path per component (main suspect) ---
    print("\n[5] location.get_filesystem_path(component) per component")
    paths = []
    t5_start = time.perf_counter()
    for i, comp in enumerate(components):
        if not location:
            paths.append("")
            continue
        t0 = time.perf_counter()
        try:
            p = location.get_filesystem_path(comp)
            paths.append(p or "")
        except Exception as e:
            paths.append("")
            print(f"  [ERROR] component {i+1}: {e}")
        elapsed = (time.perf_counter() - t0) * 1000
        if elapsed > 100:
            print(f"  [SLOW] component {i+1} ({comp.get('name','?')}): {elapsed:.0f}ms")
        else:
            print(f"  component {i+1}: {elapsed:.1f}ms")
    t5 = (time.perf_counter() - t5_start) * 1000
    print(f"  Time (total): {t5:.1f}ms")
    if components:
        print(f"  Time per component: {t5 / len(components):.1f}ms")

    # --- component.get('component_locations') + comp_loc.get('location') (lazy load?) ---
    print("\n[6] component_locations + comp_loc.get('location') - like browser (each may lazy-load)")
    t6_start = time.perf_counter()
    for comp in components:
        comp_locs = comp.get("component_locations", [])
        for i, comp_loc in enumerate(comp_locs):
            t0 = time.perf_counter()
            loc_entity = comp_loc.get("location")
            if loc_entity:
                _ = loc_entity.get("label") or loc_entity.get("name")
            elapsed = (time.perf_counter() - t0) * 1000
            if elapsed > 100:
                print(f"  [SLOW] comp_loc[{i}].get('location'): {elapsed:.0f}ms")
    t6 = (time.perf_counter() - t6_start) * 1000
    print(f"  Time (total): {t6:.1f}ms")

    # --- Batch get_filesystem_paths (hypothesis: faster) ---
    print("\n[7] location.get_filesystem_paths(components) - BATCH")
    if location and components:
        try:
            _, t7 = _timed("get_filesystem_paths (batch)", location.get_filesystem_paths, components)
            print(f"  Time: {t7:.1f}ms")
        except Exception as e:
            print(f"  [ERROR] {e}")
    else:
        print("  [SKIP] No location or components")

    # --- Summary ---
    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)
    total = t1 + t2 + t3 + t3b + t4 + t5 + t6
    print(f"  Session:        {t1:8.1f}ms")
    print(f"  Query:          {t2:8.1f}ms")
    print(f"  session.get:    {t3:8.1f}ms")
    print(f"  populate(members): {t3b:8.1f}ms")
    print(f"  pick_location:  {t4:8.1f}ms")
    print(f"  get_filesystem_path: {t5:8.1f}ms")
    print(f"  component_locations: {t6:8.1f}ms")
    print(f"  TOTAL:          {total:8.1f}ms")
    if t3b > 1000:
        print("\n  >>> BOTTLENECK: populate(members) - step 3b")
    if t5 > 1000:
        print("  >>> BOTTLENECK: get_filesystem_path (step 5)")
    if t4 > 1000:
        print("  >>> BOTTLENECK: pick_location (step 4)")
    if t6 > 1000:
        print("  >>> BOTTLENECK: component_locations iteration (step 6)")
    if t3 > 1000:
        print("  >>> BOTTLENECK: session.get (step 3)")


def discover_version_id(session):
    """Find first AssetVersion ID from first project."""
    projects = session.query("Project where status is \"Active\"").all()
    if not projects:
        projects = session.query("Project").all()
    for proj in projects[:3]:
        av = session.query(
            f'select id from AssetVersion where asset.parent.project_id is "{proj["id"]}"'
        ).first()
        if av:
            return av["id"]
    return None


def run_browser_api_path(version_id: str) -> None:
    """Profile via OptimizedFtrackApiClient.get_components_with_paths_for_version (exact browser path)."""
    print("=" * 60)
    print("BROWSER API PATH (OptimizedFtrackApiClient)")
    print("=" * 60)
    print(f"Version ID: {version_id}\n")

    from ftrack_inout.common.session_factory import get_shared_session
    from ftrack_inout.browser.browser_config_loader import get_show_sequence_frame_range
    from ftrack_inout.browser.browser_widget_optimized import OptimizedFtrackApiClient

    print(f"show_sequence_frame_range: {get_show_sequence_frame_range()} (populate(members) skipped when False)")

    session = get_shared_session()
    if not session:
        print("[FAIL] No session")
        return

    api = OptimizedFtrackApiClient()
    t0 = time.perf_counter()
    result = api.get_components_with_paths_for_version(version_id, force_refresh=False)
    elapsed = (time.perf_counter() - t0) * 1000
    print(f"get_components_with_paths_for_version: {elapsed:.0f}ms")
    print(f"Components returned: {len(result) if result else 0}")


def main():
    parser = argparse.ArgumentParser(description="Profile browser component loading")
    parser.add_argument("version_id", nargs="?", help="AssetVersion ID (optional)")
    parser.add_argument("--api", action="store_true", help="Also run via OptimizedFtrackApiClient (browser path)")
    args = parser.parse_args()

    version_id = args.version_id
    if not version_id:
        print("No version_id given, discovering from first project...")
        from ftrack_inout.common.session_factory import get_shared_session
        session = get_shared_session()
        if not session:
            print("[FAIL] No session")
            sys.exit(1)
        version_id = discover_version_id(session)
        if not version_id:
            print("[FAIL] No AssetVersion found")
            sys.exit(1)
        print(f"Using version_id: {version_id}\n")

    run_profiling(version_id)
    if args.api:
        print()
        run_browser_api_path(version_id)


if __name__ == "__main__":
    main()
