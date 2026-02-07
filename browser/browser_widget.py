"""
Complete Ftrack Task Browser - Modular Implementation

Full implementation recreated from reference file with modular architecture.
"""

import sys
import os
import tempfile
import traceback
import logging
import json
import yaml  # Add import for YAML

# Dependencies path setup
# Dependencies are located in ftrack_inout/dependencies
_deps_path = os.path.join(os.path.dirname(__file__), '..', '..', 'dependencies')
_deps_path = os.path.abspath(_deps_path)
if os.path.exists(_deps_path) and _deps_path not in sys.path:
    sys.path.insert(0, _deps_path)

try:
    from PySide6 import QtWidgets, QtCore, QtGui
    PYSIDE6_AVAILABLE = True
except ImportError:
    PYSIDE6_AVAILABLE = False

# Backward-compat flag used in some conditionals
PYSIDE2_AVAILABLE = False

from .dcc.houdini import (
    hou,
    HOUDINI_AVAILABLE,
    set_global_task_vars,
    set_task_id_on_selected_nodes,
    set_hda_params_on_selected_nodes as houdini_set_hda_params_on_selected_nodes,
    set_full_params_on_publish_nodes as houdini_set_full_params_on_publish_nodes,
    load_snapshot_hip,
    apply_scene_setup,
)

try:
    from .dcc.maya import (
        MAYA_AVAILABLE,
        set_hda_params_on_selected_nodes as maya_set_hda_params_on_selected_nodes,
        set_full_params_on_publish_nodes as maya_set_full_params_on_publish_nodes,
    )
except ImportError:
    MAYA_AVAILABLE = False
    maya_set_hda_params_on_selected_nodes = None
    maya_set_full_params_on_publish_nodes = None

if MAYA_AVAILABLE and maya_set_hda_params_on_selected_nodes is not None:
    set_hda_params_on_selected_nodes = maya_set_hda_params_on_selected_nodes
    set_full_params_on_publish_nodes = maya_set_full_params_on_publish_nodes
else:
    set_hda_params_on_selected_nodes = houdini_set_hda_params_on_selected_nodes
    set_full_params_on_publish_nodes = houdini_set_full_params_on_publish_nodes

# Configure logging
logging.basicConfig(
    level=logging.WARNING, 
    format='%(asctime)s - %(levelname)s:%(name)s:%(message)s',
    datefmt='%H:%M:%S',
    force=True
)
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# Import modular components
try:
    from .cache_wrapper import MemoryCacheWrapper, LoggingCacheWrapper
    CACHE_COMPONENTS_AVAILABLE = True
except ImportError:
    CACHE_COMPONENTS_AVAILABLE = False

try:
    from ..common.path_from_project import get_component_display_path
    PATH_FROM_PROJECT_AVAILABLE = True
except ImportError:
    get_component_display_path = None
    PATH_FROM_PROJECT_AVAILABLE = False

try:
    import ftrack_api
    import ftrack_api.cache
    import ftrack_api.symbol
    FTRACK_API_AVAILABLE = True
except ImportError:
    FTRACK_API_AVAILABLE = False

# Optional helper for multi-site / user-location bootstrap (shared with
# simple_api_client). If module is not available, simply skip extended
# location registration.
try:
    from .simple_api_client import (  # type: ignore
        _add_locations_if_available as _bootstrap_multi_site_locations,
    )
    MULTI_SITE_BOOTSTRAP_AVAILABLE = True
except Exception:  # pragma: no cover - best-effort
    _bootstrap_multi_site_locations = None  # type: ignore
    MULTI_SITE_BOOTSTRAP_AVAILABLE = False

# Import our new transfer module (optional - for legacy compatibility)
# NOTE: TransferWorker does NOT use TransferComponentsPlusAction directly.
# It publishes mroya.transfer.request event which is handled by mroya_transfer_manager.
# This import is kept for backward compatibility but is not required for transfer to work.
_integrator_path = os.path.join(os.path.dirname(__file__), '..', 'location_integrator', 'hook', 'actions')
_integrator_path = os.path.abspath(_integrator_path)
if os.path.exists(_integrator_path) and _integrator_path not in sys.path:
    sys.path.insert(0, _integrator_path)

try:
    from transfer_action import TransferComponentsPlusAction
    TRANSFER_ACTION_AVAILABLE = True
    logger.info("[OK] Successfully imported 'TransferComponentsPlusAction' from local copy.")
except ImportError as e:
    # NOTE: This is NOT a critical error - TransferWorker works independently
    # by publishing mroya.transfer.request events. TransferComponentsPlusAction
    # is only used for Ftrack action API, not for browser widget transfers.
    TRANSFER_ACTION_AVAILABLE = False
    logger.debug(f"[INFO] TransferComponentsPlusAction not available (location_integrator not found): {e}")
    logger.info("[INFO] Transfer feature will still work via TransferWorker -> mroya.transfer.request event")

# Import our widget/factory for transfer status (shared for browser and finput)
try:
    from .transfer_status_widget import TransferStatusDialog, get_transfer_dialog
    TRANSFER_STATUS_WIDGET_AVAILABLE = True
except ImportError:
    TRANSFER_STATUS_WIDGET_AVAILABLE = False

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

# Migration status tracking
MIGRATION_STATUS = {
    'cache_wrapper': True,      # [OK] Complete - memory and logging cache wrappers
    'data_loader': True,        # [OK] Complete - background data loading
    'browser_widget': True,     # [OK] Complete - main browser widget (recreated from reference)
    'api_client': True,         # [OK] Complete - existing ftrack_hou_utils integration
    'ui_helpers': True,         # [OK] Complete - functionality integrated into browser_widget
}

# REMOVED: Base FtrackApiClient class (~764 lines) - no longer used.
# browser_widget.py now uses OptimizedFtrackApiClient directly from browser_widget_optimized.py.

if PYSIDE6_AVAILABLE:
    class FtrackTaskBrowser(QtWidgets.QWidget):
        """Complete Ftrack Task Browser with exact UI from reference"""
        
        def __init__(self, parent=None):
            super().__init__(parent)
            # Always use OptimizedFtrackApiClient - no fallback to basic version
            from .browser_widget_optimized import OptimizedFtrackApiClient
            self.api = OptimizedFtrackApiClient()
            self.current_project_id = None
            self.current_loaded_entity_id = None
            self.current_task_filter_id = None  # NEW: Store task ID for filtering versions
            self.selected_item = None
            self.pending_item_data = None
            
            # Cache for optimized loading
            self._entity_assets_cache = {}
            
            # Load HDA parameter configuration
            self._load_hda_param_config()
            
            # Timer for delayed selection processing
            self.selection_timer = QtCore.QTimer()
            self.selection_timer.setSingleShot(True)
            self.selection_timer.timeout.connect(self.on_selection_timer_timeout)
            
            # Create UI first (like in original)
            self._create_complete_ui()
            
            # Load projects and locations (like in original)
            self.projects = []
            self.load_projects()
            self._load_locations()
            
            # Connect signals
            self.task_tree.itemSelectionChanged.connect(self.on_item_selected)
            self.task_tree.itemExpanded.connect(self.on_item_expanded)
            self.asset_version_tree.itemSelectionChanged.connect(self.on_asset_version_selection_changed)
            self.asset_version_tree.itemExpanded.connect(self.on_asset_item_expanded)
            self.component_list.itemSelectionChanged.connect(self.on_component_list_selection_changed)

        def _load_locations(self):
            """Load ftrack locations and populate combo boxes."""
            try:
                # 1. Get all locations, as in the original plugin
                # FIX: Remove 'priority' from query to avoid ParseError
                all_locations = self.api.session.query('select id, name, label from Location').all()
                
                # 2. Filter those that have accessor (i.e. these are real storage)
                accessible_locations = [loc for loc in all_locations if loc.accessor]
                logger.info(f"Found {len(accessible_locations)} accessible locations out of {len(all_locations)} total.")

                # 3. Use the same exclusion list as in the plugin
                excluded = [
                    'ftrack.origin', 'ftrack.connect', 
                    'ftrack.server', 'ftrack.unmanaged', 'ftrack.review'
                ]

                self.locations = [loc for loc in accessible_locations if loc['name'] not in excluded]
                
                # 4. Sort by name, since 'priority' attribute is not available in schema
                self.locations = sorted(self.locations, key=lambda loc: (loc['label'] or loc['name']).lower())

                self.from_location_combo.clear()
                self.to_location_combo.clear()

                for loc in self.locations:
                    label = loc['label'] or loc['name']
                    self.from_location_combo.addItem(label, loc['id'])
                    self.to_location_combo.addItem(label, loc['id'])
                
                logger.info(f"Loaded {len(self.locations)} final locations into UI.")
                if not self.locations:
                    self.update_status("Warning: No transferable locations found.")
                    logger.warning("No locations were found after filtering. The dropdowns will be empty.")
                else:
                    # Log found locations per user request
                    location_names = [loc['label'] or loc['name'] for loc in self.locations]
                    logger.info(f"[OK] DETECTED ACCESSIBLE LOCATIONS ON THIS MACHINE: {location_names}")


            except Exception as e:
                logger.error(f"Failed to load locations: {e}", exc_info=True)
                self.update_status("Error loading locations.")

        def _create_complete_ui(self):
            """Recreate exact UI structure from reference file"""
            # Top toolbar
            toolbar_container = QtWidgets.QWidget()
            toolbar_layout = QtWidgets.QHBoxLayout(toolbar_container)
            toolbar_layout.setContentsMargins(5, 5, 5, 5)

            project_label = QtWidgets.QLabel("Project:")
            toolbar_layout.addWidget(project_label)
            
            self.project_combo = QtWidgets.QComboBox()
            self.project_combo.setMinimumWidth(200)
            self.project_combo.currentIndexChanged.connect(self.on_project_changed)
            toolbar_layout.addWidget(self.project_combo)

            refresh_btn = QtWidgets.QPushButton("Refresh")
            refresh_btn.clicked.connect(self.on_refresh_clicked)
            toolbar_layout.addWidget(refresh_btn)
            
            self.quick_status_label = QtWidgets.QLabel("Ready")
            self.quick_status_label.setMinimumWidth(400)
            toolbar_layout.addWidget(self.quick_status_label)
            toolbar_layout.addStretch(1)

            self.change_focus_btn = QtWidgets.QPushButton("Change focus")
            self.change_focus_btn.setToolTip("Focus browser on component from selected Houdini node (componentid)")
            self.change_focus_btn.clicked.connect(self.on_change_focus_clicked)
            self.change_focus_btn.setVisible(HOUDINI_AVAILABLE)
            toolbar_layout.addWidget(self.change_focus_btn)

            # Main splitter
            main_splitter = QtWidgets.QSplitter(QtCore.Qt.Horizontal)

            # Left Pane
            left_widget = QtWidgets.QWidget()
            left_layout = QtWidgets.QVBoxLayout(left_widget)
            left_layout.setContentsMargins(0,0,0,0)

            self.task_tree = QtWidgets.QTreeWidget()
            self.task_tree.setHeaderLabels(['Name', 'Type/Status', 'Due Date'])
            self.task_tree.setColumnWidth(0, 200)
            self.task_tree.itemClicked.connect(self.on_item_selected)
            self.task_tree.itemExpanded.connect(self.on_item_expanded)
            left_layout.addWidget(self.task_tree)

            # Action buttons
            action_button_layout = QtWidgets.QHBoxLayout()
            
            self.copy_id_btn = QtWidgets.QPushButton("Copy ID")
            self.copy_id_btn.clicked.connect(self.on_copy_id_button_clicked)
            self.copy_id_btn.setEnabled(False)
            action_button_layout.addWidget(self.copy_id_btn)

            # Scene Setup: set task + scene FPS/frame range from parent shot attributes
            self.scene_setup_btn = QtWidgets.QPushButton("Scene Setup")
            self.scene_setup_btn.setToolTip(
                "Set task context and configure scene FPS/frame range from parent Shot (fstart/fend/handles/preroll/fps)"
            )
            self.scene_setup_btn.clicked.connect(self.on_scene_setup_button_clicked)
            self.scene_setup_btn.setEnabled(False)
            action_button_layout.addWidget(self.scene_setup_btn)
            
            self.set_task_btn = QtWidgets.QPushButton("Set Task")
            self.set_task_btn.setToolTip("Set FTRACK_CONTEXTID from selected task")
            self.set_task_btn.clicked.connect(self.on_set_task_button_clicked)
            self.set_task_btn.setEnabled(False)
            action_button_layout.addWidget(self.set_task_btn)
            
            self.set_task_on_node_btn = QtWidgets.QPushButton("Set Task on Sel. Node")
            self.set_task_on_node_btn.setToolTip("Set task_Id parameter on selected nodes")
            self.set_task_on_node_btn.clicked.connect(self.on_set_task_on_node_clicked)
            self.set_task_on_node_btn.setEnabled(False)
            action_button_layout.addWidget(self.set_task_on_node_btn)
            
            left_layout.addLayout(action_button_layout)
            main_splitter.addWidget(left_widget)

            # Right Pane - 3 columns
            right_widget = QtWidgets.QSplitter(QtCore.Qt.Horizontal)

            # Column 1: Asset Versions
            asset_tree_container = QtWidgets.QWidget()
            asset_tree_layout = QtWidgets.QVBoxLayout(asset_tree_container)
            asset_tree_layout.setContentsMargins(0,0,0,0)
            
            asset_versions_label = QtWidgets.QLabel("Asset Versions:")
            asset_tree_layout.addWidget(asset_versions_label)
            
            self.asset_version_tree = QtWidgets.QTreeWidget()
            self.asset_version_tree.setHeaderLabels(["Asset/Version", "Type", "Ver", "Published By", "Date", "Comment"])
            self.asset_version_tree.itemClicked.connect(self.on_asset_version_selected)
            self.asset_version_tree.itemExpanded.connect(self.on_asset_item_expanded)
            asset_tree_layout.addWidget(self.asset_version_tree)
            right_widget.addWidget(asset_tree_container)

            # Column 2: Components + Buttons
            middle_column = QtWidgets.QWidget()
            middle_layout = QtWidgets.QVBoxLayout(middle_column)
            middle_layout.setContentsMargins(0,0,0,0)
            
            components_label = QtWidgets.QLabel("Components:")
            middle_layout.addWidget(components_label)
            
            self.component_list = QtWidgets.QListWidget()
            self.component_list.itemClicked.connect(self.on_component_list_item_selected)
            middle_layout.addWidget(self.component_list)
            
            # HDA Integration buttons
            hda_group = QtWidgets.QGroupBox("HDA Integration")
            hda_layout = QtWidgets.QVBoxLayout(hda_group)
            
            self.set_hda_params_btn = QtWidgets.QPushButton("Set Full Params")
            self.set_hda_params_btn.setToolTip("Set AssetVersionId and ComponentName on selected Ftrack HDA nodes")
            self.set_hda_params_btn.clicked.connect(self.on_set_hda_params_clicked)
            self.set_hda_params_btn.setEnabled(False)
            hda_layout.addWidget(self.set_hda_params_btn)
            
            middle_layout.addWidget(hda_group)
            
            # Other action buttons
            actions_group = QtWidgets.QGroupBox("Actions")
            actions_layout = QtWidgets.QVBoxLayout(actions_group)
            
            self.copy_selected_id_btn = QtWidgets.QPushButton("Copy Sel. ID")
            self.copy_selected_id_btn.setToolTip("Copy ID of selected component or asset version")
            self.copy_selected_id_btn.clicked.connect(self.on_copy_selected_id_button_clicked)
            self.copy_selected_id_btn.setEnabled(False)
            actions_layout.addWidget(self.copy_selected_id_btn)

            self.load_snapshot_btn = QtWidgets.QPushButton("Load Snapshot") 
            self.load_snapshot_btn.setToolTip("Load selected .hip snapshot component if available")
            self.load_snapshot_btn.clicked.connect(self.on_load_snapshot_button_clicked)
            self.load_snapshot_btn.setEnabled(False)
            actions_layout.addWidget(self.load_snapshot_btn)
            
            middle_layout.addWidget(actions_group)

            # Location Management
            location_group = QtWidgets.QGroupBox("Location Management")
            location_layout = QtWidgets.QVBoxLayout(location_group)

            from_location_layout = QtWidgets.QHBoxLayout()
            from_location_layout.addWidget(QtWidgets.QLabel("From:"))
            self.from_location_combo = QtWidgets.QComboBox()
            self.from_location_combo.currentIndexChanged.connect(self._update_button_states) # Update button on change
            from_location_layout.addWidget(self.from_location_combo)
            location_layout.addLayout(from_location_layout)

            to_location_layout = QtWidgets.QHBoxLayout()
            to_location_layout.addWidget(QtWidgets.QLabel("To:"))
            self.to_location_combo = QtWidgets.QComboBox()
            self.to_location_combo.currentIndexChanged.connect(self._update_button_states) # Update button on change
            to_location_layout.addWidget(self.to_location_combo)
            location_layout.addLayout(to_location_layout)

            self.transfer_btn = QtWidgets.QPushButton("Start Transfer")
            self.transfer_btn.clicked.connect(self.on_start_transfer_clicked)
            self.transfer_btn.setEnabled(False)
            self.transfer_btn.setToolTip("Select item and locations to enable transfer")
            location_layout.addWidget(self.transfer_btn)
            
            middle_layout.addWidget(location_group)
            
            right_widget.addWidget(middle_column)

            # Column 3: Details
            details_widget = QtWidgets.QWidget()
            details_layout = QtWidgets.QVBoxLayout(details_widget)
            details_layout.setContentsMargins(0,0,0,0)
            
            metadata_label = QtWidgets.QLabel("Selection Details:")
            details_layout.addWidget(metadata_label)
            
            self.metadata_text = QtWidgets.QTextEdit()
            self.metadata_text.setReadOnly(True)
            self.metadata_text.setPlainText("No item selected")
            details_layout.addWidget(self.metadata_text)
            
            # Quick info
            self.right_pane_selected_id_label = QtWidgets.QLabel("N/A")
            self.right_pane_selected_path_label = QtWidgets.QLabel("N/A")
            
            # Configure file path label to prevent container resizing
            self.right_pane_selected_path_label.setWordWrap(True)
            self.right_pane_selected_path_label.setSizePolicy(
                QtWidgets.QSizePolicy.Ignored, 
                QtWidgets.QSizePolicy.Preferred
            )
            self.right_pane_selected_path_label.setTextInteractionFlags(
                QtCore.Qt.TextSelectableByMouse | QtCore.Qt.TextSelectableByKeyboard
            )
            
            details_layout.addWidget(QtWidgets.QLabel("Selected ID:"))
            details_layout.addWidget(self.right_pane_selected_id_label)
            details_layout.addWidget(QtWidgets.QLabel("File Path:"))
            details_layout.addWidget(self.right_pane_selected_path_label)
            
            right_widget.addWidget(details_widget)
            right_widget.setSizes([300, 300, 200])

            main_splitter.addWidget(right_widget)

            # Overall layout
            overall_layout = QtWidgets.QVBoxLayout(self)
            overall_layout.setContentsMargins(0, 0, 0, 0)
            overall_layout.setSpacing(0)
            
            overall_layout.addWidget(toolbar_container, 0)
            overall_layout.addWidget(main_splitter, 1)

            self.status_label = QtWidgets.QLabel("Status: Ready")
            overall_layout.addWidget(self.status_label, 0)

            main_splitter.setSizes([int(self.width() * 0.6), int(self.width() * 0.4)])

        def load_projects(self):
            """Load projects from API and auto-select based on FTRACK_CONTEXTID"""
            try:
                self.projects = self.api.get_projects()
                self.project_combo.clear()
                
                for project in self.projects:
                    self.project_combo.addItem(project['name'], project['id'])
                
                # Check for project from FTRACK_CONTEXTID environment variable
                context_project_id = None
                ftrack_contextid = os.environ.get('FTRACK_CONTEXTID')
                if ftrack_contextid:
                    logger.info(f"Found FTRACK_CONTEXTID: {ftrack_contextid}")
                    self.update_status(f"Checking context ID: {ftrack_contextid}")
                    
                    # Get project from context ID
                    context_project = self.api.get_project_from_context_id(ftrack_contextid)
                    if context_project:
                        context_project_id = context_project['id']
                        logger.info(f"Auto-selecting project from FTRACK_CONTEXTID: {context_project['name']}")
                        self.update_status(f"Auto-selected project: {context_project['name']}")
                    else:
                        logger.warning(f"Could not determine project from FTRACK_CONTEXTID: {ftrack_contextid}")
                        self.update_status("Could not determine project from context ID")
                
                # Auto-select project if found from context ID
                if context_project_id:
                    for i in range(self.project_combo.count()):
                        if self.project_combo.itemData(i) == context_project_id:
                            self.project_combo.setCurrentIndex(i)
                            logger.info(f"Project combo set to index {i} for project ID {context_project_id}")
                            break
                
                if self.projects:
                    self.load_tree()
                    
            except Exception as e:
                logger.error(f"Failed to load projects: {str(e)}")
                self.update_status(f"Error loading projects: {str(e)}")

        def update_status(self, text):
            """Update status display"""
            self.status_label.setText(f"Status: {text}")
            if hasattr(self, 'quick_status_label'):
                short_text = text[:27] + "..." if len(text) > 30 else text
                self.quick_status_label.setText(short_text)

        def on_project_changed(self, idx): 
            self.load_tree()
            
        def on_refresh_clicked(self):
            """Smart refresh with special logic for Task and Asset selections"""
            import time as time_module
            refresh_click_time = time_module.time()
            
            current_item = self.task_tree.currentItem()
            current_asset_item = self.asset_version_tree.currentItem()
            
            # Determine selected entity type and name for logging
            selected_entity_type = None
            selected_entity_name = None
            selected_entity_id = None
            
            if current_asset_item:
                asset_type = current_asset_item.data(0, ASSET_VERSION_ITEM_TYPE_ROLE)
                if asset_type == 'Asset':
                    selected_entity_type = 'Asset'
                    selected_entity_name = current_asset_item.text(0)
                    selected_entity_id = current_asset_item.data(0, ASSET_VERSION_ITEM_ID_ROLE)
                elif asset_type == 'AssetVersion':
                    selected_entity_type = 'AssetVersion'
                    selected_entity_name = current_asset_item.text(0)
                    selected_entity_id = current_asset_item.data(0, ASSET_VERSION_ITEM_ID_ROLE)
            elif current_item:
                item_type = current_item.data(0, ITEM_TYPE_ROLE)
                if item_type:
                    selected_entity_type = item_type
                    selected_entity_name = current_item.text(0)
                    selected_entity_id = current_item.data(0, ITEM_ID_ROLE)
            
            entity_info = f"{selected_entity_type or 'None'}"
            if selected_entity_name:
                entity_info += f" '{selected_entity_name}'"
            if selected_entity_id:
                entity_info += f" (ID: {selected_entity_id[:8]}...)"
            
            logger.info(f"[REFRESH CLICK] Refresh button clicked at {time_module.strftime('%H:%M:%S', time_module.localtime(refresh_click_time))}.{int((refresh_click_time % 1) * 1000):03d}")
            logger.info(f"[REFRESH CLICK] Selected entity: {entity_info}")
            
            # Check if Asset is selected in right pane (priority over left pane)
            if current_asset_item and current_asset_item.data(0, ASSET_VERSION_ITEM_TYPE_ROLE) == 'Asset':
                # Special case: Asset selected in right pane - refresh only its versions
                logger.info(f"[REFRESH CLICK] Action: Refresh Asset versions")
                self._refresh_asset_versions(current_asset_item, refresh_start_time=refresh_click_time)
            elif current_asset_item and current_asset_item.data(0, ASSET_VERSION_ITEM_TYPE_ROLE) == 'AssetVersion':
                # Special case: AssetVersion selected - refresh parent Asset
                logger.info(f"[REFRESH CLICK] Action: Refresh parent Asset (AssetVersion selected)")
                parent_asset_item = current_asset_item.parent()
                if parent_asset_item:
                    self._refresh_asset_versions(parent_asset_item, refresh_start_time=refresh_click_time)
                else:
                    logger.warning("AssetVersion has no parent Asset item")
            elif current_item and current_item.data(0, ITEM_TYPE_ROLE) != 'Project':
                item_type = current_item.data(0, ITEM_TYPE_ROLE)
                
                if item_type == 'Task':
                    # Special case: Task selected - refresh parent Shot and right pane
                    logger.info(f"[REFRESH CLICK] Action: Refresh Task and assets")
                    self._refresh_task_and_assets(current_item)
                else:
                    # Normal case: refresh selected branch
                    logger.info(f"[REFRESH CLICK] Action: Refresh branch ({item_type})")
                    self._refresh_branch(current_item)
            else:
                # Full refresh with state preservation
                logger.info(f"[REFRESH CLICK] Action: Full tree refresh")
                self._refresh_full_tree_with_state()
            
            refresh_end_time = time_module.time()
            total_refresh_time = refresh_end_time - refresh_click_time
            logger.info(f"[REFRESH CLICK] Completed at {time_module.strftime('%H:%M:%S', time_module.localtime(refresh_end_time))}.{int((refresh_end_time % 1) * 1000):03d}")
            logger.info(f"[REFRESH CLICK] TOTAL COST: {total_refresh_time:.3f}s ({total_refresh_time*1000:.0f}ms) - sync part only (QTimer callbacks run later)")

        def _get_path_from_component_to_project(self, session, component_id):
            """Resolve component -> version -> asset -> parent chain to project (uses session cache).
            Returns (project_id, path_entity_ids, asset_id, version_id) or (None, [], None, None).
            path_entity_ids = [project_id, folder_id?, ..., entity_id] where entity_id is asset.parent."""
            try:
                comp = session.get("Component", component_id)
                version = comp["version"]
                asset = version["asset"]
                asset_id = str(asset["id"])
                version_id = str(version["id"])
                parent_entity = asset.get("parent")
                if not parent_entity:
                    return None, [], asset_id, version_id
                path_ids = []
                current = parent_entity
                while current:
                    path_ids.append(str(current["id"]))
                    etype = getattr(current, "entity_type", None) or getattr(current, "type", None)
                    if etype and str(etype).lower() == "project":
                        break
                    parent = current.get("parent")
                    if not parent:
                        break
                    current = parent
                if not path_ids:
                    return None, [], asset_id, version_id
                project_id = path_ids[-1]
                path_from_project = list(reversed(path_ids))
                return project_id, path_from_project, asset_id, version_id
            except Exception as e:
                logger.warning("_get_path_from_component_to_project: %s", e)
                return None, [], None, None

        def _expand_tree_to_entity(self, path_from_project):
            """Expand left tree step by step along path_from_project [project_id, ..., entity_id], then select the last item."""
            if not path_from_project:
                return
            project_id = path_from_project[0]
            root = self.task_tree.topLevelItem(0)
            if not root or str(root.data(0, ITEM_ID_ROLE)) != project_id:
                return
            current_item = root
            for idx in range(1, len(path_from_project)):
                target_id = path_from_project[idx]
                if not current_item.data(0, ITEM_POPULATED_ROLE):
                    if current_item.childCount() > 0 and current_item.child(0).text(0) == DUMMY_NODE_TEXT:
                        current_item.takeChild(0)
                    self.fetch_and_populate_children(
                        current_item,
                        str(current_item.data(0, ITEM_ID_ROLE)),
                        current_item.data(0, ITEM_TYPE_ROLE),
                    )
                    current_item.setData(0, ITEM_POPULATED_ROLE, True)
                child_item = None
                for i in range(current_item.childCount()):
                    c = current_item.child(i)
                    if str(c.data(0, ITEM_ID_ROLE)) == target_id:
                        child_item = c
                        break
                if not child_item:
                    logger.warning("Change focus: entity %s not found under %s", target_id[:8], current_item.text(0))
                    return
                current_item = child_item
                current_item.setExpanded(True)
            self.task_tree.setCurrentItem(current_item)
            self.on_item_selected(current_item, 0)

        def on_change_focus_clicked(self):
            """Focus browser on component from selected Houdini node: get path from project root, switch project if needed, expand left tree to entity, then focus right pane on asset/version/component.
            Uses cache: session.get() (ftrack session cache), and API get_assets_linked_to_entity / get_versions_for_asset / get_components_with_paths_for_version (no force_refresh)."""
            if not HOUDINI_AVAILABLE:
                QtWidgets.QMessageBox.warning(
                    self, "Change focus",
                    "Houdini is not available. Use this button when the browser runs inside Houdini.",
                )
                return
            selected = hou.selectedNodes()
            if not selected:
                QtWidgets.QMessageBox.warning(
                    self, "Change focus",
                    "Select a node in Houdini that has a component (e.g. finput with componentid).",
                )
                return
            component_id = None
            for node in selected:
                parm = node.parm("componentid")
                if parm:
                    val = parm.eval()
                    if val:
                        component_id = str(val).strip()
                        break
            if not component_id:
                QtWidgets.QMessageBox.warning(
                    self, "Change focus",
                    "Selected node has no componentid (or it is empty). Select a finput node with a loaded component.",
                )
                return
            if not self.api or not getattr(self.api, "session", None):
                QtWidgets.QMessageBox.warning(self, "Change focus", "No ftrack session available.")
                return
            session = self.api.session
            project_id, path_from_project, asset_id, version_id = self._get_path_from_component_to_project(session, component_id)
            if not project_id or not path_from_project or not asset_id or not version_id:
                QtWidgets.QMessageBox.warning(
                    self, "Change focus",
                    "Could not resolve path from component to project.",
                )
                return
            current_project_id = self.project_combo.currentData()
            if current_project_id != project_id:
                for i in range(self.project_combo.count()):
                    if self.project_combo.itemData(i) == project_id:
                        self.project_combo.setCurrentIndex(i)
                        break
                self.load_tree()
            elif self.task_tree.topLevelItemCount() == 0:
                self.load_tree()
            self.clear_asset_version_tree()
            self._expand_tree_to_entity(path_from_project)
            QtCore.QTimer.singleShot(800, lambda: self._focus_right_pane_on_component(asset_id, version_id, component_id))

        def _focus_right_pane_on_component(self, asset_id, version_id, component_id):
            """After left tree is focused, select asset/version/component in the right pane."""
            asset_item = None
            for i in range(self.asset_version_tree.topLevelItemCount()):
                item = self.asset_version_tree.topLevelItem(i)
                if str(item.data(0, ASSET_VERSION_ITEM_ID_ROLE)) == asset_id:
                    asset_item = item
                    break
            if not asset_item:
                self.update_status("Focus: entity loaded; asset not in list.")
                return
            if asset_item.childCount() == 0 or (asset_item.child(0).data(0, ASSET_VERSION_ITEM_TYPE_ROLE) == "Placeholder"):
                self.load_versions_for_asset(asset_item, asset_id)
            version_item = None
            for j in range(asset_item.childCount()):
                child = asset_item.child(j)
                if str(child.data(0, ASSET_VERSION_ITEM_ID_ROLE)) == version_id:
                    version_item = child
                    break
            if not version_item:
                self.asset_version_tree.setCurrentItem(asset_item)
                self.update_status("Focus: asset loaded; version not found.")
                return
            self.asset_version_tree.setCurrentItem(version_item)
            QtCore.QTimer.singleShot(400, lambda: self._select_component_in_list(component_id))

        def _select_component_in_list(self, component_id):
            """Select the list item for the given component_id in the component list."""
            for i in range(self.component_list.count()):
                item = self.component_list.item(i)
                data = item.data(QtCore.Qt.UserRole)
                if data and str(data.get("id")) == str(component_id):
                    self.component_list.setCurrentItem(item)
                    self.update_status("Focus: %s" % (data.get("name") or component_id[:8]))
                    return

        def load_tree(self): 
            """Load project tree with lazy expansion like original"""
            logger.info("Starting to load tree (lazy)...")
            try:
                self.task_tree.clear()
                self.clear_asset_version_tree()
                self.set_task_btn.setEnabled(False) 
                self.copy_id_btn.setEnabled(False) 
                self.update_status("Loading project...")
                
                idx = self.project_combo.currentIndex()
                if idx < 0 or not self.projects:
                    self.update_status("No project selected")
                    return
                    
                project = self.projects[idx]
                project_id = project['id']
                project_name = project['name']
                
                project_item = QtWidgets.QTreeWidgetItem([project_name, 'Project', ''])
                project_item.setData(0, ITEM_ID_ROLE, project_id)
                project_item.setData(0, ITEM_TYPE_ROLE, 'Project')
                project_item.setData(0, ITEM_POPULATED_ROLE, False)
                project_item.setData(0, ITEM_NAME_ROLE, project_name)
                
                # Add dummy child to make expandable
                project_item.addChild(QtWidgets.QTreeWidgetItem([DUMMY_NODE_TEXT]))
                
                self.task_tree.addTopLevelItem(project_item)
                self.update_status("Project loaded. Expand to see content.")
                logger.info("Project item added. Tree ready for expansion.")
            except Exception as e:
                logger.error(f"Failed to load initial project tree: {str(e)}")
                self.update_status(f"Error loading project: {str(e)}")

        def clear_asset_version_tree(self):
            """Clear asset version tree and components"""
            self.asset_version_tree.clear()
            self.component_list.clear()
            self.right_pane_selected_id_label.setText("N/A")
            self.right_pane_selected_path_label.setText("N/A")
            self.current_loaded_entity_id = None
            self._update_button_states()

        def _update_button_states(self):
            """Update button enabled states based on selection"""
            # Check selections
            current_comp_item = self.component_list.currentItem()
            current_asset_item = self.asset_version_tree.currentItem()
            
            asset_version_selected = False
            component_selected = False
            
            # Check asset version selection
            if current_asset_item:
                item_type = current_asset_item.data(0, ASSET_VERSION_ITEM_TYPE_ROLE)
                asset_version_id = current_asset_item.data(0, ASSET_VERSION_ITEM_ID_ROLE)
                if item_type in ['AssetVersion', 'Asset'] and asset_version_id:
                    asset_version_selected = True
                logger.info(f"Asset version selection: type={item_type}, id={asset_version_id}, selected={asset_version_selected}")
            
            # Check component selection
            if current_comp_item:
                stored_data = current_comp_item.data(QtCore.Qt.UserRole)
                if stored_data and stored_data.get('name'):
                    component_selected = True
                logger.info(f"Component selection: data={stored_data}, selected={component_selected}")
            
            # HDA Integration buttons - Set Full Params works with any selection
            self.set_hda_params_btn.setEnabled(asset_version_selected or component_selected)
            
            # Right pane buttons
            self.copy_selected_id_btn.setEnabled(asset_version_selected or component_selected)
            logger.info(f"Button states updated: copy_selected_id={asset_version_selected or component_selected}, hda_params={asset_version_selected or component_selected}")
            
            # Load Snapshot button - only enable for .hip components
            snapshot_loadable = False
            if component_selected:
                stored_data = current_comp_item.data(QtCore.Qt.UserRole)
                comp_path = stored_data.get('path', '')
                if comp_path and comp_path.lower().endswith('.hip'):
                    snapshot_loadable = True
            self.load_snapshot_btn.setEnabled(snapshot_loadable)
            
            # Location transfer button state
            # NOTE: TRANSFER_ACTION_AVAILABLE check removed - TransferWorker works independently
            # by publishing mroya.transfer.request events. It does NOT require TransferComponentsPlusAction.
            component_or_version_selected = asset_version_selected or component_selected
            locations_are_different = (
                self.from_location_combo.currentData() != self.to_location_combo.currentData()
            )
            can_transfer = (
                component_or_version_selected and locations_are_different
            )
            self.transfer_btn.setEnabled(can_transfer)
            if can_transfer:
                self.transfer_btn.setToolTip("Start transfer (via mroya.transfer.request event)")
            else:
                if not component_or_version_selected:
                    self.transfer_btn.setToolTip("Select a component or asset version to transfer")
                elif not locations_are_different:
                    self.transfer_btn.setToolTip("Select different source and target locations")
            
        def on_item_expanded(self, item):
            """Handle tree item expansion with lazy loading"""
            item_id = item.data(0, ITEM_ID_ROLE)
            item_type = item.data(0, ITEM_TYPE_ROLE)
            is_populated = item.data(0, ITEM_POPULATED_ROLE)

            if not item_id or is_populated:
                return

            logger.info(f"Expanding item: {item.text(0)} (ID: {item_id}, Type: {item_type})")
            self.update_status(f"Loading content for {item_type} '{item.text(0)}'...")

            # Remove dummy node
            if item.childCount() > 0 and item.child(0).text(0) == DUMMY_NODE_TEXT:
                item.takeChild(0)

            # Fetch and populate children 
            self.fetch_and_populate_children(item, item_id, item_type)
            item.setData(0, ITEM_POPULATED_ROLE, True)
            self.update_status(f"Content for '{item.text(0)}' loaded.")

        def fetch_and_populate_children(self, parent_item, parent_id, parent_type):
            """Fetch children based on parent type"""
            logger.info(f"Fetching children for {parent_type} ID: {parent_id}")

            if parent_type == 'Project':
                self._add_children_of_type(parent_item, parent_id, 'Folder')
                self._add_children_of_type(parent_item, parent_id, 'AssetBuild')
                self._add_children_of_type(parent_item, parent_id, 'Sequence')
                self._add_children_of_type(parent_item, parent_id, 'Scene')
                self._add_children_of_type(parent_item, parent_id, 'Shot')

            elif parent_type == 'Folder':
                self._add_children_of_type(parent_item, parent_id, 'Folder')
                self._add_children_of_type(parent_item, parent_id, 'AssetBuild')
                self._add_children_of_type(parent_item, parent_id, 'Sequence')
                self._add_children_of_type(parent_item, parent_id, 'Scene')
                self._add_children_of_type(parent_item, parent_id, 'Shot')
            
            elif parent_type in ['AssetBuild', 'Shot']:
                # Add tasks
                tasks = self.api.get_tasks_for_entity(parent_id)
                for task in tasks:
                    task_item = QtWidgets.QTreeWidgetItem([
                        task.get('name', 'Unknown'),
                        task.get('status', {}).get('name', 'No Status'),
                        ''
                    ])
                    task_item.setData(0, ITEM_ID_ROLE, task['id'])
                    task_item.setData(0, ITEM_TYPE_ROLE, 'Task')
                    task_item.setData(0, ITEM_POPULATED_ROLE, True)
                    task_item.setData(0, ITEM_NAME_ROLE, task.get('name', 'Unknown'))
                    parent_item.addChild(task_item)
            
            elif parent_type == 'Sequence':
                # Add tasks for sequence
                tasks = self.api.get_tasks_for_entity(parent_id)
                for task in tasks:
                    task_item = QtWidgets.QTreeWidgetItem([
                        task.get('name', 'Unknown'),
                        task.get('status', {}).get('name', 'No Status'),
                        ''
                    ])
                    task_item.setData(0, ITEM_ID_ROLE, task['id'])
                    task_item.setData(0, ITEM_TYPE_ROLE, 'Task')
                    task_item.setData(0, ITEM_POPULATED_ROLE, True)
                    task_item.setData(0, ITEM_NAME_ROLE, task.get('name', 'Unknown'))
                    parent_item.addChild(task_item)
                
                # Add shots for sequence
                self._add_children_of_type(parent_item, parent_id, 'Shot')
            
            elif parent_type == 'Scene':
                # Add tasks for scene
                tasks = self.api.get_tasks_for_entity(parent_id)
                for task in tasks:
                    task_item = QtWidgets.QTreeWidgetItem([
                        task.get('name', 'Unknown'),
                        task.get('status', {}).get('name', 'No Status'),
                        ''
                    ])
                    task_item.setData(0, ITEM_ID_ROLE, task['id'])
                    task_item.setData(0, ITEM_TYPE_ROLE, 'Task')
                    task_item.setData(0, ITEM_POPULATED_ROLE, True)
                    task_item.setData(0, ITEM_NAME_ROLE, task.get('name', 'Unknown'))
                    parent_item.addChild(task_item)
                
                # Add shots for scene (scenes can contain shots)
                self._add_children_of_type(parent_item, parent_id, 'Shot')

        def _add_children_of_type(self, parent_item, parent_id, entity_type):
            """Helper to add children of specific type"""
            entities = []
            if entity_type == 'Folder':
                entities = self.api.get_folders(parent_id)
            elif entity_type == 'AssetBuild':
                entities = self.api.get_assets(parent_id)
            elif entity_type == 'Sequence':
                entities = self.api.get_sequences(parent_id)
            elif entity_type == 'Scene':
                entities = self.api.get_scenes(parent_id)
            elif entity_type == 'Shot':
                entities = self.api.get_shots(parent_id)

            # Sort entities by name for better UX
            entities = sorted(entities, key=lambda x: x.get('name', '').lower())

            for entity in entities:
                item_text = entity.get('name', 'Unknown')
                item = QtWidgets.QTreeWidgetItem([item_text, entity_type, ''])
                item.setData(0, ITEM_ID_ROLE, entity['id'])
                item.setData(0, ITEM_TYPE_ROLE, entity_type)
                item.setData(0, ITEM_POPULATED_ROLE, False)
                item.setData(0, ITEM_NAME_ROLE, item_text)

                # Color different entity types for better visual distinction
                if entity_type == 'Folder':
                    # 5 blue variants - uncomment the one you need:
                    
                    # Option 1: Classic blue (dark, saturated)
                    # item.setForeground(0, QtCore.Qt.blue)
                    # item.setForeground(1, QtCore.Qt.blue)
                    
                    # Option 2: Bright cyan blue (bright, acidic)
                    # item.setForeground(0, QtCore.Qt.cyan)
                    # item.setForeground(1, QtCore.Qt.cyan)
                    
                    # Option 3: Dark blue (muted, elegant)
                    # item.setForeground(0, QtCore.Qt.darkCyan)
                    # item.setForeground(1, QtCore.Qt.darkCyan)
                    
                    # Option 4: Medium blue (moderately bright, like sky)
                    # item.setForeground(0, QtGui.QColor(0, 150, 255))
                    # item.setForeground(1, QtGui.QColor(0, 150, 255))
                    
                    # Option 5: Steel blue (gray-blue, business-like) - ACTIVE
                    item.setForeground(0, QtGui.QColor(70, 130, 180))
                    item.setForeground(1, QtGui.QColor(70, 130, 180))
                elif entity_type == 'Sequence':
                    item.setForeground(0, QtCore.Qt.darkMagenta)
                    item.setForeground(1, QtCore.Qt.darkMagenta)
                elif entity_type == 'Shot':
                    item.setForeground(0, QtCore.Qt.darkGreen)
                    item.setForeground(1, QtCore.Qt.darkGreen)

                item.addChild(QtWidgets.QTreeWidgetItem([DUMMY_NODE_TEXT]))
                parent_item.addChild(item)

        def on_item_selected(self, item, column):
            """Handle tree item selection"""
            self.selected_item = item  # Store the selected item for the timer
            try:
                item_type = item.data(0, ITEM_TYPE_ROLE)
                item_id = item.data(0, ITEM_ID_ROLE)
                item_name = item.data(0, ITEM_NAME_ROLE)
                item_status = item.text(1) # Get status from column 1 for tasks

                logger.info(f"Item selected: {item_name} (Type: {item_type}, ID: {item_id})")

                # Enable/disable buttons based on selection
                if item_type == 'Task':
                    self.set_task_btn.setEnabled(True)
                    self.set_task_on_node_btn.setEnabled(True)
                    self.scene_setup_btn.setEnabled(True)
                else:
                    self.set_task_btn.setEnabled(False)
                    self.set_task_on_node_btn.setEnabled(False)
                    self.scene_setup_btn.setEnabled(False)

                if item_type in ['Shot', 'Task', 'AssetBuild', 'Folder', 'Sequence', 'Scene'] and item_id:
                    self.copy_id_btn.setEnabled(True)
                else:
                    self.copy_id_btn.setEnabled(False)

                if item_id and item_type and item_name:
                    self.update_status(f"Selected: {item_type} '{item_name}' (ID: {item_id})")

                # Create a dictionary to hold all item data, including its parent, for consistent processing.
                parent_data = None
                if item.parent():
                    parent_item = item.parent()
                    parent_data = {
                        'id': parent_item.data(0, ITEM_ID_ROLE),
                        'type': parent_item.data(0, ITEM_TYPE_ROLE),
                        'name': parent_item.data(0, ITEM_NAME_ROLE)
                    }

                # CORRECTED DATA STRUCTURE
                item_data = {
                    'id': item_id,
                    'name': item_name,
                    'parent': parent_data,
                    # Make data structure consistent with what metadata display expects
                    'type': {'name': item_type} if item_type == 'Task' else item_type,
                    'status': {'name': item_status} if item_type == 'Task' else None
                }
                
                self.pending_item_data = item_data

                self.update_metadata_display(item_data, item_type)

                # Determine context for loading assets in the right-hand pane
                context_id_for_assets = None
                if item_type == 'Task':
                    if parent_data:
                        context_id_for_assets = parent_data.get('id')
                        logger.info(f"Task selected, parent context: {parent_data.get('type')} ID {context_id_for_assets}")
                elif item_type in ['Shot', 'AssetBuild', 'Sequence', 'Scene']:
                    context_id_for_assets = item_id
                    logger.info(f"Entity selected, using as context: {item_type} ID {context_id_for_assets}")

                # Use a timer to delay loading/filtering, preventing rapid selections from
                # overwhelming the API. The timer is reset on each new selection.
                if item_type == 'Task' or (context_id_for_assets and self.current_loaded_entity_id != context_id_for_assets):
                    self.selection_timer.start(300)
                    self.update_status("Loading assets...")
                elif not context_id_for_assets and item_type != 'Task':
                    logger.info("No valid context for assets, clearing asset version tree")
                    self.clear_asset_version_tree()

            except Exception as e:
                logger.error(f"Error in on_item_selected: {str(e)}", exc_info=True)
                self.update_status(f"Error selecting item: {str(e)}")

        def on_selection_timer_timeout(self):
            """This function is called after the selection delay. It processes the stored item."""
            if not self.selected_item or not hasattr(self, 'pending_item_data'):
                return

            item_data = self.pending_item_data
            entity_id = item_data.get('id')
            entity_type = item_data.get('type')
            
            # Handle case where entity_type might be a dict for Tasks
            if isinstance(entity_type, dict):
                entity_type_name = entity_type.get('name', 'Unknown')
            else:
                entity_type_name = entity_type

            logger.info(f"Processing selection: {entity_type_name} {entity_id}")
            self.update_status(f"Loading {entity_type_name}...")

            if entity_type_name == 'Task':
                logger.info("Task selected. Fetching assets for task ID: {}".format(entity_id))
                
                # IMPORTANT: Store task ID for version filtering
                self.current_task_filter_id = entity_id
                
                # Clear all right-hand-side views
                self.asset_version_tree.clear()
                self.component_list.clear()
                self.metadata_text.setHtml("<p>Loading assets for task...</p>")
                self.right_pane_selected_id_label.setText("N/A")
                self.right_pane_selected_path_label.setText("N/A")
                self._update_button_states()

                try:
                    assets = self.api.get_assets_for_task(entity_id)
                    
                    if not assets:
                        self.update_status("No assets found for this task.")
                        self.asset_version_tree.addTopLevelItem(QtWidgets.QTreeWidgetItem(["No assets found for this task."]))
                    else:
                        for asset in assets:
                            asset_name = asset.get('name', 'Unknown Asset')
                            asset_type = asset.get('type', {}).get('name', 'N/A')
                            asset_id = asset['id']
                            asset_item = QtWidgets.QTreeWidgetItem([asset_name, asset_type])
                            asset_item.setData(0, ASSET_VERSION_ITEM_ID_ROLE, asset_id)
                            asset_item.setData(0, ASSET_VERSION_ITEM_TYPE_ROLE, 'Asset')
                            self.asset_version_tree.addTopLevelItem(asset_item)
                            placeholder = QtWidgets.QTreeWidgetItem(["Click to load versions..."])
                            placeholder.setData(0, ASSET_VERSION_ITEM_TYPE_ROLE, 'Placeholder')
                            asset_item.addChild(placeholder)
                        self.update_status(f"Showing {len(assets)} assets for task.")
                    
                    self.current_loaded_entity_id = f"task_{entity_id}" 

                except Exception as e:
                    logger.error(f"Failed to load assets for task {entity_id}: {e}", exc_info=True)
                    self.update_status("Error loading assets for task.")
                
            else:
                # Original logic for other entity types - clear task filter
                self.current_task_filter_id = None
                self.load_asset_versions_for_entity(entity_id)
            
            # Update metadata display for the processed item
            self.update_metadata_display(item_data, entity_type_name)

        def update_metadata_display(self, item_data=None, item_type=None):
            """Update the metadata text area with information about the selected item using HTML."""
            if not item_data:
                self.metadata_text.setHtml("<p>No item selected</p>")
                return
            
            # Wrap in div and use relative line-height for reliability
            html = "<div style='font-family: Arial, sans-serif; font-size: 8pt; line-height: 1.7;'>"
            
            if item_type == "Task":
                html += "<h5>TASK INFORMATION</h5>"
                html += f"Name: {item_data.get('name', 'N/A')}<br>"
                html += f"ID: {item_data.get('id', 'N/A')}<br>"

                # ROBUST HANDLING of 'type' data
                task_type_info = item_data.get('type', {})
                task_type_name = task_type_info.get('name', 'N/A') if isinstance(task_type_info, dict) else str(task_type_info)
                html += f"Type: {task_type_name}<br>"

                # ROBUST HANDLING of 'status' data
                task_status_info = item_data.get('status', {})
                task_status_name = task_status_info.get('name', 'N/A') if isinstance(task_status_info, dict) else str(task_status_info)
                html += f"Status: {task_status_name}<br>"
                    
            elif item_type == "AssetVersion":
                html += "<h5>ASSET VERSION INFORMATION</h5>"
                html += f"Version: v{item_data.get('version', 'N/A')}<br>"
                html += f"ID: {item_data.get('id', 'N/A')}<br>"
                html += f"Comment: {item_data.get('comment', 'N/A')}<br>"
                html += f"Date: {item_data.get('date', 'N/A')}<br>"
                if 'user' in item_data and item_data['user']:
                    user = item_data['user']
                    user_name = f"{user.get('first_name', '')} {user.get('last_name', '')}".strip()
                    html += f"Published by: {user_name}<br>"
                if 'asset' in item_data and item_data['asset']:
                    html += f"Asset: {item_data['asset'].get('name', 'N/A')}<br>"
                    
            elif item_type == "Component":
                html += "<h5>COMPONENT INFORMATION</h5>"
                html += f"Name: {item_data.get('name', 'N/A')}<br>"
                html += f"ID: {item_data.get('id', 'N/A')}<br>"
                html += f"File Type: {item_data.get('type', 'N/A')}<br>"
                html += f"Path: {item_data.get('path', 'N/A')}<br>"
                
                # --- MAIN FIX ---
                locations = item_data.get('locations', [])
                html += "<br>" # Space for aesthetics
                if locations:
                    html += f"<b>Available at ({len(locations)}):</b><ul>"
                    for loc_name in locations:
                        html += f"<li>{loc_name}</li>"
                    html += "</ul>"
                else:
                    html += "<b>Availability:</b> Not in any tracked location."

                if 'size' in item_data:
                    size_mb = round(item_data['size'] / (1024*1024), 2) if item_data['size'] else 0
                    html += f"<br>Size: {size_mb} MB"
                    
            elif item_type == "Asset":
                html += "<h5>ASSET INFORMATION</h5>"
                asset_id = item_data.get('id', 'N/A')
                html += f"Name: {item_data.get('name', 'N/A')}<br>"
                html += f"ID: {asset_id}<br>"

                asset_type = item_data.get('asset_type') or item_data.get('type') or 'Asset'
                if isinstance(asset_type, dict):
                    asset_type = asset_type.get('name', 'Asset')
                html += f"Type: {asset_type}<br>"

                # Try to fetch asset metadata from ftrack session
                metadata = {}
                session = getattr(self.api, "session", None)
                if session and asset_id not in (None, "", "N/A"):
                    try:
                        asset_entity = session.get('Asset', str(asset_id))
                        if asset_entity:
                            metadata = asset_entity.get('metadata') or {}
                    except Exception as e:
                        logger.warning(f"Failed to fetch metadata for Asset {asset_id}: {e}")

                # Fallback: metadata may already be present in item_data
                if not metadata:
                    try:
                        metadata = item_data.get('metadata') or {}
                    except Exception:
                        metadata = {}

                if metadata:
                    html += "<br><h6>ASSET METADATA</h6>"
                    try:
                        for k in sorted(metadata.keys()):
                            v = metadata.get(k)
                            html += f"{k}: {v}<br>"
                    except Exception:
                        # Non-iterable or unexpected structure
                        html += f"{metadata}<br>"
                else:
                    html += "<br><i>No metadata on this asset.</i>"

            elif item_type in ["Shot", "AssetBuild", "Sequence", "Scene", "Folder", "Project"]:
                html += f"<h5>{item_type.upper()} INFORMATION</h5>"
                html += f"Name: {item_data.get('name', 'N/A')}<br>"
                html += f"ID: {item_data.get('id', 'N/A')}<br>"
                html += f"Type: {item_type}<br>"
                if 'description' in item_data:
                    html += f"Description: {item_data.get('description', 'N/A')}<br>"
                
                if item_type == "Shot":
                    shot_id = item_data.get('id')
                    if shot_id:
                        shot_info = self.api.get_shot_custom_attributes_on_demand(shot_id)
                        if shot_info:
                            html += "<br><h6>SHOT DETAILS</h6>"
                            if shot_info.get('name'):
                                html += f"Shot Name: {shot_info['name']}<br>"
                            if shot_info.get('description'):
                                html += f"Description: {shot_info['description']}<br>"
                            
                            custom_attrs_found = False
                            keys_of_interest = ['fstart', 'fend', 'handles', 'preroll', 'fps']
                            for k in keys_of_interest:
                                v = shot_info.get(k)
                                if v not in (None, '', [], {}):
                                    html += f"{k}: {v}<br>"
                                    custom_attrs_found = True
                            if not custom_attrs_found:
                                html += "No custom frame/timing attributes found<br>"
                
            else:
                html += f"<h5>ITEM INFORMATION</h5>"
                html += f"Type: {item_type}<br>"
                for key, value in item_data.items():
                    if isinstance(value, (str, int, float)):
                        html += f"{key}: {value}<br>"
            
            html += "</div>"
            self.metadata_text.setHtml(html)

        def load_asset_versions_for_entity(self, entity_id):
            """Load assets for selected entity (versions loaded on demand when asset is selected)"""
            logger.info(f"Loading assets for entity ID: {entity_id}")
            self.clear_asset_version_tree()
            if not entity_id:
                logger.warning("No entity ID provided for asset loading")
                return

            try:
                logger.info(f"Fetching assets linked to entity {entity_id}")
                assets = self.api.get_assets_linked_to_entity(entity_id)
                if not assets:
                    self.update_status("No assets found for selected context.")
                    return

                # Sort assets by name for better UX
                assets = sorted(assets, key=lambda x: x.get('name', '').lower())

                # NEW LAZY LOADING: Load only assets, not versions (much faster!)
                logger.info(f"[LAUNCH] LAZY LOADING: Showing {len(assets)} assets (versions loaded on demand)")

                for asset in assets:
                    asset_name = asset.get('name', 'Unknown Asset')
                    raw_type = asset.get('type')
                    # Asset type is an entity/dict; extract its name safely
                    if isinstance(raw_type, dict):
                        asset_type = raw_type.get('name', 'N/A')
                    else:
                        try:
                            asset_type = raw_type.get('name', 'N/A')
                        except Exception:
                            asset_type = str(raw_type) if raw_type else 'N/A'
                    asset_id = asset['id']
                    asset_item = QtWidgets.QTreeWidgetItem([asset_name, asset_type])
                    asset_item.setData(0, ASSET_VERSION_ITEM_ID_ROLE, asset_id)
                    asset_item.setData(0, ASSET_VERSION_ITEM_TYPE_ROLE, 'Asset')
                    self.asset_version_tree.addTopLevelItem(asset_item)

                    # Add placeholder child to show it can be expanded
                    placeholder_item = QtWidgets.QTreeWidgetItem(["Click to load versions..."])
                    placeholder_item.setData(0, ASSET_VERSION_ITEM_TYPE_ROLE, 'Placeholder')
                    asset_item.addChild(placeholder_item)
                
                self.current_loaded_entity_id = entity_id
                self.update_status(f"Assets loaded for entity ID: {entity_id} (versions loaded on demand)")

            except Exception as e:
                logger.error(f"Failed to load assets: {str(e)}")
                self.update_status(f"Error loading assets: {str(e)}")

        def load_versions_for_asset(self, asset_item, asset_id):
            """Load versions for a specific asset (on-demand loading)"""
            try:
                # Check if versions are already loaded in UI
                if asset_item.childCount() > 0:
                    first_child = asset_item.child(0)
                    if first_child.data(0, ASSET_VERSION_ITEM_TYPE_ROLE) != 'Placeholder':
                        logger.info(f"Versions already loaded in UI for asset {asset_id}")
                        return

                logger.info(f"[REFRESH] Loading versions for asset {asset_id}...")
                self.update_status(f"Loading versions for asset...")

                # Remove placeholder
                asset_item.takeChildren()

                # Get versions for this specific asset, filtered by task if applicable
                # force_refresh=True: always use query to get fresh version list from server,
                # avoids stale ftrack relationship cache after browser reload
                if self.current_task_filter_id:
                    logger.info(f"[SEARCH] Filtering versions for asset {asset_id} by task {self.current_task_filter_id}")
                    versions = self.api.get_versions_for_asset_and_task(asset_id, self.current_task_filter_id)
                else:
                    versions = self.api.get_versions_for_asset(asset_id, force_refresh=True)
                
                if not versions:
                    no_versions_item = QtWidgets.QTreeWidgetItem(["No versions found"])
                    asset_item.addChild(no_versions_item)
                    self.update_status("No versions found for this asset.")
                    return

                # Sort versions by version number (newest first)
                versions = sorted(versions, key=lambda x: x.get('version', 0), reverse=True)

                for version_data in versions:
                    version_number = str(version_data.get('version', 'N/A'))
                    version_display_name = f"v{version_number}"
                    
                    # Use full_name from updated API if available, otherwise build it
                    user_data = version_data.get('user', {})
                    if user_data.get('full_name'):
                        user_name = user_data['full_name']
                    else:
                        first_name = user_data.get('first_name', '')
                        last_name = user_data.get('last_name', '')
                        user_name = f"{first_name} {last_name}".strip()
                        if not user_name:
                            user_name = user_data.get('username', 'Unknown User')
                    
                    date_obj = version_data.get('date')
                    date_str = date_obj.strftime('%Y-%m-%d %H:%M') if date_obj else 'N/A'
                    comment = version_data.get('comment', '')

                    version_item = QtWidgets.QTreeWidgetItem([
                        version_display_name,
                        "",  # Placeholder for Type column
                        version_number,
                        user_name,
                        date_str,
                        comment[:50] + ('...' if len(comment) > 50 else '')
                    ])
                    version_item.setData(0, ASSET_VERSION_ITEM_ID_ROLE, version_data['id'])
                    version_item.setData(0, ASSET_VERSION_ITEM_TYPE_ROLE, 'AssetVersion')
                    asset_item.addChild(version_item)

                # Expand the asset to show versions
                asset_item.setExpanded(True)
                
                logger.info(f"[OK] Loaded {len(versions)} versions for asset {asset_id}")
                self.update_status(f"Loaded {len(versions)} versions for asset")

            except Exception as e:
                logger.error(f"Failed to load versions for asset {asset_id}: {str(e)}")
                self.update_status(f"Error loading versions: {str(e)}")
            
        def on_asset_item_expanded(self, item):
            """Handle asset item expansion to lazy-load versions."""
            try:
                item_type = item.data(0, ASSET_VERSION_ITEM_TYPE_ROLE)
                asset_id = item.data(0, ASSET_VERSION_ITEM_ID_ROLE)

                if item_type == 'Asset' and asset_id:
                    logger.info(f"Asset item expanded: ID {asset_id}. Triggering version loading.")
                    self.load_versions_for_asset(item, asset_id)

            except Exception as e:
                logger.error(f"Error in on_asset_item_expanded: {str(e)}")

        def on_asset_version_selection_changed(self):
            """Handle asset version tree selection changes (wrapper for itemSelectionChanged signal)"""
            current_item = self.asset_version_tree.currentItem()
            if current_item:
                self.on_asset_version_selected(current_item, 0)

        def on_asset_version_selected(self, item, column, force_refresh_components=False):
            """Handle asset version selection

            Args:
                item: Selected tree item
                column: Column index (unused)
                force_refresh_components: If True, refresh component_locations to get fresh paths
                    (e.g., after transfer). Used when restoring selection after refresh.
            """
            try:
                item_type = item.data(0, ASSET_VERSION_ITEM_TYPE_ROLE)
                version_id = item.data(0, ASSET_VERSION_ITEM_ID_ROLE)
                
                self.component_list.clear()
                
                if version_id and item_type in ['Asset', 'AssetVersion']:
                    self.right_pane_selected_id_label.setText(str(version_id))
                else:
                    self.right_pane_selected_id_label.setText("N/A")

                if item_type == 'AssetVersion' and version_id:
                    logger.info(f"AssetVersion selected: ID {version_id}. Loading components... (force_refresh={force_refresh_components})")
                    self.load_components_for_version(version_id, force_refresh=force_refresh_components)
                    
                    # Update metadata display for AssetVersion
                    asset_version_data = {
                        'id': version_id,
                        'version': item.text(1) if item.columnCount() > 1 else 'N/A',
                        'comment': item.text(4) if item.columnCount() > 4 else 'N/A',
                        'date': item.text(3) if item.columnCount() > 3 else 'N/A',
                        'user': {'first_name': item.text(2) if item.columnCount() > 2 else 'Unknown', 'last_name': ''}
                    }
                    # Add parent asset info if available
                    parent_asset_item = item.parent()
                    if parent_asset_item:
                        asset_version_data['asset'] = {'name': parent_asset_item.text(0)}
                    
                    self.update_metadata_display(asset_version_data, 'AssetVersion')
                    
                elif item_type == 'Asset' and version_id:
                    logger.info(f"Asset selected: ID {version_id}")
                    
                    # NEW LAZY LOADING: Load versions for this asset when selected
                    self.load_versions_for_asset(item, version_id)
                    
                    # Update metadata display for Asset
                    asset_data = {
                        'id': version_id,
                        'name': item.text(0),
                        'asset_type': item.text(1) if item.columnCount() > 1 else 'Asset'
                    }
                    self.update_metadata_display(asset_data, 'Asset')
                
                self._update_button_states()

            except Exception as e:
                logger.error(f"Error in on_asset_version_selected: {str(e)}")
                self.update_status(f"Error processing selection: {str(e)}")

        def load_components_for_version(self, version_id, force_refresh=False):
            """Load components for selected version
            
            Args:
                version_id: Version ID to load components for
                force_refresh: If True, refresh component_locations to get fresh paths (e.g., after transfer)
            """
            import time as time_module
            components_start_time = time_module.time()
            
            try:
                logger.info(f"[COMPONENTS] Loading for version {version_id[:8] if version_id else 'N/A'}... force_refresh={force_refresh} @ {time_module.strftime('%H:%M:%S', time_module.localtime(components_start_time))}")
                api_start = time_module.time()
                components = self.api.get_components_with_paths_for_version(version_id, force_refresh=force_refresh)
                api_ms = (time_module.time() - api_start) * 1000
                if not components:
                    self.component_list.addItem("No components found.")
                    self.update_status("No components for selected version.")
                    return

                # Sort components by name for better UX
                components = sorted(components, key=lambda x: x.get('name', '').lower())

                self.component_list.clear()
                
                for comp_data in components:
                    display_name = comp_data.get('display_name', comp_data.get('name', 'Unknown'))
                    list_item = QtWidgets.QListWidgetItem(display_name)
                    
                    stored_data = {
                        'id': comp_data.get('id'),
                        'path': comp_data.get('path', 'N/A'),
                        'name': comp_data.get('name'),
                        'type': comp_data.get('file_type', ''),
                        'locations': comp_data.get('locations', []) # Pass locations to widget data
                    }
                    list_item.setData(QtCore.Qt.UserRole, stored_data)
                    self.component_list.addItem(list_item)
                
                components_end_time = time_module.time()
                components_time = components_end_time - components_start_time
                
                self.update_status(f"Components loaded for version ID: {version_id}")
                logger.info(f"[COMPONENTS] Loaded {len(components)} components in {components_time*1000:.0f}ms (API: {api_ms:.0f}ms, force_refresh={force_refresh}) @ {time_module.strftime('%H:%M:%S', time_module.localtime(components_end_time))}")

                # Automatically set "From" location
                comp_locations = stored_data.get('locations', [])
                if comp_locations:
                    # Find first component location that is in our list
                    for i in range(self.from_location_combo.count()):
                        loc_name_in_combo = self.from_location_combo.itemText(i)
                        if loc_name_in_combo in comp_locations:
                            self.from_location_combo.setCurrentIndex(i)
                            logger.info(f"Automatically set 'From' location to '{loc_name_in_combo}'")
                            break
                
                self._update_button_states()
            except Exception as e:
                logger.error(f"Error in component selection: {e}")
                self._update_button_states()
            
        def on_component_list_item_selected(self, list_item):
            """Handle component selection"""
            try:
                stored_data = list_item.data(QtCore.Qt.UserRole)
                if stored_data:
                    component_id = stored_data.get('id')
                    component_path = stored_data.get('path', 'N/A')
                    
                    self.right_pane_selected_id_label.setText(str(component_id) if component_id else "N/A")
                    self.right_pane_selected_path_label.setText(str(component_path))
                    
                    logger.info(f"Component selected: ID {component_id}, Path: {component_path}")
                    
                    # Update metadata display for Component
                    component_data = {
                        'id': component_id,
                        'name': stored_data.get('name', 'N/A'),
                        'type': stored_data.get('type', 'N/A'),
                        'path': component_path,
                        'locations': stored_data.get('locations', []) # Add locations for display
                    }
                    self.update_metadata_display(component_data, 'Component')
                    
                self._update_button_states()
            except Exception as e:
                logger.error(f"Error in component selection: {e}")
                self._update_button_states()
        
        def on_component_list_selection_changed(self):
            """Qt signal wrapper to call item-based handler with current item."""
            current = self.component_list.currentItem()
            if current is not None:
                self.on_component_list_item_selected(current)
            
        def on_copy_id_button_clicked(self):
            """Copy selected item ID to clipboard"""
            logger.info("[REFRESH] Copy ID button clicked!")
            try:
                current_item = self.task_tree.currentItem()
                if not current_item:
                    logger.warning("No item selected in task tree")
                    self.update_status("No item selected to copy ID.")
                    return

                item_id = current_item.data(0, ITEM_ID_ROLE)
                item_name = current_item.data(0, ITEM_NAME_ROLE)
                item_type = current_item.data(0, ITEM_TYPE_ROLE)

                logger.info(f"Task tree selection: id={item_id}, name={item_name}, type={item_type}")

                if item_id:
                    clipboard = QtWidgets.QApplication.clipboard()
                    clipboard.setText(str(item_id))
                    logger.info(f"[OK] Copied ID {item_id} (Type: {item_type}, Name: '{item_name}') to clipboard.")
                    self.update_status(f"ID '{item_id}' for {item_type} '{item_name}' copied to clipboard.")
                else:
                    logger.warning("Selected item has no ID")
                    self.update_status("Selected item has no ID to copy.")
            except Exception as e:
                logger.error(f"Failed to copy ID: {str(e)}")
                self.update_status(f"Error copying ID: {str(e)}")
            
        def on_set_task_button_clicked(self):
            """Set FTRACK_CONTEXTID from selected task and create scene vars FTRACK_CONTEXTID/FTRACK_TASK"""
            try:
                current_item = self.task_tree.currentItem()
                if not current_item:
                    self.update_status("No item selected.")
                    return

                item_type = current_item.data(0, ITEM_TYPE_ROLE)
                item_id = current_item.data(0, ITEM_ID_ROLE)
                item_name = current_item.data(0, ITEM_NAME_ROLE)

                if item_type == 'Task' and item_id:
                    os.environ['FTRACK_CONTEXTID'] = str(item_id)
                    logger.info(f"FTRACK_CONTEXTID set to {item_id} for task '{item_name}'")

                    # Also create human-readable task label and,
                    # if Houdini is available, save it to global scene
                    # variables through dcc layer.
                    if HOUDINI_AVAILABLE:
                        try:
                            project_name = "UnknownProject"
                            parent_name = "UnknownParent"
                            task_name = item_name or "UnknownTask"

                            # Try to fetch Task entity to get project/parent names
                            entity = None
                            session = getattr(self.api, "session", None)
                            if session:
                                try:
                                    entity = session.get('Task', str(item_id))
                                except Exception:
                                    entity = None
                                if entity is None:
                                    try:
                                        entity = session.get('TypedContext', str(item_id))
                                    except Exception:
                                        entity = None
                            if entity:
                                try:
                                    proj = entity.get('project')
                                    if proj:
                                        project_name = proj.get('name', project_name)
                                except Exception:
                                    pass
                                try:
                                    par = entity.get('parent')
                                    if par:
                                        parent_name = par.get('name', parent_name)
                                except Exception:
                                    pass

                            # Compose task label in requested format
                            task_label = f"project: {project_name}   parent: {parent_name}   task: {task_name}"
                            set_global_task_vars(str(item_id), task_label)
                            logger.info(
                                "Set scene vars via dcc.houdini: FTRACK_CONTEXTID=%s, FTRACK_TASK='%s'",
                                item_id,
                                task_label,
                            )
                        except Exception as var_e:
                            logger.warning(f"Failed to set Houdini scene variables: {var_e}")

                    self.update_status(f"FTRACK_CONTEXTID set to: {item_id} (Task: '{item_name}')")
                else:
                    self.update_status("Please select a valid Task to set context.")
            
            except Exception as e:
                logger.error(f"Failed to set FTRACK_CONTEXTID: {str(e)}")
                self.update_status(f"Error setting context: {str(e)}")

        def on_scene_setup_button_clicked(self):
            """Set task context and, if possible, configure scene FPS/frame range from parent Shot attributes."""
            try:
                current_item = self.task_tree.currentItem()
                if not current_item:
                    self.update_status("No item selected.")
                    return

                item_type = current_item.data(0, ITEM_TYPE_ROLE)
                item_id = current_item.data(0, ITEM_ID_ROLE)
                item_name = current_item.data(0, ITEM_NAME_ROLE)

                if item_type != 'Task' or not item_id:
                    self.update_status("Please select a valid Task for Scene Setup.")
                    return

                # 1) Always set task context exactly as the regular Set Task button does
                self.on_set_task_button_clicked()

                # 2) If Ftrack session is not available, we can only set context
                session = getattr(self.api, "session", None)
                if not session:
                    logger.warning("Scene Setup: Ftrack session not available; only task context was set.")
                    return

                # Resolve Task/TypedContext entity for the selected task
                entity = None
                try:
                    entity = session.get('Task', str(item_id))
                except Exception:
                    entity = None
                if entity is None:
                    try:
                        entity = session.get('TypedContext', str(item_id))
                    except Exception:
                        entity = None

                if not entity:
                    logger.warning("Scene Setup: could not resolve Task entity; skipping frame setup.")
                    return

                parent = entity.get('parent')
                shot_id = None
                if parent and parent.get('id'):
                    shot_id = parent['id']

                if not shot_id:
                    logger.info("Scene Setup: task has no parent with ID; skipping frame setup.")
                    return

                # Fetch shot custom attributes (fstart, fend, handles, preroll, fps)
                shot_info = self.api.get_shot_custom_attributes_on_demand(shot_id)
                if not shot_info:
                    logger.info("Scene Setup: parent has no custom frame attributes; only task context was set.")
                    return

                keys_of_interest = ['fstart', 'fend', 'handles', 'preroll', 'fps']
                if not any(k in shot_info for k in keys_of_interest):
                    logger.info("Scene Setup: no fstart/fend/handles/preroll/fps on parent; only task context was set.")
                    return

                # 2a) Collect scene_setup dict without direct hou calls
                workdir = os.environ.get("FTRACK_WORKDIR", "")

                project_name = ""
                try:
                    proj = entity.get("project")
                    if proj:
                        project_name = proj.get("name", "") or ""
                except Exception:
                    project_name = ""

                parent_name = parent.get("name", "") if parent else ""
                task_name = item_name or ""

                suggested_scene_name = f"{project_name}_{task_name}".strip("_") or "scene"
                suggested_scene_name += ".hip"

                suggested_scene_path = ""
                if workdir:
                    suggested_scene_path = os.path.join(
                        workdir,
                        project_name or "project",
                        parent_name or "context",
                        task_name or "task",
                        suggested_scene_name,
                    )

                fps_val = shot_info.get("fps")
                fps_f = None
                try:
                    if fps_val not in (None, "", [], {}):
                        fps_f = float(fps_val)
                        if fps_f <= 0:
                            fps_f = None
                except Exception:
                    fps_f = None

                frame_range = None
                try:
                    fstart = shot_info.get("fstart")
                    fend = shot_info.get("fend")
                    if fstart not in (None, "", [], {}) and fend not in (None, "", [], {}):
                        fstart_i = int(round(float(fstart)))
                        fend_i = int(round(float(fend)))
                        handles = shot_info.get("handles", 0) or 0
                        preroll = shot_info.get("preroll", 0) or 0
                        try:
                            handles_i = int(round(float(handles)))
                        except Exception:
                            handles_i = 0
                        try:
                            preroll_i = int(round(float(preroll)))
                        except Exception:
                            preroll_i = 0

                        start = fstart_i - handles_i - preroll_i
                        end = fend_i + handles_i
                        frame_range = {"start": start, "end": end}
                except Exception as calc_e:
                    logger.warning(
                        "Scene Setup: failed to calculate frame range from shot info: %s",
                        calc_e,
                    )

                scene_setup = {
                    "task_id": str(item_id),
                    "task_name": task_name,
                    "project_name": project_name,
                    "parent_name": parent_name,
                    "shot_id": shot_id,
                    "shot_name": parent_name,
                    "shot_info": shot_info,
                    "fps": fps_f,
                    "frame_range": frame_range,
                    "workdir": workdir,
                    "suggested_scene_name": suggested_scene_name,
                    "suggested_scene_path": suggested_scene_path,
                }

                # DCC layer itself decides how to apply these settings (Houdini or no-op).
                apply_scene_setup(scene_setup)

                summary = f"Scene Setup prepared for Task '{task_name}'"
                if fps_f:
                    summary += f", fps={fps_f}"
                if frame_range:
                    summary += f", range={frame_range['start']}-{frame_range['end']}"
                if suggested_scene_path:
                    summary += f", suggested path: {suggested_scene_path}"

                self.update_status(summary)

            except Exception as e:
                logger.error(f"Scene Setup failed: {e}", exc_info=True)
                self.update_status(f"Scene Setup error: {e}")
            
        def on_set_task_on_node_clicked(self):
            """Set task_Id parameter on selected nodes using names from config."""
            try:
                current_item = self.task_tree.currentItem()
                if not current_item:
                    self.update_status("No item selected.")
                    return

                item_type = current_item.data(0, ITEM_TYPE_ROLE)
                item_id = current_item.data(0, ITEM_ID_ROLE)
                item_name = current_item.data(0, ITEM_NAME_ROLE)

                if item_type != 'Task' or not item_id:
                    self.update_status("Please select a valid Task to set on nodes.")
                    return

                task_param_names = self.hda_param_config.get('task_id', ['task_Id'])
                
                success_count, failed_count = set_task_id_on_selected_nodes(
                    str(item_id), task_param_names
                )
                
                if success_count > 0:
                    status_msg = f"Set task ID on {success_count} node(s)"
                    if failed_count > 0:
                        status_msg += f" ({failed_count} nodes skipped)"
                    self.update_status(status_msg)
                else:
                    self.update_status(f"No nodes found with a valid task parameter.")
                
            except Exception as e:
                logger.error(f"Failed to set task_Id on nodes: {str(e)}")
                self.update_status(f"Error setting task_Id: {str(e)}")

        def on_set_hda_params_clicked(self):
            """Set full parameters on publish nodes: all p_* parameters (except task) and components.
            
            If Asset or AssetVersion is selected, sets:
            - All p_* parameters (p_project, p_parent, p_asset_id, p_asset_name, p_asset_type)
            - components count from asset version metadata (excluding snapshot)
            - comp_name and file_path for each component (if components >= 1)
            """
            try:
                current_comp_item = self.component_list.currentItem()
                current_version_item = self.asset_version_tree.currentItem()

                asset_version_id = None
                component_name = None
                component_id = None
                asset_id = None
                asset_name = None
                asset_type = None

                if current_comp_item:
                    component_data = current_comp_item.data(QtCore.Qt.UserRole) or {}
                    component_name = component_data.get('name')
                    component_id = component_data.get('id')

                # Get AssetVersion information
                if current_version_item and current_version_item.data(0, ASSET_VERSION_ITEM_TYPE_ROLE) == 'AssetVersion':
                    asset_version_id = current_version_item.data(0, ASSET_VERSION_ITEM_ID_ROLE)
                    # Get parent Asset
                    asset_item = current_version_item.parent()
                    if asset_item:
                        asset_id = asset_item.data(0, ASSET_VERSION_ITEM_ID_ROLE)
                        asset_name = asset_item.text(0)
                        asset_type = asset_item.text(1)  # Type is displayed in second column
                elif current_version_item and current_version_item.data(0, ASSET_VERSION_ITEM_TYPE_ROLE) == 'Asset':
                    # If Asset itself is selected, get latest version
                    asset_id = current_version_item.data(0, ASSET_VERSION_ITEM_ID_ROLE)
                    asset_name = current_version_item.text(0)
                    asset_type = current_version_item.text(1)  # Type is displayed in second column
                    
                    # Get latest asset version for this asset
                    try:
                        if self.api and self.api.session:
                            latest_version = self.api.session.query(
                                f'AssetVersion where asset.id is "{asset_id}" order by version desc'
                            ).first()
                            if latest_version:
                                asset_version_id = latest_version['id']
                    except Exception as e:
                        logger.warning(f"Failed to get latest version for asset {asset_id}: {e}")
                
                # If we have asset_id (from Asset or AssetVersion), try full params on publish nodes first
                # Read component list from asset.metadata (not from versions) to avoid heavy queries
                # Project/parent will be read from asset path, task parameters will be cleared
                publish_success = 0
                if asset_id and asset_name and HOUDINI_AVAILABLE and self.api and self.api.session:
                    publish_success, nodes_without_parms = set_full_params_on_publish_nodes(
                        session=self.api.session,
                        asset_id=str(asset_id),
                        asset_name=asset_name,
                        asset_type=asset_type or '',
                    )
                    
                    if publish_success > 0:
                        status_msg = f"Set full params on {publish_success} publish node(s)."
                        if nodes_without_parms > 0:
                            status_msg += f" ({nodes_without_parms} nodes skipped)."
                        self.update_status(status_msg)
                        return
                    # If no publish nodes found, fall through to try finput/other HDA nodes
                
                # Fallback to original behavior for component selection (works with finput and other HDAs)
                logger.debug(f"[SetFullParams] Fallback: asset_version_id={asset_version_id}, component_id={component_id}, asset_id={asset_id}")
                if not asset_version_id and not component_id and not asset_id:
                    self.update_status("Please select an Asset, Asset Version or a Component.")
                    return
                
                logger.debug(f"[SetFullParams] Calling set_hda_params_on_selected_nodes with config: {self.hda_param_config}")
                success_count, nodes_without_parms = set_hda_params_on_selected_nodes(
                    asset_version_id=str(asset_version_id) if asset_version_id else None,
                    component_name=component_name,
                    component_id=str(component_id) if component_id else None,
                    asset_id=str(asset_id) if asset_id else None,
                    asset_name=asset_name,
                    asset_type=asset_type,
                    hda_param_config=self.hda_param_config,
                )

                if success_count > 0:
                    status_msg = f"Set params on {success_count} node(s)."
                    if nodes_without_parms > 0:
                        status_msg += f" ({nodes_without_parms} nodes skipped)."
                    self.update_status(status_msg)
                else:
                    self.update_status(f"No nodes found with required parameters from config.")

            except Exception as e:
                logger.error(f"Failed to set HDA params: {str(e)}", exc_info=True)
                self.update_status(f"Error setting HDA params: {str(e)}")

        def on_copy_selected_id_button_clicked(self):
            """Copy selected component or asset version ID"""
            logger.info("[REFRESH] Copy Selected ID button clicked!")
            try:
                # Try component first
                current_comp_item = self.component_list.currentItem()
                if current_comp_item:
                    stored_data = current_comp_item.data(QtCore.Qt.UserRole)
                    logger.info(f"Component data: {stored_data}")
                    if stored_data and stored_data.get('id'):
                        item_id = stored_data.get('id')
                        clipboard = QtWidgets.QApplication.clipboard()
                        clipboard.setText(str(item_id))
                        logger.info(f"[OK] Copied component ID '{item_id}' to clipboard.")
                        self.update_status(f"Component ID '{item_id}' copied.")
                        return

                # Try asset version
                current_asset_item = self.asset_version_tree.currentItem()
                if current_asset_item:
                    item_id = current_asset_item.data(0, ASSET_VERSION_ITEM_ID_ROLE)
                    item_type = current_asset_item.data(0, ASSET_VERSION_ITEM_TYPE_ROLE)
                    logger.info(f"Asset/Version data: id={item_id}, type={item_type}")
                    if item_id:
                        clipboard = QtWidgets.QApplication.clipboard()
                        clipboard.setText(str(item_id))
                        logger.info(f"[OK] Copied asset/version ID '{item_id}' to clipboard.")
                        self.update_status(f"Asset/Version ID '{item_id}' copied.")
                        return
                
                logger.warning("No item with ID selected to copy")
                self.update_status("No item with ID selected to copy.")

            except Exception as e:
                logger.error(f"Failed to copy selected ID: {str(e)}")
                self.update_status(f"Error copying ID: {str(e)}")
            
        def on_load_snapshot_button_clicked(self):
            """Load snapshot component if available"""
            if not HOUDINI_AVAILABLE:
                self.update_status("Houdini not available for snapshot loading.")
                return
                
            try:
                current_item = self.component_list.currentItem()
                if not current_item:
                    self.update_status("No component selected to load.")
                    return

                stored_data = current_item.data(QtCore.Qt.UserRole)
                if not stored_data:
                    self.update_status("Selected component has no data.")
                    return

                comp_name = stored_data.get('name', '').lower()
                comp_file_type = stored_data.get('type', '').lower()
                comp_path = stored_data.get('path', 'N/A')

                if (comp_name == 'snapshot' and 
                    comp_file_type == '.hip' and 
                    comp_path not in ["N/A", "N/A (not in location)", "N/A (error)"] and
                    os.path.exists(comp_path)):
                    
                    og_file_path = hou.hipFile.path()
                    logger.info(f"Attempting to load snapshot: {comp_path}")
                    self.update_status(f"Loading snapshot: {comp_path}...")
                    
                    hou.hipFile.load(comp_path, suppress_save_prompt=True)
                    hou.hipFile.setName(og_file_path)
                    
                    logger.info(f"Snapshot '{comp_path}' loaded.")
                    self.update_status(f"Snapshot '{os.path.basename(comp_path)}' loaded.")
                else:
                    self.update_status("Selected component is not a loadable .hip snapshot.")

            except Exception as e:
                logger.error(f"Failed to load snapshot: {str(e)}")
                self.update_status(f"Error loading snapshot: {str(e)}")

        def _refresh_full_tree_with_state(self):
            """Full refresh preserving selection and expansion state"""
            self.update_status("Full tree refresh...")
            self.api.clear_cache()
            self.load_tree()
        
        def _refresh_branch(self, item):
            """Refresh only the selected branch and its children"""
            try:
                item_type = item.data(0, ITEM_TYPE_ROLE)
                item_id = item.data(0, ITEM_ID_ROLE)
                item_name = item.text(0)
                
                logger.info(f"Refreshing branch: {item_type} '{item_name}' (ID: {item_id})")
                
                # Clear cache for this specific branch
                if item_type in ['Shot', 'AssetBuild', 'Sequence']:
                    self.api.clear_cache_for_entity(item_id)
                else:
                    self.api.clear_cache()
                
                # Save current expansion and selection state
                was_expanded = item.isExpanded()
                
                # Remove all children
                # OPTIMIZATION: Disable UI updates and remove from end (much faster)
                tree_widget = item.treeWidget()
                if tree_widget:
                    tree_widget.setUpdatesEnabled(False)
                try:
                    # Remove from end (faster - no index recalculation)
                    while item.childCount() > 0:
                        last_idx = item.childCount() - 1
                        item.takeChild(last_idx)
                finally:
                    if tree_widget:
                        tree_widget.setUpdatesEnabled(True)
                
                # Mark as unpopulated to force reload
                item.setData(0, ITEM_POPULATED_ROLE, False)
                
                # If item was expanded, immediately reload its content
                if was_expanded:
                    # Directly populate children instead of using dummy node
                    self.fetch_and_populate_children(item, item_id, item_type)
                    item.setData(0, ITEM_POPULATED_ROLE, True)
                    item.setExpanded(True)
                else:
                    # Add dummy child to make expandable
                    item.addChild(QtWidgets.QTreeWidgetItem([DUMMY_NODE_TEXT]))
                
                # Handle right pane refresh for Shot/AssetBuild
                if self.current_loaded_entity_id == item_id:
                    self.current_loaded_entity_id = None
                    self.clear_asset_version_tree()
                    
                    # Schedule right pane reload after tree refresh is complete
                    if item_type in ['Shot', 'AssetBuild', 'Sequence']:
                        QtCore.QTimer.singleShot(200, lambda: self.load_asset_versions_for_entity(item_id))
                
                self.update_status(f"Refreshed branch: {item_type} '{item_name}'")
                logger.info(f"Branch refresh completed for {item_type} '{item_name}'")
                
            except Exception as e:
                logger.error(f"Error refreshing branch: {e}")
                self.update_status(f"Error refreshing branch: {str(e)}")
        
        def _refresh_task_and_assets(self, task_item):
            """Special refresh for Task: refresh parent Shot and update right pane assets"""
            try:
                task_id = task_item.data(0, ITEM_ID_ROLE)
                task_name = task_item.text(0)
                
                # Get parent Shot/AssetBuild
                parent_item = task_item.parent()
                if not parent_item:
                    logger.warning("Task has no parent item")
                    return
                
                parent_type = parent_item.data(0, ITEM_TYPE_ROLE)
                parent_id = parent_item.data(0, ITEM_ID_ROLE)
                parent_name = parent_item.text(0)
                
                logger.info(f"Refreshing task '{task_name}' and parent '{parent_name}'")
                
                # Clear cache for parent entity
                self.api.clear_cache_for_entity(parent_id)
                
                # Save current task selection state
                task_was_selected = (self.task_tree.currentItem() == task_item)
                
                # Refresh parent (Shot/AssetBuild) which will reload all its tasks
                self._refresh_branch(parent_item)
                
                # Restore task selection after parent refresh
                if task_was_selected:
                    QtCore.QTimer.singleShot(100, lambda: self._restore_task_selection(parent_item, task_id))
                
                # Force refresh right pane assets if this context was loaded
                if self.current_loaded_entity_id == parent_id:
                    QtCore.QTimer.singleShot(150, lambda: self.load_asset_versions_for_entity(parent_id))
                
                self.update_status(f"Refreshed Task '{task_name}' and parent '{parent_name}' with assets")
                logger.info(f"Task refresh completed for '{task_name}' under '{parent_name}'")
                
            except Exception as e:
                logger.error(f"Error refreshing task and assets: {e}")
                self.update_status(f"Error refreshing task: {str(e)}")
        
        def _restore_task_selection(self, parent_item, task_id):
            """Find and select task by ID after parent refresh"""
            try:
                for i in range(parent_item.childCount()):
                    child = parent_item.child(i)
                    if child.data(0, ITEM_ID_ROLE) == task_id:
                        self.task_tree.setCurrentItem(child)
                        self.on_item_selected(child, 0)
                        logger.info(f"Restored task selection: {child.text(0)}")
                        break
            except Exception as e:
                logger.error(f"Error restoring task selection: {e}")
        
        def _refresh_asset_versions(self, asset_item, refresh_start_time=None):
            """Special refresh for Asset: refresh only its versions while preserving selection"""
            import time as time_module
            if refresh_start_time is None:
                refresh_start_time = time_module.time()
            
            try:
                asset_id = asset_item.data(0, ASSET_VERSION_ITEM_ID_ROLE)
                asset_name = asset_item.text(0)
                
                logger.info(f"[REFRESH ASSET] Starting refresh for Asset '{asset_name}' (ID: {asset_id[:8] if asset_id else 'N/A'}...) at {time_module.strftime('%H:%M:%S', time_module.localtime(refresh_start_time))}.{int((refresh_start_time % 1) * 1000):03d}")
                
                step_times = {}
                step_start = time_module.time()
                
                if not asset_id:
                    logger.warning("Asset item has no ID")
                    return
                
                logger.info(f"Refreshing asset versions for '{asset_name}' (ID: {asset_id})")
                
                # Clear cache for this specific asset
                cache_clear_start = time_module.time()
                if asset_id in self.api._asset_versions_cache:
                    del self.api._asset_versions_cache[asset_id]
                step_times['cache_clear'] = time_module.time() - cache_clear_start
                
                # Force refresh of asset metadata from server
                metadata_start = time_module.time()
                session = getattr(self.api, "session", None)
                if session:
                    try:
                        asset_entity = session.get('Asset', str(asset_id))
                        if asset_entity:
                            # Force reload metadata from server
                            session.populate([asset_entity], 'metadata')
                            logger.debug(f"Refreshed metadata for Asset {asset_id}")
                    except Exception as e:
                        logger.warning(f"Failed to refresh Asset metadata: {e}")
                step_times['metadata_refresh'] = time_module.time() - metadata_start
                
                # Save expansion state and current selections
                ui_state_start = time_module.time()
                t1 = time_module.time()
                was_expanded = asset_item.isExpanded()
                logger.info(f"[UI STATE] isExpanded() took {(time_module.time() - t1)*1000:.1f}ms")
                
                selected_asset_version_id = None
                had_components_loaded = False  # True if component_list had items (need force_refresh on restore)
                
                # Check if any version under this asset is currently selected
                t2 = time_module.time()
                current_version_item = self.asset_version_tree.currentItem()
                logger.info(f"[UI STATE] currentItem() took {(time_module.time() - t2)*1000:.1f}ms")
                
                t3 = time_module.time()
                if current_version_item and current_version_item.parent() == asset_item:
                    selected_asset_version_id = current_version_item.data(0, ASSET_VERSION_ITEM_ID_ROLE)
                    had_components_loaded = self.component_list.count() > 0
                logger.info(f"[UI STATE] parent check + data() took {(time_module.time() - t3)*1000:.1f}ms")
                
                # Remove all version children from this asset
                # OPTIMIZATION: Disable UI updates and remove from end (much faster)
                t4 = time_module.time()
                child_count = asset_item.childCount()
                logger.info(f"[UI STATE] childCount() = {child_count}, took {(time_module.time() - t4)*1000:.1f}ms")
                
                t5 = time_module.time()
                # Disable UI updates to prevent repainting during removal
                self.asset_version_tree.setUpdatesEnabled(False)
                try:
                    removed = 0
                    # Remove from end (faster - no index recalculation)
                    while asset_item.childCount() > 0:
                        last_idx = asset_item.childCount() - 1
                        asset_item.takeChild(last_idx)
                        removed += 1
                        if removed % 10 == 0:
                            logger.info(f"[UI STATE] Removed {removed} children, elapsed: {(time_module.time() - t5)*1000:.1f}ms")
                    logger.info(f"[UI STATE] takeChild() loop removed {removed} children, took {(time_module.time() - t5)*1000:.1f}ms")
                finally:
                    # Re-enable UI updates
                    self.asset_version_tree.setUpdatesEnabled(True)
                
                step_times['ui_state'] = time_module.time() - ui_state_start
                logger.info(f"[UI STATE] Total UI state save/clear took {step_times['ui_state']*1000:.1f}ms")
                
                # Reload versions for this asset (force refresh to get fresh metadata)
                # Use provided refresh_start_time if available (from button click), otherwise use current time
                refresh_start = refresh_start_time if refresh_start_time else time_module.time()
                api_call_start = time_module.time()
                
                # If a specific version was selected, refresh only that version (much faster)
                # NOTE: Use selected_asset_version_id saved BEFORE takeChild() - after removing children,
                # currentItem()/parent() is invalid so we would never enter this block and miss
                # component_locations refresh (paths would not update after transfer).
                # Component_locations may change after transfer, so we refresh paths for already-loaded components.
                single_version_refresh = False
                current_version_id = selected_asset_version_id
                if current_version_id:
                    # Refresh only the selected version (optimization - ~30x faster)
                    logger.info(f"[OPTIMIZATION] Refreshing only selected version {current_version_id} instead of all versions")
                    refreshed_version = self.api.refresh_single_version(current_version_id)
                    if refreshed_version:
                        single_version_refresh = True
                        # Get versions with force_refresh=True - must not use cache here,
                        # otherwise list "rolls back" (relationship/cache can be stale,
                        # missing new versions). Refresh button must show current state.
                        versions = self.api.get_versions_for_asset(asset_id, force_refresh=True)
                        # Replace the refreshed version in the list (redundant with force_refresh
                        # but keeps refreshed_version in case populate missed something)
                        for i, v in enumerate(versions):
                            if v['id'] == current_version_id:
                                versions[i] = refreshed_version
                                break
                        
                        # NOTE: If components were loaded, force_refresh_components is passed to
                        # _restore_asset_version_selection so on_asset_version_selected loads
                        # with force_refresh=True (fresh component_locations after transfer)
                    else:
                        # Fallback: refresh all versions
                        logger.warning(f"Single version refresh failed, falling back to full refresh")
                        versions = self.api.get_versions_for_asset(asset_id, force_refresh=True)
                else:
                    # No version selected, refresh all versions (to see new versions)
                    versions = self.api.get_versions_for_asset(asset_id, force_refresh=True)
                
                api_call_end = time_module.time()
                api_time = api_call_end - api_call_start
                step_times['api_call'] = api_time
                
                # Log timing breakdown
                logger.info(f"[REFRESH ASSET] Timing breakdown:")
                logger.info(f"  Cache clear: {step_times.get('cache_clear', 0)*1000:.1f}ms")
                logger.info(f"  Metadata refresh: {step_times.get('metadata_refresh', 0)*1000:.1f}ms")
                logger.info(f"  UI state save/clear: {step_times.get('ui_state', 0)*1000:.1f}ms")
                logger.info(f"  API call: {step_times.get('api_call', 0)*1000:.1f}ms")
                
                if single_version_refresh:
                    logger.info(f"[REFRESH TIMING] Single version refresh took {api_time:.3f}s")
                else:
                    logger.info(f"[REFRESH TIMING] Full refresh took {api_time:.3f}s")
                
                # Repopulate asset versions
                ui_start = time_module.time()
                if not versions:
                    asset_item.addChild(QtWidgets.QTreeWidgetItem(["No versions found"]))
                else:
                    for version_data in versions:
                        version_number = str(version_data.get('version', 'N/A'))
                        version_display_name = f"v{version_number}"
                        
                        # --- FIX: Use the same code as in load_versions_for_asset ---
                        user_data = version_data.get('user', {})
                        if user_data.get('full_name'):
                            user_name = user_data['full_name']
                        else:
                            first_name = user_data.get('first_name', '')
                            last_name = user_data.get('last_name', '')
                            user_name = f"{first_name} {last_name}".strip()
                            if not user_name:
                                user_name = user_data.get('username', 'Unknown User')
                        
                        date_obj = version_data.get('date')
                        date_str = date_obj.strftime('%Y-%m-%d %H:%M') if date_obj else 'N/A'
                        comment = version_data.get('comment', '')

                        version_item = QtWidgets.QTreeWidgetItem([
                            version_display_name, 
                            version_number, 
                            user_name, 
                            date_str,
                            comment[:50] + ('...' if len(comment) > 50 else '')
                        ])
                        # --- END OF FIX ---
                        
                        version_item.setData(0, ASSET_VERSION_ITEM_ID_ROLE, version_data['id'])
                        version_item.setData(0, ASSET_VERSION_ITEM_TYPE_ROLE, 'AssetVersion')
                        asset_item.addChild(version_item)
                
                # Restore expansion state
                if was_expanded:
                    asset_item.setExpanded(True)
                
                ui_time = time_module.time() - ui_start
                total_refresh_time = time_module.time() - refresh_start
                logger.info(f"[REFRESH TIMING] UI repopulation took {ui_time:.3f}s, total refresh: {total_refresh_time:.3f}s")
                
                # Restore version selection if needed (force_refresh_components when we had
                # components loaded - to get fresh paths/locations after transfer)
                if selected_asset_version_id:
                    QtCore.QTimer.singleShot(50, lambda: self._restore_asset_version_selection(
                        asset_item, selected_asset_version_id, force_refresh_components=had_components_loaded))
                
                refresh_end_time = time_module.time()
                total_refresh_time = refresh_end_time - refresh_start_time
                
                self.update_status(f"Refreshed versions for asset '{asset_name}'")
                logger.info(f"[REFRESH ASSET] Asset versions refresh completed for '{asset_name}' at {time_module.strftime('%H:%M:%S', time_module.localtime(refresh_end_time))}.{int((refresh_end_time % 1) * 1000):03d}")
                logger.info(f"[REFRESH ASSET] TOTAL: {total_refresh_time:.3f}s ({total_refresh_time*1000:.0f}ms) | cache_clear: {step_times.get('cache_clear', 0)*1000:.0f}ms, metadata: {step_times.get('metadata_refresh', 0)*1000:.0f}ms, ui_state: {step_times.get('ui_state', 0)*1000:.0f}ms, api: {step_times.get('api_call', 0)*1000:.0f}ms, ui_repop: {ui_time*1000:.0f}ms")
                
            except Exception as e:
                refresh_end_time = time_module.time()
                total_refresh_time = refresh_end_time - refresh_start_time
                logger.error(f"[REFRESH ASSET] Error refreshing asset versions after {total_refresh_time:.3f}s: {e}")
                self.update_status(f"Error refreshing asset versions: {str(e)}")
        
        def _restore_asset_version_selection(self, asset_item, version_id, force_refresh_components=False):
            """Find and select asset version by ID after parent refresh

            Args:
                asset_item: Parent Asset tree item
                version_id: AssetVersion ID to restore selection for
                force_refresh_components: If True, load components with force_refresh to get
                    fresh component_locations (paths) after transfer. Use when components
                    were loaded before refresh (user had version with components selected).
            """
            import time as time_module
            restore_start = time_module.time()
            try:
                for i in range(asset_item.childCount()):
                    child = asset_item.child(i)
                    if child.data(0, ASSET_VERSION_ITEM_ID_ROLE) == version_id:
                        self.asset_version_tree.setCurrentItem(child)
                        sel_start = time_module.time()
                        self.on_asset_version_selected(child, 0, force_refresh_components=force_refresh_components)
                        sel_ms = (time_module.time() - sel_start) * 1000
                        restore_ms = (time_module.time() - restore_start) * 1000
                        logger.info(f"[REFRESH RESTORE] Restored selection '{child.text(0)}' in {restore_ms:.0f}ms (on_asset_version_selected: {sel_ms:.0f}ms, force_refresh_components={force_refresh_components})")
                        break
            except Exception as e:
                logger.error(f"Error restoring asset version selection: {e}")
            
        def _load_hda_param_config(self):
            """Load HDA parameter names from an external YAML config file."""
            self.hda_param_config = {
                # Defaults in case the config is missing - include all common variants
                "task_id": ["task_Id", "task_id", "taskId", "ftrack_task_id"],
                "asset_version_id": ["AssetVersion", "assetversionid", "AssetVersionId", "asset_version_id"],
                "component_name": ["ComponentName", "componentname", "component_name"],
                "component_id": ["componentid", "ComponentId", "component_id"],
                "asset_id": ["asset_id", "assetid", "AssetId"],
                "asset_name": ["asset_name", "assetname", "AssetName"],
                "asset_type": ["Type", "type", "asset_type", "AssetType"],
            }
            try:
                # FIX: Use correct configuration file name
                config_filename = "hda_params_config.yaml"
                # Search for file relative to current file (browser_widget.py)
                config_path = os.path.join(os.path.dirname(__file__), config_filename)
                
                if os.path.exists(config_path):
                    with open(config_path, 'r') as f:
                        config_data = yaml.safe_load(f)
                        if config_data and "hda_parameters" in config_data:
                            self.hda_param_config.update(config_data["hda_parameters"])
                            logger.info(f"[OK] Successfully loaded HDA parameter config from {config_path}")
                            logger.info(f"HDA param config loaded: {self.hda_param_config}")
                        else:
                            logger.warning(f"[WARN] HDA config file '{config_path}' is empty or has wrong format. Using defaults.")
                else:
                    logger.info(f"[INFO] HDA parameter config file not found at '{config_path}'. Using default parameter names.")
            except Exception as e:
                logger.error(f"Failed to load HDA param config: {e}", exc_info=True)
                self.update_status("Error loading HDA config.")

        def on_start_transfer_clicked(self):
            """Handle start transfer button click."""
            logger.info("browser_widget.on_start_transfer_clicked: Transfer button clicked")
            
            # NOTE: TRANSFER_ACTION_AVAILABLE check removed - TransferWorker works independently
            # by publishing mroya.transfer.request events. It does NOT require TransferComponentsPlusAction.

            # --- 1. Collect information from UI ---
            from_location_id = self.from_location_combo.currentData()
            to_location_id = self.to_location_combo.currentData()
            from_location_name = self.from_location_combo.currentText()
            to_location_name = self.to_location_combo.currentText()
            
            selected_components = []
            selection_entities = []  # for ftrack action API
            
            # Determine what is selected: component or version
            current_comp_item = self.component_list.currentItem()
            current_version_item = self.asset_version_tree.currentItem()

            if current_comp_item:
                # If component is selected, take it
                comp_data = current_comp_item.data(QtCore.Qt.UserRole)
                if comp_data and comp_data.get('id'):
                    selected_components.append({
                        'id': comp_data['id'],
                        'name': comp_data.get('name', 'Unknown Component')
                    })
                    selection_entities.append({
                        'entityType': 'Component',
                        'entityId': comp_data['id']
                    })
            elif current_version_item and current_version_item.data(0, ASSET_VERSION_ITEM_TYPE_ROLE) == 'AssetVersion':
                # If version is selected, take all its components
                version_id = current_version_item.data(0, ASSET_VERSION_ITEM_ID_ROLE)
                components_data = self.api.get_components_with_paths_for_version(version_id)
                for comp_data in components_data:
                    selected_components.append({
                        'id': comp_data['id'],
                        'name': comp_data.get('name', 'Unknown Component')
                    })
                # For action API pass the version itself
                selection_entities.append({
                    'entityType': 'assetversion',
                    'entityId': version_id
                })
            
            if not selected_components:
                self.update_status("Please select a component or asset version to transfer.")
                return

            # --- 2. Prepare to launch task ---
            try:
                # FIX: Get current Ftrack user ID
                user = self.api.session.query(f'User where username is "{self.api.session.api_user}"').one()
                user_id = user['id']

                # --- 3. Launch task in separate thread ---
            # We pass only IDs to the "worker" so it creates all objects in its own thread.
            # Local TransferStatusDialog window is no longer raised -- visualization
            # of queue now lives in ftrack Connect (Mroya Transfer Manager).

            # Determine human-readable name: full path from project root so e.g. "snapshot" is distinguishable
                if len(selected_components) == 1:
                    comp_id = selected_components[0].get('id')
                    if PATH_FROM_PROJECT_AVAILABLE and get_component_display_path and comp_id and self.api and getattr(self.api, 'session', None):
                        component_label = get_component_display_path(self.api.session, str(comp_id)) or selected_components[0].get('name', 'selection')
                    else:
                        component_label = selected_components[0].get('name', 'selection')
                else:
                    component_label = f"{len(selected_components)} components"

                logger.info(
                    "browser_widget.on_start_transfer_clicked: Creating TransferWorker with "
                    "from=%s (%s), to=%s (%s), selection=%d entities, label=%s",
                    from_location_id,
                    from_location_name,
                    to_location_id,
                    to_location_name,
                    len(selection_entities),
                    component_label,
                )

                worker = TransferWorker(
                    selection_entities,
                    from_location_id,
                    to_location_id,
                    user_id,
                    component_label,
                    to_location_name,
                )
                
                # Light signals only for logs / status at bottom of browser.
                worker.signals.job_created.connect(
                    lambda job, comp_name: self.update_status(
                        f"Transfer started for '{comp_name}'. Job: {job.get('id', 'n/a')}"
                    )
                )
                worker.signals.error.connect(
                    lambda error_msg: self.update_status(f"Transfer Error: {error_msg}")
                )
                
                # Start worker in Qt thread pool.
                logger.info("browser_widget.on_start_transfer_clicked: Starting TransferWorker in Qt thread pool...")
                QtCore.QThreadPool.globalInstance().start(worker)

                self.update_status(f"Initiating transfer for {len(selected_components)} component(s)...")
                logger.info("browser_widget.on_start_transfer_clicked: TransferWorker started, waiting for job creation...")

            except Exception as e:
                error_msg = f"Failed to start transfer: {e}"
                logger.error(error_msg, exc_info=True)
                self.update_status(error_msg)
                
        @QtCore.Slot(str)
        def _on_transfer_complete(self, component_id):
            """
            Callback function triggered when a transfer job finishes.
            Refreshes the view for the parent asset version.
            """
            logger.info(f"Received transfer completion signal for component: {component_id}")
            self.update_status(f"Transfer complete for component {component_id}. Refreshing...")

            # Find and update parent asset version
            asset_version_item = self.asset_version_tree.currentItem()
            
            # If version is selected, that's it
            if asset_version_item and asset_version_item.data(0, ASSET_VERSION_ITEM_TYPE_ROLE) == 'AssetVersion':
                parent_asset_item = asset_version_item.parent()
                if parent_asset_item:
                    logger.info(f"Refreshing asset '{parent_asset_item.text(0)}' to show updated component locations.")
                    self._refresh_asset_versions(parent_asset_item)
                    # Restore version selection after update
                    QtCore.QTimer.singleShot(100, lambda: self._restore_asset_version_selection(parent_asset_item, asset_version_item.data(0, ASSET_VERSION_ITEM_ID_ROLE)))
            else:
                logger.warning("Could not determine the asset version to refresh. A manual refresh may be needed.")
                self.update_status("Transfer complete. Please refresh manually if view is not updated.")

        def _process_selection(self, entity_data):
            """Process the selected entity."""
            if not entity_data:
                return

            entity_id = entity_data.get('id')
            entity_type = entity_data.get('type')
            
            # FIX: Ensure parent_data is a dictionary to prevent errors
            parent_data = entity_data.get('parent') if isinstance(entity_data.get('parent'), dict) else {}

            if not entity_id or not entity_type:
                return

            self.logger.info("Processing selection: {} {}".format(entity_type, entity_id))

            if entity_type == 'Task':
                if parent_data:
                    self.logger.info("Task selected, parent context: {} ID {}".format(parent_data.get('type'), parent_data.get('id')))
                
                self.logger.info("Fetching assets specifically for task ID: {}".format(entity_id))
                task_assets = self.api.get_assets_for_task(entity_id)

                # --- CORRECTED CODE BLOCK ---
                # Use the correct widget name: self.asset_version_tree
                self.asset_version_tree.clear()
                self.component_list.clear()
                self.metadata_text.setHtml("<p>Assets filtered by selected task.</p>")
                self.right_pane_selected_id_label.setText("N/A")
                self.right_pane_selected_path_label.setText("N/A")
                self._update_button_states()
                # --- END OF CORRECTION ---

                if not task_assets:
                    self.logger.info("No assets found for this task.")
                    self.update_status("No assets found for this task.")
                    self.asset_version_tree.addTopLevelItem(QtWidgets.QTreeWidgetItem(["No assets found for this task."]))
                else:
                    self.logger.info("Displaying {} assets for task.".format(len(task_assets)))
                    self.update_status(f"Displaying {len(task_assets)} assets for task.")

                    for asset in task_assets:
                        asset_name = asset.get('name', 'Unknown Asset')
                        asset_type_data = asset.get('type', {})
                        asset_type = asset_type_data.get('name', 'N/A') if asset_type_data else 'N/A'
                        asset_id = asset['id']

                        asset_item = QtWidgets.QTreeWidgetItem([asset_name, asset_type])
                        asset_item.setData(0, ASSET_VERSION_ITEM_ID_ROLE, asset_id)
                        asset_item.setData(0, ASSET_VERSION_ITEM_TYPE_ROLE, 'Asset')
                        self.asset_version_tree.addTopLevelItem(asset_item)

                        placeholder_item = QtWidgets.QTreeWidgetItem(["Click to load versions..."])
                        placeholder_item.setData(0, ASSET_VERSION_ITEM_TYPE_ROLE, 'Placeholder')
                        asset_item.addChild(placeholder_item)
                
                # Use a unique context ID for tasks to avoid conflicts with parent selection
                self.current_loaded_entity_id = f"task_{entity_id}"

            else:
                self.logger.info("Entity selected, using as context: {} ID {}".format(entity_type, entity_id))
                if self.current_loaded_entity_id != entity_id:
                    self.load_assets_for_entity(entity_id)
                else:
                    self.logger.info("Assets already loaded for this context.")

            # Set FTRACK_CONTEXTID for Houdini context
            self.set_context_id(entity_id, entity_type, entity_data.get('name'))


# --- Helper classes for background task execution ---

class WorkerSignals(QtCore.QObject):
    """
    Defines the signals available from a running worker thread.
    """
    job_created = QtCore.Signal(dict, str)
    error = QtCore.Signal(str)
    finished = QtCore.Signal()

class TransferWorker(QtCore.QRunnable):
    """
    Worker thread that creates a Job and publishes mroya.transfer.request event.

    Actual data transfer is performed in ftrack Connect process by plugin
    mroya_transfer_manager, which listens to topic="mroya.transfer.request"
    and uses transfer_component_custom() for advanced transfer features
    (multipart S3 upload, resume, pause/stop, parallel sequences).
    
    This worker does NOT require location_integrator or TransferComponentsPlusAction.
    It works independently by publishing events.
    """
    def __init__(
        self,
        selection_entities,
        source_loc_id,
        target_loc_id,
        user_id,
        component_label="selection",
        target_loc_name=None,
    ):
        super(TransferWorker, self).__init__()
        self.selection_entities = selection_entities
        self.source_loc_id = source_loc_id
        self.target_loc_id = target_loc_id
        self.user_id = user_id
        self.component_label = component_label or "selection"
        self.target_loc_name = target_loc_name
        self.signals = WorkerSignals()

    @QtCore.Slot()
    def run(self):
        logger.info("=" * 80)
        logger.info("TransferWorker.run: STARTED in background thread")
        logger.info("TransferWorker.run: selection_entities=%r", self.selection_entities)
        logger.info("TransferWorker.run: from_location_id=%s, to_location_id=%s", self.source_loc_id, self.target_loc_id)
        logger.info("TransferWorker.run: component_label=%s, target_loc_name=%s", self.component_label, self.target_loc_name)
        logger.info("=" * 80)
        
        try:
            if not self.selection_entities:
                raise ValueError("No selection to transfer.")

            import ftrack_api

            logger.info("TransferWorker.run: Creating ftrack_api.Session...")
            
            # Try to use shared session factory (with optimized caching)
            session = None
            try:
                from ..common.session_factory import get_shared_session
                session = get_shared_session()
                if session:
                    logger.info("TransferWorker.run: Using shared session from common factory")
            except ImportError:
                logger.debug("TransferWorker.run: Common session factory not available, creating local session")
            except Exception as e:
                logger.debug(f"TransferWorker.run: Failed to get shared session: {e}")
            
            # Fallback: Create new session
            if not session:
                session = ftrack_api.Session()
                logger.info("TransferWorker.run: Session created successfully")

            # Get location and file size information
            from_location_type = "unknown"
            to_location_type = "unknown"
            total_size = 0
            
            try:
                from_location = session.get("Location", self.source_loc_id)
                to_location = session.get("Location", self.target_loc_id)
                
                # Determine location types (for future transfer optimization)
                def _get_location_type(location):
                    """Determine location type (s3, disk, unknown)."""
                    if not hasattr(location, 'accessor') or not location.accessor:
                        return 'unknown'
                    try:
                        accessor_type = type(location.accessor).__name__
                        accessor_module = type(location.accessor).__module__
                        if 's3' in accessor_module.lower() or 's3' in accessor_type.lower():
                            return 's3'
                        elif 'disk' in accessor_module.lower() or 'disk' in accessor_type.lower():
                            return 'disk'
                    except Exception:
                        pass
                    return 'unknown'
                
                from_location_type = _get_location_type(from_location)
                to_location_type = _get_location_type(to_location)
                
                # Get total size of components
                try:
                    for entity_data in self.selection_entities:
                        entity_type = entity_data.get('entityType', '').lower()
                        entity_id = entity_data.get('entityId')
                        if not entity_id:
                            continue
                        try:
                            if entity_type == 'component':
                                component = session.get('Component', entity_id)
                                total_size += component.get('size', 0) or 0
                            elif entity_type == 'assetversion':
                                version = session.get('AssetVersion', entity_id)
                                components = version.get('components', [])
                                for comp in components:
                                    total_size += comp.get('size', 0) or 0
                        except Exception:
                            pass
                except Exception as e:
                    logger.warning("TransferWorker.run: Failed to get component sizes: %s", e)
            except Exception as e:
                logger.warning("TransferWorker.run: Failed to get location info: %s", e)

            # Create Job immediately so it can be displayed in TransferStatusDialog
            # and so Connect plugin can pick it up as "ours" by data field.
            payload_meta = {
                "tag": "mroya_transfer",
                "description": (
                    "Transfer components from {0} to {1} "
                    "(initiated from Mroya browser)".format(
                        self.source_loc_id, self.target_loc_id
                    )
                ),
                "component_label": self.component_label,
                "from_location_id": self.source_loc_id,
                "to_location_id": self.target_loc_id,
                "to_location_name": self.target_loc_name,
                "from_location_type": from_location_type,
                "to_location_type": to_location_type,
                "total_size_bytes": total_size,
            }

            logger.info("TransferWorker.run: Creating Job with meta: %r", payload_meta)
            job = session.create(
                "Job",
                {
                    "user_id": self.user_id,
                    "status": "running",
                    "data": json.dumps(payload_meta),
                },
            )
            session.commit()
            logger.info("TransferWorker.run: Job created and committed: %s", job["id"])

            job_id = job["id"]

            # Publish event for background manager in ftrack Connect.
            try:
                from ftrack_api.event.base import Event  # type: ignore

                payload = {
                    "job_id": job_id,
                    "user_id": self.user_id,
                    "from_location_id": self.source_loc_id,
                    "to_location_id": self.target_loc_id,
                    "selection": list(self.selection_entities),
                    "ignore_component_not_in_location": False,
                    "ignore_location_errors": False,
                }
                logger.info("TransferWorker.run: Preparing to publish mroya.transfer.request event")
                logger.info("TransferWorker.run: Event payload: %r", payload)
                
                try:
                    # Try to connect to event hub, but don't block for long
                    logger.info("TransferWorker.run: Attempting to connect to event_hub...")
                    try:
                        session.event_hub.connect()
                        logger.info("TransferWorker.run: Event hub connected successfully")
                    except Exception as connect_exc:
                        logger.warning(
                            "TransferWorker.run: event_hub.connect() failed, trying to publish anyway: %s",
                            connect_exc,
                        )
                    
                    logger.info("TransferWorker.run: Creating Event object with topic='mroya.transfer.request'")
                    
                    # Get hostname to include in event source for proper workstation filtering
                    import socket
                    current_hostname = socket.gethostname().lower()
                    logger.info("TransferWorker.run: Current machine hostname: %s", current_hostname)
                    
                    # Get current user for event source
                    # This ensures the subscription filter (source.user.username) matches
                    current_username = session.api_user
                    logger.info("TransferWorker.run: Current session user: %s", current_username)
                    
                    # Create event with explicit source including hostname and user
                    # IMPORTANT: event_hub._prepare_event uses setdefault for source.user,
                    # which means if source.user already exists, it won't be overwritten.
                    # But we need to ensure source.user.username matches session.api_user
                    # for the subscription filter to work correctly.
                    # 
                    # The subscription filter requires: source.user.username="{username}"
                    # We set it explicitly here, and event_hub.publish() will use setdefault,
                    # which should preserve our username if it's already set correctly.
                    event = Event(
                        topic="mroya.transfer.request", 
                        data=payload,
                        source={
                            'hostname': current_hostname,
                            'user': {
                                'username': current_username,
                            }
                        }
                    )
                    
                    # Log event details before publishing for debugging
                    logger.info("=" * 80)
                    logger.info("TransferWorker.run: Event details BEFORE publishing:")
                    logger.info("Current session: user=%s, event_hub.id=%s, hostname=%s", 
                                session.api_user, session.event_hub.id, current_hostname)
                    logger.info("Event topic: %s", event.get('topic'))
                    logger.info("Event ID: %s", event.get('id'))
                    logger.info("Event data (payload): %s", json.dumps(payload, indent=2, default=str))
                    event_source_before = dict(event.get('source', {}))
                    logger.info("Event source (before publish, with hostname and user): %s", json.dumps(event_source_before, indent=2, default=str))
                    logger.info("Subscription filter should match: source.user.username='%s' and hostname='%s'", current_username, current_hostname)
                    logger.info("=" * 80)
                    
                    # CRITICAL: event_hub._prepare_event uses setdefault for source.user,
                    # which means if source.user already exists, it won't be overwritten.
                    # However, we need to ensure source.user.username matches session.api_user
                    # for the subscription filter to work correctly.
                    # 
                    # IMPORTANT: Check if event_hub._api_user differs from session.api_user
                    # If they differ, we need to ensure our username is set correctly BEFORE publish
                    # because setdefault won't overwrite an existing value.
                    event_hub_api_user = getattr(session.event_hub, '_api_user', None)
                    if event_hub_api_user and event_hub_api_user != current_username:
                        logger.warning(
                            "TransferWorker.run: event_hub._api_user (%s) differs from session.api_user (%s). "
                            "This may cause subscription filter mismatch!",
                            event_hub_api_user,
                            current_username
                        )
                        # Ensure our username is set correctly - setdefault won't overwrite it
                        event.get('source', {}).setdefault('user', {})['username'] = current_username
                        logger.info(
                            "TransferWorker.run: Explicitly set source.user.username to %s to match subscription filter",
                            current_username
                        )
                    
                    logger.info("TransferWorker.run: Publishing event to event_hub...")
                    session.event_hub.publish(event, on_error="ignore")
                    
                    # Log event details after publishing (source should be populated by event_hub)
                    event_source_after = event.get('source', {})
                    event_user_after = event_source_after.get('user', {})
                    event_username_after = event_user_after.get('username') if isinstance(event_user_after, dict) else None
                    
                    logger.info("=" * 80)
                    logger.info("TransferWorker.run: Event details AFTER publishing:")
                    logger.info("Event source (after publish, should be populated): %s", json.dumps(dict(event_source_after), indent=2, default=str))
                    logger.info("Event username after publish: %s (expected: %s)", event_username_after, current_username)
                    if event_username_after != current_username:
                        logger.error(
                            "TransferWorker.run: ERROR - Event username mismatch after publish! "
                            "Expected: %s, Got: %s. Subscription filter may not match!",
                            current_username,
                            event_username_after
                        )
                    logger.info("=" * 80)
                    
                    logger.info("TransferWorker.run: Event published successfully!")
                except Exception as publish_exc:
                    logger.warning(
                        "TransferWorker.run: Failed to publish event (non-critical): %s",
                        publish_exc,
                    )
            except Exception as exc:
                logger.error(
                    "TransferWorker.run: FAILED to publish mroya.transfer.request: %s",
                    exc,
                    exc_info=True,
                )

            # Notify UI about created job so TransferStatusDialog can start monitoring it.
            logger.info("TransferWorker.run: Emitting job_created signal to UI (job_id=%s, label=%s)", job_id, self.component_label)
            self.signals.job_created.emit(job, self.component_label)
            logger.info("TransferWorker.run: Signal emitted, worker finished successfully")

        except Exception as e:
            logger.error("=" * 80)
            logger.error("TransferWorker.run: EXCEPTION occurred: %s", e, exc_info=True)
            logger.error("=" * 80)
            self.signals.error.emit(str(e))
        finally:
            logger.info("TransferWorker.run: Emitting finished signal and exiting worker thread")
            self.signals.finished.emit()

def show():
    """Show browser in a PySide2 application."""
    if not PYSIDE6_AVAILABLE:
        logger.error("PySide6 not available, can't show browser.")
        return
    
    app = QtWidgets.QApplication.instance()
    if not app:
        app = QtWidgets.QApplication(sys.argv)
        
    browser = FtrackTaskBrowser()
    browser.show()
    
    # Start event loop if not already running
    if not hasattr(app, '_is_running_event_loop') or not app._is_running_event_loop:
        app._is_running_event_loop = True
        app.exec_()

if __name__ == '__main__':
    # Add a handler to see logs in the console
    handler = logging.StreamHandler(sys.stdout)
    formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    handler.setFormatter(formatter)
    logging.getLogger().addHandler(handler)
    logging.getLogger().setLevel(logging.INFO)

    show()
else:
    # Class aliases for direct import (like original)
    FtrackBrowser = FtrackTaskBrowser
    
    # Global factory function
    _global_browser_instance = None
    
    def create_browser_widget():
        """Factory function to create a single instance of the browser."""
        global _global_browser_instance
        if _global_browser_instance is None:
            _global_browser_instance = FtrackTaskBrowser()
        return _global_browser_instance
