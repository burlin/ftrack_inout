"""
Maya Publisher Window - Qt UI for publisher node.

Shows the full publisher interface (like use_custom in Houdini HDA)
with Test and Publish buttons. Syncs data to/from Maya node.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

_log = logging.getLogger(__name__)

# Maya imports
try:
    import maya.cmds as cmds
    import maya.OpenMayaUI as omui
    MAYA_AVAILABLE = True
except ImportError:
    MAYA_AVAILABLE = False
    cmds = None
    omui = None

# Qt imports
try:
    from PySide6 import QtWidgets, QtCore
    from shiboken6 import wrapInstance
except ImportError:
    try:
        from PySide2 import QtWidgets, QtCore
        from shiboken2 import wrapInstance
    except ImportError:
        QtWidgets = None
        QtCore = None
        wrapInstance = None


def get_maya_main_window():
    """Get Maya main window as QWidget."""
    if not MAYA_AVAILABLE or wrapInstance is None:
        return None
    try:
        ptr = omui.MQtUtil.mainWindow()
        if ptr is None:
            return None
        return wrapInstance(int(ptr), QtWidgets.QWidget)
    except Exception:
        return None


class MayaPublisherWindow(QtWidgets.QDialog):
    """
    Maya Publisher Window - wraps PublisherWidget with Maya node sync.
    
    Features:
    - Full publisher UI (same as standalone/Houdini)
    - Sync to/from Maya node attributes
    - Test (dry-run) and Publish buttons
    """
    
    # Class-level reference to keep window alive
    _instance = None
    
    def __init__(self, node_name: str, parent=None):
        if parent is None:
            parent = get_maya_main_window()
        
        super().__init__(parent)
        
        self.node_name = node_name
        self._setup_ui()
        self._load_from_node()
        
        # Store instance
        MayaPublisherWindow._instance = self
    
    def _setup_ui(self):
        """Create UI layout."""
        self.setWindowTitle(f"Mroya Publisher - {self.node_name}")
        self.setMinimumSize(500, 700)
        self.resize(550, 800)
        
        # Main layout
        main_layout = QtWidgets.QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)
        
        # Node info bar
        info_bar = QtWidgets.QWidget()
        info_bar.setStyleSheet("background-color: #3a3a3a; padding: 5px;")
        info_layout = QtWidgets.QHBoxLayout(info_bar)
        info_layout.setContentsMargins(10, 5, 10, 5)
        
        self.node_label = QtWidgets.QLabel(f"Node: {self.node_name}")
        self.node_label.setStyleSheet("font-weight: bold; color: #aaa;")
        info_layout.addWidget(self.node_label)
        
        info_layout.addStretch()
        
        # Sync button
        sync_btn = QtWidgets.QPushButton("↻ Reload")
        sync_btn.setToolTip("Reload data from node")
        sync_btn.setMaximumWidth(80)
        sync_btn.clicked.connect(self._load_from_node)
        info_layout.addWidget(sync_btn)
        
        main_layout.addWidget(info_bar)
        
        # Import and create PublisherWidget
        try:
            from ftrack_inout.publisher.ui.publisher_widget import PublisherWidget
            self.publisher_widget = PublisherWidget(self)
            
            # Hide the original Render button - we'll use our own
            if hasattr(self.publisher_widget, 'publish_btn'):
                self.publisher_widget.publish_btn.hide()
            
            main_layout.addWidget(self.publisher_widget, stretch=1)
        except ImportError as e:
            _log.error(f"Failed to import PublisherWidget: {e}")
            error_label = QtWidgets.QLabel(f"Error: Could not load publisher UI\n{e}")
            error_label.setStyleSheet("color: red; padding: 20px;")
            main_layout.addWidget(error_label)
            self.publisher_widget = None
        
        # Bottom buttons bar
        btn_bar = QtWidgets.QWidget()
        btn_bar.setStyleSheet("background-color: #2a2a2a; padding: 10px;")
        btn_layout = QtWidgets.QHBoxLayout(btn_bar)
        btn_layout.setContentsMargins(10, 10, 10, 10)
        btn_layout.setSpacing(10)
        
        # Save to Node button
        save_btn = QtWidgets.QPushButton("Save to Node")
        save_btn.setMinimumHeight(35)
        save_btn.setToolTip("Save current values to Maya node")
        save_btn.clicked.connect(self._save_to_node)
        btn_layout.addWidget(save_btn)
        
        btn_layout.addStretch()
        
        # Test button
        test_btn = QtWidgets.QPushButton("Test")
        test_btn.setMinimumHeight(40)
        test_btn.setMinimumWidth(100)
        test_btn.setStyleSheet("background-color: #555566; font-weight: bold;")
        test_btn.setToolTip("Dry-run test (no changes to Ftrack)")
        test_btn.clicked.connect(self._on_test_clicked)
        btn_layout.addWidget(test_btn)
        
        # Publish button
        publish_btn = QtWidgets.QPushButton("Publish")
        publish_btn.setMinimumHeight(40)
        publish_btn.setMinimumWidth(120)
        publish_btn.setStyleSheet("background-color: #336633; font-weight: bold; font-size: 14px;")
        publish_btn.setToolTip("Publish to Ftrack")
        publish_btn.clicked.connect(self._on_publish_clicked)
        btn_layout.addWidget(publish_btn)
        
        main_layout.addWidget(btn_bar)
    
    def _load_from_node(self):
        """Load parameter values from Maya node."""
        if not MAYA_AVAILABLE or not self.publisher_widget:
            return
        
        if not cmds.objExists(self.node_name):
            _log.warning(f"Node {self.node_name} no longer exists")
            return
        
        _log.debug(f"[MayaPublisher] Loading from node: {self.node_name}")
        
        # Map of widget parameters to Maya attributes
        param_map = {
            'p_task_id': 'p_task_id',
            'p_project': 'p_project',
            'p_parent': 'p_parent',
            'p_asset_id': 'p_asset_id',
            'p_asset_name': 'p_asset_name',
            'p_asset_type': 'p_asset_type',
            'comment': 'comment',
            'use_snapshot': 'use_snapshot',
            'use_playblast': 'use_playblast',
            'playblast': 'playblast',
            'thumbnail_path': 'thumbnail_path',
            'components': 'components',
        }
        
        for widget_param, maya_attr in param_map.items():
            value = self._get_maya_attr(maya_attr)
            if value is not None:
                self.publisher_widget.set_parameter(widget_param, value)
        
        # Load component data
        comp_count = self._get_maya_attr('components') or 0
        for i in range(1, comp_count + 1):
            self._load_component(i)
        
        _log.info(f"[MayaPublisher] Loaded data from node: {self.node_name}")
    
    def _load_component(self, index: int):
        """Load single component data from node."""
        if not self.publisher_widget:
            return
        
        comp_data = {}
        
        # Read component attributes
        comp_data[f'comp_name{index}'] = self._get_maya_attr(f'comp_name{index}') or ''
        comp_data[f'file_path{index}'] = self._get_maya_attr(f'file_path{index}') or ''
        comp_data[f'export{index}'] = 1 if self._get_maya_attr(f'export{index}') else 0
        
        meta_count = self._get_maya_attr(f'meta_count{index}') or 0
        comp_data[f'meta_count{index}'] = meta_count
        
        for m in range(1, meta_count + 1):
            comp_data[f'key{index}_{m}'] = self._get_maya_attr(f'key{index}_{m}') or ''
            comp_data[f'value{index}_{m}'] = self._get_maya_attr(f'value{index}_{m}') or ''
        
        # Set on widget
        if hasattr(self.publisher_widget, 'component_tabs'):
            tab_index = index - 1
            if tab_index < self.publisher_widget.component_tabs.count():
                tab = self.publisher_widget.component_tabs.widget(tab_index)
                if tab and hasattr(tab, 'set_component_data'):
                    tab.set_component_data(comp_data)
    
    def _save_to_node(self):
        """Save parameter values to Maya node."""
        if not MAYA_AVAILABLE or not self.publisher_widget:
            return
        
        if not cmds.objExists(self.node_name):
            QtWidgets.QMessageBox.warning(self, "Error", f"Node {self.node_name} no longer exists")
            return
        
        _log.debug(f"[MayaPublisher] Saving to node: {self.node_name}")
        
        # Save main parameters
        param_map = {
            'p_task_id': 'p_task_id',
            'p_project': 'p_project',
            'p_parent': 'p_parent',
            'p_asset_id': 'p_asset_id',
            'p_asset_name': 'p_asset_name',
            'p_asset_type': 'p_asset_type',
            'comment': 'comment',
            'use_snapshot': 'use_snapshot',
            'use_playblast': 'use_playblast',
            'playblast': 'playblast',
            'thumbnail_path': 'thumbnail_path',
            'components': 'components',
        }
        
        for widget_param, maya_attr in param_map.items():
            value = self.publisher_widget.get_parameter(widget_param)
            self._set_maya_attr(maya_attr, value)
        
        # Save component data
        comp_count = self.publisher_widget.get_parameter('components') or 0
        
        # Ensure component attributes exist
        from ftrack_inout.publisher.dcc.maya import add_component_attributes
        for i in range(1, comp_count + 1):
            add_component_attributes(self.node_name, i)
        
        # Save each component
        if hasattr(self.publisher_widget, 'component_tabs'):
            for i in range(self.publisher_widget.component_tabs.count()):
                tab = self.publisher_widget.component_tabs.widget(i)
                if tab and hasattr(tab, 'get_component_data'):
                    self._save_component(i + 1, tab.get_component_data())
        
        _log.info(f"[MayaPublisher] Saved data to node: {self.node_name}")
        
        # Visual feedback
        self.node_label.setText(f"Node: {self.node_name} ✓")
        QtCore.QTimer.singleShot(2000, lambda: self.node_label.setText(f"Node: {self.node_name}"))
    
    def _save_component(self, index: int, comp_data: Dict[str, Any]):
        """Save single component data to node."""
        self._set_maya_attr(f'comp_name{index}', comp_data.get(f'comp_name{index}', ''))
        self._set_maya_attr(f'file_path{index}', comp_data.get(f'file_path{index}', ''))
        self._set_maya_attr(f'export{index}', comp_data.get(f'export{index}', 1))
        
        meta_count = comp_data.get(f'meta_count{index}', 0)
        self._set_maya_attr(f'meta_count{index}', meta_count)
        
        # Add metadata attributes if needed
        for m in range(1, meta_count + 1):
            key_attr = f'key{index}_{m}'
            value_attr = f'value{index}_{m}'
            
            # Create attributes if they don't exist
            if not cmds.attributeQuery(key_attr, node=self.node_name, exists=True):
                cmds.addAttr(self.node_name, longName=key_attr, dataType="string")
            if not cmds.attributeQuery(value_attr, node=self.node_name, exists=True):
                cmds.addAttr(self.node_name, longName=value_attr, dataType="string")
            
            self._set_maya_attr(key_attr, comp_data.get(f'key{index}_{m}', ''))
            self._set_maya_attr(value_attr, comp_data.get(f'value{index}_{m}', ''))
    
    def _get_maya_attr(self, attr_name: str) -> Any:
        """Get attribute value from Maya node."""
        if not cmds.attributeQuery(attr_name, node=self.node_name, exists=True):
            return None
        
        try:
            attr_path = f"{self.node_name}.{attr_name}"
            return cmds.getAttr(attr_path)
        except Exception:
            return None
    
    def _set_maya_attr(self, attr_name: str, value: Any):
        """Set attribute value on Maya node."""
        if not cmds.attributeQuery(attr_name, node=self.node_name, exists=True):
            return
        
        try:
            attr_path = f"{self.node_name}.{attr_name}"
            attr_type = cmds.getAttr(attr_path, type=True)
            
            if attr_type == "string":
                cmds.setAttr(attr_path, str(value) if value else "", type="string")
            elif attr_type == "bool":
                cmds.setAttr(attr_path, bool(value))
            elif attr_type in ("long", "short", "int"):
                cmds.setAttr(attr_path, int(value) if value else 0)
            else:
                cmds.setAttr(attr_path, value)
        except Exception as e:
            _log.warning(f"Failed to set {attr_path}: {e}")
    
    def _on_test_clicked(self):
        """Test button clicked - dry run."""
        # Save current values to node first
        self._save_to_node()
        
        try:
            from ftrack_inout.publisher.dcc.maya import publish_dry_run_callback
            cmds.select(self.node_name)
            publish_dry_run_callback(self.node_name)
        except Exception as e:
            QtWidgets.QMessageBox.critical(self, "Test Failed", str(e))
    
    def _on_publish_clicked(self):
        """Publish button clicked."""
        # Save current values to node first
        self._save_to_node()
        
        try:
            from ftrack_inout.publisher.dcc.maya import publish_callback
            cmds.select(self.node_name)
            publish_callback(self.node_name)
        except Exception as e:
            QtWidgets.QMessageBox.critical(self, "Publish Failed", str(e))
    
    def closeEvent(self, event):
        """Handle window close."""
        # Ask to save changes
        result = QtWidgets.QMessageBox.question(
            self,
            "Save Changes?",
            "Save current values to node before closing?",
            QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No | QtWidgets.QMessageBox.Cancel
        )
        
        if result == QtWidgets.QMessageBox.Yes:
            self._save_to_node()
            event.accept()
        elif result == QtWidgets.QMessageBox.No:
            event.accept()
        else:
            event.ignore()


def show_publisher_window(node_name: str = None):
    """Show publisher window for given node.
    
    Args:
        node_name: Maya node name. If None, uses selected node.
    """
    if not MAYA_AVAILABLE:
        _log.error("Maya is not available")
        return
    
    # Get node from selection if not provided
    if node_name is None:
        selection = cmds.ls(selection=True)
        if selection:
            node_name = selection[0]
        else:
            cmds.warning("Please select a publisher node or specify node name")
            return
    
    # Check if it's a publisher node
    if not cmds.objExists(node_name):
        cmds.warning(f"Node '{node_name}' does not exist")
        return
    
    if not cmds.attributeQuery("isMroyaPublisher", node=node_name, exists=True):
        cmds.warning(f"Node '{node_name}' is not a Mroya publisher node")
        return
    
    # Close existing window if open
    if MayaPublisherWindow._instance is not None:
        try:
            MayaPublisherWindow._instance.close()
        except Exception:
            pass
    
    # Create and show new window
    window = MayaPublisherWindow(node_name)
    window.show()
    window.raise_()
    
    return window
