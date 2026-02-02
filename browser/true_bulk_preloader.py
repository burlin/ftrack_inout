#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
TRUE bulk cache preloader

Reads entire DBM file into memory in one operation,
not one key at a time like current bulk_cache_preloader does
"""

import time
import os
import logging
import dbm

logger = logging.getLogger(__name__)

class TrueBulkCachePreloader:
    """
    TRUE bulk cache preloader
    
    Reads entire DBM file into memory in one operation
    instead of looping through each key
    """
    
    def __init__(self, session=None):
        self.session = session
        self.cache = session.cache if session else None
    
    def true_bulk_preload_entire_cache(self):
        """
        TRUE bulk preload - reads entire DBM in one operation
        """
        
        if not self.cache:
            logger.warning("No cache available for true bulk preload")
            return 0
            
        print("[LAUNCH] STARTING TRUE BULK CACHE PRELOAD...")
        start_time = time.time()
        
        # Find FileCache in chain
        file_cache = self._find_file_cache()
        if not file_cache:
            print("[FAIL] FileCache not found in cache chain")
            return 0
            
        # Find MemoryCacheWrapper in chain  
        memory_cache = self._find_memory_cache()
        if not memory_cache:
            print("[FAIL] MemoryCacheWrapper not found in cache chain")
            return 0
            
        print("[OK] FileCache found: {}".format(type(file_cache)))
        print("[OK] MemoryCacheWrapper found: {}".format(type(memory_cache)))
        
        # Get path to DBM file
        dbm_path = self._get_dbm_path(file_cache)
        if not dbm_path:
            print("[FAIL] Could not determine DBM file path")
            return 0
            
        print("[FOLDER] DBM file path: {}".format(dbm_path))
        
        # TRUE bulk load - read entire DBM file in one operation
        loaded_count = self._true_bulk_load_dbm_to_memory(dbm_path, memory_cache)
        
        total_time = (time.time() - start_time) * 1000
        
        print("[OK] TRUE BULK PRELOAD COMPLETED!")
        print("[STATS] Loaded {} keys in {:.1f}ms".format(loaded_count, total_time))
        
        if loaded_count > 0:
            print("[FAST] Average: {:.2f}ms per key".format(total_time/loaded_count))
        
        return loaded_count
    
    def _true_bulk_load_dbm_to_memory(self, dbm_path, memory_cache):
        """TRUE bulk load - reads entire DBM in one operation"""
        
        print("🔥 TRUE BULK LOADING: Reading entire DBM file to memory...")
        
        loaded_count = 0
        
        try:
            # Open DBM file for reading
            with dbm.open(dbm_path, 'r') as db:
                print("📖 DBM file opened successfully")
                
                # Get direct access to memory cache
                if not hasattr(memory_cache, '_cache'):
                    print("[FAIL] No direct access to _cache")
                    return 0
                    
                direct_memory = memory_cache._cache
                access_order = getattr(memory_cache, '_access_order', None)
                
                print("💾 Direct memory access established")
                print("[REFRESH] Loading ALL keys in ONE operation...")
                
                # BULK load all keys in one operation
                bulk_start = time.time()
                
                # Read ALL keys and values in one loop
                all_items = []
                key_count = 0
                for key in db.keys():
                    try:
                        value = db[key]
                        all_items.append((key, value))
                        
                        # Show first few keys for debugging
                        key_count += 1
                        if key_count <= 5:
                            key_str = key.decode('utf-8') if isinstance(key, bytes) else str(key)
                            print("[SEARCH] Sample key {}: '{}'".format(key_count, key_str[:100]))
                            
                    except Exception as e:
                        print("[WARN] Failed to read key {}: {}".format(key, e))
                        continue
                
                bulk_read_time = (time.time() - bulk_start) * 1000
                print("📚 Read {} items from DBM in {:.1f}ms".format(len(all_items), bulk_read_time))
                
                # Now BULK write to memory cache
                memory_start = time.time()
                
                for key, value in all_items:
                    try:
                        # Deserialize key (DBM stores in bytes)
                        if isinstance(key, bytes):
                            key_str = key.decode('utf-8')
                        else:
                            key_str = str(key)
                            
                        # Parse key back to tuple format
                        cache_key = self._parse_cache_key(key_str)
                        if cache_key:
                            # DIRECT write to memory cache (bypassing all wrappers!)
                            direct_memory[cache_key] = value
                            
                            # Update LRU if present
                            if access_order is not None:
                                if cache_key in access_order:
                                    access_order.remove(cache_key)
                                access_order.append(cache_key)
                            
                            loaded_count += 1
                            
                    except Exception as e:
                        print("[WARN] Failed to process item {}: {}".format(key, e))
                        continue
                
                memory_write_time = (time.time() - memory_start) * 1000
                print("💾 Wrote {} items to memory in {:.1f}ms".format(loaded_count, memory_write_time))
                
                # Check size limit
                max_size = getattr(memory_cache, '_max_size', 200000)
                if access_order and len(access_order) > max_size:
                    print("🧹 Trimming cache to {} items...".format(max_size))
                    while len(access_order) > max_size:
                        oldest_key = access_order.pop(0)
                        direct_memory.pop(oldest_key, None)
                        loaded_count -= 1
                
                print("🎉 TRUE BULK LOADING COMPLETED!")
                
        except Exception as e:
            print("[FAIL] Error in true bulk loading: {}".format(e))
            import traceback
            traceback.print_exc()
            
        return loaded_count
    
    def _parse_cache_key(self, key_str):
        """Parse string key back to tuple format"""
        
        try:
            # Use eval for correct tuple parsing
            # Format: ('EntityType', ['entity-id'])
            parsed_key = eval(key_str)
            
            # Check that it's a tuple with 2 elements
            if isinstance(parsed_key, tuple) and len(parsed_key) == 2:
                entity_type, entity_ids = parsed_key
                
                # Check data types
                if isinstance(entity_type, str) and isinstance(entity_ids, list) and entity_ids:
                    # Convert list to tuple for hashability
                    hashable_key = (entity_type, tuple(entity_ids))
                    return hashable_key
                    
        except Exception as e:
            # Show a few examples for debugging
            if not hasattr(self, '_debug_count'):
                self._debug_count = 0
            self._debug_count += 1
            
            if self._debug_count <= 3:  # Show only first 3 errors
                print("[SEARCH] DEBUG key {}: '{}'".format(self._debug_count, key_str[:100]))
                print("   Error: {}".format(e))
            
        return None
    
    def _get_dbm_path(self, file_cache):
        """Get path to DBM file"""
        
        try:
            # Check _path attribute
            if hasattr(file_cache, '_path'):
                return file_cache._path
                
            # Check other possible attributes
            for attr in ['path', 'file_path', '_file_path']:
                if hasattr(file_cache, attr):
                    path = getattr(file_cache, attr)
                    if path and os.path.exists(path):
                        return path
                        
        except Exception as e:
            print("Error getting DBM path: {}".format(e))
            
        return None
    
    def _find_file_cache(self):
        """Find FileCache in cache chain"""
        
        try:
            # Check LayeredCache
            if hasattr(self.cache, 'caches'):
                for cache_layer in self.cache.caches:
                    file_cache = self._find_file_cache_in_layer(cache_layer)
                    if file_cache:
                        return file_cache
            
            # Direct check
            return self._find_file_cache_in_layer(self.cache)
            
        except Exception as e:
            print("Error finding file cache: {}".format(e))
            return None
    
    def _find_file_cache_in_layer(self, layer):
        """Recursively search for FileCache in layer"""
        
        layer_type = type(layer).__name__
        
        # Check by type name
        if 'FileCache' in layer_type:
            return layer
            
        # Check wrappers
        for attr_name in ['wrapped_cache', '_cache', 'cache', 'proxied']:
            if hasattr(layer, attr_name):
                inner = getattr(layer, attr_name)
                if inner:
                    result = self._find_file_cache_in_layer(inner)
                    if result:
                        return result
        
        return None
    
    def _find_memory_cache(self):
        """Find MemoryCacheWrapper in cache chain"""
        
        try:
            # Check LayeredCache
            if hasattr(self.cache, 'caches'):
                for cache_layer in self.cache.caches:
                    memory_cache = self._find_memory_cache_in_layer(cache_layer)
                    if memory_cache:
                        return memory_cache
            
            # Direct check
            return self._find_memory_cache_in_layer(self.cache)
            
        except Exception as e:
            print("Error finding memory cache: {}".format(e))
            return None
    
    def _find_memory_cache_in_layer(self, layer):
        """Recursively search for MemoryCacheWrapper in layer"""
        
        layer_type = type(layer).__name__
        
        # Check by type name
        if 'MemoryCache' in layer_type or 'MemoryCacheWrapper' in layer_type:
            return layer
            
        # Check wrappers
        for attr_name in ['wrapped_cache', '_cache', 'cache']:
            if hasattr(layer, attr_name):
                inner = getattr(layer, attr_name)
                if inner:
                    result = self._find_memory_cache_in_layer(inner)
                    if result:
                        return result
        
        return None

def create_true_bulk_preloader(session):
    """Create instance of true bulk preloader"""
    return TrueBulkCachePreloader(session) 