"""
Core publisher logic - DCC-agnostic.

This module contains all business logic that is independent of DCC (Houdini, Maya, etc.)
and can be reused across different DCC implementations.
"""

from .selector import (
    check_task_id,
    apply_task_id,
    apply_asset_params,
    get_assets_list,
    apply_name,
)

from .publisher import (
    ComponentData,
    PublishJob,
    PublishResult,
    Publisher,
)

from .job_builder import (
    JobBuilder,
)

__all__ = [
    # Selector functions
    'check_task_id',
    'apply_task_id',
    'apply_asset_params',
    'get_assets_list',
    'apply_name',
    # Publisher classes
    'ComponentData',
    'PublishJob',
    'PublishResult',
    'Publisher',
    'JobBuilder',
]
