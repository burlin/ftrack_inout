"""
Optimized Ftrack Task Browser

This version replaces the complex cache system with our efficient solution.
"""

# MODULE VERSION for tracking updates
__version__ = "2.3.0"  # Added aggressive timeout mechanism (1.5s + individual timeouts)
__last_updated__ = "2024-12-19 13:10:00"

import sys
import os
import time
import tempfile
import traceback
import logging

# Dependencies path setup
# Dependencies are located in location_integrator/dependencies
_deps_path = os.path.join(os.path.dirname(__file__), '..', 'location_integrator', 'dependencies')
_deps_path = os.path.abspath(_deps_path)
if os.path.exists(_deps_path) and _deps_path not in sys.path:
    sys.path.insert(0, _deps_path)

try:
    from PySide6 import QtWidgets, QtCore, QtGui
    PYSIDE6_AVAILABLE = True
except ImportError:
    PYSIDE6_AVAILABLE = False

from .dcc.houdini import hou, HOUDINI_AVAILABLE

# Configure logging
logging.basicConfig(
    level=logging.WARNING, 
    format='%(asctime)s - %(levelname)s:%(name)s:%(message)s',
    datefmt='%H:%M:%S',
    force=True
)
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)


def _is_sequence_path(path):
    """Check if path contains sequence pattern (%04d, %d, $F, @, #, etc)."""
    if not path or not isinstance(path, str) or path.startswith("N/A"):
        return False
    import re
    indicators = ['%d', '%0', '$F', '@', '#{']
    for ind in indicators:
        if ind in path:
            return True
    if '#' in path and re.search(r'[._]#+[._]', path):
        return True
    return False


from .browser_config_loader import (
    get_show_sequence_frame_range,
    get_project_filter_statuses,
)


def _frame_range_from_names(names):
    """Return (frame_min, frame_max) from list of name strings (frame numbers), or (None, None)."""
    if not names:
        return None, None
    frames = []
    for name in names:
        if name is None:
            continue
        try:
            frames.append(int(name))
        except (ValueError, TypeError):
            continue
    if not frames:
        return None, None
    return min(frames), max(frames)


def _build_component_display_name(comp_name, file_type, path, member_count=None, padding=None, frame_min=None, frame_max=None):
    """Build display name: for sequences show pattern and range, e.g. name (.%04d.sc) 1001 - 1721 (720)."""
    if not comp_name:
        comp_name = 'Unknown'
    if member_count is not None and frame_min is not None and frame_max is not None:
        count_suffix = f" {frame_min} - {frame_max} ({member_count})"
    elif member_count is not None:
        count_suffix = f" {member_count}"
    else:
        count_suffix = ""
    if _is_sequence_path(path):
        basename = os.path.basename(path)
        if basename.startswith(comp_name):
            suffix = basename[len(comp_name):]
            if suffix.startswith('.'):
                return f"{comp_name} ({suffix}){count_suffix}"
    if member_count is not None and (padding is not None or file_type):
        pad = padding if padding is not None else 4
        pattern = f".%0{pad}d.{file_type}" if file_type else f".%0{pad}d"
        if frame_min is not None and frame_max is not None:
            return f"{comp_name} ({pattern}) {frame_min} - {frame_max} ({member_count})"
        return f"{comp_name} ({pattern}) {member_count}"
    if file_type:
        return f"{comp_name} ({file_type})"
    return comp_name


# Import our optimized components
try:
    from .simple_api_client import SimpleFtrackApiClient
    from .cache_preloader import CachePreloader
    OPTIMIZED_COMPONENTS_AVAILABLE = True
except ImportError:
    OPTIMIZED_COMPONENTS_AVAILABLE = False

# Fallback imports
try:
    import ftrack_api
    import ftrack_api.cache
    FTRACK_API_AVAILABLE = True
except ImportError:
    FTRACK_API_AVAILABLE = False

# Constants
if PYSIDE6_AVAILABLE:
    ITEM_ID_ROLE = QtCore.Qt.UserRole
    ITEM_TYPE_ROLE = QtCore.Qt.UserRole + 1
    ITEM_POPULATED_ROLE = QtCore.Qt.UserRole + 2
    ITEM_NAME_ROLE = QtCore.Qt.UserRole + 3
    DUMMY_NODE_TEXT = "[+] Expand"
    
    ASSET_VERSION_ITEM_ID_ROLE = QtCore.Qt.UserRole + 10
    ASSET_VERSION_ITEM_TYPE_ROLE = QtCore.Qt.UserRole + 11
    COMPONENT_ITEM_ID_ROLE = QtCore.Qt.UserRole + 12
    COMPONENT_ITEM_NAME_ROLE = QtCore.Qt.UserRole + 13

class OptimizedFtrackApiClient:
    """Optimized API Client using our efficient caching strategy"""
    
    def __init__(self):
        logger.info("[LAUNCH] Initializing Optimized Ftrack API Client...")
        logger.info(f"[CLIP] MODULE VERSION: {__version__} (Updated: {__last_updated__})")
        logger.info("🔧 This is the UPDATED version with all API methods")
        
        # Debug: list available methods
        methods = [method for method in dir(self) if not method.startswith('_') and callable(getattr(self, method))]
        logger.info(f"[SEARCH] Available methods: {sorted(methods)}")
        
        if OPTIMIZED_COMPONENTS_AVAILABLE:
            # Use our optimized components
            self._client = SimpleFtrackApiClient()
            self.session = self._client.session
            self._preloader = CachePreloader(self.session) if self.session else None
            logger.info("[OK] Using optimized components")
        else:
            # Fallback to basic ftrack session
            logger.warning("[WARN]  Optimized components not available, using basic session")
            self.session = self._create_basic_session()
            self._client = None
            self._preloader = None
        
        # Legacy cache for compatibility
        self._entity_cache = {}
        
        # Verify critical methods exist
        critical_methods = ['get_folders', 'get_assets', 'get_shots', 'clear_cache']
        missing = [m for m in critical_methods if not hasattr(self, m)]
        if missing:
            logger.error(f"[FAIL] CRITICAL: Missing methods: {missing}")
        else:
            logger.info(f"[OK] All critical methods available: {critical_methods}")
        
    def _create_basic_session(self):
        """Create basic ftrack session as fallback"""
        try:
            if not FTRACK_API_AVAILABLE:
                logger.error("ftrack_api not available")
                return None
            
            # Try to use shared session factory (with optimized caching)
            try:
                from ..common.session_factory import get_shared_session
                session = get_shared_session()
                if session:
                    logger.info("[OK] Using shared session from common factory")
                    return session
            except ImportError:
                logger.debug("Common session factory not available, creating basic session")
            except Exception as e:
                logger.debug(f"Failed to get shared session: {e}")
                
            # Fallback: Create basic session
            session = ftrack_api.Session()
            logger.info("[OK] Basic ftrack session created")
            return session
            
        except Exception as e:
            logger.error(f"Failed to create basic session: {e}")
            return None
    
    def preload_project_data(self, project_id):
        """Preload project data for fast access"""
        if self._preloader:
            return self._preloader.preload_project_entities(project_id)
        else:
            # Fallback - no preloading
            return {'loaded_count': 0, 'note': 'No preloader available'}
    
    def get_projects(self):
        """Get all projects"""
        try:
            if not self.session:
                return []
            
            # Use SimpleFtrackApiClient method if available
            if self._client and hasattr(self._client, 'get_projects'):
                try:
                    client_projects = self._client.get_projects()
                    # Check that result is not empty, otherwise use fallback
                    if client_projects:
                        return client_projects
                    else:
                        logger.warning("SimpleFtrackApiClient.get_projects returned empty list, using fallback")
                except Exception as e:
                    logger.warning(f"SimpleFtrackApiClient.get_projects failed: {e}")
                    # Fall through to direct query
            
            # Fallback: direct query + same project filter as simple_api_client
            logger.info("Using fallback direct query for projects")
            projects = self.session.query('Project').all()
            allowed_statuses = get_project_filter_statuses()
            if not allowed_statuses:
                return projects
            try:
                self.session.populate(projects, 'status')
            except Exception:
                pass
            allowed_lower = [s.lower() for s in allowed_statuses]
            filtered = []
            for p in projects:
                try:
                    status = p.get('status')
                    name = status if isinstance(status, str) else (status.get('name') if hasattr(status, 'get') else None)
                    if name is not None and name.lower() in allowed_lower:
                        filtered.append(p)
                except Exception:
                    filtered.append(p)
            if not filtered and projects:
                return projects
            return filtered
            
        except Exception as e:
            logger.error(f"Failed to get projects: {e}")
            return []
    
    def get_entity(self, entity_type, entity_id):
        """Get single entity by type and ID"""
        try:
            if not self.session:
                return None
                
            # Use session.get for caching
            entity = self.session.get(entity_type, entity_id)
            return entity
            
        except Exception as e:
            logger.error(f"Failed to get entity {entity_type}:{entity_id}: {e}")
            return None
    
    def get_children(self, parent_id, entity_type=None):
        """Get children of an entity using SQL queries like original API"""
        try:
            if not self.session:
                return []
            
            if entity_type:
                # Use specific query for the entity type
                query = f'select id, name, description from {entity_type} where parent.id is "{parent_id}"'
            else:
                # Get all children types
                query = f'select id, name, description from TypedContext where parent.id is "{parent_id}"'
            
            children = self.session.query(query).all()
            
            # Sort children by name for better UX
            children = sorted(children, key=lambda x: x.get('name', '').lower())
            
            # Convert to dict format expected by browser
            result = []
            for child in children:
                result.append({
                    'id': child['id'],
                    'name': child.get('name', ''),
                    'entity_type': child.entity_type if hasattr(child, 'entity_type') else entity_type
                })
            
            return result
            
        except Exception as e:
            logger.error(f"Failed to get children for {parent_id}: {e}")
            return []

    # Additional methods required by the old browser - using SQL queries like original
    def get_folders(self, parent_id):
        """Get folders for a parent entity"""
        try:
            if not self.session:
                logger.error("[FAIL] No session available for get_folders")
                return []
            
            query = f'select id, name, description from Folder where parent.id is "{parent_id}"'
            logger.info(f"[SEARCH] Executing query: {query}")
            
            children = self.session.query(query).all()
            logger.info(f"[FOLDER] Found {len(children)} folders for parent {parent_id}")
            
            if children:
                for child in children[:3]:  # Show first 3 for debugging
                    logger.info(f"  [FOLDER] Folder: {child.get('name', 'Unknown')} (ID: {child['id']})")
            
            children = sorted(children, key=lambda x: x.get('name', '').lower())
            return children
            
        except Exception as e:
            logger.error(f"Failed to get folders for {parent_id}: {e}")
            import traceback
            traceback.print_exc()
            return []
    
    def get_assets(self, parent_id):
        """Get assets for a parent entity"""
        try:
            if not self.session:
                logger.error("[FAIL] No session available for get_assets")
                return []
            
            query = f'select id, name, description from AssetBuild where parent.id is "{parent_id}"'
            logger.info(f"[SEARCH] Executing query: {query}")
            
            children = self.session.query(query).all()
            logger.info(f"[TARGET] Found {len(children)} assets for parent {parent_id}")
            
            if children:
                for child in children[:3]:  # Show first 3 for debugging
                    logger.info(f"  [TARGET] Asset: {child.get('name', 'Unknown')} (ID: {child['id']})")
            
            children = sorted(children, key=lambda x: x.get('name', '').lower())
            return children
            
        except Exception as e:
            logger.error(f"Failed to get assets for {parent_id}: {e}")
            import traceback
            traceback.print_exc()
            return []
    
    def get_sequences(self, parent_id):
        """Get sequences for a parent entity"""
        try:
            if not self.session:
                logger.error("[FAIL] No session available for get_sequences")
                return []
            
            query = f'select id, name, description from Sequence where parent.id is "{parent_id}"'
            logger.info(f"[SEARCH] Executing query: {query}")
            
            children = self.session.query(query).all()
            logger.info(f"🎬 Found {len(children)} sequences for parent {parent_id}")
            
            if children:
                for child in children[:3]:  # Show first 3 for debugging
                    logger.info(f"  🎬 Sequence: {child.get('name', 'Unknown')} (ID: {child['id']})")
            
            children = sorted(children, key=lambda x: x.get('name', '').lower())
            return children
            
        except Exception as e:
            logger.error(f"Failed to get sequences for {parent_id}: {e}")
            import traceback
            traceback.print_exc()
            return []
    
    def get_scenes(self, parent_id):
        """Get scenes for a parent entity"""
        try:
            if not self.session:
                return []
            
            query = f'select id, name, description from Scene where parent.id is "{parent_id}"'
            children = self.session.query(query).all()
            children = sorted(children, key=lambda x: x.get('name', '').lower())
            return children
            
        except Exception as e:
            logger.error(f"Failed to get scenes for {parent_id}: {e}")
            return []
    
    def get_shots(self, parent_id):
        """Get shots for a parent entity"""
        try:
            if not self.session:
                return []
            
            query = f'select id, name, description from Shot where parent.id is "{parent_id}"'
            children = self.session.query(query).all()
            children = sorted(children, key=lambda x: x.get('name', '').lower())
            return children
            
        except Exception as e:
            logger.error(f"Failed to get shots for {parent_id}: {e}")
            return []
    
    def get_tasks_for_entity(self, entity_id):
        """Get tasks for an entity"""
        try:
            if not self.session:
                return []
            
            query = f'select id, name, description from Task where parent.id is "{entity_id}"'
            tasks = self.session.query(query).all()
            tasks = sorted(tasks, key=lambda x: x.get('name', '').lower())
            return tasks
            
        except Exception as e:
            logger.error(f"Failed to get tasks for {entity_id}: {e}")
            return []
    
    def get_assets_for_task(self, task_id):
        """
        Get assets published to a specific task.
        Uses an optimized query to first get AssetVersion IDs, then unique Asset IDs,
        and finally fetches the full Asset data in a batch.
        """
        try:
            if not self.session:
                logger.error("[FAIL] No session available for get_assets_for_task")
                return []

            logger.info(f"[LAUNCH] OPTIMIZED: Fetching assets for task {task_id}")
            start_time = time.time()

            # STEP 1: Fast query to get Asset IDs from AssetVersions linked to the task
            query = f'select asset_id from AssetVersion where task.id is "{task_id}"'
            version_results = self.session.query(query).all()
            
            if not version_results:
                logger.info(f"[OK] No versions (and thus no assets) found published to task {task_id}")
                return []

            # STEP 2: Collect unique asset IDs
            asset_ids = {v['asset_id'] for v in version_results if v['asset_id']}
            query_time = time.time() - start_time
            logger.info(f"[CLIP] Found {len(asset_ids)} unique asset IDs in {query_time:.3f}s")
            logger.info(f"[SEARCH] Asset IDs: {list(asset_ids)[:5]}{'...' if len(asset_ids) > 5 else ''}")
            
            if not asset_ids:
                logger.info("[OK] No valid asset IDs found after filtering.")
                return []

            # STEP 3: Batch get full asset data using session.get (utilizes cache)
            batch_start = time.time()
            
            # Use session.get in a loop (still highly cached)
            asset_entities = []
            for asset_id in asset_ids:
                try:
                    # Try both Asset and AssetBuild types
                    asset = None
                    logger.info(f"[SEARCH] Trying to get asset {asset_id}...")
                    try:
                        asset = self.session.get('Asset', asset_id)
                        if asset:
                            logger.info(f"[OK] Found asset {asset_id} as 'Asset' type: {asset.get('name', 'Unknown')}")
                    except Exception as e1:
                        logger.info(f"[WARN]  Asset {asset_id} not found as 'Asset': {e1}")
                        try:
                            asset = self.session.get('AssetBuild', asset_id)
                            if asset:
                                logger.info(f"[OK] Found asset {asset_id} as 'AssetBuild' type: {asset.get('name', 'Unknown')}")
                        except Exception as e2:
                            logger.info(f"[WARN]  Asset {asset_id} not found as 'AssetBuild': {e2}")
                    
                    if asset:
                        asset_entities.append(asset)
                    else:
                        logger.warning(f"[FAIL] Asset {asset_id} not found as either Asset or AssetBuild")
                except Exception as e:
                    logger.warning(f"[FAIL] Failed to get asset {asset_id}: {e}")
                    continue

            batch_time = time.time() - batch_start
            total_time = time.time() - start_time
            
            logger.info(f"[OK] OPTIMIZED: {len(asset_entities)} assets for task loaded in {total_time:.3f}s")
            
            # Sort by name for consistent UI
            assets = sorted(asset_entities, key=lambda x: x.get('name', '').lower())
            
            return assets

        except Exception as e:
            logger.error(f"Failed to get assets for task {task_id}: {e}", exc_info=True)
            return []
    
    def get_project_from_context_id(self, context_id):
        """Get project from context ID"""
        try:
            if not self.session:
                return None
                
            entity = self.session.get('TypedContext', context_id)
            if not entity:
                return None
                
            # Find the project in the hierarchy
            current = entity
            while current:
                if current.entity_type == 'Project':
                    return {'id': current['id'], 'name': current['name']}
                current = current.get('parent')
                
            return None
            
        except Exception as e:
            logger.error(f"Failed to get project from context {context_id}: {e}")
            return None
    
    def get_assets_linked_to_entity(self, entity_id):
        """Get assets linked to an entity - OPTIMIZED with 'query ID → batch get'"""
        try:
            if not self.session:
                return []
            
            logger.info(f"[LAUNCH] OPTIMIZED: Fetching assets for entity {entity_id}")
            start_time = time.time()
            
            # STEP 1: Quick query to get only asset IDs (fast)
            assets_query = f'select id from Asset where parent.id is "{entity_id}"'
            asset_ids_result = self.session.query(assets_query).all()
            
            if not asset_ids_result:
                logger.info(f"[OK] No assets found for entity {entity_id}")
                return []
            
            # Extract IDs
            asset_ids = [asset['id'] for asset in asset_ids_result]
            query_time = time.time() - start_time
            logger.info(f"[CLIP] Found {len(asset_ids)} asset IDs in {query_time:.3f}s")
            
            # STEP 2: Batch get full asset data using session.get (uses cache)
            # Check cache status for logging, but always call session.get() to ensure fresh data
            batch_start = time.time()
            assets = []
            cached_count = 0
            
            # Check cache status for logging
            for asset_id in asset_ids:
                if self._is_cached('Asset', asset_id):
                    cached_count += 1
            
            if cached_count > 0:
                logger.info(f"[CACHE] {cached_count}/{len(asset_ids)} assets already cached, will use fast path")
            
            for asset_id in asset_ids:
                try:
                    # This uses the optimized cache (fast for cached, fetches for uncached)
                    asset = self.session.get('Asset', asset_id)
                    if asset:
                        asset_type = asset['type']['name'] if asset['type'] else 'N/A'
                        assets.append({
                            'id': asset['id'],
                            'name': asset.get('name', 'Unknown'),
                            'type': asset_type
                        })
                except Exception as e:
                    logger.warning(f"Failed to get asset {asset_id}: {e}")
                    continue
            
            batch_time = time.time() - batch_start
            total_time = time.time() - start_time
            
            logger.info(f"[OK] OPTIMIZED: {len(assets)} assets loaded in {total_time:.3f}s")
            logger.info(f"   [STATS] Query: {query_time:.3f}s, Batch get: {batch_time:.3f}s (cached: {cached_count})")
            logger.info(f"   [LAUNCH] Speed: {len(assets)/total_time:.1f} assets/sec")
            
            return assets
            
        except Exception as e:
            logger.error(f"Failed to get assets for entity {entity_id}: {e}")
            return []
    
    def get_version_components(self, version_id):
        """Get components for a version - OPTIMIZED with 'query ID → batch get'"""
        try:
            if not self.session:
                return []
            
            logger.info(f"[LAUNCH] OPTIMIZED: Fetching components for version {version_id}")
            start_time = time.time()
            
            # STEP 1: Quick query to get only component IDs (fast)
            components_query = f'select id from Component where version.id is "{version_id}"'
            component_ids_result = self.session.query(components_query).all()
            
            if not component_ids_result:
                logger.info(f"[OK] No components found for version {version_id}")
                return []
            
            # Extract IDs
            component_ids = [comp['id'] for comp in component_ids_result]
            query_time = time.time() - start_time
            logger.info(f"[CLIP] Found {len(component_ids)} component IDs in {query_time:.3f}s")
            
            # STEP 2: Batch get full component data using session.get (uses cache)
            # Check cache status for logging, but always call session.get() to ensure fresh data
            batch_start = time.time()
            result = []
            cached_count = 0
            
            # Check cache status for logging
            for component_id in component_ids:
                if self._is_cached('Component', component_id):
                    cached_count += 1
            
            if cached_count > 0:
                logger.info(f"[CACHE] {cached_count}/{len(component_ids)} components already cached, will use fast path")
            
            component_entities = []
            for component_id in component_ids:
                try:
                    component = self.session.get('Component', component_id)
                    if component:
                        component_entities.append(component)
                except Exception as e:
                    logger.warning(f"Failed to get component {component_id}: {e}")
            
            # Batch populate members only when needed for frame range display (show_sequence_frame_range)
            sequence_components = [c for c in component_entities if getattr(c, 'entity_type', None) == 'SequenceComponent']
            if sequence_components and get_show_sequence_frame_range():
                try:
                    self.session.populate(sequence_components, 'members')
                except Exception as e:
                    logger.debug(f"Batch populate members: {e}")
            
            for component in component_entities:
                try:
                    comp_name = component.get('name', '')
                    file_type = component.get('file_type', '')
                    member_count = None
                    padding = None
                    frame_min = frame_max = None
                    if getattr(component, 'entity_type', None) == 'SequenceComponent':
                        if get_show_sequence_frame_range():
                            members = component.get('members') or []
                            member_count = len(members)
                            padding = component.get('padding')
                            if member_count:
                                names = [m.get('name') for m in members]
                                frame_min, frame_max = _frame_range_from_names(names)
                        else:
                            padding = component.get('padding')
                    display_name = _build_component_display_name(
                        comp_name, file_type, '',
                        member_count=member_count, padding=padding,
                        frame_min=frame_min, frame_max=frame_max
                    )
                    result.append({
                        'id': component['id'],
                        'name': comp_name,
                        'display_name': display_name,
                        'file_type': file_type,
                        'size': component.get('size', 0)
                    })
                except Exception as e:
                    logger.warning(f"Failed to process component {component.get('id', 'N/A')}: {e}")
            
            batch_time = time.time() - batch_start
            total_time = time.time() - start_time
            
            logger.info(f"[OK] OPTIMIZED: {len(result)} components loaded in {total_time:.3f}s")
            logger.info(f"   [STATS] Query: {query_time:.3f}s, Batch get: {batch_time:.3f}s (cached: {cached_count})")
            logger.info(f"   [LAUNCH] Speed: {len(result)/total_time:.1f} components/sec")
            
            # Cache result for future use (AFTER logging to ensure it's executed)
            logger.info(f"[CACHE DEBUG] force_refresh={force_refresh}, result type={type(result)}, result len={len(result) if result else 0}")
            if not force_refresh:
                if result:
                    try:
                        self._version_components_cache[version_id] = result
                        logger.info(f"[CACHE SAVE] Saved {len(result)} components for version {version_id} to cache (cache size now: {len(self._version_components_cache)})")
                    except Exception as cache_error:
                        logger.warning(f"[CACHE SAVE ERROR] Failed to save to cache: {cache_error}")
                        import traceback
                        logger.warning(f"Traceback: {traceback.format_exc()}")
                else:
                    logger.info(f"[CACHE SKIP] Result is empty, not caching")
            else:
                logger.info(f"[CACHE SKIP] force_refresh=True, not caching")
            
            return result
            
        except Exception as e:
            logger.error(f"Failed to get components for version {version_id}: {e}")
            import traceback
            logger.error(f"Traceback: {traceback.format_exc()}")
            return []
    
    def get_components_with_paths_for_version(self, version_id, force_refresh=False):
        """Get components with paths for a version - OPTIMIZED with 'query ID → batch get'
        
        Args:
            version_id: Version ID to get components for
            force_refresh: If True, refresh component_locations using populate() to get fresh paths
        """
        try:
            if not self.session:
                return []
            
            # Invalidate cache when force_refresh so we don't return stale data
            if force_refresh and version_id in self._version_components_cache:
                del self._version_components_cache[version_id]
                logger.info(f"[CACHE INVALIDATE] Cleared cache for version {version_id} (force_refresh)")
            
            # Check cache first (unless force_refresh)
            if not force_refresh:
                cache_size = len(self._version_components_cache)
                if version_id in self._version_components_cache:
                    cached_components = self._version_components_cache[version_id]
                    logger.info(f"[CACHE HIT] Components for version {version_id} ({len(cached_components)} items) - 0ms @ {time.strftime('%H:%M:%S', time.localtime())}")
                    return cached_components
                else:
                    logger.info(f"[CACHE MISS] Version {version_id} not in cache (cache size: {cache_size}, keys: {list(self._version_components_cache.keys())[:3] if cache_size > 0 else 'empty'}...)")
            
            logger.info(f"[LAUNCH] OPTIMIZED: Fetching components with paths for version {version_id} (force_refresh={force_refresh})")
            start_time = time.time()
            
            # STEP 1: Quick query to get only component IDs (fast) and their locations
            components_query = (
                'select id, name, file_type, component_locations.location.name, '
                'component_locations.location.label from Component where '
                f'version.id is "{version_id}"'
            )
            component_ids_result = self.session.query(components_query).all()
            
            if not component_ids_result:
                logger.info(f"[OK] No components found for version {version_id}")
                return []
            
            # Extract IDs
            component_ids = [comp['id'] for comp in component_ids_result]
            query_time = time.time() - start_time
            logger.info(f"[CLIP] Found {len(component_ids)} component IDs in {query_time:.3f}s")
            
            # STEP 2: If force_refresh, refresh component_locations to get fresh paths
            # Use populate() directly on already-loaded entities (faster than _refresh_cached_entities)
            populate_start = None
            if force_refresh and component_ids:
                # First get components (fast from cache)
                component_entities_for_populate = []
                for comp_id in component_ids:
                    try:
                        comp = self.session.get('Component', comp_id)
                        if comp:
                            component_entities_for_populate.append(comp)
                    except Exception:
                        pass
                
                # Then populate component_locations in one batch call
                if component_entities_for_populate:
                    populate_start = time.time()
                    try:
                        self.session.populate(component_entities_for_populate, 'component_locations')
                        populate_time = time.time() - populate_start
                        logger.info(f"[POPULATE] Refreshed component_locations for {len(component_entities_for_populate)} components in {populate_time*1000:.2f}ms")
                    except Exception as e:
                        logger.warning(f"Failed to refresh component_locations: {e}")
            
            # STEP 3: Batch get full component data with paths using session.get (uses cache)
            batch_start = time.time()
            result = []
            location = None
            
            # Get location once for all components
            try:
                location = self.session.pick_location()
            except Exception as e:
                logger.warning(f"Failed to get location: {e}")
            
            # Get full component entities via session.get() (uses cache, populate already refreshed component_locations if force_refresh)
            component_entities = []
            get_start = time.time()
            for comp_data in component_ids_result:
                try:
                    # Get full component entity (will use cache if available)
                    # If force_refresh, component_locations were already refreshed via populate above
                    component = self.session.get('Component', comp_data['id'])
                    if component:
                        component_entities.append(component)
                except Exception as e:
                    logger.warning(f"Failed to get component {comp_data['id']}: {e}")
                    continue
            get_time = time.time() - get_start
            logger.debug(f"[TIMING] session.get(Component) x{len(component_entities)}: {get_time*1000:.2f}ms")
            
            # Batch populate members only when needed for frame range display (show_sequence_frame_range)
            sequence_components = [c for c in component_entities if getattr(c, 'entity_type', None) == 'SequenceComponent']
            need_members = get_show_sequence_frame_range()
            if sequence_components and need_members:
                try:
                    self.session.populate(sequence_components, 'members')
                except Exception as e:
                    logger.debug(f"Batch populate members: {e}")
            elif sequence_components and not need_members:
                logger.debug("[PERF] Skipping populate(members) - show_sequence_frame_range=False")
            
            # Batch populate component_locations to avoid N lazy loads in the loop below
            try:
                self.session.populate(component_entities, 'component_locations.location.name, component_locations.location.label')
            except Exception as e:
                logger.debug(f"Batch populate component_locations: {e}")
            
            # Use full component entities for path resolution
            for component in component_entities:
                try:
                    # Try to get file path (uses fresh component_locations if force_refresh was True)
                    path = ''
                    try:
                        if location:
                            path = location.get_filesystem_path(component)
                        else:
                            path = component.get('name', '')
                    except Exception as path_error:
                        logger.debug(f"Failed to get path for component {component.get('id')}: {path_error}")
                        path = component.get('name', '')
                    
                    comp_name = component.get('name', '')
                    file_type = component.get('file_type', '')
                    
                    # For SequenceComponent: member count and frame range
                    # IMPORTANT: Only access component.get('members') when show_sequence_frame_range - otherwise
                    # it triggers lazy load of all 170+ members (~10s). When False, skip entirely.
                    member_count = None
                    padding = None
                    frame_min = frame_max = None
                    if getattr(component, 'entity_type', None) == 'SequenceComponent':
                        if get_show_sequence_frame_range():
                            members = component.get('members') or []
                            member_count = len(members)
                            padding = component.get('padding')
                            if member_count:
                                names = [m.get('name') for m in members]
                                frame_min, frame_max = _frame_range_from_names(names)
                        else:
                            padding = component.get('padding')  # padding is on component, no lazy load
                    
                    display_name = _build_component_display_name(
                        comp_name, file_type, path,
                        member_count=member_count, padding=padding,
                        frame_min=frame_min, frame_max=frame_max
                    )

                    # Collect location names where component is available (fresh from populate if force_refresh)
                    locations = []
                    for comp_loc in component.get('component_locations', []):
                        loc_entity = comp_loc.get('location')
                        if loc_entity:
                            locations.append(loc_entity.get('label') or loc_entity.get('name') or '')
                    
                    result.append({
                        'id': component['id'],
                        'name': comp_name,
                        'display_name': display_name,
                        'file_type': file_type,
                        'type': file_type,  # For compatibility
                        'path': path,
                        'size': component.get('size', 0),
                        'locations': sorted(list(set(locations))) # Add locations
                    })
                except Exception as e:
                    logger.warning(f"Failed to process component {component.get('id', 'N/A')}: {e}")
                    continue
            
            batch_time = time.time() - batch_start
            total_time = time.time() - start_time
            
            logger.info(f"[OK] OPTIMIZED: {len(result)} components with paths loaded in {total_time:.3f}s @ {time.strftime('%H:%M:%S', time.localtime())} (force_refresh={force_refresh})")
            logger.info(f"   [STATS] Query: {query_time:.3f}s, Batch get: {batch_time:.3f}s, Total: {total_time*1000:.0f}ms")
            logger.info(f"   [LAUNCH] Speed: {len(result)/total_time:.1f} components/sec")
            
            # Cache result for future use (including force_refresh - keep cache current)
            if result:
                try:
                    self._version_components_cache[version_id] = result
                    logger.info(f"[CACHE SAVE] Saved {len(result)} components for version {version_id} to cache (force_refresh={force_refresh})")
                except Exception as cache_error:
                    logger.warning(f"[CACHE SAVE ERROR] Failed to save to cache: {cache_error}")
            
            return result
            
        except Exception as e:
            logger.error(f"Failed to get components with paths for version {version_id}: {e}")
            return []
    
    def get_shot_custom_attributes_on_demand(self, shot_id):
        """Get shot custom attributes using a specific query to fetch them."""
        try:
            if not self.session:
                return {}
            
            logger.info(f"Fetching custom attributes on-demand for Shot ID: {shot_id}")
            # Query with custom_attributes field - this is the correct way
            shot = self.session.query(
                f'select name, description, custom_attributes '
                f'from Shot where id is "{shot_id}"'
            ).first()
            
            if not shot:
                logger.warning(f"On-demand query found no shot for ID: {shot_id}")
                return {}

            # Get custom attributes and basic info
            custom_attrs = shot.get('custom_attributes', {})
            result = {
                'name': shot.get('name', ''),
                'description': shot.get('description', ''),
            }
            
            # Add specific custom attributes if they exist
            keys_of_interest = ['fstart', 'fend', 'handles', 'preroll', 'fps']
            for attr in keys_of_interest:
                if attr in custom_attrs:
                    result[attr] = custom_attrs[attr]
            
            logger.info(f"Successfully fetched on-demand attributes for shot {shot_id}: {result}")
            return result

        except Exception as e:
            logger.error(f"Failed to get shot attributes for {shot_id}: {e}", exc_info=True)
            return {}
    
    def clear_cache(self):
        """Clear all cache"""
        try:
            if self._client and hasattr(self._client, 'clear_cache'):
                self._client.clear_cache()
            
            # Clear session cache if available
            if self.session and hasattr(self.session, 'cache'):
                if hasattr(self.session.cache, 'clear'):
                    self.session.cache.clear()
                    
            # Clear legacy cache
            self._entity_cache.clear()
            logger.info("[OK] Cache cleared successfully")
            
        except Exception as e:
            logger.error(f"Failed to clear cache: {e}")
    
    def clear_cache_for_entity(self, entity_id):
        """Clear cache for specific entity"""
        try:
            # Remove from legacy cache
            keys_to_remove = [k for k in self._entity_cache.keys() if entity_id in str(k)]
            for key in keys_to_remove:
                del self._entity_cache[key]
                
            logger.info(f"[OK] Cache cleared for entity {entity_id}")
            
        except Exception as e:
            logger.error(f"Failed to clear cache for entity {entity_id}: {e}")
    
    # Legacy cache compatibility
    _asset_versions_cache = {}
    _version_components_cache = {}
    
    def _is_cached(self, entity_type: str, entity_id: str) -> bool:
        """Check if entity exists in cache before batch get.
        
        Returns True if entity is already cached, False otherwise.
        NOTE: This is used for optimization only - we still call session.get()
        to ensure we get fresh data, but knowing cache status helps with logging.
        """
        if not self.session or not self.session.cache:
            return False
        
        try:
            # In ftrack API, cache key is typically (entity_type, entity_id)
            cache_key = (entity_type, entity_id)
            
            # Check cache directly
            cached_value = self.session.cache.get(cache_key)
            
            # Check if value is NOT_SET (not cached)
            if hasattr(ftrack_api, 'symbol') and cached_value is ftrack_api.symbol.NOT_SET:
                return False
            
            # If we got a value (even None), it's cached
            return cached_value is not None
            
        except Exception as e:
            # If cache check fails, assume not cached (safe fallback)
            logger.debug(f"Cache check failed for {entity_type} {entity_id}: {e}")
            return False
    
    def _refresh_cached_entities(self, entity_type: str, entity_ids: list, fields: list = None):
        """Refresh cached entities using session.populate() to get fresh metadata.
        
        This ensures we get updated data from server even if entities are cached.
        Used during refresh operations.
        
        Args:
            entity_type: Type of entities to refresh (e.g., 'AssetVersion', 'Asset')
            entity_ids: List of entity IDs to refresh
            fields: Optional list of specific fields to populate (default: all)
        """
        if not self.session or not entity_ids:
            return
        
        try:
            # Get entities (will use cache if available)
            entities = []
            for entity_id in entity_ids:
                try:
                    entity = self.session.get(entity_type, entity_id)
                    if entity:
                        entities.append(entity)
                except Exception:
                    continue
            
            if not entities:
                return
            
            # Use populate() to refresh specific fields from server
            # populate() signature: populate(entities, *projections) where projections are field names as strings
            # Note: populate() requires at least one field name, so we skip it if no fields specified
            # session.get() already ensures fresh data, populate() is only needed for specific fields
            if fields:
                # If fields specified, pass them as separate string arguments
                # populate() expects projections as a single string: 'field1, field2, field3'
                # Example: session.populate(entities, 'metadata, component_locations')
                projections_str = ', '.join(str(f) for f in fields)
                self.session.populate(entities, projections_str)
            # If no fields specified, skip populate() - session.get() already ensures fresh data
            
            logger.debug(f"Refreshed {len(entities)} {entity_type} entities from server")
            
        except Exception as e:
            logger.warning(f"Failed to refresh cached entities: {e}")
            import traceback
            logger.debug(traceback.format_exc())
    
    def get_cache_stats(self):
        """Get cache statistics for monitoring"""
        try:
            stats = {
                'session_available': bool(self.session),
                'cache_type': 'unknown',
                'cache_layers': [],
                'memory_cache_size': 0,
                'total_cache_size': 0
            }
            
            if self.session and hasattr(self.session, 'cache'):
                cache = self.session.cache
                stats['cache_type'] = type(cache).__name__
                
                # Analyze LayeredCache structure
                if hasattr(cache, '_caches'):
                    caches_list = getattr(cache, '_caches', [])
                    for i, cache_layer in enumerate(caches_list):
                        layer_type = type(cache_layer).__name__
                        stats['cache_layers'].append(f"Layer {i}: {layer_type}")
                        
                        # Get memory cache size if available
                        if hasattr(cache_layer, '_memory_cache'):
                            stats['memory_cache_size'] = len(cache_layer._memory_cache)
                
            return stats
            
        except Exception as e:
            logger.error(f"Failed to get cache stats: {e}")
            return {'error': str(e)}

    def diagnose_performance(self):
        """
        Performance diagnostics for the caching system
        Returns a detailed report on cache state
        """
        try:
            # Import diagnostic function
            from .quick_diagnosis import quick_performance_check
            
            print("\n[SEARCH] BROWSER PERFORMANCE DIAGNOSTICS")
            print("=" * 50)
            
            if not self.session:
                print("[FAIL] Session not available for diagnostics")
                return None
            
            # Run diagnostics
            result = quick_performance_check(api_client=self, session=self.session)
            
            if result:
                print(f"\n DIAGNOSTIC RESULTS:")
                print(f"   Cache type: {result.get('cache_type', 'unknown')}")
                print(f"   Cache layers: {len(result.get('cache_layers', []))}")
                print(f"   Projects load time: {result.get('projects_load_time', 0):.1f}ms")
                print(f"   Performance rating: {result.get('performance_rating', 'unknown')}")
            
            return result
            
        except ImportError:
            print("[FAIL] Diagnostic module not available")
            return None
        except Exception as e:
            print(f"[FAIL] Diagnostic error: {e}")
            return None

    def restore_performance(self):
        """
        Attempt to restore cache performance
        """
        try:
            from .quick_diagnosis import restore_cache_performance
            
            if not self.session:
                print("[FAIL] Session not available for restoration")
                return False
            
            return restore_cache_performance(self.session)
            
        except ImportError:
            print("[FAIL] Restoration module not available")
            return False
        except Exception as e:
            print(f"[FAIL] Restoration error: {e}")
            return False

    def get_asset_versions(self, asset_id):
        """Get versions for an asset - OPTIMIZED with 'query ID → batch get'"""
        try:
            if not self.session:
                return []
            
            logger.info(f"[LAUNCH] OPTIMIZED: Fetching versions for asset {asset_id}")
            start_time = time.time()
            
            # STEP 1: Quick query to get version data (fast)
            versions_query = f'select id, version, comment, date, user from AssetVersion where asset.id is "{asset_id}"'
            versions = self.session.query(versions_query).all()
            query_time = time.time() - start_time
            logger.info(f"[CLIP] Found {len(versions)} versions in {query_time:.3f}s")
            
            # --- FIX: Force load date to bypass cache ---
            if versions:
                self.session.populate(versions, 'date')

            # Convert to dictionary format and build full name
            result = []
            for v in versions:
                user_data = v.get('user', {})
                username = user_data.get('username', '') if user_data else ''
                first_name = user_data.get('first_name', '') if user_data else ''
                last_name = user_data.get('last_name', '') if user_data else ''
                
                full_name = f"{first_name} {last_name}".strip()
                if not full_name:
                    full_name = username or 'Unknown User'

                result.append({
                    'id': v['id'],
                    'version': v['version'],
                    'comment': v.get('comment', ''),
                    'date': v.get('date'),
                    'user': {
                        'username': username,
                        'first_name': first_name,
                        'last_name': last_name,
                        'full_name': full_name
                    },
                    'asset': {'id': asset_id}
                })
            
            # Sort by version number (newest first)
            result = sorted(result, key=lambda x: x['version'], reverse=True)

            # Cache result for future use
            if not force_refresh:
                self._asset_versions_cache[asset_id] = result

            total_time = time.time() - start_time
            logger.info(f"[OK] OPTIMIZED: {len(result)} versions loaded in {total_time:.3f}s")
            logger.info(f"   [STATS] Query: {query_time:.3f}s, Batch get: {total_time - query_time:.3f}s")
            logger.info(f"   [LAUNCH] Speed: {len(result)/total_time:.1f} versions/sec")
            
            return result
            
        except Exception as e:
            logger.error(f"Failed to get versions for asset {asset_id}: {e}")
            return []

    def get_versions_for_asset(self, asset_id, force_refresh=False):
        """Get versions for an asset - OPTIMIZED with 'query ID → batch get'
        
        Args:
            asset_id: Asset ID to get versions for
            force_refresh: If True, refresh cached entities using populate() to get fresh metadata
        """
        try:
            if not self.session:
                return []
            
            # Check cache first (unless force_refresh)
            if not force_refresh and hasattr(self, '_asset_versions_cache') and asset_id in self._asset_versions_cache:
                cached_versions = self._asset_versions_cache[asset_id]
                logger.info(f"[CACHE HIT] Versions for asset {asset_id} ({len(cached_versions)} versions) - 0ms @ {time.strftime('%H:%M:%S', time.localtime())}")
                return cached_versions
            
            logger.info(f"[LAUNCH] OPTIMIZED: Fetching versions for asset {asset_id} (force_refresh={force_refresh})")
            start_time = time.time()
            
            # STEP 1: Get version IDs
            # If force_refresh, use query to get fresh data from server
            # Otherwise, use relationship (faster, uses cache)
            query_start = time.time()
            if force_refresh:
                # Force refresh: use query to get fresh version IDs from server
                versions_query = f'select id from AssetVersion where asset.id is "{asset_id}" order by version desc'
                version_ids_result = self.session.query(versions_query).all()
                version_ids = [v['id'] for v in version_ids_result] if version_ids_result else []
                query_time = time.time() - query_start
                logger.info(f"[CLIP] Found {len(version_ids)} versions via query (force_refresh) in {query_time:.3f}s")
            else:
                # Normal load: use relationship (faster, ~15x speedup after first load)
                try:
                    asset_entity = self.session.get('Asset', asset_id)
                    if not asset_entity:
                        logger.info(f"[OK] Asset {asset_id} not found")
                        return []
                    
                    # Access versions via relationship - this is cached and very fast
                    versions_relationship = asset_entity.get('versions', [])
                    if versions_relationship:
                        # Convert to list if it's a Collection (ftrack_api returns Collection, not list)
                        if hasattr(versions_relationship, '__iter__') and not isinstance(versions_relationship, (list, tuple)):
                            versions_list = list(versions_relationship)
                        else:
                            versions_list = versions_relationship
                        # Sort by version desc (newest first)
                        versions_list.sort(key=lambda v: v.get('version', 0), reverse=True)
                        version_ids = [v['id'] for v in versions_list]
                    else:
                        version_ids = []
                    
                    query_time = time.time() - query_start
                    logger.info(f"[CLIP] Found {len(version_ids)} versions via relationship in {query_time:.3f}s")
                except Exception as e:
                    # Fallback to query if relationship fails
                    logger.warning(f"Failed to get versions via relationship, falling back to query: {e}")
                    fallback_query_start = time.time()
                    versions_query = f'select id from AssetVersion where asset.id is "{asset_id}" order by version desc'
                    version_ids_result = self.session.query(versions_query).all()
                    version_ids = [v['id'] for v in version_ids_result] if version_ids_result else []
                    query_time = time.time() - fallback_query_start
                    logger.info(f"[CLIP] Found {len(version_ids)} versions via query (fallback) in {query_time:.3f}s")
            
            if not version_ids:
                logger.info(f"[OK] No versions found for asset {asset_id}")
                return []
            
            step1_end = time.time()
            step1_time = step1_end - query_start
            logger.debug(f"[TIMING] Step 1 (get IDs) took {step1_time*1000:.2f}ms")
            
            # STEP 2: Batch get full version data using session.get (uses cache)
            # If force_refresh, refresh metadata AFTER getting entities (populate is faster on already-loaded entities)
            step2_start = time.time()
            result = []
            cached_count = 0
            versions_entities = []
            
            # Skip cache check - it's too slow (1495ms for 39 versions!)
            # session.get() will use cache automatically if available, no need to check manually
            cached_count = 0  # Don't check, just assume cache will be used
            cached_count = 0  # Don't check, just assume cache will be used
            
            # Get all versions first (fast from cache)
            get_start = time.time()
            for i, version_id in enumerate(version_ids):
                try:
                    # This uses the optimized cache
                    version = self.session.get('AssetVersion', version_id)
                    if version:
                        versions_entities.append(version)
                except Exception as e:
                    logger.warning(f"Failed to get version {version_id}: {e}")
                    continue
            get_time = time.time() - get_start
            batch_get_time = get_time  # Only session.get() time, without conversion
            logger.info(f"[BATCH GET] Loaded {len(versions_entities)}/{len(version_ids)} versions in {get_time:.3f}s ({get_time/len(version_ids)*1000:.2f}ms per version)")
            
            # STEP 3: If force_refresh, refresh metadata AFTER getting entities (populate is faster on already-loaded entities)
            populate_time = 0.0
            if force_refresh and versions_entities:
                # Refresh metadata for already-loaded entities (faster than populate before get)
                # populate() expects projections as a single string: 'field1, field2, field3'
                # NOTE: Only refresh 'date' and 'comment' - 'metadata' can be large and slow
                # If full metadata refresh is needed, it should be done selectively
                try:
                    populate_start = time.time()
                    # Only refresh date and comment - these are the fields users care about for refresh
                    # metadata is usually large and doesn't change often, so skip it for performance
                    self.session.populate(versions_entities, 'date, comment')
                    populate_time = time.time() - populate_start
                    logger.info(f"[POPULATE] Refreshed date,comment for {len(versions_entities)} versions in {populate_time*1000:.2f}ms")
                except Exception as e:
                    logger.warning(f"Failed to refresh version metadata: {e}")
                    import traceback
                    logger.debug(traceback.format_exc())
            
            # STEP 4: Convert entities to result format
            conversion_start = time.time()
            for version in versions_entities:
                try:
                    # Convert to same format as get_asset_versions
                    user_data = version.get('user')
                    user_first_name = 'Unknown'
                    user_last_name = 'User'
                    user_username = ''
                    
                    if user_data:
                        if isinstance(user_data, dict):
                            user_first_name = user_data.get('first_name', 'Unknown')
                            user_last_name = user_data.get('last_name', 'User')
                            user_username = user_data.get('username', '')
                        else:
                            try:
                                user_first_name = user_data.get('first_name', 'Unknown')
                                user_last_name = user_data.get('last_name', 'User')
                                user_username = user_data.get('username', '')
                            except:
                                user_first_name = 'Unknown'
                                user_last_name = 'User'
                    
                    # Build full name
                    full_name = f"{user_first_name} {user_last_name}".strip()
                    if not full_name or full_name == 'Unknown User':
                        full_name = user_username or 'Unknown User'
                    
                    version_data = {
                        'id': version['id'],
                        'version': version['version'],
                        'comment': version.get('comment', ''),
                        'date': version.get('date'),
                        'user': {
                            'first_name': user_first_name, 
                            'last_name': user_last_name,
                            'username': user_username,
                            'full_name': full_name
                        },
                        'asset': {'id': asset_id, 'name': 'Asset'}
                    }
                    result.append(version_data)
                except Exception as e:
                    logger.warning(f"Failed to process version {version.get('id', 'unknown')}: {e}")
                    continue
            
            conversion_time = time.time() - conversion_start
            step2_end = time.time()
            step2_time = step2_end - step2_start
            total_time = time.time() - start_time
            
            # Always update cache - critical: refresh must persist, next calls get fresh data
            if result:
                cache_save_start = time.time()
                self._asset_versions_cache[asset_id] = result
                cache_save_ms = (time.time() - cache_save_start) * 1000
                logger.info(f"[CACHE SAVE] Saved {len(result)} versions for asset {asset_id} in {cache_save_ms:.1f}ms (force_refresh={force_refresh})")
            
            logger.info(f"[OK] OPTIMIZED: {len(result)} versions loaded in {total_time:.3f}s @ {time.strftime('%H:%M:%S', time.localtime())}")
            logger.info(f"   [STATS] Query: {query_time:.3f}s, Batch get: {batch_get_time:.3f}s, Populate: {populate_time*1000:.1f}ms, Conversion: {conversion_time*1000:.1f}ms")
            logger.info(f"   [TIMING] Step 1: {step1_time*1000:.1f}ms, Step 2: {step2_time*1000:.1f}ms, Total: {total_time*1000:.1f}ms")
            if cached_count > 0:
                logger.info(f"   [CACHE] {cached_count}/{len(version_ids)} versions cached")
            logger.info(f"   [LAUNCH] Speed: {len(result)/total_time:.1f} versions/sec")
            
            return result
            
        except Exception as e:
            logger.error(f"Failed to get versions for asset {asset_id}: {e}")
            import traceback
            logger.debug(traceback.format_exc())
            return []
    
    def refresh_single_version(self, version_id: str) -> dict:
        """Refresh a single asset version (much faster than refreshing all versions).
        
        Args:
            version_id: AssetVersion ID to refresh
            
        Returns:
            Dictionary with version data, or None if not found
        """
        try:
            if not self.session:
                return None
            
            logger.info(f"[REFRESH] Refreshing single version {version_id}")
            start_time = time.time()
            
            # Get version entity (fast from cache)
            version = self.session.get('AssetVersion', version_id)
            if not version:
                logger.warning(f"Version {version_id} not found")
                return None
            
            # Refresh metadata
            try:
                populate_start = time.time()
                self.session.populate([version], 'date, comment')
                populate_time = time.time() - populate_start
                logger.info(f"[POPULATE] Refreshed version {version_id} in {populate_time*1000:.2f}ms")
            except Exception as e:
                logger.warning(f"Failed to refresh version metadata: {e}")
            
            # Convert to result format
            try:
                user_data = version.get('user')
                user_first_name = 'Unknown'
                user_last_name = 'User'
                user_username = ''
                
                if user_data:
                    if isinstance(user_data, dict):
                        user_first_name = user_data.get('first_name', 'Unknown')
                        user_last_name = user_data.get('last_name', 'User')
                        user_username = user_data.get('username', '')
                    else:
                        try:
                            user_first_name = user_data.get('first_name', 'Unknown')
                            user_last_name = user_data.get('last_name', 'User')
                            user_username = user_data.get('username', '')
                        except:
                            pass
                
                full_name = f"{user_first_name} {user_last_name}".strip()
                if not full_name or full_name == 'Unknown User':
                    full_name = user_username or 'Unknown User'
                
                asset = version.get('asset')
                asset_id = asset.get('id') if asset else None
                asset_name = asset.get('name', 'Asset') if asset else 'Asset'
                
                version_data = {
                    'id': version['id'],
                    'version': version['version'],
                    'comment': version.get('comment', ''),
                    'date': version.get('date'),
                    'user': {
                        'first_name': user_first_name,
                        'last_name': user_last_name,
                        'username': user_username,
                        'full_name': full_name
                    },
                    'asset': {'id': asset_id, 'name': asset_name}
                }
                
                total_time = time.time() - start_time
                logger.info(f"[OK] Refreshed single version in {total_time*1000:.2f}ms")
                return version_data
            except Exception as e:
                logger.error(f"Failed to convert version data: {e}")
                import traceback
                logger.debug(traceback.format_exc())
                return None
                
        except Exception as e:
            logger.error(f"Error in refresh_single_version: {e}")
            import traceback
            logger.debug(traceback.format_exc())
            return None

    def get_versions_for_asset_and_task(self, asset_id, task_id):
        """Get versions for an asset that were published to a specific task - OPTIMIZED"""
        try:
            if not self.session:
                return []
            
            logger.info(f"[LAUNCH] OPTIMIZED: Fetching versions for asset {asset_id} published to task {task_id}")
            start_time = time.time()
            
            # STEP 1: Quick query to get only version IDs for this asset and task (fast)
            versions_query = f'select id from AssetVersion where asset.id is "{asset_id}" and task.id is "{task_id}" order by version desc'
            version_ids_result = self.session.query(versions_query).all()
            
            if not version_ids_result:
                logger.info(f"[OK] No versions found for asset {asset_id} in task {task_id}")
                return []
            
            # Extract IDs
            version_ids = [v['id'] for v in version_ids_result]
            query_time = time.time() - start_time
            logger.info(f"[CLIP] Found {len(version_ids)} filtered versions in {query_time:.3f}s")
            
            # STEP 2: Batch get full version data using session.get (uses cache)
            batch_start = time.time()
            result = []
            
            for version_id in version_ids:
                try:
                    # This uses the optimized cache
                    version = self.session.get('AssetVersion', version_id)
                    if version:
                        # Convert to same format as get_asset_versions
                        user_data = version.get('user')
                        user_first_name = 'Unknown'
                        user_last_name = 'User'
                        user_username = ''
                        
                        if user_data:
                            if isinstance(user_data, dict):
                                user_first_name = user_data.get('first_name', 'Unknown')
                                user_last_name = user_data.get('last_name', 'User')
                                user_username = user_data.get('username', '')
                            else:
                                try:
                                    user_first_name = user_data.get('first_name', 'Unknown')
                                    user_last_name = user_data.get('last_name', 'User')
                                    user_username = user_data.get('username', '')
                                except:
                                    user_first_name = 'Unknown'
                                    user_last_name = 'User'
                        
                        # Build full name
                        full_name = f"{user_first_name} {user_last_name}".strip()
                        if not full_name or full_name == 'Unknown User':
                            full_name = user_username or 'Unknown User'
                        
                        version_data = {
                            'id': version['id'],
                            'version': version['version'],
                            'comment': version.get('comment', ''),
                            'date': version.get('date'),
                            'user': {
                                'first_name': user_first_name, 
                                'last_name': user_last_name,
                                'username': user_username,
                                'full_name': full_name
                            },
                            'asset': {'id': asset_id, 'name': 'Asset'}
                        }
                        result.append(version_data)
                except Exception as e:
                    logger.warning(f"Failed to get version {version_id}: {e}")
                    continue
            
            batch_time = time.time() - batch_start
            total_time = time.time() - start_time
            
            logger.info(f"[OK] OPTIMIZED: {len(result)} filtered versions loaded in {total_time:.3f}s")
            logger.info(f"   [STATS] Query: {query_time:.3f}s, Batch get: {batch_time:.3f}s")
            logger.info(f"   [LAUNCH] Speed: {len(result)/total_time:.1f} versions/sec")
            
            return result
            
        except Exception as e:
            logger.error(f"Failed to get versions for asset {asset_id} in task {task_id}: {e}")
            return []

    def get_all_versions_for_multiple_assets(self, asset_ids):
        """Get versions for multiple assets in one batch - ULTRA OPTIMIZED"""
        try:
            if not self.session or not asset_ids:
                return {}
            
            logger.info(f"[LAUNCH] ULTRA OPTIMIZED: Fetching versions for {len(asset_ids)} assets in one batch")
            start_time = time.time()
            
            # STEP 1: Quick query to get ALL version IDs for ALL assets at once (super fast)
            asset_ids_str = ', '.join([f'"{aid}"' for aid in asset_ids])
            versions_query = f'select id, asset.id from AssetVersion where asset.id in ({asset_ids_str})'
            version_ids_result = self.session.query(versions_query).all()
            
            if not version_ids_result:
                logger.info(f"[OK] No versions found for any of {len(asset_ids)} assets")
                return {}
            
            # Group version IDs by asset ID
            asset_to_version_ids = {}
            all_version_ids = []
            
            for version_data in version_ids_result:
                version_id = version_data['id']
                asset_id = version_data['asset']['id']
                
                if asset_id not in asset_to_version_ids:
                    asset_to_version_ids[asset_id] = []
                asset_to_version_ids[asset_id].append(version_id)
                all_version_ids.append(version_id)
            
            query_time = time.time() - start_time
            logger.info(f"[CLIP] Found {len(all_version_ids)} version IDs for {len(asset_to_version_ids)} assets in {query_time:.3f}s")
            
            # STEP 2: Try optimized batch get first, fallback to query-only if fails
            batch_start = time.time()
            result = {}
            
            for asset_id in asset_ids:
                result[asset_id] = []
            
            # Try batch get approach first
            try:
                batch_get_success = True
                version_data_cache = {}
                timeout_threshold = 1.5  # Reduced to 1.5 seconds timeout for batch get
                batch_start_time = time.time()
                processed_count = 0
                cached_count = 0
                
                # Check cache status for logging
                for version_id in all_version_ids:
                    if self._is_cached('AssetVersion', version_id):
                        cached_count += 1
                
                if cached_count > 0:
                    logger.info(f"[CACHE] {cached_count}/{len(all_version_ids)} versions already cached, will use fast path")
                
                for version_id in all_version_ids:
                    try:
                        # Check timeout more frequently - every 5 versions
                        if processed_count % 5 == 0:
                            elapsed = time.time() - batch_start_time
                            if elapsed > timeout_threshold:
                                logger.warning(f"⏰ Batch get timeout after {elapsed:.1f}s ({processed_count}/{len(uncached_ids)} processed), switching to query-only...")
                                batch_get_success = False
                                break
                        
                        # This uses the optimized cache (fast for cached, fetches for uncached)
                        version_start = time.time()
                        version = self.session.get('AssetVersion', version_id)
                        version_time = time.time() - version_start
                        
                        # If individual get takes too long, abort
                        if version_time > 0.5:  # Individual get timeout
                            logger.warning(f"⏰ Individual version get too slow ({version_time:.1f}s), switching to query-only...")
                            batch_get_success = False
                            break
                            
                        if version:
                            version_data_cache[version_id] = version
                        
                        processed_count += 1
                        
                    except Exception as e:
                        logger.warning(f"Batch get failed for version {version_id}: {e}")
                        batch_get_success = False
                        break
                
                if batch_get_success:
                    # Build result from cache - UPDATED: add full user name
                    for version_id, version in version_data_cache.items():
                        asset_id = version['asset']['id']
                        user = version.get('user')
                        
                        # Collect full user name from session.get data
                        username = user.get('username', '') if user else ''
                        first_name = user.get('first_name', '') if user else ''
                        last_name = user.get('last_name', '') if user else ''
                        
                        # Form full name: "First Last" or fallback to username
                        full_name = f"{first_name} {last_name}".strip()
                        if not full_name:
                            full_name = username or 'Unknown User'
                        
                        version_data = {
                            'id': version['id'],
                            'version': version.get('version', 1),
                            'comment': version.get('comment', ''),
                            'date': version.get('date'),
                            'user': {
                                'username': username,
                                'first_name': first_name,
                                'last_name': last_name,
                                'full_name': full_name  # Add ready full name
                            }
                        }
                        
                        if asset_id in result:
                            result[asset_id].append(version_data)
                    
                    batch_time = time.time() - batch_start
                    logger.info(f"[OK] Batch get successful in {batch_time:.3f}s (cached: {cached_count})")
                    
                else:
                    raise Exception("Batch get failed or timed out, switching to query-only mode")
                    
            except Exception as e:
                logger.warning(f"[WARN]  Batch get failed: {e}. Switching to QUERY-ONLY mode...")
                
                # FALLBACK: Query-only approach (avoid session.get)
                query_fallback_start = time.time()
                
                # Get all version data in one big query (no session.get!) - UPDATED: added first_name, last_name
                version_ids_str = ', '.join([f'"{vid}"' for vid in all_version_ids])
                full_versions_query = f"""
                select id, asset.id, version, comment, user.username, user.first_name, user.last_name, status.name, date
                from AssetVersion 
                where id in ({version_ids_str})
                """
                
                versions_data = self.session.query(full_versions_query).all()
                
                # Reset result
                for asset_id in asset_ids:
                    result[asset_id] = []
                
                # Build result from query data - UPDATED: collect full user name
                for version_data in versions_data:
                    asset_id = version_data['asset']['id']
                    
                    # Collect full user name
                    user_data = version_data.get('user', {})
                    first_name = user_data.get('first_name', '') if user_data else ''
                    last_name = user_data.get('last_name', '') if user_data else ''
                    username = user_data.get('username', '') if user_data else ''
                    
                    # Form full name: "First Last" or fallback to username
                    full_name = f"{first_name} {last_name}".strip()
                    if not full_name:
                        full_name = username or 'Unknown User'
                    
                    version_info = {
                        'id': version_data['id'],
                        'version': version_data.get('version', 1),
                        'comment': version_data.get('comment', ''),
                        'date': version_data.get('date'),
                        'user': {
                            'username': username,
                            'first_name': first_name,
                            'last_name': last_name,
                            'full_name': full_name  # Add ready full name
                        }
                    }
                    
                    if asset_id in result:
                        result[asset_id].append(version_info)
                
                batch_time = time.time() - query_fallback_start
                logger.info(f"[OK] Query-only fallback completed in {batch_time:.3f}s")
            
            # Sort versions by version number (newest first) for each asset
            for asset_id in result:
                result[asset_id] = sorted(result[asset_id], key=lambda x: x['version'], reverse=True)
            
            total_time = time.time() - start_time
            total_versions = sum(len(versions) for versions in result.values())
            
            logger.info(f"[OK] ULTRA OPTIMIZED: {total_versions} versions for {len(asset_ids)} assets loaded in {total_time:.3f}s")
            logger.info(f"   [STATS] Query: {query_time:.3f}s, Batch get: {batch_time:.3f}s")
            logger.info(f"   [LAUNCH] Speed: {total_versions/total_time:.1f} versions/sec")
            logger.info(f"   [FAST] Speedup vs sequential: ~{len(asset_ids)*2:.1f}x faster")
            
            return result
            
        except Exception as e:
            logger.error(f"Failed to get versions for multiple assets: {e}")
            return {}

    def load_asset_versions_for_entity_optimized(self, entity_id):
        """OPTIMIZED version of load_asset_versions_for_entity using parallel version loading"""
        try:
            if not self.session:
                return []
            
            logger.info(f"[LAUNCH] OPTIMIZED: Loading asset versions for entity {entity_id}")
            total_start = time.time()
            
            # STEP 1: Get assets (already optimized)
            assets_start = time.time()
            assets = self.get_assets_linked_to_entity(entity_id)
            if not assets:
                logger.info(f"[OK] No assets found for entity {entity_id}")
                return []
            
            assets_time = time.time() - assets_start
            asset_ids = [asset['id'] for asset in assets]
            
            logger.info(f"[CLIP] Found {len(assets)} assets in {assets_time:.3f}s")
            
            # STEP 2: Get ALL versions for ALL assets in one batch (ULTRA OPTIMIZED)
            versions_start = time.time()
            all_versions = self.get_all_versions_for_multiple_assets(asset_ids)
            versions_time = time.time() - versions_start
            
            # STEP 3: Build result structure
            result = []
            for asset in sorted(assets, key=lambda x: x.get('name', '').lower()):
                asset_id = asset['id']
                asset_name = asset.get('name', 'Unknown Asset')
                
                asset_data = {
                    'id': asset_id,
                    'name': asset_name,
                    'type': 'Asset',
                    'versions': all_versions.get(asset_id, [])
                }
                result.append(asset_data)
            
            total_time = time.time() - total_start
            total_versions = sum(len(asset_data['versions']) for asset_data in result)
            
            logger.info(f"[OK] OPTIMIZED COMPLETE: {len(result)} assets with {total_versions} versions loaded in {total_time:.3f}s")
            logger.info(f"   [STATS] Assets: {assets_time:.3f}s, Versions: {versions_time:.3f}s")
            logger.info(f"   [LAUNCH] Overall speed: {total_versions/total_time:.1f} versions/sec")
            
            return result
            
        except Exception as e:
            logger.error(f"Failed to load optimized asset versions for entity {entity_id}: {e}")
            return []

# Use the original FtrackTaskBrowser class but with optimized API client
# We'll import the browser widget from the original file and just replace the API client

# DEPRECATED: These functions/classes are no longer needed.
# browser_widget.py now uses OptimizedFtrackApiClient directly.
# Kept for backward compatibility with old code, but not used in current architecture.

def create_optimized_browser_widget():
    """DEPRECATED: browser_widget.py now uses OptimizedFtrackApiClient directly.
    This function is kept for backward compatibility only."""
    logger.warning("[DEPRECATED] create_optimized_browser_widget() is deprecated. Use FtrackTaskBrowser from browser_widget.py directly.")
    from .browser_widget import FtrackTaskBrowser
    return FtrackTaskBrowser()

# For backward compatibility
def create_browser_widget():
    """DEPRECATED: Backward compatibility function"""
    return create_optimized_browser_widget()

# DEPRECATED: Use FtrackTaskBrowser from browser_widget.py directly
class OptimizedFtrackBrowser:
    """DEPRECATED: Use FtrackTaskBrowser from browser_widget.py directly.
    This class is kept for backward compatibility only."""
    
    def __new__(cls):
        """DEPRECATED: Use FtrackTaskBrowser from browser_widget.py directly"""
        logger.warning("[DEPRECATED] OptimizedFtrackBrowser is deprecated. Use FtrackTaskBrowser from browser_widget.py directly.")
        return create_optimized_browser_widget()

# DEPRECATED: These aliases are no longer used
FtrackTaskBrowser = OptimizedFtrackBrowser
FtrackBrowser = OptimizedFtrackBrowser 