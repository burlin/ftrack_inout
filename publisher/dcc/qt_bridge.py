"""
Qt bridge for standalone publisher UI.

Adapts Qt widget parameter interface to core ParameterInterface protocol.
"""

from __future__ import annotations

from typing import Any, Optional

try:
    from PySide2 import QtWidgets
except ImportError:
    try:
        from PySide6 import QtWidgets
    except ImportError:
        from PyQt5 import QtWidgets

from ..core.selector import (
    check_task_id as core_check_task_id,
    apply_task_id as core_apply_task_id,
    apply_asset_params as core_apply_asset_params,
    get_assets_list as core_get_assets_list,
    apply_name as core_apply_name,
)


class QtParameterInterface:
    """Qt parameter interface adapter."""
    
    def __init__(self, widget):
        """Initialize with Qt widget."""
        self.widget = widget
    
    def get_parameter(self, name: str) -> Any:
        """Get parameter value from widget."""
        return self.widget.get_parameter(name)
    
    def set_parameter(self, name: str, value: Any) -> None:
        """Set parameter value on widget."""
        self.widget.set_parameter(name, value)
    
    def show_message(self, message: str, severity: str = "info") -> None:
        """Show message using QMessageBox."""
        if severity == "warning":
            QtWidgets.QMessageBox.warning(self.widget, "Warning", message)
        elif severity == "error":
            QtWidgets.QMessageBox.critical(self.widget, "Error", message)
        else:
            QtWidgets.QMessageBox.information(self.widget, "Info", message)


import logging

_log = logging.getLogger(__name__)


def check_task_id_qt(widget, session, task_info_label):
    """Qt wrapper for check_task_id."""
    _log.info("[qt_bridge] check_task_id_qt called")
    interface = QtParameterInterface(widget)
    result = core_check_task_id(interface, session, task_info_label)
    _log.info(f"[qt_bridge] check_task_id_qt result: {result}")
    return result


def apply_task_id_qt(widget, session):
    """Qt wrapper for apply_task_id."""
    _log.info("[qt_bridge] apply_task_id_qt called")
    interface = QtParameterInterface(widget)
    
    def show_dialog(message: str, buttons: tuple, title: str = "Info"):
        """Show dialog using QMessageBox with custom buttons.
        
        Returns:
            int: Index of selected button (0, 1, 2, ...) or None if dialog was cancelled
        """
        _log.info(f"[qt_bridge] show_dialog called: {title} - {message} - buttons: {buttons}")
        
        # Create message box
        msg_box = QtWidgets.QMessageBox(widget)
        msg_box.setWindowTitle(title)
        msg_box.setText(message)
        
        # Add buttons
        button_ids = []
        for i, button_text in enumerate(buttons):
            if button_text == "Cancel":
                role = QtWidgets.QMessageBox.RejectRole
            else:
                role = QtWidgets.QMessageBox.AcceptRole
            
            btn = msg_box.addButton(button_text, role)
            button_ids.append(btn)
        
        # Show dialog (exec_() works in both PySide2 and PySide6)
        result = msg_box.exec_()
        
        # Find which button was clicked
        clicked_button = msg_box.clickedButton()
        if clicked_button:
            try:
                button_index = button_ids.index(clicked_button)
                _log.info(f"[qt_bridge] User selected button index: {button_index} ('{buttons[button_index]}')")
                return button_index
            except (ValueError, IndexError):
                _log.warning(f"[qt_bridge] Could not find clicked button in list")
                return None
        
        # If no button was clicked (shouldn't happen, but just in case)
        _log.warning(f"[qt_bridge] No button was clicked")
        return None
    
    result = core_apply_task_id(interface, session, show_dialog)
    _log.info(f"[qt_bridge] apply_task_id_qt result: {result}")
    return result


def apply_asset_params_qt(widget, session, task_info_label):
    """Qt wrapper for apply_asset_params."""
    _log.info("[qt_bridge] apply_asset_params_qt called")
    interface = QtParameterInterface(widget)
    result = core_apply_asset_params(interface, session, task_info_label)
    _log.info(f"[qt_bridge] apply_asset_params_qt result: {result}")
    return result


def get_assets_list_qt(session, task_id):
    """Qt wrapper for get_assets_list."""
    _log.info(f"[qt_bridge] get_assets_list_qt called with task_id: {task_id}")
    result = core_get_assets_list(session, task_id)
    _log.info(f"[qt_bridge] get_assets_list_qt result: {len(result[0])} assets")
    return result


def apply_name_qt(widget, session, assets_menu_ids=None, assets_menu_index=None):
    """Qt wrapper for apply_name."""
    _log.info(f"[qt_bridge] apply_name_qt called with assets_menu_index: {assets_menu_index}")
    interface = QtParameterInterface(widget)
    
    def show_message(message: str, severity: str = "info"):
        """Show message using QMessageBox."""
        _log.info(f"[qt_bridge] show_message called: {severity} - {message}")
        if severity == "warning":
            QtWidgets.QMessageBox.warning(widget, "Warning", message)
        elif severity == "error":
            QtWidgets.QMessageBox.critical(widget, "Error", message)
        else:
            QtWidgets.QMessageBox.information(widget, "Info", message)
    
    result = core_apply_name(interface, session, assets_menu_ids, assets_menu_index, show_message)
    _log.info(f"[qt_bridge] apply_name_qt result: {result}")
    return result
