"""
Test script for PublisherWidget with JobBuilder and Publisher.

Run this script to test the Qt UI widget and dry-run publish:
    python test_publisher_widget.py

This will:
1. Create PublisherWidget with test data
2. When you click "Render", it will execute dry-run publish
3. Console will show what would be published
"""

import sys
import os
import logging

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

# Add ftrack_plugins to path
current_dir = os.path.dirname(os.path.abspath(__file__))
ftrack_plugins_dir = os.path.dirname(os.path.dirname(os.path.dirname(current_dir)))
sys.path.insert(0, ftrack_plugins_dir)

try:
    from PySide2 import QtWidgets
except ImportError:
    try:
        from PySide6 import QtWidgets
    except ImportError:
        from PyQt5 import QtWidgets

from ftrack_inout.publisher.ui.publisher_widget import PublisherWidget


def setup_test_data(widget):
    """Setup test data in widget for dry-run testing."""
    print("\n" + "="*60)
    print("Setting up test data...")
    print("="*60)
    
    # Task parameters
    widget.set_parameter('task_Id', 'test-task-id-12345')
    widget.set_parameter('p_task_id', 'test-task-id-12345')
    widget.set_parameter('task_project', 'Test Project')
    widget.set_parameter('task_parent', 'Shot_010')
    widget.set_parameter('task_name', 'comp')
    
    # Asset parameters
    widget.set_parameter('p_asset_name', 'main_render')
    widget.set_parameter('p_asset_type', 'Render')
    widget.set_parameter('p_project', 'Test Project')
    widget.set_parameter('p_parent', 'Shot_010')
    
    # Snapshot
    widget.set_parameter('use_snapshot', 1)
    
    # Components
    widget.set_parameter('components', 2)
    
    # Comment
    widget.set_parameter('comment', 'Test publish from Qt UI')
    
    # Wait for component tabs to be created
    QtWidgets.QApplication.processEvents()
    
    # Set component data (if tabs are available)
    if hasattr(widget, 'component_tabs') and widget.component_tabs.count() >= 2:
        tab0 = widget.component_tabs.widget(0)
        if tab0 and hasattr(tab0, 'name_edit'):
            tab0.name_edit.setText('beauty.exr')
            tab0.file_path_edit.setText('/renders/shot_010/beauty.%04d.exr')
        
        tab1 = widget.component_tabs.widget(1)
        if tab1 and hasattr(tab1, 'name_edit'):
            tab1.name_edit.setText('main.abc')
            tab1.file_path_edit.setText('/cache/shot_010/main.abc')
    
    print("\nTest data setup complete.")
    print("Click 'Render' button to execute dry-run publish.")
    print("="*60 + "\n")


def test_job_builder_directly(widget):
    """Test JobBuilder directly (without clicking button)."""
    print("\n" + "="*60)
    print("Testing JobBuilder directly...")
    print("="*60)
    
    try:
        from ftrack_inout.publisher.core import JobBuilder, Publisher
        
        # Build job from widget
        job = JobBuilder.from_qt_widget(widget, source_dcc="test")
        
        # Print job data
        print("\nPublishJob created:")
        print(f"  task_id: {job.task_id}")
        print(f"  asset_id: {job.asset_id}")
        print(f"  asset_name: {job.asset_name}")
        print(f"  asset_type: {job.asset_type}")
        print(f"  comment: {job.comment}")
        print(f"  source_dcc: {job.source_dcc}")
        print(f"  components: {len(job.components)}")
        
        for i, comp in enumerate(job.components):
            print(f"\n  Component {i+1}:")
            print(f"    name: {comp.name}")
            print(f"    type: {comp.component_type}")
            print(f"    path: {comp.file_path}")
            print(f"    enabled: {comp.export_enabled}")
            print(f"    metadata: {comp.metadata}")
        
        # Validate
        is_valid, errors = job.validate()
        print(f"\nValidation: {'PASSED' if is_valid else 'FAILED'}")
        if errors:
            for error in errors:
                print(f"  - {error}")
        
        # Execute dry-run
        print("\n" + "-"*60)
        publisher = Publisher(dry_run=True)
        result = publisher.execute(job)
        
        print("\nPublishResult:")
        print(f"  success: {result.success}")
        print(f"  asset_version_id: {result.asset_version_id}")
        print(f"  asset_version_number: {result.asset_version_number}")
        print(f"  component_ids: {result.component_ids}")
        
    except Exception as e:
        print(f"\nError: {e}")
        import traceback
        traceback.print_exc()
    
    print("="*60 + "\n")


def main():
    """Run the test application."""
    app = QtWidgets.QApplication(sys.argv)
    
    # Create and show widget
    widget = PublisherWidget()
    widget.setWindowTitle("Universal Publisher - Test UI (Dry Run)")
    widget.resize(800, 1000)
    
    # Setup test data
    setup_test_data(widget)
    
    # Show widget
    widget.show()
    
    # Also test JobBuilder directly
    test_job_builder_directly(widget)
    
    print("\nWidget is ready. Click 'Render' to test publish workflow.")
    print("Close the window to exit.\n")
    
    sys.exit(app.exec_())


if __name__ == '__main__':
    main()
