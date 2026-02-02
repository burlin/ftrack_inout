"""
Ftrack Browser - Modular Qt-based browser for Houdini

A refactored, modular version of the Ftrack Browser panel with clean separation
of concerns and better maintainability.

Components:
- FtrackBrowser: Main Qt widget
- FtrackApiClient: API client with caching
- DataLoader: Background data loading
- Cache wrappers: Performance optimization
"""

# Dependencies path setup is handled in individual modules as needed

# Version info
__version__ = "2.0.0"
__author__ = "Ftrack Integration Team"

# Main exports - Using OPTIMIZED version for performance
# Ensure expected Qt binding is present on Houdini 21.x (PySide6)
_qt_ok = True
try:
    import PySide6  # noqa: F401
except Exception as _qt_err:
    _qt_ok = False
    print(f"[FAIL] PySide6 not available for 21.x environment: {_qt_err}")

if _qt_ok:
    try:
        # Import browser directly - it already uses OptimizedFtrackApiClient internally
        from .browser_widget import FtrackTaskBrowser
        FtrackBrowser = FtrackTaskBrowser
        print("[OK] Using Ftrack Browser with OptimizedFtrackApiClient")
    except ImportError as e:
        FtrackBrowser = None
        FtrackTaskBrowser = None
        print(f"[FAIL] No browser available: {e}")
else:
    FtrackBrowser = None
    FtrackTaskBrowser = None

try:
    from .api_client import FtrackApiClient
except ImportError:
    # Use existing API client during migration
    try:
        from ..ftrack_hou_utils.api_client import FtrackApiClient
    except ImportError:
        FtrackApiClient = None

# Import completed modules (conditionally)
try:
    from .cache_wrapper import (
        MemoryCacheWrapper, 
        LoggingCacheWrapper, 
        create_optimized_cache,
        get_cache_stats
    )
    cache_available = True
except ImportError as e:
    print(f"Cache wrapper not available: {e}")
    MemoryCacheWrapper = None
    LoggingCacheWrapper = None
    create_optimized_cache = None
    get_cache_stats = None
    cache_available = False

try:
    from .data_loader import DataLoader, BackgroundLoader
    data_loader_available = True
except ImportError as e:
    print(f"Data loader not available: {e}")
    DataLoader = None
    BackgroundLoader = None
    data_loader_available = False

try:
    from .user_tasks_widget import UserTasksWidget
    print("[ftrack_inout.browser] [OK] UserTasksWidget imported successfully")
except Exception as e:
    import traceback
    print(f"[ftrack_inout.browser] [FAIL] Failed to import UserTasksWidget: {e}")
    print(f"[ftrack_inout.browser] Traceback:\n{traceback.format_exc()}")
    UserTasksWidget = None  # type: ignore

# Additional components (will be added during migration)
__all__ = [
    'FtrackBrowser',
    'FtrackTaskBrowser',  # Backward compatibility alias
    'FtrackApiClient',
    # Cache components
    'MemoryCacheWrapper',
    'LoggingCacheWrapper', 
    'create_optimized_cache',
    'get_cache_stats',
    # Data loader components
    'DataLoader',
    'BackgroundLoader',
    # Additional UI components
    'UserTasksWidget',
]

# Migration status tracking  
MIGRATION_STATUS = {
    'api_client': True,                   # [OK] COMPLETED - integrated with existing ftrack_hou_utils
    'cache_wrapper': cache_available,     # [OK] COMPLETED - cache_wrapper.py is ready
    'data_loader': data_loader_available, # [OK] COMPLETED - data_loader.py is ready  
    'browser_widget': FtrackBrowser is not None, # [OK] COMPLETED - browser_widget_optimized.py is ready
    'ui_helpers': True,                   # [OK] COMPLETED - functionality integrated into browser_widget
    'optimization': True,                 # [OK] COMPLETED - using optimized browser version with enhanced caching
}

def get_migration_progress():
    """Get current migration progress"""
    completed = sum(MIGRATION_STATUS.values())
    total = len(MIGRATION_STATUS)
    return f"{completed}/{total} modules migrated ({completed/total*100:.1f}%)"

def createInterface():
    """Entry point for Houdini Python Panel - maintains compatibility"""
    if FtrackBrowser:
        return FtrackBrowser()
    else:
        # Fallback to embedded version during migration
        raise ImportError(
            "Modular FtrackBrowser not ready yet. "
            f"Migration progress: {get_migration_progress()}"
        ) 