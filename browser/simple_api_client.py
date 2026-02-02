"""
Complete Ftrack API Client - Extracted from Original Browser

This module contains the complete FtrackApiClient class with all optimizations,
caching logic, and API methods from the original browser implementation.
"""

import sys
import os
import time
import tempfile
import traceback
import logging
from pathlib import Path
from typing import Optional

# Compatibility: imp module was removed in Python 3.12+, but ftrack_api dependencies may need it
# Add imp module stub before importing ftrack_api (only for Python 3.12+)
# Note: Python 3.11 (used in Houdini/Maya) still has imp module, so this stub is not needed there
if sys.version_info >= (3, 12) and 'imp' not in sys.modules:
    import types
    # Create a minimal imp module stub for compatibility
    class ImpModule:
        """Minimal imp module stub for Python 3.12+ compatibility"""
        @staticmethod
        def find_module(name, path=None):
            return None
        @staticmethod
        def load_module(name, file=None, pathname=None, description=None):
            raise ImportError(f"imp.load_module is not supported in Python 3.12+")
        @staticmethod
        def new_module(name):
            return types.ModuleType(name)
        @staticmethod
        def get_suffixes():
            return []
        @staticmethod
        def acquire_lock():
            pass
        @staticmethod
        def release_lock():
            pass
    
    imp_stub = ImpModule()
    sys.modules['imp'] = imp_stub  # type: ignore

# Dependencies path setup - DISABLED to use system ftrack_api
# _deps_path = os.path.join(os.path.dirname(__file__), '..', 'dependencies')
# _deps_path = os.path.abspath(_deps_path)
# if os.path.exists(_deps_path) and _deps_path not in sys.path:
#     sys.path.insert(0, _deps_path)

# Configure logging
logger = logging.getLogger(__name__)

# Import cache components - fixed for Houdini compatibility
try:
    # Try relative import
    from .cache_wrapper import MemoryCacheWrapper, LoggingCacheWrapper
    CACHE_COMPONENTS_AVAILABLE = True
    logger.info("Cache components available from relative import")
except ImportError:
    try:
        # Fallback: direct import without relative path
        from cache_wrapper import MemoryCacheWrapper, LoggingCacheWrapper
        CACHE_COMPONENTS_AVAILABLE = True
        logger.info("Cache components available from direct import")
    except ImportError:
        logger.warning("Cache components not available")
        CACHE_COMPONENTS_AVAILABLE = False

# Import true bulk preloader - fixed for Houdini compatibility
try:
    # Try relative import
    from .true_bulk_preloader import TrueBulkCachePreloader, create_true_bulk_preloader
    TRUE_BULK_PRELOADER_AVAILABLE = True
    logger.info("True bulk preloader available from relative import")
except ImportError:
    try:
        # Fallback: direct import without relative path
        from true_bulk_preloader import TrueBulkCachePreloader, create_true_bulk_preloader
        TRUE_BULK_PRELOADER_AVAILABLE = True
        logger.info("True bulk preloader available from direct import")
    except ImportError:
        logger.warning("True bulk preloader not available")
        TRUE_BULK_PRELOADER_AVAILABLE = False
        # Mock functions for compatibility
        def create_true_bulk_preloader(session):
            return None

# Try to import ftrack_api with detailed error reporting
FTRACK_API_AVAILABLE = False
ftrack_api = None  # type: ignore

try:
    import ftrack_api
    import ftrack_api.cache
    import ftrack_api.symbol
    FTRACK_API_AVAILABLE = True
    logger.info("ftrack_api available")
except ImportError as import_err:
    # Log detailed error information for debugging
    logger.warning("ftrack_api not available - running in mock mode")
    logger.debug(f"Import error details: {import_err}")
    logger.debug(f"sys.path entries: {len(sys.path)}")
    logger.debug(f"First 5 sys.path entries: {sys.path[:5]}")
    
    # Check if ftrack_api might be in expected locations
    expected_paths = [
        Path(__file__).parent.parent / "dependencies",
        Path(__file__).parent.parent.parent / "multi-site-location-0.2.0" / "dependencies",
    ]
    for expected_path in expected_paths:
        ftrack_api_path = expected_path / "ftrack_api"
        if ftrack_api_path.exists():
            logger.debug(f"Found ftrack_api at: {ftrack_api_path}")
        else:
            logger.debug(f"ftrack_api NOT found at: {ftrack_api_path}")
    
    FTRACK_API_AVAILABLE = False
    # Mock ftrack_api for testing without installed ftrack
    class MockFtrackApi:
        class Session:
            def __init__(self, *args, **kwargs):
                pass
        class cache:
            class FileCache:
                def __init__(self, *args, **kwargs):
                    pass
    ftrack_api = MockFtrackApi()

# Optional python-dotenv for dev environments (to mirror dev_ftrack_session)
try:  # pragma: no cover - optional
    import dotenv  # type: ignore
except Exception:  # ImportError etc.
    dotenv = None  # type: ignore

THIS_DIR = Path(__file__).resolve().parent
FTRACK_INOUT_ROOT = THIS_DIR.parent
FTRACK_PLUGINS_ROOT = FTRACK_INOUT_ROOT.parent
MULTI_SITE_PLUGIN_PATH = FTRACK_PLUGINS_ROOT / "multi-site-location-0.2.0"


def _add_locations_if_available(session: "ftrack_api.Session") -> None:
    """Register S3 / user locations if multi-site plugin is available.

    Logic repeats dev_ftrack_session.add_locations, but without hard
    dependency on mroya_task_hub. Safely silent if plugin is not available.
    
    Uses relative paths from project structure to work
    on different machines without absolute paths.
    """
    try:
        if not MULTI_SITE_PLUGIN_PATH.is_dir():
            logger.debug("Multi-site plugin path not found: %s", MULTI_SITE_PLUGIN_PATH)
            return

        # Load plugin .env if python-dotenv is available.
        if dotenv is not None:
            env_path = MULTI_SITE_PLUGIN_PATH / ".env"
            if env_path.is_file():
                dotenv.load_dotenv(env_path)  # type: ignore[arg-type]
                logger.debug("Loaded .env from multi-site plugin")

        hook_locations_path = MULTI_SITE_PLUGIN_PATH / "hook" / "locations"
        if not hook_locations_path.is_dir():
            logger.debug("Multi-site hook/locations path not found: %s", hook_locations_path)
            return

        # Add path to hook/locations in sys.path for module imports
        # Use relative path from project structure
        hook_str = str(hook_locations_path)
        if hook_str not in sys.path:
            sys.path.insert(0, hook_str)
            logger.debug("Added multi-site hook/locations to sys.path: %s", hook_str)

        # Import location plugins (now available via sys.path)
        try:
            import s3_location_plugin  # type: ignore
            import user_location_plugin  # type: ignore
            logger.debug("Successfully imported multi-site location plugins")
        except ImportError as import_exc:
            logger.warning("Failed to import multi-site location plugins: %s", import_exc)
            return

        # Register locations into the current ftrack_api.Session immediately.
        s3_location_plugin.session_add_s3_location(session)

        location_setup = user_location_plugin.load_location_config(  # type: ignore[attr-defined]
            config_path=hook_locations_path / "disk_locations.yaml",
            user_name=session.api_user,
        )
        user_location_plugin.session_add_user_location(  # type: ignore[attr-defined]
            session, location_setup
        )

        logger.info("Multi-site locations registered successfully")
    except Exception as exc:  # pragma: no cover - best-effort
        logger.warning("Failed to register multi-site locations: %s", exc)


class FtrackApiClient:
    """Complete Optimized API Client with efficient caching - from original browser"""
    
    def __init__(self, _enable_bulk_preload=True):
        logger.info("[LAUNCH] OPTIMIZED FtrackApiClient starting...")
        self._enable_bulk_preload = _enable_bulk_preload
        
        # Import our optimized components - fixed for Houdini compatibility
        try:
            # Try relative import
            from .cache_preloader import CachePreloader
            logger.info("📦 CachePreloader imported via relative import")
        except ImportError:
            try:
                # Fallback: direct import
                from cache_preloader import CachePreloader
                logger.info("📦 CachePreloader imported via direct import")
            except ImportError as e:
                logger.warning(f"[WARN] Failed to import CachePreloader: {e}")
                CachePreloader = None
        
        logger.info("📦 Loading optimized components...")
        # Create session with cache first
        self.session = self._create_session_with_cache()
        self._preloader = CachePreloader(self.session) if (self.session and CachePreloader) else None
        
        if self._preloader:
            logger.info(f"[OK] OPTIMIZED API CLIENT READY - session: {bool(self.session)}, preloader: {bool(self._preloader)}")
        else:
            logger.warning("[WARN] Using fallback implementation without preloader")
        
        # Legacy cache dictionaries for compatibility
        self._asset_versions_cache = {}
        self._entity_assets_cache = {}
        self._entity_tasks_cache = {}
        self._entity_children_cache = {}
        self._shot_metadata_cache = {}
        self._task_metadata_cache = {}
        self._entity_metadata_cache = {}

    def get_session(self):
        """Get the ftrack session"""
        return self.session

    def _preload_entire_cache_to_memory_with_session(self, session):
        """DIRECT massive loading of entire DBM cache to memory in one pass"""
        logger.info(f"Cache preload method CALLED - session: {bool(session)}, type: {type(session)}")
        logger.info(f"Components available: {CACHE_COMPONENTS_AVAILABLE}")
        
        if not session:
            logger.error("Session is None - cannot preload cache")
            return
            
        if not CACHE_COMPONENTS_AVAILABLE:
            logger.warning("Cache components not available - falling back to query preload")
            self._preload_via_queries_with_session(session)
            return
            
        start_time = time.time()
        logger.info("Starting DIRECT cache preload - Loading entire DBM cache to memory...")
        
        try:
            # Get access to memory cache through wrapper chain
            cache = session.cache
            memory_cache = None
            
            logger.info(f"Session cache type: {type(session.cache)}")
            
            # Explore LayeredCache structure - ftrack ALWAYS creates LayeredCache
            # with MemoryCache at position 0 and our cache at position 1
            if hasattr(session.cache, '_caches'):
                caches_list = getattr(session.cache, '_caches', [])
                logger.info(f"LayeredCache contains {len(caches_list)} caches:")
                for i, cache_item in enumerate(caches_list):
                    cache_type = type(cache_item).__name__
                    logger.info(f"  Cache {i}: {cache_type}")
                    
                    # According to documentation: our cache is always at position 1 (second level)
                    if i == 1:  # Second level = our cache
                        logger.info(f"  Checking our cache at position {i}: {cache_type}")
                        
                        # Look for our LoggingCacheWrapper
                        if 'LoggingCacheWrapper' in cache_type:
                            logger.info(f"  *** FOUND our LoggingCacheWrapper at position {i} ***")
                            # Check its wrapped_cache
                            if hasattr(cache_item, 'wrapped_cache'):
                                wrapped = cache_item.wrapped_cache
                                wrapped_type = type(wrapped).__name__
                                logger.info(f"    LoggingCacheWrapper.wrapped_cache: {wrapped_type}")
                                
                                if 'MemoryCacheWrapper' in wrapped_type:
                                    memory_cache = wrapped
                                    logger.info("*** SUCCESS: Found our MemoryCacheWrapper! ***")
                                    break
                        
                        # Or our cache may be directly MemoryCacheWrapper
                        elif 'MemoryCacheWrapper' in cache_type:
                            memory_cache = cache_item
                            logger.info(f"  *** FOUND our MemoryCacheWrapper directly at position {i} ***")
                            break
                                
            # Fallback: check direct wrapped_cache
            if not memory_cache and hasattr(session.cache, 'wrapped_cache'):
                wrapped = session.cache.wrapped_cache
                logger.info(f"Session has wrapped_cache: {type(wrapped)}")
                
                # LoggingCacheWrapper -> MemoryCacheWrapper
                if hasattr(wrapped, 'wrapped_cache') and 'MemoryCacheWrapper' in str(type(wrapped)):
                    memory_cache = wrapped
                    logger.info("Found MemoryCacheWrapper via LoggingCacheWrapper")
                # Or directly MemoryCacheWrapper    
                elif 'MemoryCacheWrapper' in str(type(wrapped)):
                    memory_cache = wrapped
                    logger.info("Found MemoryCacheWrapper directly")
                    
            if not memory_cache:
                logger.warning("Could not find our MemoryCacheWrapper - falling back to query preload")
                self._preload_via_queries_with_session(session)
                return
            
            # CRITICAL: bypass ftrack's top-level MemoryCache and load data
            # directly into OUR MemoryCacheWrapper at second level
            logger.info("DIRECT preload: Loading data directly into OUR MemoryCacheWrapper...")
            logger.info("This bypasses ftrack's top-level MemoryCache to populate our cache")
            
            # Create temporary session that uses ONLY our cache
            # This allows preload to load data into our cache
            try:
                # Find our LoggingCacheWrapper at second level
                our_cache = None
                if hasattr(session.cache, '_caches') and len(session.cache._caches) > 1:
                    our_cache = session.cache._caches[1]  # Our cache at position 1
                    logger.info(f"Using our cache directly: {type(our_cache)}")
                
                if our_cache:
                    # Temporarily replace session.cache with our cache for preload
                    original_cache = session.cache
                    session.cache = our_cache
                    logger.info("Temporarily using OUR cache for preload...")
                    
                    # Now preload will load data into OUR cache
                    self._preload_via_queries_with_session(session)
                    
                    # Restore original cache
                    session.cache = original_cache
                    logger.info("Restored original LayeredCache")
                else:
                    logger.warning("Could not access our cache directly - using normal preload")
                    self._preload_via_queries_with_session(session)
                    
            except Exception as e:
                logger.error(f"Direct cache preload failed: {e}")
                # Fallback to normal preload
                self._preload_via_queries_with_session(session)
            
            # Check result
            if hasattr(memory_cache, '_memory_cache'):
                cache_size = len(memory_cache._memory_cache)
                logger.info(f"Our MemoryCacheWrapper populated: {cache_size} items")
                
                if cache_size > 0:
                    logger.info("SUCCESS: Our memory cache is now populated!")
                    logger.info("Next cache requests may show improved performance")
                else:
                    logger.warning("Our memory cache is empty after preload")
            else:
                logger.warning("Memory cache structure not as expected")
                
        except Exception as e:
            logger.warning(f"Direct preload failed: {e}")
            self._preload_via_queries_with_session(session)

    def _preload_entire_cache_to_memory(self):
        """DIRECT massive loading of entire DBM cache to memory in one pass (legacy)"""
        return self._preload_entire_cache_to_memory_with_session(self.session)
    
    def _preload_via_queries_with_session(self, session):
        """CACHING preload via session.get() to pass through cache"""
        logger.info("CACHE-AWARE preload: Loading data through cache system...")
        
        try:
            total_loaded = 0
            
            # Critical data for fast startup
            critical_queries = [
                ('Location', 'Location'),
                ('Project', 'Project'), 
                ('User', 'User'),
                ('Status', 'Status'),
            ]
            
            for name, query in critical_queries:
                try:
                    # First do query to get IDs
                    entities = session.query(query).all()
                    entity_ids = [e['id'] for e in entities]
                    
                    logger.info(f"Found {len(entity_ids)} {name} entities, loading through cache...")
                    
                    # Now load each entity via session.get()
                    # which forces data through entire cache chain
                    loaded_count = 0
                    for entity_id in entity_ids[:100]:  # Limit for performance
                        try:
                            entity = session.get(name, entity_id)
                            if entity:
                                loaded_count += 1
                                total_loaded += 1
                        except Exception as e:
                            logger.debug(f"Failed to load {name} {entity_id}: {e}")
                    
                    logger.info(f"Loaded {loaded_count}/{len(entity_ids)} {name} entities through cache")
                    
                except Exception as e:
                    logger.warning(f"Failed to preload {name}: {e}")
            
            logger.info(f"Cache-aware preload completed: {total_loaded} entities loaded")
            
        except Exception as e:
            logger.error(f"Cache-aware preload failed: {e}")

    def _preload_via_queries(self):
        """CACHING preload via session.get() to pass through cache (legacy)"""
        return self._preload_via_queries_with_session(self.session)

    def _preload_common_data(self):
        """
        OPTIMIZED data preload to achieve 0.0ms access
        
        Uses correct session.get() strategy to move
        data from FileCache to MemoryCache
        """
        if not self.session:
            return
            
        try:
            logger.info("[LAUNCH] OPTIMIZED common data preload...")
            start_time = time.time()
            
            # Preload all locations - most frequent cache misses in logs
            logger.info("📍 Preloading locations...")
            locations = self.session.query('Location').all()
            for location in locations:
                # KEY OPERATION: session.get() moves to memory cache
                cached_location = self.session.get('Location', location['id'])
            logger.info(f"[OK] {len(locations)} locations preloaded to memory cache")
            
            # Preload statuses
            logger.info("[STATS] Preloading statuses...")
            statuses = self.session.query('Status').all()
            for status in statuses:
                cached_status = self.session.get('Status', status['id'])
            logger.info(f"[OK] {len(statuses)} statuses preloaded")
            
            # Preload users
            logger.info("👥 Preloading users...")
            users = self.session.query('User').all()
            for user in users:
                cached_user = self.session.get('User', user['id'])
            logger.info(f"[OK] {len(users)} users preloaded")
            
            elapsed = (time.time() - start_time) * 1000
            total_entities = len(locations) + len(statuses) + len(users)
            
            logger.info("=" * 50)
            logger.info(f"🎉 Common data preloaded in {elapsed:.1f}ms")
            logger.info(f"[STATS] Total entities: {total_entities}")
            logger.info(f"[FAST] Performance: {total_entities/elapsed:.2f} entities/ms")
            logger.info("💾 Data moved to memory cache for instant access")
            logger.info("=" * 50)
            
        except Exception as e:
            logger.warning(f"[FAIL] Optimized preload failed: {e}")
            logger.info("[REFRESH] Using fallback without preload")

    def _create_session_with_cache(self):
        """Create session with optimized cache - EXACT COPY FROM ORIGINAL"""
        if not FTRACK_API_AVAILABLE:
            logger.error("ftrack_api not available")
            return None
        
        # Use UNIQUE cache path for modular browser to avoid conflicts
        cache_path = os.environ.get('FTRACK_CACHE')
        if not cache_path:
            cache_path = os.path.join(tempfile.gettempdir(), 'ftrack_modular_cache.dbm')
        
        logger.info(f"Using Ftrack cache path: {cache_path}")

        def cache_maker(session_instance):
            """Return cache instance for session."""
            # Environment variable for cache path.
            cache_path_from_env = os.environ.get('FTRACK_CACHE')

            # Use a temporary file if no cache path is provided.
            if not cache_path_from_env:
                cache_path_from_env = os.path.join(
                    tempfile.gettempdir(), 'ftrack_houdini_cache'
                )
                logger.info(
                    'FTRACK_CACHE not set, using temporary directory: {0}'.format(
                        cache_path_from_env
                    )
                )

            # Standard ftrack cache filename.
            cache_filename = "ftrack_cache_db"
            
            # Check if the provided path is a directory.
            if os.path.isdir(cache_path_from_env):
                # If it's a directory, join it with the filename.
                cache_path = os.path.join(cache_path_from_env, cache_filename)
                cache_dir = cache_path_from_env
            else:
                # Assume it's a file path and get the directory.
                cache_path = cache_path_from_env
                cache_dir = os.path.dirname(cache_path)

            logger.info("Using FileCache at path: {0}".format(cache_path))
            
            # Ensure the directory exists.
            if not os.path.exists(cache_dir):
                try:
                    os.makedirs(cache_dir)
                    logger.info("Created cache directory: {0}".format(cache_dir))
                except OSError as e:
                    logger.error(
                        "Could not create cache directory {0}: {1}".format(
                            cache_dir, e
                        )
                    )
                    # Fallback to no cache.
                    return ftrack_api.cache.MemoryCache()

            file_cache = ftrack_api.cache.FileCache(cache_path)
            
            serialised_cache = ftrack_api.cache.SerialisedCache(
                file_cache,
                encode=lambda obj: session_instance.encode(obj),
                decode=lambda data: session_instance.decode(data)
            )

            # Wrap in our custom wrappers if available
            if CACHE_COMPONENTS_AVAILABLE:
                # Components available - create optimized cache
                try:
                    # FIX: Create wrapper chain (ftrack Session will add as one layer)
                    logger.info("Creating optimized cache chain...")
                    
                    # Almost entire cache in memory (1.86 MB easily fits)
                    # Increase to 200K elements for full dataset coverage
                    logger.info("Creating MemoryCacheWrapper with 200K max items...")
                    memory_cache = MemoryCacheWrapper(serialised_cache, max_size=200000)
                    logger.info("Created MemoryCacheWrapper: {0}".format(type(memory_cache)))
                    
                    logger.info("Creating LoggingCacheWrapper...")
                    logging_wrapped_cache = LoggingCacheWrapper(memory_cache, logger)
                    logger.info("Created LoggingCacheWrapper: {0}".format(type(logging_wrapped_cache)))
                    
                    logger.info("[OK] OPTIMIZED CACHE CHAIN CREATED!")
                    logger.info("Cache chain: LoggingCacheWrapper -> MemoryCacheWrapper -> SerialisedCache -> FileCache")
                    logger.info("Returning cache: {0}".format(type(logging_wrapped_cache)))
                    return logging_wrapped_cache
                except Exception as e:
                    logger.warning("Failed to create optimized cache: {0}".format(e))
                    import traceback
                    traceback.print_exc()
                    # Fallback to serialised cache
                    return serialised_cache
            else:
                logger.warning("[FAIL] Cache components not available - using basic cache")
                return serialised_cache

        try:
            logger.info("Creating ftrack session with cache...")
            
            # Create session with custom cache immediately
            logger.info("Creating session with custom cache maker...")
            try:
                session = ftrack_api.Session(cache=cache_maker)
            except AttributeError as e:
                if "'str' object has no attribute 'merge'" in str(e):
                    logger.warning("Session creation failed with merge error, trying fallback approach...")
                    # Create standard session, then replace cache
                    session = ftrack_api.Session()
                    logger.info("Standard session created, replacing cache...")
                    session.cache = cache_maker(session)
                    logger.info("Cache replaced successfully")
                else:
                    raise
            except Exception as e:
                logger.error(f"Session creation failed: {e}")
                # Fallback to standard session
                logger.info("Falling back to standard session...")
                session = ftrack_api.Session()
                logger.info("Standard session created as fallback")
            
            logger.info(f"Session created: {type(session)}")
            logger.info(f"Session.cache type: {type(session.cache)}")

            # IMPORTANT: any heavy operations (preload, etc.) execute only
            # AFTER successful session creation.
            if session:
                # 1) Register multi-site / user locations if plugin is available.
                # Logic repeats test dev-script and provides clear logs
                # like "Multi-site locations registered successfully".
                try:
                    _add_locations_if_available(session)
                except Exception as e:
                    logger.warning(
                        "Multi-site locations bootstrap failed inside client: %s", e
                    )

                # 2) If needed, start TRUE BULK preload.
                # Check bulk preload disable flag (instance variable has priority)
                enable_bulk_preload = getattr(
                    self,
                    "_enable_bulk_preload",
                    getattr(self.__class__, "_enable_bulk_preload", True),
                )

                if enable_bulk_preload and TRUE_BULK_PRELOADER_AVAILABLE:
                    logger.info(
                        "Session created successfully, starting TRUE BULK cache preload..."
                    )
                    try:
                        # TRUE bulk preload of entire cache from disk to memory in one operation
                        true_bulk_preloader = create_true_bulk_preloader(session)

                        if true_bulk_preloader:
                            # Use TRUE bulk load - entire DBM to memory in one operation
                            logger.info(
                                "[LAUNCH] Using TRUE BULK PRELOAD for maximum performance..."
                            )
                            loaded_count = (
                                true_bulk_preloader.true_bulk_preload_entire_cache()
                            )
                            logger.info(
                                f"[OK] TRUE BULK cache preload completed: {loaded_count} items loaded"
                            )
                        else:
                            logger.warning("True bulk preloader creation failed")
                    except Exception as e:
                        logger.error(f"[FAIL] TRUE BULK cache preload failed: {e}")
                        import traceback

                        traceback.print_exc()
                elif enable_bulk_preload and not TRUE_BULK_PRELOADER_AVAILABLE:
                    logger.warning("True bulk preloader not available - preload disabled")
                else:
                    logger.info("Bulk preload DISABLED by _enable_bulk_preload flag")
            else:
                logger.warning("Session is None!")
                        
            return session
        except Exception as e:
            logger.error(f"Failed to create Ftrack session: {e}")
            import traceback
            traceback.print_exc()
            return None

    # === API METHODS ===

    def get_projects(self):
        """Get all active projects - USE CACHE via session.get()"""
        if not self.session:
            return []
        try:
            # WORKAROUND for session.get() issue - use direct query
            # This will still use cache, but safer
            logger.info("Loading projects via direct query (still uses cache)...")
            projects = self.session.query('Project').all()
            
            logger.info(f"Loaded {len(projects)} projects from cache via query")
            
            # Filter active projects in Python
            active_projects = []
            for p in projects:
                try:
                    status = p.get('status')
                    # status can be string or object
                    if status:
                        if isinstance(status, str):
                            # If status is string, check directly
                            if status == 'Active':
                                active_projects.append(p)
                        elif hasattr(status, 'get'):
                            # If status is object, check name
                            if status.get('name') == 'Active':
                                active_projects.append(p)
                        else:
                            # Unknown status type, add project
                            active_projects.append(p)
                    else:
                        # No status, add project
                        active_projects.append(p)
                except Exception as status_error:
                    logger.warning(f"Error checking project status: {status_error}")
                    # If can't determine status, add project
                    active_projects.append(p)
            
            logger.info(f"Found {len(active_projects)} active projects")
            return active_projects
            
        except Exception as e:
            logger.error(f"Failed to get projects from cache: {e}")
            # Fallback - old method via query
            try:
                logger.info("Fallback to direct query...")
                projects = self.session.query('Project').all()
                # Safe filtering of active projects
                active_projects = []
                for p in projects:
                    try:
                        status = p.get('status')
                        if status:
                            if isinstance(status, str) and status == 'Active':
                                active_projects.append(p)
                            elif hasattr(status, 'get') and status.get('name') == 'Active':
                                active_projects.append(p)
                            else:
                                active_projects.append(p)  # Add all projects if can't determine
                        else:
                            active_projects.append(p)
                    except:
                        active_projects.append(p)
                return active_projects
            except Exception as e2:
                logger.error(f"Fallback project query also failed: {e2}")
                return []

    def get_project_from_context_id(self, context_id):
        """Get project from context entity ID (Task, Shot, AssetBuild, etc.)"""
        if not self.session or not context_id:
            return None
            
        try:
            # Try to get the entity and find its project
            entity = self.session.get('TypedContext', context_id)
            if not entity:
                logger.warning(f"No entity found for context ID: {context_id}")
                return None
                
            # Get the project through the entity's hierarchy
            project = entity.get('project')
            if project:
                logger.info(f"Found project {project['name']} for context ID {context_id}")
                return project
            else:
                logger.warning(f"No project found for context ID: {context_id}")
                return None
                
        except Exception as e:
            logger.error(f"Failed to get project from context ID {context_id}: {e}")
            return None

    def get_tasks_for_entity(self, entity_id):
        """Get all tasks for an entity"""
        if not self.session:
            return []
            
        try:
            query = f'select id, name, type.name, status.name, description from Task where parent.id is "{entity_id}"'
            tasks = self.session.query(query).all()
            # Sort tasks by name for better UX
            tasks = sorted(tasks, key=lambda x: x.get('name', '').lower())
            return tasks
        except Exception as e:
            logger.error(f"Failed to get tasks for entity {entity_id}: {e}")
            return []

    def get_assets_linked_to_entity(self, entity_id):
        """Get all assets linked to an entity"""
        if not self.session:
            return []
            
        try:
            query = f'Asset where context_id is "{entity_id}"'
            assets = self.session.query(query).all()
            return assets
        except Exception as e:
            logger.error(f"Failed to get assets for entity {entity_id}: {e}")
            return []

    def get_versions_for_asset(self, asset_id):
        """Get all versions for an asset"""
        if not self.session:
            return []
            
        try:
            query = f'select id, version, comment, date, user.first_name from AssetVersion where asset_id is "{asset_id}" order by version desc'
            versions_raw = self.session.query(query).all()
            
            versions = []
            for version_raw in versions_raw:
                user_data = version_raw.get('user')
                user_first_name = 'Unknown'
                
                if user_data:
                    if isinstance(user_data, dict):
                        user_first_name = user_data.get('first_name', 'Unknown')
                    else:
                        try:
                            user_first_name = user_data.get('first_name', 'Unknown')
                        except:
                            user_first_name = 'Unknown'
                
                version_data = {
                    'id': version_raw['id'],
                    'version': version_raw['version'],
                    'comment': version_raw.get('comment', ''),
                    'date': version_raw.get('date'),
                    'user': {'first_name': user_first_name, 'last_name': 'User', 'id': None},
                    'asset': {'id': asset_id, 'name': 'Asset'}
                }
                versions.append(version_data)
            
            return versions
            
        except Exception as e:
            logger.error(f"Failed to get versions for asset {asset_id}: {e}")
            return []

    def get_components_with_paths_for_version(self, version_id):
        """Get all components with file paths for a version"""
        if not self.session:
            return []
            
        try:
            query = f'select id, name, file_type from Component where version.id is "{version_id}"'
            components_data = self.session.query(query).all()
        except Exception as e:
            logger.error(f"Failed to get components for version {version_id}: {e}")
            return []

        processed_components = []
        location = None
        try:
            location = self.session.pick_location()
        except Exception as e:
            logger.warning(f"Error picking location: {e}")

        for comp in components_data:
            path = "N/A"
            if location:
                try:
                    path = location.get_filesystem_path(comp)
                    if path is None:
                        path = "N/A (not in location)"
                except Exception as e:
                    path = "N/A (error)"
            
            comp_name = comp.get('name', 'Unknown Component')
            file_type = comp.get('file_type', '')
            if file_type:
                display_name = f"{comp_name} ({file_type})"
            else:
                display_name = comp_name
            
            processed_components.append({
                'id': comp['id'],
                'name': comp_name,
                'display_name': display_name,
                'file_type': file_type,
                'path': path
            })
        return processed_components

    def get_shot_custom_attributes_on_demand(self, shot_id):
        """Fetch shot custom attributes on-demand when needed for metadata display"""
        if not self.session:
            return {}
            
        try:
            # Query with custom_attributes field - this is the correct way
            shot = self.session.query(
                f'select id, name, description, custom_attributes '
                f'from Shot where id is "{shot_id}"'
            ).first()
            
            if shot:
                # Get custom attributes and basic info
                custom_attrs = shot.get('custom_attributes', {})
                logger.info(f"Shot {shot_id} custom_attributes: {custom_attrs}")
                
                result = {
                    'name': shot.get('name', ''),
                    'description': shot.get('description', '')
                }
                
                # Add custom attributes if they exist (exactly like original browser)
                keys_of_interest = ['fstart', 'fend', 'handles', 'preroll', 'fps']
                for attr in keys_of_interest:
                    if attr in custom_attrs:
                        result[attr] = custom_attrs[attr]
                        logger.info(f"Found custom attribute {attr}: {custom_attrs[attr]}")
                
                logger.info(f"Final shot info result: {result}")
                return result
            return {}
        except Exception as e:
            logger.warning(f"Failed to fetch shot info for {shot_id}: {e}")
            return {}

    def get_sequences(self, parent_id):
        """Get sequences for a parent entity"""
        return self._get_cached_children(parent_id, 'Sequence',
            'select id, name, description from Sequence where parent.id is "{}"')

    def get_shots(self, parent_id):
        """Get shots for a parent entity"""
        return self._get_cached_children(parent_id, 'Shot', 
            'select id, name, description from Shot where parent.id is "{}"')

    def get_scenes(self, parent_id):
        """Get scenes for a parent entity"""
        return self._get_cached_children(parent_id, 'Scene', 
            'select id, name, description from Scene where parent.id is "{}"')

    def get_folders(self, parent_id):
        """Get folders for a parent entity"""
        return self._get_cached_children(parent_id, 'Folder',
            'select id, name, description from Folder where parent.id is "{}"')

    def get_assets(self, parent_id):
        """Get assets (AssetBuild) for a parent entity"""
        return self._get_cached_children(parent_id, 'AssetBuild',
            'select id, name, description from AssetBuild where parent.id is "{}"')

    def _get_cached_children(self, parent_id, entity_type, query_template):
        """Universal cached children loading - USES PRELOADED CACHE via session.get()"""
        cache_key = f"{parent_id}_{entity_type}"
        
        # Check local cache first
        if cache_key in self._entity_children_cache:
            logger.debug(f"Local cache HIT for {entity_type} children of {parent_id}")
            return self._entity_children_cache[cache_key]
        
        if not self.session:
            return []
        
        start_time = time.time()
        try:
            # CRITICAL: First get only IDs via query, then load objects via session.get()
            # This allows using preloaded cache!
            
            # Get only children IDs
            id_query = f'select id from {entity_type} where parent.id is "{parent_id}"'
            children_ids_result = self.session.query(id_query).all()
            children_ids = [child['id'] for child in children_ids_result]
            
            logger.debug(f"Found {len(children_ids)} {entity_type} IDs for parent {parent_id}")
            
            # Load full objects via session.get() - THIS USES PRELOADED CACHE!
            children = []
            cache_hits = 0
            for child_id in children_ids:
                try:
                    child = self.session.get(entity_type, child_id)
                    if child:
                        children.append(child)
                        cache_hits += 1
                except Exception as e:
                    logger.warning(f"Failed to get {entity_type} {child_id} from cache: {e}")
                    continue
            
            # Cache the result locally
            self._entity_children_cache[cache_key] = children
            
            query_time = (time.time() - start_time) * 1000
            logger.info(f"[OK] Loaded {len(children)} {entity_type} children for {parent_id} in {query_time:.1f}ms ({cache_hits} from cache)")
            
            return children
            
        except Exception as e:
            query_time = (time.time() - start_time) * 1000
            logger.error(f"[FAIL] Failed to get {entity_type} children for {parent_id} in {query_time:.1f}ms: {e}")
            
            # Fallback - old method via query
            try:
                logger.info(f"Fallback to direct query for {entity_type} children...")
                query = query_template.format(parent_id)
                children = self.session.query(query).all()
                self._entity_children_cache[cache_key] = children
                return children
            except Exception as e2:
                logger.error(f"Fallback query also failed: {e2}")
                return []

    def get_cache_stats(self):
        """Get cache statistics including size and item counts"""
        import sys
        
        def get_deep_size(obj, seen=None):
            """Calculate deep size of object in bytes"""
            if seen is None:
                seen = set()
            
            obj_id = id(obj)
            if obj_id in seen:
                return 0
            
            seen.add(obj_id)
            size = sys.getsizeof(obj)
            
            if isinstance(obj, dict):
                size += sum([get_deep_size(v, seen) for v in obj.values()])
                size += sum([get_deep_size(k, seen) for k in obj.keys()])
            elif hasattr(obj, '__dict__'):
                size += get_deep_size(obj.__dict__, seen)
            elif hasattr(obj, '__iter__') and not isinstance(obj, (str, bytes, bytearray)):
                size += sum([get_deep_size(i, seen) for i in obj])
            
            return size
        
        stats = {
            'asset_versions_cache': {
                'items': len(self._asset_versions_cache),
                'size_bytes': get_deep_size(self._asset_versions_cache)
            },
            'entity_assets_cache': {
                'items': len(self._entity_assets_cache),
                'size_bytes': get_deep_size(self._entity_assets_cache)
            },
            'entity_tasks_cache': {
                'items': len(self._entity_tasks_cache),
                'size_bytes': get_deep_size(self._entity_tasks_cache)
            },
            'entity_children_cache': {
                'items': len(self._entity_children_cache),
                'size_bytes': get_deep_size(self._entity_children_cache)
            }
        }
        
        # Calculate totals
        total_items = sum(cache['items'] for cache in stats.values())
        total_size = sum(cache['size_bytes'] for cache in stats.values())
        
        stats['total'] = {
            'items': total_items,
            'size_bytes': total_size,
            'size_kb': round(total_size / 1024, 2),
            'size_mb': round(total_size / (1024 * 1024), 2)
        }
        
        return stats

    def clear_cache(self):
        """Clear all cached data to force fresh API calls"""
        self._asset_versions_cache.clear()
        self._entity_assets_cache.clear()
        self._entity_tasks_cache.clear()
        self._entity_children_cache.clear()
        logger.info("All API caches cleared")
    
    def clear_cache_for_entity(self, entity_id):
        """Clear cache only for specific entity and its assets"""
        # Clear assets for this entity
        if entity_id in self._entity_assets_cache:
            del self._entity_assets_cache[entity_id]
            logger.info(f"Cleared assets cache for entity {entity_id}")
        
        # Clear tasks for this entity
        if entity_id in self._entity_tasks_cache:
            del self._entity_tasks_cache[entity_id]
            logger.info(f"Cleared tasks cache for entity {entity_id}")
        
        # Clear asset versions for assets linked to this entity
        try:
            assets = self.get_assets_linked_to_entity(entity_id)
            for asset in assets:
                asset_id = asset['id']
                if asset_id in self._asset_versions_cache:
                    del self._asset_versions_cache[asset_id]
                    logger.info(f"Cleared versions cache for asset {asset_id}")
        except Exception as e:
            logger.warning(f"Could not clear asset versions cache for entity {entity_id}: {e}")
        
        logger.info(f"Selective cache cleared for entity {entity_id}")

    # === PRELOADER INTEGRATION ===
    
    def preload_project_data(self, project_id):
        """Preload all data for a project using the cache preloader"""
        if self._preloader:
            return self._preloader.preload_project_entities(project_id)
        else:
            logger.warning("No preloader available")
            return {'error': 'No preloader available'}


# Legacy compatibility - DISABLED to test fallback
# SimpleFtrackApiClient = FtrackApiClient


def create_api_client():
    """Factory function to create API client"""
    return FtrackApiClient()

# Legacy compatibility alias for browser_widget_optimized.py
SimpleFtrackApiClient = FtrackApiClient 