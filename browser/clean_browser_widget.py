"""
Clean and efficient Ftrack Task Browser

Uses proper caching strategy with session.get() for instant performance.
"""

import sys
import os
import time
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

# Backward-compat flag for reused conditionals
PYSIDE2_AVAILABLE = False

from .dcc.houdini import hou, HOUDINI_AVAILABLE

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(message)s')
logger = logging.getLogger(__name__)

# Import our clean API client
from simple_api_client import create_api_client

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

class CleanFtrackTaskBrowser(QtWidgets.QWidget):
    """Clean and fast Ftrack Task Browser"""
    
    def __init__(self, parent=None):
        super(CleanFtrackTaskBrowser, self).__init__(parent)
        
        # Initialize API client
        self.api = create_api_client()
        if not self.api.session:
            logger.error("Failed to initialize ftrack API")
            return
            
        logger.info("Clean Ftrack Task Browser initialized")
        
        # UI elements
        self.project_combo = None
        self.task_tree = None
        self.asset_version_tree = None
        self.component_list = None
        self.status_label = None
        self.metadata_text = None
        
        # Current selections
        self.current_project_id = None
        self.current_entity_id = None
        self.current_version_id = None
        
        self._create_ui()
        self._load_projects()
    
    def _create_ui(self):
        """Create clean UI layout"""
        layout = QtWidgets.QVBoxLayout(self)
        
        # Toolbar
        toolbar_layout = QtWidgets.QHBoxLayout()
        
        # Project selector
        toolbar_layout.addWidget(QtWidgets.QLabel("Project:"))
        self.project_combo = QtWidgets.QComboBox()
        self.project_combo.currentIndexChanged.connect(self._on_project_changed)
        toolbar_layout.addWidget(self.project_combo)
        
        # Refresh button
        refresh_btn = QtWidgets.QPushButton("Refresh")
        refresh_btn.clicked.connect(self._on_refresh_clicked)
        toolbar_layout.addWidget(refresh_btn)
        
        toolbar_layout.addStretch()
        
        # Status label
        self.status_label = QtWidgets.QLabel("Ready")
        toolbar_layout.addWidget(self.status_label)
        
        layout.addLayout(toolbar_layout)
        
        # Main splitter
        main_splitter = QtWidgets.QSplitter(QtCore.Qt.Horizontal)
        
        # Left panel - Task tree
        left_panel = QtWidgets.QWidget()
        left_layout = QtWidgets.QVBoxLayout(left_panel)
        
        left_layout.addWidget(QtWidgets.QLabel("Tasks & Assets:"))
        self.task_tree = QtWidgets.QTreeWidget()
        self.task_tree.setHeaderLabels(["Name", "Type"])
        self.task_tree.itemSelectionChanged.connect(self._on_task_selected)
        left_layout.addWidget(self.task_tree)
        
        main_splitter.addWidget(left_panel)
        
        # Right panel
        right_panel = QtWidgets.QWidget()
        right_layout = QtWidgets.QVBoxLayout(right_panel)
        
        # Asset versions
        right_layout.addWidget(QtWidgets.QLabel("Asset Versions:"))
        self.asset_version_tree = QtWidgets.QTreeWidget()
        self.asset_version_tree.setHeaderLabels(["Version", "Comment", "User"])
        self.asset_version_tree.itemSelectionChanged.connect(self._on_version_selected)
        right_layout.addWidget(self.asset_version_tree)
        
        # Components
        right_layout.addWidget(QtWidgets.QLabel("Components:"))
        self.component_list = QtWidgets.QListWidget()
        right_layout.addWidget(self.component_list)
        
        # Metadata
        right_layout.addWidget(QtWidgets.QLabel("Details:"))
        self.metadata_text = QtWidgets.QTextEdit()
        self.metadata_text.setMaximumHeight(100)
        right_layout.addWidget(self.metadata_text)
        
        main_splitter.addWidget(right_panel)
        main_splitter.setSizes([300, 400])
        
        layout.addWidget(main_splitter)
    
    def _load_projects(self):
        """Load projects into combo box"""
        self.status_label.setText("Loading projects...")
        
        try:
            projects = self.api.get_projects()
            
            self.project_combo.clear()
            for project in projects:
                self.project_combo.addItem(project['name'], project['id'])
            
            self.status_label.setText(f"Loaded {len(projects)} projects")
            logger.info(f"Loaded {len(projects)} projects")
            
        except Exception as e:
            self.status_label.setText(f"Error loading projects: {e}")
            logger.error(f"Failed to load projects: {e}")
    
    def _on_project_changed(self, index):
        """Handle project selection change"""
        if index < 0:
            return
            
        project_id = self.project_combo.itemData(index)
        if project_id == self.current_project_id:
            return
            
        self.current_project_id = project_id
        project_name = self.project_combo.itemText(index)
        
        self.status_label.setText(f"Loading project: {project_name}...")
        logger.info(f"Loading project: {project_name}")
        
        # Clear current data
        self.task_tree.clear()
        self.asset_version_tree.clear()
        self.component_list.clear()
        self.metadata_text.clear()
        
        # Preload project data in background
        QtCore.QTimer.singleShot(100, lambda: self._preload_and_load_project(project_id))
    
    def _preload_and_load_project(self, project_id):
        """Preload project data then load tree"""
        try:
            # Preload project data for fast access
            start_time = time.time()
            result = self.api.preload_project_data(project_id)
            preload_time = (time.time() - start_time) * 1000
            
            if 'error' not in result:
                logger.info(f"Preloaded {result['loaded_count']} entities in {preload_time:.1f}ms")
                self.status_label.setText(f"Preloaded {result['loaded_count']} entities - loading tree...")
            
            # Now load the tree (will be fast due to preloading)
            self._load_project_tree(project_id)
            
        except Exception as e:
            self.status_label.setText(f"Error loading project: {e}")
            logger.error(f"Failed to load project: {e}")
    
    def _load_project_tree(self, project_id):
        """Load project tree structure"""
        try:
            # Get project entity (from cache - instant)
            project = self.api.get_entity('Project', project_id)
            if not project:
                return
            
            # Get top-level children (sequences, folders, assets)
            children = self.api.get_children(project_id, 'TypedContext')
            
            for child in children:
                self._add_entity_item(self.task_tree, child)
            
            self.status_label.setText(f"Loaded {len(children)} items")
            
        except Exception as e:
            self.status_label.setText(f"Error loading tree: {e}")
            logger.error(f"Failed to load tree: {e}")
    
    def _add_entity_item(self, parent, entity):
        """Add entity item to tree"""
        if isinstance(parent, QtWidgets.QTreeWidget):
            item = QtWidgets.QTreeWidgetItem(parent)
        else:
            item = QtWidgets.QTreeWidgetItem(parent)
        
        item.setText(0, entity['name'])
        item.setText(1, entity['entity_type'])
        item.setData(0, ITEM_ID_ROLE, entity['id'])
        item.setData(0, ITEM_TYPE_ROLE, entity['entity_type'])
        
        # Add dummy child for expandable items
        if entity['entity_type'] in ['Sequence', 'Folder', 'Asset']:
            dummy = QtWidgets.QTreeWidgetItem(item)
            dummy.setText(0, DUMMY_NODE_TEXT)
        
        return item
    
    def _on_task_selected(self):
        """Handle task/entity selection"""
        items = self.task_tree.selectedItems()
        if not items:
            return
            
        item = items[0]
        entity_id = item.data(0, ITEM_ID_ROLE)
        entity_type = item.data(0, ITEM_TYPE_ROLE)
        
        if entity_id == self.current_entity_id:
            return
            
        self.current_entity_id = entity_id
        
        # Clear previous data
        self.asset_version_tree.clear()
        self.component_list.clear()
        
        # Load asset versions if this is an asset
        if entity_type == 'Asset':
            self._load_asset_versions(entity_id)
        
        # Update metadata
        self._update_metadata(entity_id, entity_type)
    
    def _load_asset_versions(self, asset_id):
        """Load asset versions for selected asset"""
        try:
            self.status_label.setText("Loading asset versions...")
            
            versions = self.api.get_asset_versions(asset_id)
            
            for version in versions:
                item = QtWidgets.QTreeWidgetItem(self.asset_version_tree)
                item.setText(0, f"v{version['version']}")
                item.setText(1, version.get('comment', ''))
                item.setText(2, version.get('user', {}).get('username', ''))
                item.setData(0, ASSET_VERSION_ITEM_ID_ROLE, version['id'])
            
            self.status_label.setText(f"Loaded {len(versions)} versions")
            
        except Exception as e:
            self.status_label.setText(f"Error loading versions: {e}")
            logger.error(f"Failed to load versions: {e}")
    
    def _on_version_selected(self):
        """Handle version selection"""
        items = self.asset_version_tree.selectedItems()
        if not items:
            return
            
        item = items[0]
        version_id = item.data(0, ASSET_VERSION_ITEM_ID_ROLE)
        
        if version_id == self.current_version_id:
            return
            
        self.current_version_id = version_id
        self._load_version_components(version_id)
    
    def _load_version_components(self, version_id):
        """Load components for selected version"""
        try:
            self.status_label.setText("Loading components...")
            
            components = self.api.get_version_components(version_id)
            
            self.component_list.clear()
            for component in components:
                item = QtWidgets.QListWidgetItem(self.component_list)
                item.setText(f"{component['name']} ({component['file_type']})")
                item.setData(QtCore.Qt.UserRole, component)
            
            self.status_label.setText(f"Loaded {len(components)} components")
            
        except Exception as e:
            self.status_label.setText(f"Error loading components: {e}")
            logger.error(f"Failed to load components: {e}")
    
    def _update_metadata(self, entity_id, entity_type):
        """Update metadata display"""
        try:
            entity = self.api.get_entity(entity_type, entity_id)
            if not entity:
                return
            
            metadata = []
            metadata.append(f"Name: {entity['name']}")
            metadata.append(f"Type: {entity['entity_type']}")
            metadata.append(f"ID: {entity['id']}")
            
            if 'description' in entity and entity['description']:
                metadata.append(f"Description: {entity['description']}")
            
            self.metadata_text.setPlainText('\n'.join(metadata))
            
        except Exception as e:
            logger.error(f"Failed to update metadata: {e}")
    
    def _on_refresh_clicked(self):
        """Handle refresh button click"""
        if self.current_project_id:
            self._on_project_changed(self.project_combo.currentIndex())

def create_clean_browser_widget():
    """Factory function to create clean browser widget"""
    if not PYSIDE6_AVAILABLE:
        logger.error("PySide6 not available")
        return None
        
    return CleanFtrackTaskBrowser()

# For backward compatibility
def create_browser_widget():
    """Backward compatibility function"""
    return create_clean_browser_widget()

# Main class alias for backward compatibility  
FtrackTaskBrowser = CleanFtrackTaskBrowser 