"""
Cache wrappers for Ftrack API optimization

Provides memory and logging cache layers to improve performance
and provide debugging information for Ftrack API calls.
"""

import time
import logging

logger = logging.getLogger(__name__)

# Try to import ftrack_api (graceful degradation if not available)
FTRACK_API_AVAILABLE = False
try:
    # Use local ftrack_api from dependencies
    # Dependencies are located in ftrack_inout/dependencies
    try:
        # Try to import from ftrack_inout/dependencies
        import sys
        from pathlib import Path
        _this_file = Path(__file__).resolve()
        _deps_path = _this_file.parent.parent / 'dependencies'
        if str(_deps_path) not in sys.path and _deps_path.exists():
            sys.path.insert(0, str(_deps_path))
        import ftrack_api
        import ftrack_api.cache
        import ftrack_api.symbol
    except ImportError:
        # Fallback to system ftrack_api
        import ftrack_api
        import ftrack_api.cache
        import ftrack_api.symbol
    FTRACK_API_AVAILABLE = True
except ImportError:
    logger.debug("ftrack_api not available - some cache features disabled")
    # Create mock objects for graceful degradation
    class MockSymbol:
        NOT_SET = object()
    
    class MockCache:
        pass
    
    # Create namespace-like objects
    ftrack_api = type('MockFtrackApi', (), {
        'cache': type('MockCacheModule', (), {'Cache': MockCache}),
        'symbol': MockSymbol
    })()


class MemoryCacheWrapper(ftrack_api.cache.Cache if FTRACK_API_AVAILABLE else object):
    """Fast memory cache layer over file cache with LRU eviction"""
    
    def __init__(self, wrapped_cache, max_size=1000):
        if FTRACK_API_AVAILABLE:
            super(MemoryCacheWrapper, self).__init__()
        self.wrapped_cache = wrapped_cache
        self._memory_cache = {}
        self._access_order = []
        self._max_size = max_size
        logger.info(f"MemoryCacheWrapper initialized with max_size={max_size}")
    
    def _evict_if_needed(self):
        """Remove oldest items if cache is full"""
        while len(self._memory_cache) >= self._max_size and self._access_order:
            oldest_key = self._access_order.pop(0)
            self._memory_cache.pop(oldest_key, None)
    
    def _update_access(self, key):
        """Update access order for LRU"""
        if key in self._access_order:
            self._access_order.remove(key)
        self._access_order.append(key)
    
    def get(self, key):
        # Check memory first
        if key in self._memory_cache:
            self._update_access(key)
            logger.debug(f"MEMORY HIT for {key}")
            return self._memory_cache[key]
        
        # Fallback to wrapped cache (if available)
        if self.wrapped_cache:
            logger.info(f"MEMORY MISS for {key}, checking disk... (memory size: {len(self._memory_cache)})")
            value = self.wrapped_cache.get(key)
            if value is not ftrack_api.symbol.NOT_SET:
                logger.info(f"Got value from wrapped cache, storing in memory...")
                self._evict_if_needed()
                self._memory_cache[key] = value
                self._update_access(key)
                logger.info(f"STORED IN MEMORY: {key}, memory size now: {len(self._memory_cache)}")
            else:
                logger.info(f"Not found on disk either")
            return value
        else:
            # No wrapped cache - return NOT_SET
            logger.debug(f"MEMORY MISS for {key}, no wrapped cache")
            return ftrack_api.symbol.NOT_SET
    
    def set(self, key, value):
        if self.wrapped_cache:
            self.wrapped_cache.set(key, value)
        self._evict_if_needed()
        self._memory_cache[key] = value
        self._update_access(key)
        logger.info(f"SET in memory cache: {key}, size now: {len(self._memory_cache)}")
    
    def remove(self, key):
        if self.wrapped_cache:
            self.wrapped_cache.remove(key)
        self._memory_cache.pop(key, None)
        if key in self._access_order:
            self._access_order.remove(key)
    
    def clear(self, expression=None):
        if self.wrapped_cache:
            self.wrapped_cache.clear(expression)
        self._memory_cache.clear()
        self._access_order.clear()

    @property
    def memory_size(self):
        """Get current memory cache size"""
        return len(self._memory_cache)
    
    @property
    def max_size(self):
        """Get maximum memory cache size"""
        return self._max_size
    
    def report_stats(self):
        """Report memory cache statistics"""
        logger.info(f"Memory Cache Stats: {len(self._memory_cache)}/{self._max_size} items ({100*len(self._memory_cache)/self._max_size:.1f}% full)")
        return {
            'size': len(self._memory_cache),
            'max_size': self._max_size,
            'usage_percent': 100 * len(self._memory_cache) / self._max_size
        }


class LoggingCacheWrapper(ftrack_api.cache.Cache if FTRACK_API_AVAILABLE else object):
    """Cache wrapper that logs cache hits/misses with timing"""
    
    def __init__(self, wrapped_cache, logger_instance=None):
        if FTRACK_API_AVAILABLE:
            super(LoggingCacheWrapper, self).__init__()
        self.wrapped_cache = wrapped_cache
        self.logger = logger_instance or logger

    def get(self, key):
        start_time = time.time()
        
        # Check if the wrapped cache is a MemoryCacheWrapper
        is_memory_cache = isinstance(self.wrapped_cache, MemoryCacheWrapper)
        was_in_memory = False
        
        if is_memory_cache:
            # Check if key is in memory BEFORE the get call
            was_in_memory = key in self.wrapped_cache._memory_cache
            self.logger.info(f"OUR_CACHE CHECK key {key}: {'IN MEMORY' if was_in_memory else 'NOT IN MEMORY'}")
        
        value = self.wrapped_cache.get(key)
        elapsed = (time.time() - start_time) * 1000  # Convert to milliseconds
        
        if value is ftrack_api.symbol.NOT_SET:
            self.logger.info(f"OUR_CACHE MISS for key: {key}. Will fetch from server. ({elapsed:.1f}ms)")
        else:
            # For MemoryCacheWrapper, determine actual source based on timing and previous state
            if is_memory_cache:
                if was_in_memory and elapsed < 5:  # Fast response from memory
                    cache_type = "OUR_MEMORY"
                elif not was_in_memory and elapsed < 5:  # Fast but wasn't in memory = just loaded
                    cache_type = "DISK->OUR_MEMORY" 
                else:  # Slow response = disk access
                    cache_type = "DISK"
            else:
                cache_type = "DISK"
                
            self.logger.info(f"OUR_CACHE HIT ({cache_type}) for key: {key}. ({elapsed:.1f}ms)")
        return value

    def set(self, key, value):
        self.wrapped_cache.set(key, value)

    def remove(self, key):
        self.wrapped_cache.remove(key)

    def clear(self, expression=None):
        self.wrapped_cache.clear(expression)

    @property
    def Mtime(self):
        if hasattr(self.wrapped_cache, 'Mtime'):
            return self.wrapped_cache.Mtime
        return super(LoggingCacheWrapper, self).Mtime


def create_optimized_cache(session_instance, cache_path, max_memory_size=50000, logger_instance=None):
    """
    Create an optimized cache chain with file -> memory -> logging layers
    
    Args:
        session_instance: Ftrack session for encode/decode
        cache_path: Path to file cache
        max_memory_size: Maximum items in memory cache (default 50k for full dataset)
        logger_instance: Logger for cache events
        
    Returns:
        Optimized cache instance
    """
    # File cache layer
    file_cache = ftrack_api.cache.FileCache(cache_path)
    
    # Serialization layer  
    serialised_cache = ftrack_api.cache.SerialisedCache(
        file_cache,
        encode=session_instance.encode,
        decode=session_instance.decode
    )
    
    # Memory cache layer for speed
    memory_cache = MemoryCacheWrapper(serialised_cache, max_size=max_memory_size)
    
    # Logging layer for debugging
    logging_cache = LoggingCacheWrapper(memory_cache, logger_instance)
    
    return logging_cache


class SimpleCache:
    """Simple cache implementation that doesn't require ftrack_api"""
    
    def __init__(self, max_size=1000):
        self._cache = {}
        self._access_order = []
        self._max_size = max_size
    
    def _evict_if_needed(self):
        """Remove oldest items if cache is full"""
        while len(self._cache) >= self._max_size and self._access_order:
            oldest_key = self._access_order.pop(0)
            self._cache.pop(oldest_key, None)
    
    def _update_access(self, key):
        """Update access order for LRU"""
        if key in self._access_order:
            self._access_order.remove(key)
        self._access_order.append(key)
    
    def get(self, key):
        if key in self._cache:
            self._update_access(key)
            return self._cache[key]
        return None  # Simple None instead of ftrack_api.symbol.NOT_SET
    
    def set(self, key, value):
        self._evict_if_needed()
        self._cache[key] = value
        self._update_access(key)
    
    def remove(self, key):
        self._cache.pop(key, None)
        if key in self._access_order:
            self._access_order.remove(key)
    
    def clear(self):
        self._cache.clear()
        self._access_order.clear()
    
    @property
    def size(self):
        return len(self._cache)


def create_simple_cache():
    """
    Create a simple cache without session dependencies
    Returns None if creation fails, for graceful degradation
    """
    try:
        return SimpleCache(max_size=1000)
    except Exception as e:
        logger.warning(f"Cannot create simple cache: {e}")
        return None


def get_cache_stats(cache):
    """Get cache statistics for monitoring"""
    stats = {
        'type': cache.__class__.__name__,
        'memory_size': 0,
        'max_memory_size': 0,
    }
    
    # Traverse cache chain to find memory cache
    current = cache
    while current:
        if isinstance(current, MemoryCacheWrapper):
            stats['memory_size'] = current.memory_size
            stats['max_memory_size'] = current.max_size
            break
        elif hasattr(current, 'wrapped_cache'):
            current = current.wrapped_cache
        else:
            break
    
    return stats 