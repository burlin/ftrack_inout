"""
Background data loader for non-blocking UI updates

Provides thread-safe data loading with Qt signals for communication
with the main UI thread.
"""

import logging
from typing import List
from PySide6.QtCore import QObject, Signal, QThread

logger = logging.getLogger(__name__)


class DataLoader(QObject):
    """Background data loader for non-blocking UI updates"""
    
    # Signals for communication with main thread
    projects_loaded = Signal(list)
    children_loaded = Signal(str, list)  # parent_id, children
    versions_loaded = Signal(str, list)  # asset_id, versions
    components_loaded = Signal(str, list)  # version_id, components
    error_occurred = Signal(str)
    progress_updated = Signal(str)  # progress message
    
    def __init__(self, api_client):
        super().__init__()
        self.api_client = api_client
        self._stop_requested = False
        self._current_operation = None
    
    def stop(self):
        """Request to stop all background operations"""
        self._stop_requested = True
        logger.info("DataLoader stop requested")
    
    def _check_stop(self):
        """Check if stop was requested and raise exception if so"""
        if self._stop_requested:
            raise InterruptedError("Operation stopped by user request")
    
    def load_projects(self):
        """Load all projects"""
        if self._stop_requested:
            return
            
        self._current_operation = "Loading projects"
        self.progress_updated.emit(self._current_operation)
        
        try:
            logger.info("Starting projects load in background")
            self._check_stop()
            
            projects = self.api_client.get_projects()
            
            self._check_stop()
            logger.info(f"Loaded {len(projects)} projects in background")
            
            if not self._stop_requested:
                self.projects_loaded.emit(projects)
                
        except InterruptedError:
            logger.info("Projects load interrupted")
        except Exception as e:
            logger.error(f"Failed to load projects in background: {e}")
            if not self._stop_requested:
                self.error_occurred.emit(f"Failed to load projects: {str(e)}")
        finally:
            self._current_operation = None
    
    def load_children(self, parent_id: str, parent_type: str):
        """Load children of a parent entity"""
        if self._stop_requested:
            return
            
        self._current_operation = f"Loading children for {parent_type}"
        self.progress_updated.emit(self._current_operation)
        
        try:
            logger.info(f"Starting children load for {parent_type} {parent_id}")
            self._check_stop()
            
            if parent_type == 'Project':
                children = self.api_client.get_project_children(parent_id)
            else:
                children = self.api_client.get_task_children(parent_id)
            
            self._check_stop()
            logger.info(f"Loaded {len(children)} children for {parent_type} {parent_id}")
            
            if not self._stop_requested:
                self.children_loaded.emit(parent_id, children)
                
        except InterruptedError:
            logger.info(f"Children load interrupted for {parent_type} {parent_id}")
        except Exception as e:
            logger.error(f"Failed to load children for {parent_type} {parent_id}: {e}")
            if not self._stop_requested:
                self.error_occurred.emit(f"Failed to load children: {str(e)}")
        finally:
            self._current_operation = None
    
    def load_versions(self, asset_id: str):
        """Load versions for an asset"""
        if self._stop_requested:
            return
            
        self._current_operation = f"Loading versions for asset"
        self.progress_updated.emit(self._current_operation)
        
        try:
            logger.info(f"Starting versions load for asset {asset_id}")
            self._check_stop()
            
            versions = self.api_client.get_asset_versions(asset_id)
            
            self._check_stop()
            logger.info(f"Loaded {len(versions)} versions for asset {asset_id}")
            
            if not self._stop_requested:
                self.versions_loaded.emit(asset_id, versions)
                
        except InterruptedError:
            logger.info(f"Versions load interrupted for asset {asset_id}")
        except Exception as e:
            logger.error(f"Failed to load versions for asset {asset_id}: {e}")
            if not self._stop_requested:
                self.error_occurred.emit(f"Failed to load versions: {str(e)}")
        finally:
            self._current_operation = None
    
    def load_components(self, version_id: str):
        """Load components for a version"""
        if self._stop_requested:
            return
            
        self._current_operation = f"Loading components for version"
        self.progress_updated.emit(self._current_operation)
        
        try:
            logger.info(f"Starting components load for version {version_id}")
            self._check_stop()
            
            components = self.api_client.get_version_components(version_id)
            
            self._check_stop()
            logger.info(f"Loaded {len(components)} components for version {version_id}")
            
            if not self._stop_requested:
                self.components_loaded.emit(version_id, components)
                
        except InterruptedError:
            logger.info(f"Components load interrupted for version {version_id}")
        except Exception as e:
            logger.error(f"Failed to load components for version {version_id}: {e}")
            if not self._stop_requested:
                self.error_occurred.emit(f"Failed to load components: {str(e)}")
        finally:
            self._current_operation = None
    
    def load_asset_versions_for_entity(self, entity_id: str):
        """Load asset versions for an entity (optimized batch loading)"""
        if self._stop_requested:
            return
            
        self._current_operation = f"Loading asset versions for entity"
        self.progress_updated.emit(self._current_operation)
        
        try:
            logger.info(f"Starting asset versions load for entity {entity_id}")
            self._check_stop()
            
            # Get assets linked to entity
            assets = self.api_client.get_assets_linked_to_entity(entity_id)
            self._check_stop()
            
            if not assets:
                logger.info(f"No assets found for entity {entity_id}")
                if not self._stop_requested:
                    self.versions_loaded.emit(entity_id, [])
                return
            
            # OPTIMIZED: Parallel loading of all versions at once (19.6x faster!)
            asset_ids = [asset['id'] for asset in assets]
            logger.info(f"ULTRA OPTIMIZED: Loading versions for {len(assets)} assets in parallel...")
            versions_by_asset = self.api_client.get_all_versions_for_multiple_assets(asset_ids)
            
            self._check_stop()
            
            # Flatten to version list with asset info
            all_versions = []
            for asset in assets:
                asset_id = asset['id']
                versions = versions_by_asset.get(asset_id, [])
                for version in versions:
                    version['asset_name'] = asset.get('name', 'Unknown Asset')
                    version['asset_id'] = asset_id
                    all_versions.append(version)
            
            logger.info(f"Loaded {len(all_versions)} asset versions for entity {entity_id}")
            
            if not self._stop_requested:
                self.versions_loaded.emit(entity_id, all_versions)
                
        except InterruptedError:
            logger.info(f"Asset versions load interrupted for entity {entity_id}")
        except Exception as e:
            logger.error(f"Failed to load asset versions for entity {entity_id}: {e}")
            if not self._stop_requested:
                self.error_occurred.emit(f"Failed to load asset versions: {str(e)}")
        finally:
            self._current_operation = None
    
    @property
    def current_operation(self):
        """Get current operation description"""
        return self._current_operation
    
    @property 
    def is_busy(self):
        """Check if loader is currently processing"""
        return self._current_operation is not None and not self._stop_requested


class BackgroundLoader:
    """Manager for background data loading with thread management"""
    
    def __init__(self, api_client):
        self.api_client = api_client
        self.data_loader = None
        self.loader_thread = None
        
    def setup(self):
        """Setup background loader and thread"""
        if self.loader_thread:
            self.cleanup()
            
        self.loader_thread = QThread()
        self.data_loader = DataLoader(self.api_client)
        self.data_loader.moveToThread(self.loader_thread)
        
        self.loader_thread.start()
        logger.info("Background loader thread started")
        
        return self.data_loader
    
    def cleanup(self):
        """Clean up background loader and thread"""
        if self.data_loader:
            self.data_loader.stop()
            
        if self.loader_thread:
            self.loader_thread.quit()
            if not self.loader_thread.wait(3000):  # Wait up to 3 seconds
                logger.warning("Background loader thread did not finish within timeout")
                self.loader_thread.terminate()
                self.loader_thread.wait(1000)
            logger.info("Background loader thread stopped")
            
        self.data_loader = None
        self.loader_thread = None
    
    @property
    def is_ready(self):
        """Check if background loader is ready"""
        return (self.data_loader is not None and 
                self.loader_thread is not None and 
                self.loader_thread.isRunning())
    
    def get_stats(self):
        """Get loader statistics"""
        if not self.is_ready:
            return {"status": "not_ready"}
            
        return {
            "status": "ready",
            "is_busy": self.data_loader.is_busy,
            "current_operation": self.data_loader.current_operation,
            "thread_running": self.loader_thread.isRunning()
        } 