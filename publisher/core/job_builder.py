"""
JobBuilder - builds PublishJob from different sources.

This module provides builders that collect data from:
- Qt PublisherWidget
- Houdini HDA node (TODO)
- Maya node (TODO)
- Dictionary/JSON (for testing)
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from .publisher import ComponentData, PublishJob

_log = logging.getLogger(__name__)


class JobBuilder:
    """Builds PublishJob from different sources."""
    
    @staticmethod
    def from_qt_widget(widget, source_dcc: str = "standalone") -> PublishJob:
        """Build PublishJob from Qt PublisherWidget.
        
        Args:
            widget: PublisherWidget instance
            source_dcc: Source DCC name (default: "standalone")
            
        Returns:
            PublishJob ready for execution
        """
        _log.info("[JobBuilder] Building PublishJob from Qt widget")
        
        components: List[ComponentData] = []
        
        # 1. Snapshot component
        use_snapshot = widget.get_parameter('use_snapshot')
        if use_snapshot:
            _log.debug("[JobBuilder] Adding snapshot component")
            components.append(ComponentData(
                name='snapshot',
                file_path=None,  # Will be created during real publish
                component_type='snapshot',
                export_enabled=True,
                metadata={}  # No 'dcc' tag for snapshot
            ))
        
        # 2. Playblast component
        use_playblast = widget.get_parameter('use_playblast')
        if use_playblast:
            playblast_path = widget.get_parameter('playblast') or ''
            _log.debug(f"[JobBuilder] Adding playblast component: {playblast_path}")
            components.append(ComponentData(
                name='playblast',
                file_path=playblast_path,
                component_type='playblast',
                export_enabled=True,
                metadata={'dcc': source_dcc}
            ))
        
        # 3. File components from tabs
        component_count = widget.get_parameter('components') or 0
        _log.debug(f"[JobBuilder] Processing {component_count} file components")
        
        # Access component tabs directly
        if hasattr(widget, 'component_tabs'):
            for i in range(widget.component_tabs.count()):
                tab = widget.component_tabs.widget(i)
                if tab and hasattr(tab, 'get_component_data'):
                    comp_data = tab.get_component_data()
                    idx = i + 1  # 1-based index (matches HDA parameter naming)
                    
                    # Read with indexed keys (comp_name1, file_path1, export1, etc.)
                    comp_name = comp_data.get(f'comp_name{idx}', f'component_{idx}')
                    file_path = comp_data.get(f'file_path{idx}', '')
                    export_val = comp_data.get(f'export{idx}', 1)
                    export_enabled = (export_val == 1 or export_val == True)
                    
                    # Collect metadata from component
                    metadata = {'dcc': source_dcc}
                    meta_count = comp_data.get(f'meta_count{idx}', 0)
                    for m in range(1, meta_count + 1):
                        key = comp_data.get(f'key{idx}_{m}', '')
                        value = comp_data.get(f'value{idx}_{m}', '')
                        if key:
                            metadata[key] = value
                    
                    # Determine if it's a sequence
                    component_type = 'file'
                    sequence_pattern = None
                    if file_path and _is_sequence_pattern(file_path):
                        component_type = 'sequence'
                        sequence_pattern = file_path
                    
                    _log.debug(
                        f"[JobBuilder] Adding component {idx}: "
                        f"name='{comp_name}', type='{component_type}', enabled={export_enabled}, "
                        f"path='{file_path}'"
                    )
                    
                    components.append(ComponentData(
                        name=comp_name,
                        file_path=file_path,
                        component_type=component_type,
                        export_enabled=export_enabled,
                        metadata=metadata,
                        sequence_pattern=sequence_pattern,
                    ))
        
        # Build PublishJob
        job = PublishJob(
            task_id=widget.get_parameter('p_task_id') or '',
            asset_id=widget.get_parameter('p_asset_id') or None,
            asset_name=widget.get_parameter('p_asset_name') or None,
            asset_type=widget.get_parameter('p_asset_type') or None,
            comment=widget.get_parameter('comment') or '',
            components=components,
            source_dcc=source_dcc,
            source_scene=None,  # TODO: get from widget if available
        )
        
        _log.info(
            f"[JobBuilder] Built PublishJob: task={job.task_id}, "
            f"asset={job.asset_id or job.asset_name}, "
            f"components={len(components)}"
        )
        
        return job
    
    @staticmethod
    def from_dict(data: Dict[str, Any]) -> PublishJob:
        """Build PublishJob from dictionary.
        
        Useful for testing and loading saved jobs.
        
        Args:
            data: Dictionary with job data
            
        Returns:
            PublishJob
        """
        return PublishJob.from_dict(data)
    
    @staticmethod
    def from_houdini_node(node, session=None) -> PublishJob:
        """Build PublishJob from Houdini HDA node.
        
        Args:
            node: Houdini node (hou.Node) or node path (str)
            session: Ftrack session for metadata lookup (optional)
            
        Returns:
            PublishJob
        """
        try:
            from ..dcc.houdini import build_job_from_hda
            return build_job_from_hda(node)
        except ImportError as e:
            raise NotImplementedError(
                f"Houdini bridge not available: {e}. "
                "Make sure Houdini is running and ftrack_inout is in PYTHONPATH."
            )
    
    @staticmethod
    def from_maya_node(node_name: str, session=None) -> PublishJob:
        """Build PublishJob from Maya node.
        
        Args:
            node_name: Maya node name (string)
            session: Ftrack session for metadata lookup (optional)
            
        Returns:
            PublishJob
        """
        try:
            from ..dcc.maya import build_job_from_maya_node
            return build_job_from_maya_node(node_name)
        except ImportError as e:
            raise NotImplementedError(
                f"Maya bridge not available: {e}. "
                "Make sure Maya is running and ftrack_inout is in PYTHONPATH."
            )


def _is_sequence_pattern(path: str) -> bool:
    """Check if path contains sequence pattern.
    
    Detects patterns like:
    - %04d, %d
    - $F, $F4
    - @, @@@@
    - #, ####
    - [1-100]
    - #{4}
    """
    if not path:
        return False
    
    sequence_indicators = [
        '%d', '%0',           # printf style
        '$F',                 # Houdini style
        '@',                  # Nuke style
        '#',                  # fileseq/Nuke style
        '#{',                 # Maya/other style
    ]
    
    # Check for indicators (but avoid false positives from # in other contexts)
    for indicator in sequence_indicators:
        if indicator in path:
            # For '#' alone, make sure it's part of filename pattern (not a comment)
            if indicator == '#':
                # Check if # is surrounded by . or _ (typical sequence pattern)
                import re
                if re.search(r'[._]#+[._]', path) or path.endswith('#'):
                    return True
            else:
                return True
    
    return False
