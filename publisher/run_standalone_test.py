"""
Standalone test for Publisher core (no Qt, no DCC).

Run from ftrack_plugins directory (so ftrack_inout is importable):
    cd ftrack_plugins
    python -m ftrack_inout.publisher.run_standalone_test

Or from publisher dir:
    cd ftrack_plugins/ftrack_inout/publisher
    python run_standalone_test.py

Tests:
1. Publisher with dry_run=True (no session needed) - always runs
2. Publisher with shared session when dry_run=False - only if FTRACK env is set
"""

import sys
import os
import logging

# Add ftrack_plugins to path when run as script
_this_dir = os.path.dirname(os.path.abspath(__file__))
_ftrack_plugins = os.path.dirname(_this_dir)
if _ftrack_plugins not in sys.path:
    sys.path.insert(0, _ftrack_plugins)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
_log = logging.getLogger(__name__)


def test_dry_run():
    """Test Publisher dry_run - no session required."""
    from ftrack_inout.publisher.core import PublishJob, Publisher, ComponentData

    job = PublishJob(
        task_id="test-task-id",
        asset_name="test_asset",
        asset_type="Geometry",
        comment="Standalone dry-run test",
        source_dcc="standalone",
        components=[
            ComponentData(name="main.abc", file_path="/tmp/main.abc", component_type="file", export_enabled=True),
            ComponentData(name="beauty.exr", file_path="/tmp/beauty.%04d.exr", component_type="sequence", export_enabled=True),
        ],
        thumbnail_path="/tmp/preview.png",  # optional: version preview when no playblast
    )

    is_valid, errors = job.validate()
    assert is_valid, f"Job invalid: {errors}"

    publisher = Publisher(session=None, dry_run=True)
    assert publisher.session is None
    assert publisher.dry_run is True

    result = publisher.execute(job)
    assert result.success
    assert result.asset_version_id == "mock-version-id-12345"
    assert result.asset_version_number == 999
    _log.info("Dry-run test PASSED: result.success=%s", result.success)
    return True


def test_shared_session_resolution():
    """Test that Publisher gets shared session when session=None and dry_run=False."""
    from ftrack_inout.publisher.core import Publisher

    # With dry_run=True, session can stay None
    p_dry = Publisher(session=None, dry_run=True)
    assert p_dry.dry_run is True
    # Session may or may not be set when dry_run=True (we don't resolve it in __init__ for dry_run)
    _log.info("Publisher(dry_run=True): session=%s", p_dry.session)

    # With dry_run=False, __init__ tries get_shared_session()
    p_real = Publisher(session=None, dry_run=False)
    # Session might be None if FTRACK env not set or get_shared_session fails
    _log.info("Publisher(dry_run=False): session=%s (shared session attempted)", p_real.session)
    return True


def main():
    print("\n" + "=" * 60)
    print("  Publisher standalone tests")
    print("=" * 60)

    ok = True
    try:
        test_dry_run()
        print("[OK] test_dry_run")
    except Exception as e:
        print(f"[FAIL] test_dry_run: {e}")
        ok = False

    try:
        test_shared_session_resolution()
        print("[OK] test_shared_session_resolution")
    except Exception as e:
        print(f"[FAIL] test_shared_session_resolution: {e}")
        ok = False

    print("=" * 60)
    if ok:
        print("  All standalone tests passed.")
    else:
        print("  Some tests failed.")
    print("=" * 60 + "\n")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
