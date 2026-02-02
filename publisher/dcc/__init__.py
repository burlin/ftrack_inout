"""
DCC-specific bridges for publisher.

Each DCC (Houdini, Maya, standalone Qt) has its own bridge that adapts
the DCC-specific parameter interface to the core ParameterInterface protocol.

Available bridges:
- houdini: HoudiniParameterInterface, build_job_from_hda, publish_callback
- maya: MayaDCCBridge (TODO)
- qt_bridge: QtBridge for standalone Qt UI
"""

# Lazy imports - bridges are only loaded when needed
__all__ = [
    'get_houdini_bridge',
    'get_maya_bridge',
    'get_qt_bridge',
]


def get_houdini_bridge():
    """Get Houdini bridge (only available inside Houdini)."""
    from .houdini import (
        HoudiniParameterInterface,
        build_job_from_hda,
        publish_callback,
        publish_dry_run_callback,
        get_target_node,
    )
    return {
        'HoudiniParameterInterface': HoudiniParameterInterface,
        'build_job_from_hda': build_job_from_hda,
        'publish_callback': publish_callback,
        'publish_dry_run_callback': publish_dry_run_callback,
        'get_target_node': get_target_node,
    }


def get_maya_bridge():
    """Get Maya bridge (only available inside Maya)."""
    from .maya import MayaDCCBridge
    return {
        'MayaDCCBridge': MayaDCCBridge,
    }


def get_qt_bridge():
    """Get Qt bridge for standalone UI."""
    from .qt_bridge import apply_task_id_qt, apply_name_qt, apply_type_qt
    return {
        'apply_task_id_qt': apply_task_id_qt,
        'apply_name_qt': apply_name_qt,
        'apply_type_qt': apply_type_qt,
    }
