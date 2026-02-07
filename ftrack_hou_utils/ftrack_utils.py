import ftrack_api
from typing import Optional, Dict, Any, List
from .logger_utils import get_logger

logger = get_logger("ftrack.utils")

# Global Ftrack session cache for the entire Houdini instance (fallback)
_ftrack_session: Optional[ftrack_api.Session] = None

def get_session() -> Optional[ftrack_api.Session]:
    """
    Get a shared, cached ftrack_api.Session with optimized caching.
    First tries to use the common session factory (with optimized caching),
    falls back to local session cache if common module is not available.
    """
    global _ftrack_session
    
    # Try to use shared session factory (with optimized caching)
    try:
        from ..common.session_factory import get_shared_session
        session = get_shared_session()
        if session:
            # Cache locally for backward compatibility
            _ftrack_session = session
            return session
    except ImportError:
        logger.debug("Common session factory not available, using local session cache")
    except Exception as e:
        logger.debug(f"Failed to get shared session: {e}")
    
    # Fallback: Use local session cache
    if _ftrack_session is None:
        try:
            logger.info("No shared Ftrack session found, creating a new one...")
            _ftrack_session = ftrack_api.Session(auto_connect_event_hub=True)
            logger.info("New Ftrack session created and cached.")
        except Exception as e:
            logger.error(f"Failed to create shared ftrack session: {e}", exc_info=True)
            return None
    return _ftrack_session

def get_entity(entity_type: str, entity_id: str) -> Optional[Dict[str, Any]]:
    """Get entity by type and ID using the shared session."""
    session = get_session()
    if not session:
        return None
    try:
        entity = session.get(entity_type, entity_id)
        logger.info(f"Successfully fetched entity: {entity_type} {entity_id}")
        return entity
    except Exception as e:
        logger.error(f"Failed to get {entity_type} {entity_id}: {e}", exc_info=True)
        return None

def query_one(query: str) -> Optional[Dict[str, Any]]:
    """Execute a query and return the first result using the shared session."""
    session = get_session()
    if not session:
        return None
    try:
        result = session.query(query).first()
        if result:
            logger.info(f"Query successful for: {query}")
        else:
            logger.warning(f"Query returned no results for: {query}")
        return result
    except Exception as e:
        logger.error(f"Query failed: {query} - {e}", exc_info=True)
        return None

def query_all(query: str) -> List[Dict[str, Any]]:
    """Execute a query and return all results using the shared session."""
    session = get_session()
    if not session:
        return []
    try:
        results = session.query(query).all()
        logger.info(f"Query successful, found {len(results)} results for: {query}")
        return results
    except Exception as e:
        logger.error(f"Query failed: {query} - {e}", exc_info=True)
        return []

def _normalize_path_for_houdini(path: str) -> str:
    """Normalize path: backslashes to forward, %04d to $F4."""
    path = path.replace("\\", "/")
    if ".%04d." in path:
        path = path.replace(".%04d.", ".$F4.")
    return path


def get_component_path(component: Dict[str, Any]) -> Optional[str]:
    """
    Gets the filesystem path for a given ftrack component entity.

    First tries session.pick_location(). If the component is not there (e.g.
    pick_location returns ftrack.unmanaged but component is in burlin.local),
    iterates over all locations with 100% availability and uses the first
    that successfully returns a path. Prefers Disk locations over S3.
    """
    session = get_session()
    if not session or not component:
        return None

    # 1) Try pick_location first (same as before)
    try:
        location = session.pick_location()
        if location:
            availability = location.get_component_availability(component)
            if availability >= 100.0:
                path = location.get_filesystem_path(component)
                if path and str(path).strip():
                    path = _normalize_path_for_houdini(str(path))
                    logger.info(f"Resolved path for component '{component['name']}': {path}")
                    return path
    except Exception as e:
        logger.debug(f"pick_location path failed for '{component['name']}': {e}")

    # 2) Fallback: iterate over locations where component has 100% availability
    try:
        locations = session.query("Location").all()
        disk_locations = []
        other_locations = []
        for loc in locations:
            try:
                avail = loc.get_component_availability(component)
                if avail < 100.0:
                    continue
                acc = getattr(loc, "accessor", None)
                if acc and hasattr(acc, "get_filesystem_path"):
                    if hasattr(ftrack_api.accessor, "disk") and isinstance(acc, ftrack_api.accessor.disk.DiskAccessor):
                        disk_locations.append(loc)
                    else:
                        other_locations.append(loc)
            except Exception:
                continue

        for loc in disk_locations + other_locations:
            try:
                path = loc.get_filesystem_path(component)
                if path and str(path).strip():
                    path = _normalize_path_for_houdini(str(path))
                    logger.info(f"Resolved path for component '{component['name']}' via {loc['name']}: {path}")
                    return path
            except Exception as e:
                logger.debug(f"Location {loc.get('name', '?')} get_filesystem_path failed: {e}")
                continue
    except Exception as e:
        logger.error(f"Fallback location iteration failed for '{component['name']}': {e}", exc_info=True)

    return None 