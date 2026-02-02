"""
Modular Ftrack Task Browser

This version uses the new modular architecture:
- browser_core.py - Business logic without UI dependencies
- browser_ui.py - UI components
- This file - Integration and coordination
"""

import sys
import os
import logging

# Dependencies path setup
_deps_path = os.path.join(os.path.dirname(__file__), '..', 'dependencies')
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

# Import our modular components
try:
    from .browser_core import FtrackBrowserCore
    CORE_AVAILABLE = True
except ImportError as e:
    logger.error(f"Failed to import browser core: {e}")
    CORE_AVAILABLE = False

try:
    from .browser_ui import FtrackBrowserUI
    UI_AVAILABLE = True
except ImportError as e:
    logger.error(f"Failed to import browser UI: {e}")
    UI_AVAILABLE = False

class ModularFtrackTaskBrowser(QtWidgets.QWidget):
    """
    Modular Ftrack Task Browser
    
    This class coordinates between the business logic (core) and UI components.
    It provides the same interface as the original browser but with clean separation.
    """
    
    def __init__(self, parent=None):
        super(ModularFtrackTaskBrowser, self).__init__(parent)
        
        logger.info("[LAUNCH] Initializing Modular Ftrack Task Browser...")
        
        # Initialize core business logic
        if not CORE_AVAILABLE:
            logger.error("Browser core not available")
            self._show_error("Browser core not available")
            return
            
        self.core = FtrackBrowserCore()
        
        if not self.core.is_connected():
            logger.error("Failed to connect to ftrack")
            self._show_error("Failed to connect to ftrack")
            return
        
        # Initialize UI
        if not UI_AVAILABLE or not PYSIDE6_AVAILABLE:
            logger.error("Browser UI not available")
            self._show_error("Browser UI not available (PySide6 required)")
            return
            
        self.ui = FtrackBrowserUI(self.core, self)
        
        # Setup layout
        layout = QtWidgets.QVBoxLayout(self)
        layout.addWidget(self.ui)
        layout.setContentsMargins(0, 0, 0, 0)
        
        # Connect signals
        self._connect_core_to_ui()
        
        # Initialize data
        self._load_initial_data()
        
        logger.info("[OK] Modular browser initialized successfully")
    
    def _show_error(self, message):
        """Show error message in UI"""
        layout = QtWidgets.QVBoxLayout(self)
        error_label = QtWidgets.QLabel(f"Error: {message}")
        error_label.setStyleSheet("color: red; font-weight: bold; padding: 20px;")
        error_label.setAlignment(QtCore.Qt.AlignCenter)
        layout.addWidget(error_label)
    
    def _connect_core_to_ui(self):
        """Connect core business logic to UI events"""
        
        # UI -> Core connections
        self.ui.projectChanged.connect(self._on_project_changed)
        self.ui.entitySelected.connect(self._on_entity_selected)
        self.ui.versionSelected.connect(self._on_version_selected)
        self.ui.refreshRequested.connect(self._on_refresh_requested)
        
        logger.info("[OK] Core-UI connections established")
    
    def _load_initial_data(self):
        """Load initial data on startup"""
        try:
            # Load projects
            projects = self.core.get_projects()
            self.ui.update_projects(projects)
            
            logger.info(f"[OK] Initial data loaded: {len(projects)} projects")
            
        except Exception as e:
            logger.error(f"Failed to load initial data: {e}")
            self.ui.show_status(f"Failed to load initial data: {e}", 5000)
    
    # === EVENT HANDLERS ===
    
    def _on_project_changed(self, project_id):
        """Handle project selection change"""
        logger.info(f"Project changed: {project_id}")
        
        try:
            self.ui.show_status("Loading project...")
            
            # Set current project in core (includes preloading)
            success = self.core.set_current_project(project_id)
            
            if success:
                # Load project structure
                entities = self.core.get_project_children(project_id)
                self.ui.update_entity_tree(entities)
                
                # Clear other panels
                self.ui.update_asset_versions([])
                self.ui.update_components([])
                self.ui.update_metadata({})
                
                self.ui.show_status(f"Project loaded: {len(entities)} entities")
                
            else:
                self.ui.show_status("Failed to load project", 3000)
                
        except Exception as e:
            logger.error(f"Failed to handle project change: {e}")
            self.ui.show_status(f"Error: {e}", 5000)
    
    def _on_entity_selected(self, entity_id, entity_type):
        """Handle entity selection"""
        logger.info(f"Entity selected: {entity_type}:{entity_id}")
        
        try:
            # Update metadata
            metadata = self.core.get_entity_metadata(entity_id, entity_type)
            self.ui.update_metadata(metadata)
            
            # If it's an asset, load versions
            if entity_type == 'Asset':
                self.ui.show_status("Loading asset versions...")
                versions = self.core.get_asset_versions(entity_id)
                self.ui.update_asset_versions(versions)
                self.ui.show_status(f"Loaded {len(versions)} versions")
            else:
                # Clear versions for non-assets
                self.ui.update_asset_versions([])
            
            # Clear components
            self.ui.update_components([])
            
        except Exception as e:
            logger.error(f"Failed to handle entity selection: {e}")
            self.ui.show_status(f"Error: {e}", 5000)
    
    def _on_version_selected(self, version_id):
        """Handle version selection"""
        logger.info(f"Version selected: {version_id}")
        
        try:
            self.ui.show_status("Loading components...")
            components = self.core.get_version_components(version_id)
            self.ui.update_components(components)
            self.ui.show_status(f"Loaded {len(components)} components")
            
        except Exception as e:
            logger.error(f"Failed to handle version selection: {e}")
            self.ui.show_status(f"Error: {e}", 5000)
    
    def _on_refresh_requested(self):
        """Handle refresh request"""
        logger.info("Refresh requested")
        
        try:
            self.ui.show_status("Refreshing...")
            
            # Clear core caches
            self.core.clear_cache()
            
            # Reload projects
            projects = self.core.get_projects(force_refresh=True)
            self.ui.update_projects(projects)
            
            # Clear other data
            self.ui.update_entity_tree([])
            self.ui.update_asset_versions([])
            self.ui.update_components([])
            self.ui.update_metadata({})
            
            self.ui.show_status("Refreshed")
            
        except Exception as e:
            logger.error(f"Failed to handle refresh: {e}")
            self.ui.show_status(f"Error: {e}", 5000)
    
    # === PUBLIC API (for backward compatibility) ===
    
    @property
    def api(self):
        """Access to core API for backward compatibility"""
        return self.core
    
    def get_projects(self):
        """Get projects (backward compatibility)"""
        return self.core.get_projects()
    
    def get_cache_stats(self):
        """Get cache statistics (backward compatibility)"""
        return self.core.get_cache_stats()
    
    def clear_cache(self):
        """Clear cache (backward compatibility)"""
        return self.core.clear_cache()
    
    def update_status(self, text):
        """Update status (backward compatibility)"""
        self.ui.show_status(text)
    
    # === HOUDINI INTEGRATION ===
    
    def load_projects(self):
        """Load projects (backward compatibility method)"""
        try:
            projects = self.core.get_projects(force_refresh=True)
            self.ui.update_projects(projects)
            return True
        except Exception as e:
            logger.error(f"Failed to load projects: {e}")
            return False
    
    def on_project_changed(self, idx):
        """Handle project combo change (backward compatibility)"""
        if hasattr(self.ui, 'project_combo'):
            project_id = self.ui.project_combo.itemData(idx)
            if project_id:
                self._on_project_changed(project_id)
    
    def on_refresh_clicked(self):
        """Handle refresh button (backward compatibility)"""
        self._on_refresh_requested()

# === FACTORY FUNCTIONS ===

def create_modular_browser_widget(parent=None):
    """Create modular browser widget"""
    if not PYSIDE6_AVAILABLE:
        logger.error("PySide6 not available")
        return None
        
    if not CORE_AVAILABLE:
        logger.error("Browser core not available")
        return None
        
    if not UI_AVAILABLE:
        logger.error("Browser UI not available")
        return None
        
    return ModularFtrackTaskBrowser(parent)

def create_browser_widget(parent=None):
    """Main factory function (backward compatibility)"""
    return create_modular_browser_widget(parent)

# Backward compatibility class alias
FtrackTaskBrowser = ModularFtrackTaskBrowser

# === STANDALONE CORE ACCESS ===

def create_core_only():
    """Create only the core (no UI) for standalone use"""
    if not CORE_AVAILABLE:
        logger.error("Browser core not available")
        return None
        
    return FtrackBrowserCore()

# === USAGE EXAMPLES ===

if __name__ == "__main__":
    # Example 1: Core only (no UI dependencies)
    print("=== Core Only Example ===")
    core = create_core_only()
    if core and core.is_connected():
        projects = core.get_projects()
        print(f"Found {len(projects)} projects")
        
        if projects:
            project = projects[0]
            core.set_current_project(project['id'])
            entities = core.get_project_children()
            print(f"Project '{project['name']}' has {len(entities)} top-level entities")
    
    # Example 2: Full UI (requires PySide6)
    if PYSIDE6_AVAILABLE:
        print("\n=== Full UI Example ===")
        app = QtWidgets.QApplication.instance()
        if app is None:
            app = QtWidgets.QApplication([])
            
        browser = create_browser_widget()
        if browser:
            browser.show()
            print("Browser widget created and shown")
        else:
            print("Failed to create browser widget")
    else:
        print("\n=== UI Example Skipped (PySide2 not available) ===") 