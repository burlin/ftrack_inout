"""
Maya Ftrack Input Window - finput-like loader for Maya.

Shows FtrackInputWidget; on selection resolved offers:
- Create Reference: cmds.file(path, reference=True)
- Create File: cmds.file(path, open=True) (optional, less common for assets)
- Create Input Node: locator with asset_version_id, component_id, file_path, __ftrack_used_CompId
  and optionally create reference under it.

Run from Maya:
    from ftrack_inout.browser.dcc.maya import open_ftrack_input_window
    open_ftrack_input_window()
"""

from __future__ import annotations

import logging
import os
from typing import Optional, TYPE_CHECKING

_log = logging.getLogger(__name__)

# Maya imports
try:
    import maya.cmds as cmds
    import maya.OpenMayaUI as omui
    MAYA_AVAILABLE = True
except ImportError:
    MAYA_AVAILABLE = False
    cmds = None  # type: ignore
    omui = None  # type: ignore

# Qt imports
try:
    from PySide6 import QtWidgets, QtCore
    from shiboken6 import wrapInstance
except ImportError:
    try:
        from PySide2 import QtWidgets, QtCore
        from shiboken2 import wrapInstance
    except ImportError:
        QtWidgets = None  # type: ignore
        QtCore = None  # type: ignore
        wrapInstance = None  # type: ignore

if TYPE_CHECKING:
    from ...ftrack_input_widget import FtrackComponentSelection  # noqa: F401


def get_maya_main_window():
    """Get Maya main window as QWidget."""
    if not MAYA_AVAILABLE or wrapInstance is None or QtWidgets is None:
        return None
    try:
        ptr = omui.MQtUtil.mainWindow()
        if ptr is None:
            return None
        return wrapInstance(int(ptr), QtWidgets.QWidget)
    except Exception:
        return None


# Singleton window reference
_input_window_instance = None  # type: Optional["MayaFtrackInputWindow"]


class MayaFtrackInputWindow(QtWidgets.QDialog if QtWidgets else object):
    """
    Maya Ftrack Input window: FtrackInputWidget + Maya actions.

    When user resolves a component (get from assetver):
    - Create Reference: create file reference with path; store __ftrack_used_CompId on reference node if possible
    - Create Input Node: create mroya_input locator with attributes + optional reference
    """

    def __init__(self, parent=None):
        if QtWidgets is None:
            raise RuntimeError("PySide6 or PySide2 is required")
        if parent is None:
            parent = get_maya_main_window()
        super().__init__(parent)

        self._last_selection = None  # type: Optional["FtrackComponentSelection"]
        self._input_widget = None

        self.setWindowTitle("Ftrack Input (Maya)")
        self.setMinimumSize(520, 520)
        self.resize(560, 560)

        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(8)

        # Info label
        info = QtWidgets.QLabel("Select component (get from assetver), then use one of the buttons below.")
        info.setWordWrap(True)
        info.setStyleSheet("color: #aaa; padding: 4px;")
        layout.addWidget(info)

        # FtrackInputWidget
        try:
            from ...ftrack_input_widget import FtrackInputWidget
            self._input_widget = FtrackInputWidget(self)
            self._input_widget.selectionResolved.connect(self._on_selection_resolved)
            self._input_widget.transferRequested.connect(self._on_transfer_requested)
            layout.addWidget(self._input_widget, 1)
        except ImportError as e:
            _log.error("Failed to import FtrackInputWidget: %s", e)
            layout.addWidget(QtWidgets.QLabel(f"Error: {e}"))

        # Maya actions (enabled when path is resolved)
        actions_group = QtWidgets.QGroupBox("Maya actions")
        actions_layout = QtWidgets.QHBoxLayout(actions_group)
        self._create_reference_btn = QtWidgets.QPushButton("Create Reference")
        self._create_reference_btn.setToolTip("Create file reference from resolved path")
        self._create_reference_btn.setEnabled(False)
        self._create_reference_btn.clicked.connect(self._on_create_reference)
        actions_layout.addWidget(self._create_reference_btn)

        self._create_file_btn = QtWidgets.QPushButton("Create File (import)")
        self._create_file_btn.setToolTip("Import file into scene (merge)")
        self._create_file_btn.setEnabled(False)
        self._create_file_btn.clicked.connect(self._on_create_file)
        actions_layout.addWidget(self._create_file_btn)

        self._create_input_node_btn = QtWidgets.QPushButton("Create Input Node")
        self._create_input_node_btn.setToolTip("Create mroya_input locator with component data + reference")
        self._create_input_node_btn.setEnabled(False)
        self._create_input_node_btn.clicked.connect(self._on_create_input_node)
        actions_layout.addWidget(self._create_input_node_btn)

        actions_layout.addStretch(1)
        layout.addWidget(actions_group)

        self.setAttribute(QtCore.Qt.WA_DeleteOnClose, True)

    def _on_selection_resolved(self, selection: "FtrackComponentSelection"):
        """Enable Maya action buttons when path is resolved."""
        self._last_selection = selection
        has_path = bool(selection and selection.file_path and selection.file_path.strip())
        self._create_reference_btn.setEnabled(has_path)
        self._create_file_btn.setEnabled(has_path)
        self._create_input_node_btn.setEnabled(has_path)

    def _on_transfer_requested(self, selection: "FtrackComponentSelection"):
        """Transfer requested - widget handles it; we just log."""
        _log.info("Transfer requested for component %s", getattr(selection, "component_id", None))

    def _on_create_reference(self):
        """Create Maya file reference from resolved path."""
        if not MAYA_AVAILABLE or not self._last_selection or not self._last_selection.file_path:
            return
        path = self._last_selection.file_path.strip()
        if not path or not os.path.isfile(path):
            QtWidgets.QMessageBox.warning(
                self,
                "Invalid path",
                f"File does not exist:\n{path}",
            )
            return
        try:
            ref_nodes = cmds.file(
                path,
                reference=True,
                type=self._get_maya_file_type(path),
                namespace=None,
                returnNewNodes=True,
            )
            comp_id = getattr(self._last_selection, "used_component_id", None) or getattr(
                self._last_selection, "component_id", None
            )
            if comp_id and ref_nodes:
                # Try to set __ftrack_used_CompId on first ref node (e.g. top transform)
                for node in ref_nodes:
                    if cmds.objectType(node, isType="transform") or "." in node:
                        try:
                            _add_ftrack_comp_id_attr(node, comp_id)
                            break
                        except Exception:
                            pass
            QtWidgets.QMessageBox.information(
                self,
                "Reference created",
                f"Created reference from:\n{path}\n\nNodes: {len(ref_nodes)}",
            )
        except Exception as e:
            _log.exception("Create reference failed")
            QtWidgets.QMessageBox.critical(
                self,
                "Error",
                f"Failed to create reference:\n{e}",
            )

    def _on_create_file(self):
        """Import file (merge) into scene."""
        if not MAYA_AVAILABLE or not self._last_selection or not self._last_selection.file_path:
            return
        path = self._last_selection.file_path.strip()
        if not path or not os.path.isfile(path):
            QtWidgets.QMessageBox.warning(self, "Invalid path", f"File does not exist:\n{path}")
            return
        try:
            cmds.file(path, open=False, i=True, type=self._get_maya_file_type(path))
            QtWidgets.QMessageBox.information(self, "File imported", f"Imported:\n{path}")
        except Exception as e:
            _log.exception("Create file (import) failed")
            QtWidgets.QMessageBox.critical(self, "Error", f"Failed to import:\n{e}")

    def _on_create_input_node(self):
        """Create mroya_input locator with component attributes and optional reference."""
        if not MAYA_AVAILABLE or not self._last_selection:
            return
        sel = self._last_selection
        path = (sel.file_path or "").strip()

        try:
            node_name = create_input_node(
                asset_version_id=getattr(sel, "version_id", None) or "",
                component_id=getattr(sel, "component_id", None) or "",
                component_name=getattr(sel, "component_name", None) or "",
                file_path=path,
                used_component_id=getattr(sel, "used_component_id", None) or getattr(sel, "component_id", None) or "",
            )
            if path and os.path.isfile(path):
                ref_nodes = cmds.file(
                    path,
                    reference=True,
                    type=self._get_maya_file_type(path),
                    namespace=None,
                    returnNewNodes=True,
                )
                if ref_nodes:
                    # Parent first ref transform under input node if possible
                    for rn in ref_nodes:
                        if cmds.objectType(rn, isType="transform"):
                            try:
                                cmds.parent(rn, node_name)
                            except Exception:
                                pass
                            break
            QtWidgets.QMessageBox.information(
                self,
                "Input node created",
                f"Created: {node_name}",
            )
        except Exception as e:
            _log.exception("Create input node failed")
            QtWidgets.QMessageBox.critical(self, "Error", f"Failed to create input node:\n{e}")

    def _get_maya_file_type(self, path: str) -> str:
        """Return Maya file type for path (e.g. mayaAscii, alembic, FBX)."""
        ext = os.path.splitext(path)[1].lower()
        if ext in (".ma", ".maya"):
            return "mayaAscii"
        if ext == ".mb":
            return "mayaBinary"
        if ext == ".abc":
            return "Alembic"
        if ext == ".fbx":
            return "FBX"
        if ext in (".obj",):
            return "OBJ"
        return "mayaAscii"


def _add_ftrack_comp_id_attr(node: str, comp_id: str) -> None:
    """Add __ftrack_used_CompId string attribute to node if not present."""
    if not MAYA_AVAILABLE:
        return
    attr_name = "__ftrack_used_CompId"
    full_attr = f"{node}.{attr_name}"
    if not cmds.attributeQuery(attr_name, node=node, exists=True):
        cmds.addAttr(node, longName=attr_name, dataType="string")
    cmds.setAttr(full_attr, comp_id, type="string")


def create_input_node(
    asset_version_id: str = "",
    component_id: str = "",
    component_name: str = "",
    file_path: str = "",
    used_component_id: str = "",
) -> str:
    """
    Create Maya locator node (mroya_input) with Ftrack component attributes.

    Attributes: asset_version_id, component_id, component_name, file_path, __ftrack_used_CompId.
    Returns node name.
    """
    if not MAYA_AVAILABLE:
        raise RuntimeError("Maya is not available")

    base_name = "mroya_input"
    node_name = base_name + "1"
    counter = 1
    while cmds.objExists(node_name):
        counter += 1
        node_name = f"{base_name}{counter}"

    loc = cmds.spaceLocator(name=node_name)[0]
    node = loc

    cmds.addAttr(node, longName="isMroyaInput", attributeType="bool", defaultValue=True)
    cmds.addAttr(node, longName="asset_version_id", dataType="string")
    cmds.addAttr(node, longName="component_id", dataType="string")
    cmds.addAttr(node, longName="component_name", dataType="string")
    cmds.addAttr(node, longName="file_path", dataType="string")
    cmds.addAttr(node, longName="__ftrack_used_CompId", dataType="string")

    cmds.setAttr(f"{node}.asset_version_id", asset_version_id, type="string")
    cmds.setAttr(f"{node}.component_id", component_id, type="string")
    cmds.setAttr(f"{node}.component_name", component_name, type="string")
    cmds.setAttr(f"{node}.file_path", file_path, type="string")
    cmds.setAttr(f"{node}.__ftrack_used_CompId", used_component_id or component_id, type="string")

    cmds.setAttr(f"{node}.localScaleX", 0.3)
    cmds.setAttr(f"{node}.localScaleY", 0.3)
    cmds.setAttr(f"{node}.localScaleZ", 0.3)
    for attr in ["tx", "ty", "tz", "rx", "ry", "rz", "sx", "sy", "sz"]:
        cmds.setAttr(f"{node}.{attr}", lock=True)

    _log.info("Created input node: %s", node)
    return node


def open_ftrack_input_window():
    """
    Open Ftrack Input window in Maya.

    Call from shelf or script:
        from ftrack_inout.browser.dcc.maya import open_ftrack_input_window
        open_ftrack_input_window()
    """
    global _input_window_instance

    if not MAYA_AVAILABLE:
        _log.error("Maya is not available")
        if cmds:
            cmds.warning("Ftrack Input: Maya is not available")
        return None

    if QtWidgets is None:
        _log.error("PySide6/PySide2 is not available")
        if cmds:
            cmds.warning("Ftrack Input: PySide not available")
        return None

    if _input_window_instance is not None:
        try:
            if _input_window_instance.isVisible():
                _input_window_instance.raise_()
                _input_window_instance.activateWindow()
                return _input_window_instance
            _input_window_instance = None
        except Exception:
            _input_window_instance = None

    parent = get_maya_main_window()
    _input_window_instance = MayaFtrackInputWindow(parent)
    _input_window_instance.show()
    _input_window_instance.raise_()
    _input_window_instance.activateWindow()

    def _on_close():
        global _input_window_instance
        _input_window_instance = None

    try:
        _input_window_instance.finished.connect(_on_close)
    except Exception:
        pass

    return _input_window_instance
