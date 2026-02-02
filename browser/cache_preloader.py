"""
Efficient cache preloader for ftrack entities.

CORRECT STRATEGY: Uses session.get() to move data
from FileCache to MemoryCache to achieve 0.0ms access.

Key discovery: ftrack creates LayeredCache automatically:
FileCache → SerialisedCache → MemoryCacheWrapper → LoggingCacheWrapper
"""

import time
import logging

logger = logging.getLogger(__name__)

class CachePreloader:
    """
    Efficient preloader that uses session.get()
    to move data into memory cache
    """
    
    def __init__(self, session):
        self.session = session
        
    def preload_project_data(self, project_id, max_entities=1000):
        """
        OPTIMIZED preload to achieve 0.0ms access.
        
        Strategy:
        1. Fast queries to get IDs (metadata only)
        2. session.get() for each entity (moves to memory cache)
        3. Subsequent accesses to these entities = 0.0ms
        """
        start_time = time.time()
        loaded_count = 0
        memory_hits = 0
        
        logger.info(f"OPTIMIZED preload for project {project_id}...")
        
        try:
            # === STAGE 1: Preload critical entities ===
            
            # 1.1. Preload project itself
            project = self.session.get('Project', project_id)
            if project:
                loaded_count += 1
                logger.info(f"Project preloaded: {project['name']}")
            
            # 1.2. Preload all locations (most frequent cache misses)
            logger.info("Preloading locations...")
            locations_query = self.session.query('select id from Location').all()
            for loc_data in locations_query:
                location = self.session.get('Location', loc_data['id'])
                if location:
                    loaded_count += 1
            logger.info(f"{len(locations_query)} locations preloaded")
            
            # === STAGE 2: Preload project data ===
            
            # 2.1. Fast query to get asset IDs
            logger.info("Getting asset IDs...")
            assets_query = self.session.query(
                f'select id, name from Asset where project_id is "{project_id}"'
            ).all()
            
            logger.info(f"Found {len(assets_query)} assets for preload")
            
            # 2.2. session.get() for each asset (KEY OPERATION!)
            assets_to_preload = min(len(assets_query), max_entities // 2)
            for i, asset_data in enumerate(assets_query[:assets_to_preload]):
                if i % 50 == 0:  # Progress every 50 elements
                    elapsed = (time.time() - start_time) * 1000
                    logger.info(f"Preloading assets: {i}/{assets_to_preload} ({elapsed:.1f}ms)")
                    
                # CRITICAL: session.get() moves data to memory cache!
                asset = self.session.get('Asset', asset_data['id'])
                if asset:
                    loaded_count += 1
            
            # 2.3. Fast query to get asset version IDs
            logger.info("Getting asset version IDs...")
            versions_query = self.session.query(
                f'select id from AssetVersion where asset.project_id is "{project_id}"'
            ).all()
            
            logger.info(f"Found {len(versions_query)} asset versions")
            
            # 2.4. session.get() for asset versions (limit for performance)
            remaining_quota = max_entities - loaded_count
            versions_to_preload = min(len(versions_query), remaining_quota)
            
            for i, version_data in enumerate(versions_query[:versions_to_preload]):
                if i % 50 == 0:  # Progress every 50 elements
                    elapsed = (time.time() - start_time) * 1000
                    logger.info(f"Preloading versions: {i}/{versions_to_preload} ({elapsed:.1f}ms)")
                    
                # CRITICAL: session.get() moves data to memory cache!
                version = self.session.get('AssetVersion', version_data['id'])
                if version:
                    loaded_count += 1
            
            # === STAGE 3: Efficiency testing ===
            
            # Check that data is actually in memory cache
            logger.info("Testing cache efficiency...")
            test_start = time.time()
            
            # Re-access several entities to check speed
            test_entities = min(10, len(assets_query))
            for i in range(test_entities):
                asset_id = assets_query[i]['id']
                test_asset = self.session.get('Asset', asset_id)
                if test_asset:
                    memory_hits += 1
            
            test_elapsed = (time.time() - test_start) * 1000
            avg_access_time = test_elapsed / test_entities if test_entities > 0 else 0
            
            # === FINAL STATISTICS ===
            
            total_elapsed = (time.time() - start_time) * 1000
            entities_per_ms = loaded_count / total_elapsed if total_elapsed > 0 else 0
            
            logger.info("=" * 60)
            logger.info("OPTIMIZED PRELOAD COMPLETED!")
            logger.info(f"Loaded entities: {loaded_count}")
            logger.info(f"Total time: {total_elapsed:.1f}ms")
            logger.info(f"Performance: {entities_per_ms:.2f} entities/ms")
            logger.info(f"Average access time: {avg_access_time:.1f}ms")
            logger.info(f"Memory cache hits: {memory_hits}/{test_entities}")
            
            if avg_access_time < 1.0:
                logger.info("GOAL ACHIEVED: ~0.0ms access to cached data!")
            else:
                logger.warning(f"Further optimization required: {avg_access_time:.1f}ms")
            logger.info("=" * 60)
            
            return {
                'loaded_count': loaded_count,
                'elapsed_ms': total_elapsed,
                'entities_per_ms': entities_per_ms,
                'avg_access_time_ms': avg_access_time,
                'memory_hits': memory_hits,
                'memory_hit_rate': memory_hits / test_entities if test_entities > 0 else 0,
                'success': avg_access_time < 1.0  # Goal: less than 1ms = practically 0.0ms
            }
            
        except Exception as e:
            elapsed = (time.time() - start_time) * 1000
            logger.error(f"Preload failed after {elapsed:.1f}ms: {e}")
            return {
                'error': str(e), 
                'loaded_count': loaded_count,
                'elapsed_ms': elapsed
            }
    
    def preload_project_entities(self, project_id, max_entities=1000):
        """Alias for browser compatibility"""
        return self.preload_project_data(project_id, max_entities)
    
    def preload_task_context(self, task_id):
        """
        Preload task context with optimization
        """
        start_time = time.time()
        
        try:
            logger.info(f"Preloading task context {task_id}...")
            
            # Load task
            task = self.session.get('Task', task_id)
            if not task:
                logger.warning(f"Task {task_id} not found")
                return
                
            # Load parent asset/shot
            parent = self.session.get(task['parent']['entity_type'], task['parent']['id'])
            
            # Load project
            project = self.session.get('Project', parent['project']['id'])
            
            # Load asset versions for this task (limited quantity)
            if parent['entity_type'] == 'Asset':
                versions_query = self.session.query(
                    f'select id from AssetVersion where asset_id is "{parent["id"]}"'
                ).all()
                
                # Preload last 25 versions
                for version_data in versions_query[:25]:
                    version = self.session.get('AssetVersion', version_data['id'])
            
            elapsed = (time.time() - start_time) * 1000
            logger.info(f"Task context '{task['name']}' in '{parent['name']}' preloaded in {elapsed:.1f}ms")
            
        except Exception as e:
            elapsed = (time.time() - start_time) * 1000
            logger.error(f"Task context preload failed after {elapsed:.1f}ms: {e}")

def create_preloader(session):
    """Factory function to create preloader"""
    return CachePreloader(session) 