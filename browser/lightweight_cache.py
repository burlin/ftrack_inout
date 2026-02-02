"""
Lightweight Ftrack Cache

Lightweight caching module for use in HDA nodes.
Minimal dependencies, fast initialization, efficient caching.
"""

import os
import logging
import time
from typing import Optional, Dict, Any, List

logger = logging.getLogger(__name__)

try:
    import ftrack_api
    FTRACK_AVAILABLE = True
except ImportError:
    FTRACK_AVAILABLE = False
    logger.warning("ftrack_api not available")


class LightweightFtrackCache:
    """
    Lightweight cache for ftrack data
    Optimized for fast access in HDA nodes
    """
    
    def __init__(self, session=None, cache_duration=300):
        """
        Args:
            session: ftrack session (if None - will be created automatically)
            cache_duration: cache lifetime in seconds (default 5 minutes)
        """
        self.session = session
        self.cache_duration = cache_duration
        self._cache = {}
        self._cache_timestamps = {}
        self._session_created = False
        
        if not self.session and FTRACK_AVAILABLE:
            self._create_session()
    
    def _create_session(self):
        """Create ftrack session"""
        try:
            self.session = ftrack_api.Session()
            self._session_created = True
            logger.info("[OK] Ftrack session created")
        except Exception as e:
            logger.error(f"[FAIL] Failed to create ftrack session: {e}")
            self.session = None
    
    def _is_cache_valid(self, key):
        """Check cache validity"""
        if key not in self._cache_timestamps:
            return False
        
        age = time.time() - self._cache_timestamps[key]
        return age < self.cache_duration
    
    def _set_cache(self, key, value):
        """Set value in cache"""
        self._cache[key] = value
        self._cache_timestamps[key] = time.time()
    
    def _get_cache(self, key):
        """Get value from cache"""
        if self._is_cache_valid(key):
            return self._cache[key]
        return None
    
    def get_asset_version(self, asset_version_id):
        """
        Get asset version by ID
        
        Args:
            asset_version_id: Asset version ID
            
        Returns:
            dict: asset version data or None
        """
        if not self.session or not asset_version_id:
            return None
        
        cache_key = f"asset_version_{asset_version_id}"
        cached = self._get_cache(cache_key)
        if cached is not None:
            return cached
        
        try:
            asset_version = self.session.get('AssetVersion', asset_version_id)
            if asset_version:
                result = {
                    'id': asset_version['id'],
                    'version_number': asset_version['version_number'],
                    'comment': asset_version.get('comment', ''),
                    'asset_name': asset_version['asset']['name'],
                    'asset_id': asset_version['asset']['id']
                }
                self._set_cache(cache_key, result)
                return result
        except Exception as e:
            logger.warning(f"Failed to get asset version {asset_version_id}: {e}")
        
        return None
    
    def get_component(self, component_id):
        """
        Get component by ID
        
        Args:
            component_id: Component ID
            
        Returns:
            dict: component data or None
        """
        if not self.session or not component_id:
            return None
        
        cache_key = f"component_{component_id}"
        cached = self._get_cache(cache_key)
        if cached is not None:
            return cached
        
        try:
            component = self.session.get('Component', component_id)
            if component:
                # Get file path
                file_path = None
                try:
                    location = self.session.pick_location()
                    file_path = location.get_resource_identifier(component)
                except:
                    pass
                
                result = {
                    'id': component['id'],
                    'name': component['name'],
                    'file_type': component.get('file_type', ''),
                    'size': component.get('size', 0),
                    'file_path': file_path
                }
                self._set_cache(cache_key, result)
                return result
        except Exception as e:
            logger.warning(f"Failed to get component {component_id}: {e}")
        
        return None
    
    def get_task(self, task_id):
        """
        Get task by ID
        
        Args:
            task_id: Task ID
            
        Returns:
            dict: task data or None
        """
        if not self.session or not task_id:
            return None
        
        cache_key = f"task_{task_id}"
        cached = self._get_cache(cache_key)
        if cached is not None:
            return cached
        
        try:
            task = self.session.get('Task', task_id)
            if task:
                result = {
                    'id': task['id'],
                    'name': task['name'],
                    'type_name': task['type']['name'],
                    'status_name': task['status']['name']
                }
                self._set_cache(cache_key, result)
                return result
        except Exception as e:
            logger.warning(f"Failed to get task {task_id}: {e}")
        
        return None
    
    def get_asset_version_components(self, asset_version_id):
        """
        Get all components of asset version
        
        Args:
            asset_version_id: Asset version ID
            
        Returns:
            list: list of components
        """
        if not self.session or not asset_version_id:
            return []
        
        cache_key = f"components_{asset_version_id}"
        cached = self._get_cache(cache_key)
        if cached is not None:
            return cached
        
        try:
            query = f"select id, name, file_type, size from Component where version_id is '{asset_version_id}'"
            components = self.session.query(query).all()
            
            result = []
            for comp in components:
                result.append({
                    'id': comp['id'],
                    'name': comp['name'],
                    'file_type': comp.get('file_type', ''),
                    'size': comp.get('size', 0)
                })
            
            self._set_cache(cache_key, result)
            return result
        except Exception as e:
            logger.warning(f"Failed to get components for asset version {asset_version_id}: {e}")
        
        return []
    
    def clear_cache(self):
        """Clear cache"""
        self._cache.clear()
        self._cache_timestamps.clear()
        logger.info("🗑 Cache cleared")
    
    def get_cache_stats(self):
        """Get cache statistics"""
        total_items = len(self._cache)
        valid_items = sum(1 for key in self._cache if self._is_cache_valid(key))
        
        return {
            'total_items': total_items,
            'valid_items': valid_items,
            'expired_items': total_items - valid_items,
            'cache_duration': self.cache_duration
        }
    
    def cleanup_expired(self):
        """Remove expired cache items"""
        expired_keys = [key for key in self._cache if not self._is_cache_valid(key)]
        for key in expired_keys:
            del self._cache[key]
            del self._cache_timestamps[key]
        
        if expired_keys:
            logger.info(f"🧹 Cleaned up {len(expired_keys)} expired cache items")
    
    def close(self):
        """Close connection"""
        if self._session_created and self.session:
            try:
                self.session.close()
                logger.info("🔒 Ftrack session closed")
            except:
                pass
            self.session = None
            self._session_created = False


# Global instance for convenience
_global_cache = None


def get_global_cache(cache_duration=300):
    """
    Get global cache instance
    
    Args:
        cache_duration: cache lifetime in seconds
        
    Returns:
        LightweightFtrackCache: cache instance
    """
    global _global_cache
    if _global_cache is None:
        _global_cache = LightweightFtrackCache(cache_duration=cache_duration)
    return _global_cache


def clear_global_cache():
    """Clear global cache"""
    global _global_cache
    if _global_cache:
        _global_cache.clear_cache()


def close_global_cache():
    """Close global cache"""
    global _global_cache
    if _global_cache:
        _global_cache.close()
        _global_cache = None


# Convenience functions for quick access
def get_asset_version_info(asset_version_id, cache_duration=300):
    """
    Quick get asset version information
    
    Args:
        asset_version_id: Asset version ID
        cache_duration: cache lifetime
        
    Returns:
        dict: asset version information
    """
    cache = get_global_cache(cache_duration)
    return cache.get_asset_version(asset_version_id)


def get_component_info(component_id, cache_duration=300):
    """
    Quick get component information
    
    Args:
        component_id: Component ID
        cache_duration: cache lifetime
        
    Returns:
        dict: component information
    """
    cache = get_global_cache(cache_duration)
    return cache.get_component(component_id)


def get_task_info(task_id, cache_duration=300):
    """
    Quick get task information
    
    Args:
        task_id: Task ID
        cache_duration: cache lifetime
        
    Returns:
        dict: task information
    """
    cache = get_global_cache(cache_duration)
    return cache.get_task(task_id)


# Example usage in HDA node:
"""
# In HDA node (e.g., finput):

from ftrack_inout.browser.lightweight_cache import get_asset_version_info, get_component_info

# Get IDs from node parameters
asset_version_id = hou.pwd().parm("assetversionid").eval()
component_id = hou.pwd().parm("componentid").eval()

# Quick get information (with caching)
if asset_version_id:
    asset_info = get_asset_version_info(asset_version_id)
    if asset_info:
        print(f"Asset: {asset_info['asset_name']}, Version: {asset_info['version_number']}")

if component_id:
    comp_info = get_component_info(component_id)
    if comp_info and comp_info['file_path']:
        # Use file path
        file_path = comp_info['file_path']
        print(f"Component file: {file_path}")
""" 