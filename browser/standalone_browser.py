"""
Standalone Ftrack Browser

Universal ftrack browser without Houdini dependencies.
Can be used in any applications or as standalone application.
"""

import sys
import os
import logging
from PySide6.QtWidgets import QApplication, QMainWindow, QVBoxLayout, QWidget
from PySide6.QtCore import QTimer

# Add path to modules
current_dir = os.path.dirname(__file__)
if current_dir not in sys.path:
    sys.path.insert(0, current_dir)

from browser_ui import FtrackBrowserUI
from simple_api_client import SimpleFtrackClient
from cache_preloader import CachePreloader

logger = logging.getLogger(__name__)


class StandaloneFtrackBrowser(QMainWindow):
    """
    Standalone ftrack browser without Houdini dependencies
    """
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Ftrack Browser - Standalone")
        self.setMinimumSize(800, 600)
        
        # Initialize components
        self.api_client = None
        self.cache_preloader = None
        self.browser_ui = None
        
        self.setup_ui()
        self.setup_connections()
        
        # Auto-connect to ftrack
        QTimer.singleShot(100, self.auto_connect)
    
    def setup_ui(self):
        """Setup interface"""
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        
        layout = QVBoxLayout(central_widget)
        layout.setContentsMargins(5, 5, 5, 5)
        
        # Create browser UI
        self.browser_ui = FtrackBrowserUI()
        layout.addWidget(self.browser_ui)
        
        # Hide Houdini-specific buttons
        self.hide_houdini_buttons()
    
    def hide_houdini_buttons(self):
        """Hide Houdini-specific buttons"""
        if hasattr(self.browser_ui, 'hda_params_btn'):
            self.browser_ui.hda_params_btn.setVisible(False)
        if hasattr(self.browser_ui, 'task_btn'):
            self.browser_ui.task_btn.setVisible(False)
        if hasattr(self.browser_ui, 'snapshot_btn'):
            self.browser_ui.snapshot_btn.setVisible(False)
    
    def setup_connections(self):
        """Setup signal connections"""
        if self.browser_ui:
            # Connect basic signals
            if hasattr(self.browser_ui, 'refresh_btn'):
                self.browser_ui.refresh_btn.clicked.connect(self.refresh_data)
            
            # Add double-click handler for opening files
            if hasattr(self.browser_ui, 'components_tree'):
                self.browser_ui.components_tree.itemDoubleClicked.connect(self.on_component_double_clicked)
    
    def auto_connect(self):
        """Automatic connection to ftrack"""
        try:
            self.api_client = SimpleFtrackClient()
            if self.api_client.session:
                logger.info("Connected to ftrack")
                
                # Initialize cache
                self.cache_preloader = CachePreloader(self.api_client.session)
                
                # Load data into UI
                if self.browser_ui:
                    self.browser_ui.set_api_client(self.api_client)
                    self.refresh_data()
            else:
                logger.error("Failed to connect to ftrack")
                
        except Exception as e:
            logger.error(f"Connection error: {e}")
    
    def refresh_data(self):
        """Update data"""
        if self.browser_ui and self.api_client:
            try:
                self.browser_ui.refresh_data()
                logger.info("Data refreshed")
            except Exception as e:
                logger.error(f"Refresh error: {e}")
    
    def on_component_double_clicked(self, item, column):
        """Handler for component double-click"""
        try:
            # Get component data
            component_data = item.data(0, 32)  # UserRole
            if component_data and 'file_path' in component_data:
                file_path = component_data['file_path']
                
                # Open file with system application
                import subprocess
                import platform
                
                if platform.system() == 'Windows':
                    os.startfile(file_path)
                elif platform.system() == 'Darwin':  # macOS
                    subprocess.run(['open', file_path])
                else:  # Linux
                    subprocess.run(['xdg-open', file_path])
                
                logger.info(f"Opened file: {os.path.basename(file_path)}")
                
        except Exception as e:
            logger.error(f"Failed to open file: {e}")
    
    def get_selected_component_data(self):
        """Get selected component data"""
        if not self.browser_ui or not hasattr(self.browser_ui, 'components_tree'):
            return None
        
        current_item = self.browser_ui.components_tree.currentItem()
        if current_item:
            return current_item.data(0, 32)  # UserRole
        return None
    
    def get_current_asset_version_id(self):
        """Get current asset version ID"""
        component_data = self.get_selected_component_data()
        if component_data:
            return component_data.get('asset_version_id')
        return None
    
    def get_current_component_info(self):
        """Get current component information"""
        component_data = self.get_selected_component_data()
        if component_data:
            return {
                'component_id': component_data.get('id'),
                'component_name': component_data.get('name'),
                'asset_version_id': component_data.get('asset_version_id'),
                'file_path': component_data.get('file_path')
            }
        return None


class StandaloneBrowserApp:
    """Class for running browser as standalone application"""
    
    def __init__(self):
        self.app = None
        self.browser = None
    
    def run(self):
        """Run application"""
        # Create QApplication if it doesn't exist
        if not QApplication.instance():
            self.app = QApplication(sys.argv)
        else:
            self.app = QApplication.instance()
        
        # Setup logging
        logging.basicConfig(
            level=logging.INFO,
            format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
        )
        
        # Create and show browser
        self.browser = StandaloneFtrackBrowser()
        self.browser.show()

        # Run event loop
        if self.app:
            return self.app.exec()
        return 0


# Functions for integration into other applications
def create_browser_widget(parent=None):
    """
    Create browser widget for embedding in other applications
    
    Args:
        parent: parent widget
        
    Returns:
        StandaloneFtrackBrowser: browser widget
    """
    return StandaloneFtrackBrowser(parent)


def get_ftrack_data(asset_name=None, project_name=None):
    """
    Get data from ftrack without UI (for scripts)
    
    Args:
        asset_name: asset name for filtering
        project_name: project name for filtering
        
    Returns:
        dict: data from ftrack
    """
    try:
        client = SimpleFtrackClient()
        if not client.session:
            return None
        
        # Base query
        query = "select id, name, version_number from AssetVersion"
        
        # Add filters
        filters = []
        if project_name:
            filters.append(f"asset.parent.project.name is '{project_name}'")
        if asset_name:
            filters.append(f"asset.name is '{asset_name}'")
        
        if filters:
            query += " where " + " and ".join(filters)
        
        # Execute query
        asset_versions = client.session.query(query).all()
        
        return {
            'asset_versions': [
                {
                    'id': av['id'],
                    'name': av['name'],
                    'version': av['version_number']
                }
                for av in asset_versions
            ]
        }
        
    except Exception as e:
        logger.error(f"Failed to get ftrack data: {e}")
        return None


if __name__ == "__main__":
    # Run as standalone application
    app = StandaloneBrowserApp()
    sys.exit(app.run())