"""
Shared Ftrack session factory with optimized caching.

This module provides a unified way to create Ftrack sessions with optimized
caching across all ftrack_inout plugins (browser, Asset Watcher, Houdini, Maya, etc.).

Uses FTRACK_CACHE environment variable and implements the proven caching strategy:
1. Fast queries for IDs only
2. session.get() for batch loading into memory cache
3. Layered cache: FileCache -> SerialisedCache -> MemoryCacheWrapper -> LoggingCacheWrapper
"""

import os
import sys
import tempfile
import logging
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# Try to import ftrack_api
FTRACK_API_AVAILABLE = False
ftrack_api = None
try:
    import ftrack_api
    import ftrack_api.cache
    FTRACK_API_AVAILABLE = True
except ImportError:
    logger.warning("ftrack_api not available - session creation will fail")

# Import cache components from common module
try:
    from .cache_wrapper import MemoryCacheWrapper, LoggingCacheWrapper
    CACHE_COMPONENTS_AVAILABLE = True
except ImportError:
    logger.warning("Cache components not available")
    CACHE_COMPONENTS_AVAILABLE = False
    MemoryCacheWrapper = None
    LoggingCacheWrapper = None

# Optional python-dotenv for dev environments
try:
    import dotenv
except ImportError:
    dotenv = None

# Global session cache
_shared_session: Optional["ftrack_api.Session"] = None


def _add_locations_if_available(session: "ftrack_api.Session") -> None:
    """Register S3 / user locations if multi-site plugin is available.
    
    Safely silent if plugin is not available.
    """
    try:
        # Determine plugin path relative to this file
        this_file = Path(__file__).resolve()
        ftrack_inout_root = this_file.parent.parent
        ftrack_plugins_root = ftrack_inout_root.parent
        multi_site_plugin_path = ftrack_plugins_root / "multi-site-location-0.2.0"
        
        if not multi_site_plugin_path.is_dir():
            logger.debug("Multi-site plugin path not found: %s", multi_site_plugin_path)
            return

        # Load plugin .env if python-dotenv is available
        if dotenv is not None:
            env_path = multi_site_plugin_path / ".env"
            if env_path.is_file():
                dotenv.load_dotenv(env_path)
                logger.debug("Loaded .env from multi-site plugin")

        hook_locations_path = multi_site_plugin_path / "hook" / "locations"
        if not hook_locations_path.is_dir():
            logger.debug("Multi-site hook/locations path not found: %s", hook_locations_path)
            return

        # Add path to hook/locations in sys.path
        hook_str = str(hook_locations_path)
        if hook_str not in sys.path:
            sys.path.insert(0, hook_str)
            logger.debug("Added multi-site hook/locations to sys.path: %s", hook_str)

        # Import location plugins
        try:
            import s3_location_plugin
            import user_location_plugin
            logger.debug("Successfully imported multi-site location plugins")
        except ImportError as import_exc:
            logger.warning("Failed to import multi-site location plugins: %s", import_exc)
            return

        # Register locations
        s3_location_plugin.session_add_s3_location(session)

        location_setup = user_location_plugin.load_location_config(
            config_path=hook_locations_path / "disk_locations.yaml",
            user_name=session.api_user,
        )
        user_location_plugin.session_add_user_location(session, location_setup)

        logger.info("Multi-site locations registered successfully")
    except Exception as exc:
        logger.warning("Failed to register multi-site locations: %s", exc)


def _create_cache_maker(logger_instance=None):
    """Create a cache maker function for ftrack session.
    
    Returns a function that creates an optimized cache chain when called by ftrack.
    """
    log = logger_instance or logger
    
    def cache_maker(session_instance):
        """Return cache instance for session."""
        # Get cache path from environment
        cache_path_from_env = os.environ.get('FTRACK_CACHE')
        
        # Use temporary directory if no cache path provided
        if not cache_path_from_env:
            cache_path_from_env = os.path.join(
                tempfile.gettempdir(), 'ftrack_cache'
            )
            log.info(
                'FTRACK_CACHE not set, using temporary directory: {0}'.format(
                    cache_path_from_env
                )
            )

        # Standard ftrack cache filename
        cache_filename = "ftrack_cache_db"
        
        # Determine cache path and directory
        if os.path.isdir(cache_path_from_env):
            cache_path = os.path.join(cache_path_from_env, cache_filename)
            cache_dir = cache_path_from_env
        else:
            cache_path = cache_path_from_env
            cache_dir = os.path.dirname(cache_path)

        log.info("Using FileCache at path: {0}".format(cache_path))
        
        # Ensure directory exists
        if not os.path.exists(cache_dir):
            try:
                os.makedirs(cache_dir)
                log.info("Created cache directory: {0}".format(cache_dir))
            except OSError as e:
                log.error(
                    "Could not create cache directory {0}: {1}".format(
                        cache_dir, e
                    )
                )
                return ftrack_api.cache.MemoryCache()

        # Create file cache
        file_cache = ftrack_api.cache.FileCache(cache_path)
        
        # Create serialized cache
        serialised_cache = ftrack_api.cache.SerialisedCache(
            file_cache,
            encode=lambda obj: session_instance.encode(obj),
            decode=lambda data: session_instance.decode(data)
        )

        # Wrap in custom wrappers if available
        if CACHE_COMPONENTS_AVAILABLE and MemoryCacheWrapper and LoggingCacheWrapper:
            try:
                log.info("Creating optimized cache chain...")
                
                # Large memory cache for full dataset (200K items)
                log.info("Creating MemoryCacheWrapper with 200K max items...")
                memory_cache = MemoryCacheWrapper(serialised_cache, max_size=200000)
                log.info("Created MemoryCacheWrapper: {0}".format(type(memory_cache)))
                
                log.info("Creating LoggingCacheWrapper...")
                logging_wrapped_cache = LoggingCacheWrapper(memory_cache, log)
                log.info("Created LoggingCacheWrapper: {0}".format(type(logging_wrapped_cache)))
                
                log.info("[OK] OPTIMIZED CACHE CHAIN CREATED!")
                log.info("Cache chain: LoggingCacheWrapper -> MemoryCacheWrapper -> SerialisedCache -> FileCache")
                return logging_wrapped_cache
            except Exception as e:
                log.warning("Failed to create optimized cache: {0}".format(e))
                import traceback
                traceback.print_exc()
                return serialised_cache
        else:
            log.warning("[FAIL] Cache components not available - using basic cache")
            return serialised_cache
    
    return cache_maker


def create_shared_session(
    enable_locations: bool = True,
    logger_instance: Optional[logging.Logger] = None
) -> Optional["ftrack_api.Session"]:
    """
    Create a shared Ftrack session with optimized caching.
    
    This function creates a session using the FTRACK_CACHE environment variable
    and implements the proven caching strategy from the browser.
    
    Args:
        enable_locations: Whether to register multi-site locations (default: True)
        logger_instance: Optional logger instance (default: uses module logger)
        
    Returns:
        Ftrack session instance, or None if creation failed
    """
    global _shared_session
    
    if _shared_session is not None:
        logger.debug("Returning existing shared session")
        return _shared_session
    
    if not FTRACK_API_AVAILABLE:
        logger.error("ftrack_api not available - cannot create session")
        return None
    
    log = logger_instance or logger
    
    try:
        log.info("Creating ftrack session with optimized cache...")
        
        # Create cache maker
        cache_maker = _create_cache_maker(log)
        
        # Create session with custom cache
        try:
            session = ftrack_api.Session(cache=cache_maker)
        except AttributeError as e:
            if "'str' object has no attribute 'merge'" in str(e):
                log.warning("Session creation failed with merge error, trying fallback...")
                session = ftrack_api.Session()
                log.info("Standard session created, replacing cache...")
                session.cache = cache_maker(session)
                log.info("Cache replaced successfully")
            else:
                raise
        except Exception as e:
            log.error(f"Session creation failed: {e}")
            log.info("Falling back to standard session...")
            session = ftrack_api.Session()
            log.info("Standard session created as fallback")
        
        log.info(f"Session created: {type(session)}")
        log.info(f"Session.cache type: {type(session.cache)}")

        # Register locations if requested
        if session and enable_locations:
            try:
                _add_locations_if_available(session)
            except Exception as e:
                log.warning("Multi-site locations bootstrap failed: %s", e)
        
        # Cache the session
        _shared_session = session
        
        return session
        
    except Exception as e:
        log.error(f"Failed to create Ftrack session: {e}")
        import traceback
        traceback.print_exc()
        return None


def get_shared_session() -> Optional["ftrack_api.Session"]:
    """
    Get the shared Ftrack session, creating it if necessary.
    
    Returns:
        Ftrack session instance, or None if creation failed
    """
    if _shared_session is None:
        return create_shared_session()
    return _shared_session


def reset_shared_session():
    """Reset the shared session (useful for testing or reconnection)."""
    global _shared_session
    if _shared_session is not None:
        try:
            _shared_session.close()
        except Exception:
            pass
    _shared_session = None
    logger.info("Shared session reset")
