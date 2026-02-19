"""
Core publisher engine with PublishJob pattern.

This module provides:
- ComponentData: Data for a single component
- PublishJob: Complete publish request object
- PublishResult: Result of publish execution
- Publisher: Executes PublishJob (supports dry_run mode)
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

_log = logging.getLogger(__name__)


@dataclass
class ComponentData:
    """Data for a single component to publish.
    
    Attributes:
        name: Component name (e.g., "main.abc", "snapshot")
        file_path: Path to file/sequence (None for snapshot until prepared)
        component_type: Type of component ('snapshot', 'playblast', 'file', 'sequence')
        export_enabled: Whether this component should be published
        metadata: Key-value metadata to attach to component
        sequence_pattern: For sequences - pattern like "frame.%04d.exr"
        frame_range: For sequences - (start, end) frame range
    """
    name: str
    file_path: Optional[str] = None
    component_type: str = "file"  # 'snapshot', 'playblast', 'file', 'sequence'
    export_enabled: bool = True
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    # Sequence-specific
    sequence_pattern: Optional[str] = None
    frame_range: Optional[Tuple[int, int]] = None
    
    def to_dict(self) -> dict:
        """Convert to dictionary for serialization/logging."""
        return {
            'name': self.name,
            'file_path': self.file_path,
            'component_type': self.component_type,
            'export_enabled': self.export_enabled,
            'metadata': self.metadata,
            'sequence_pattern': self.sequence_pattern,
            'frame_range': self.frame_range,
        }
    
    @classmethod
    def from_dict(cls, data: dict) -> 'ComponentData':
        """Create from dictionary."""
        return cls(
            name=data.get('name', ''),
            file_path=data.get('file_path'),
            component_type=data.get('component_type', 'file'),
            export_enabled=data.get('export_enabled', True),
            metadata=data.get('metadata', {}),
            sequence_pattern=data.get('sequence_pattern'),
            frame_range=data.get('frame_range'),
        )


@dataclass
class PublishJob:
    """Complete publish request object.
    
    Contains all data needed to execute a publish:
    - Target (task, asset)
    - Components to publish
    - Metadata and context
    
    Attributes:
        task_id: Ftrack Task ID (required)
        asset_id: Existing Asset ID (optional - use for existing asset)
        asset_name: Asset name (required if creating new asset)
        asset_type: Asset type (required if creating new asset)
        comment: Version comment
        components: List of components to publish
        source_dcc: Source DCC name ('houdini', 'maya', 'standalone')
        source_scene: Path to source scene file
        created_at: When this job was created
    """
    task_id: str
    asset_id: Optional[str] = None
    asset_name: Optional[str] = None
    asset_type: Optional[str] = None
    comment: str = ""
    components: List[ComponentData] = field(default_factory=list)
    source_dcc: str = "unknown"
    source_scene: Optional[str] = None
    created_at: datetime = field(default_factory=datetime.now)
    
    # Validation state
    _is_valid: bool = field(default=False, repr=False)
    _validation_errors: List[str] = field(default_factory=list, repr=False)
    
    def validate(self) -> Tuple[bool, List[str]]:
        """Validate the job before execution.
        
        Returns:
            Tuple of (is_valid, list_of_errors)
        """
        self._validation_errors.clear()
        
        # Task ID is required
        if not self.task_id:
            self._validation_errors.append("task_id is required")
        
        # Either asset_id or asset_name is required
        if not self.asset_id and not self.asset_name:
            self._validation_errors.append("Either asset_id or asset_name is required")
        
        # If creating new asset, asset_type is required
        if not self.asset_id and self.asset_name and not self.asset_type:
            self._validation_errors.append("asset_type is required when creating new asset")
        
        # Check components
        enabled_components = [c for c in self.components if c.export_enabled]
        if not enabled_components:
            self._validation_errors.append("No components enabled for publish")
        
        # Validate each enabled component
        for comp in enabled_components:
            if not comp.name:
                self._validation_errors.append(f"Component has no name")
            
            # File path required for non-snapshot components
            if comp.component_type not in ('snapshot',) and not comp.file_path:
                self._validation_errors.append(
                    f"Component '{comp.name}' has no file_path"
                )
        
        self._is_valid = len(self._validation_errors) == 0
        return self._is_valid, self._validation_errors
    
    @property
    def is_valid(self) -> bool:
        """Check if job is valid (call validate() first)."""
        return self._is_valid
    
    @property
    def validation_errors(self) -> List[str]:
        """Get validation errors (call validate() first)."""
        return self._validation_errors
    
    @property
    def enabled_components(self) -> List[ComponentData]:
        """Get only enabled components."""
        return [c for c in self.components if c.export_enabled]
    
    def to_dict(self) -> dict:
        """Convert to dictionary for serialization/logging."""
        return {
            'task_id': self.task_id,
            'asset_id': self.asset_id,
            'asset_name': self.asset_name,
            'asset_type': self.asset_type,
            'comment': self.comment,
            'components': [c.to_dict() for c in self.components],
            'source_dcc': self.source_dcc,
            'source_scene': self.source_scene,
            'created_at': self.created_at.isoformat(),
        }
    
    def to_json(self, indent: int = 2) -> str:
        """Convert to JSON string."""
        return json.dumps(self.to_dict(), indent=indent, ensure_ascii=False)
    
    @classmethod
    def from_dict(cls, data: dict) -> 'PublishJob':
        """Create from dictionary."""
        components = [
            ComponentData.from_dict(c) for c in data.get('components', [])
        ]
        created_at = data.get('created_at')
        if isinstance(created_at, str):
            created_at = datetime.fromisoformat(created_at)
        elif created_at is None:
            created_at = datetime.now()
        
        return cls(
            task_id=data.get('task_id', ''),
            asset_id=data.get('asset_id'),
            asset_name=data.get('asset_name'),
            asset_type=data.get('asset_type'),
            comment=data.get('comment', ''),
            components=components,
            source_dcc=data.get('source_dcc', 'unknown'),
            source_scene=data.get('source_scene'),
            created_at=created_at,
        )


@dataclass
class PublishResult:
    """Result of publish execution.

    Contains information for downstream automation:
    - Success/failure status
    - Created asset version info
    - Component IDs for transfer queue
    - Timelog info (auto-created on successful publish)
    """
    success: bool
    error_message: Optional[str] = None

    # Asset version info (for automation)
    asset_version_id: Optional[str] = None
    asset_version_number: Optional[int] = None
    asset_id: Optional[str] = None
    asset_name: Optional[str] = None

    # Component info (for transfer queue)
    component_ids: List[str] = field(default_factory=list)
    component_paths: Dict[str, str] = field(default_factory=dict)  # {comp_id: file_path}

    # Detailed info
    created_components: List[dict] = field(default_factory=list)

    # Timelog info (populated when auto-timelog succeeds)
    timelog_id: Optional[str] = None
    timelog_seconds: float = 0.0

    def to_dict(self) -> dict:
        """Convert to dictionary."""
        return {
            'success': self.success,
            'error_message': self.error_message,
            'asset_version_id': self.asset_version_id,
            'asset_version_number': self.asset_version_number,
            'asset_id': self.asset_id,
            'asset_name': self.asset_name,
            'component_ids': self.component_ids,
            'component_paths': self.component_paths,
            'created_components': self.created_components,
            'timelog_id': self.timelog_id,
            'timelog_seconds': self.timelog_seconds,
        }


class Publisher:
    """Executes PublishJob.
    
    Supports two modes:
    - dry_run=True: Just prints what would be done (for debugging)
    - dry_run=False: Actually publishes to Ftrack
    """
    
    def __init__(self, session=None, dry_run: bool = True, auto_timelog: bool = True):
        """Initialize publisher.

        Args:
            session: Ftrack API session (optional; if None, uses shared session with cache)
            dry_run: If True, just print actions without executing
            auto_timelog: If True, automatically create a timelog on successful publish.
                Set to False when the caller handles time logging itself (e.g. Maya
                batch publish with user-editable time dialog).
        """
        if session is None and not dry_run:
            try:
                from ..common.session_factory import get_shared_session
                session = get_shared_session()
                if session:
                    _log.info("[Publisher] Using shared session (with cache)")
            except ImportError:
                pass
            except Exception as e:
                _log.debug(f"[Publisher] Could not get shared session: {e}")
        self.session = session
        self.dry_run = dry_run
        self.auto_timelog = auto_timelog
    
    def execute(self, job: PublishJob) -> PublishResult:
        """Execute a publish job.
        
        Args:
            job: PublishJob to execute
            
        Returns:
            PublishResult with success/failure and created entities
        """
        _log.info(f"[Publisher] execute() called, dry_run={self.dry_run}")
        
        # Validate job first
        is_valid, errors = job.validate()
        if not is_valid:
            error_msg = "Validation failed:\n" + "\n".join(f"  - {e}" for e in errors)
            _log.error(f"[Publisher] {error_msg}")
            return PublishResult(success=False, error_message=error_msg)
        
        if self.dry_run:
            return self._execute_dry_run(job)
        else:
            return self._execute_real(job)
    
    def _execute_dry_run(self, job: PublishJob) -> PublishResult:
        """Dry run - just print what would be done."""
        separator = "=" * 70
        
        print(f"\n{separator}")
        print("  DRY RUN - PublishJob Preview")
        print(separator)
        
        # Target info
        print(f"\n{'Target:':<15}")
        print(f"  Task ID:      {job.task_id}")
        if job.asset_id:
            print(f"  Asset ID:     {job.asset_id} (existing)")
        else:
            print(f"  Asset Name:   {job.asset_name} (NEW)")
            print(f"  Asset Type:   {job.asset_type}")
        
        # Context
        print(f"\n{'Context:':<15}")
        print(f"  Source DCC:   {job.source_dcc}")
        print(f"  Scene:        {job.source_scene or '(not saved)'}")
        print(f"  Comment:      {job.comment or '(no comment)'}")
        print(f"  Created at:   {job.created_at.strftime('%Y-%m-%d %H:%M:%S')}")
        
        # Components
        enabled = job.enabled_components
        disabled = [c for c in job.components if not c.export_enabled]
        
        print(f"\n{'Components:':<15} ({len(enabled)} enabled, {len(disabled)} disabled)")
        print("-" * 70)
        
        for i, comp in enumerate(job.components, 1):
            status = "✓ ENABLED" if comp.export_enabled else "✗ DISABLED"
            print(f"\n  [{i}] {comp.name}")
            print(f"      Status:   {status}")
            print(f"      Type:     {comp.component_type}")
            print(f"      Path:     {comp.file_path or '(will be generated)'}")
            if comp.sequence_pattern:
                print(f"      Pattern:  {comp.sequence_pattern}")
            if comp.frame_range:
                print(f"      Frames:   {comp.frame_range[0]} - {comp.frame_range[1]}")
            if comp.metadata:
                print(f"      Metadata: {comp.metadata}")
        
        print(f"\n{separator}")
        print("  Actions that would be performed:")
        print(separator)
        
        actions = []
        if job.asset_id:
            actions.append(f"1. Get existing Asset: {job.asset_id}")
        else:
            actions.append(f"1. Create new Asset: '{job.asset_name}' (type: {job.asset_type})")
        
        actions.append(f"2. Create AssetVersion (comment: '{job.comment or 'none'}')")
        
        for i, comp in enumerate(enabled, 1):
            if comp.component_type == 'snapshot':
                actions.append(f"3.{i}. Create 'snapshot' component from: {comp.file_path}")
            elif comp.component_type == 'playblast':
                actions.append(f"3.{i}. Encode media: {comp.file_path}")
            else:
                actions.append(f"3.{i}. Create component '{comp.name}' from: {comp.file_path}")
        
        actions.append(f"4. Update asset metadata index")
        actions.append(f"5. Commit session")
        
        for action in actions:
            print(f"  {action}")
        
        print(f"\n{separator}")
        print("  DRY RUN COMPLETE - No changes made")
        print(f"{separator}\n")
        
        # Return mock result
        mock_component_ids = [f"mock-comp-{i}" for i in range(len(enabled))]
        mock_paths = {
            f"mock-comp-{i}": comp.file_path or f"(snapshot-path-{i})"
            for i, comp in enumerate(enabled)
        }
        
        return PublishResult(
            success=True,
            asset_version_id="mock-version-id-12345",
            asset_version_number=999,
            asset_id=job.asset_id or "mock-asset-id-67890",
            asset_name=job.asset_name or "(existing asset)",
            component_ids=mock_component_ids,
            component_paths=mock_paths,
            created_components=[
                {'name': comp.name, 'type': comp.component_type, 'id': f'mock-comp-{i}'}
                for i, comp in enumerate(enabled)
            ]
        )
    
    def _execute_real(self, job: PublishJob) -> PublishResult:
        """Real execution - publish to Ftrack."""
        import os
        
        if not self.session:
            return PublishResult(
                success=False,
                error_message="Ftrack session is not available"
            )
        
        _log.info("[Publisher] Starting real publish...")
        session = self.session
        
        try:
            # ---------------------------------------------------------------
            # 1. Get Task (use session.get for cache)
            # ---------------------------------------------------------------
            _log.info(f"[Publisher] Fetching task: {job.task_id}")
            task = session.get('Task', job.task_id)
            if not task:
                return PublishResult(success=False, error_message=f"Task not found: {job.task_id}")
            asset_parent = task['parent']
            _log.info(f"[Publisher] Task: {task['name']}, Parent: {asset_parent['name']}")
            
            # ---------------------------------------------------------------
            # 2. Get or Create Asset
            # ---------------------------------------------------------------
            asset = None
            
            if job.asset_id:
                # Use existing asset (session.get uses cache)
                _log.info(f"[Publisher] Using existing asset: {job.asset_id}")
                asset = session.get('Asset', job.asset_id)
                if not asset:
                    return PublishResult(success=False, error_message=f"Asset not found: {job.asset_id}")
            else:
                # Check if asset with this name already exists (case-insensitive)
                _log.info(f"[Publisher] Checking if asset '{job.asset_name}' exists...")
                
                existing_assets = session.query(
                    f"Asset where parent.id is '{asset_parent['id']}'"
                ).all()
                
                name_lower = job.asset_name.lower()
                for existing in existing_assets:
                    if existing['name'].lower() == name_lower:
                        asset = existing
                        _log.info(f"[Publisher] Found existing asset: {asset['name']} ({asset['id']})")
                        break
                
                if asset is None:
                    # Create new asset
                    _log.info(f"[Publisher] Creating new asset: {job.asset_name} (type: {job.asset_type})")
                    
                    asset_type = session.query(
                        f'AssetType where name is "{job.asset_type}"'
                    ).one()
                    
                    asset = session.create('Asset', {
                        'name': job.asset_name,
                        'type': asset_type,
                        'parent': asset_parent
                    })
            
            # ---------------------------------------------------------------
            # 3. Create AssetVersion
            # ---------------------------------------------------------------
            _log.info("[Publisher] Creating AssetVersion...")
            
            version_data = {
                'asset': asset,
                'task': task
            }
            
            asset_version = session.create('AssetVersion', version_data)
            
            # Commit to get version number
            _log.info("[Publisher] Initial commit...")
            session.commit()
            
            version_number = asset_version['version']
            _log.info(f"[Publisher] Created version {version_number}")
            
            # Create Note for comment (ftrack uses Notes, not comment field)
            if job.comment:
                try:
                    api_user = session.api_user
                    # User lookup by username - query required (no get by username)
                    user = session.query(f'User where username is "{api_user}"').first()
                    if user:
                        asset_version.create_note(job.comment, author=user)
                        _log.info(f"[Publisher] Created note: {job.comment[:50]}...")
                    else:
                        _log.warning(f"[Publisher] Could not find user '{api_user}' for note author")
                except Exception as note_err:
                    _log.warning(f"[Publisher] Failed to create note: {note_err}")
            
            # ---------------------------------------------------------------
            # 4. Create Components
            # ---------------------------------------------------------------
            created_components = []
            component_ids = []
            component_paths = {}
            
            for comp in job.enabled_components:
                _log.info(f"[Publisher] Processing component: {comp.name} ({comp.component_type})")
                
                try:
                    comp_entity = None
                    
                    if comp.component_type == 'playblast':
                        # Playblast uses encode_media
                        if comp.file_path:
                            file_path = os.path.normpath(comp.file_path)
                            _log.info(f"[Publisher] Encoding media: {file_path}")
                            asset_version.encode_media(file_path)
                            try:
                                session.commit()
                            except Exception as ce:
                                _log.warning(f"[Publisher] Commit after encode_media: {ce}")
                            continue
                    
                    else:
                        # Regular component (snapshot, file, sequence)
                        file_path = comp.file_path
                        if file_path:
                            try:
                                file_path = os.path.normpath(file_path)
                            except Exception:
                                pass
                        
                        # Skip missing files (unless it's a sequence pattern)
                        if file_path:
                            is_sequence = (
                                '%' in file_path or 
                                '@' in file_path or 
                                ('[' in file_path and ']' in file_path)
                            )
                            if not is_sequence and not os.path.exists(file_path):
                                _log.warning(f"[Publisher] File not found, skipping: {file_path}")
                                continue
                        
                        # Prepare metadata
                        metadata = dict(comp.metadata) if comp.metadata else {}
                        
                        _log.info(f"[Publisher] Creating component: {comp.name}, path: {file_path}")
                        
                        comp_entity = asset_version.create_component(
                            file_path,
                            data={
                                'name': comp.name,
                                'metadata': metadata
                            },
                            location='auto'
                        )
                        
                        created_components.append(comp_entity)
                        component_ids.append(comp_entity['id'])
                        component_paths[comp_entity['id']] = file_path
                        
                        _log.info(f"[Publisher] Component created: {comp_entity['id']}")
                
                except Exception as comp_error:
                    _log.error(f"[Publisher] Failed to create component {comp.name}: {comp_error}", exc_info=True)
            
            # ---------------------------------------------------------------
            # 5. Update Asset Metadata Index
            # ---------------------------------------------------------------
            _log.info("[Publisher] Updating asset metadata index...")
            try:
                asset_meta = asset.get('metadata') or {}
                if not isinstance(asset_meta, dict):
                    try:
                        asset_meta = dict(asset_meta)
                    except Exception:
                        asset_meta = {}
                
                for comp_entity in created_components:
                    try:
                        comp_name = comp_entity.get('name', '') or ''
                        raw_ext = comp_entity.get('file_type', '') or ''
                        ext = str(raw_ext).lstrip('.')
                        key = f"{comp_name}.{ext}" if (comp_name and ext) else comp_name or ''
                        comp_id = comp_entity.get('id')
                        if key and comp_id:
                            asset_meta[key] = comp_id
                            _log.debug(f"[Publisher] Asset metadata: {key} = {comp_id}")
                    except Exception as _e:
                        _log.warning(f"[Publisher] Failed to update asset metadata for component: {_e}")
                
                asset['metadata'] = asset_meta
                _log.info(f"[Publisher] Updated asset metadata: {len(created_components)} components indexed")
            except Exception as _e:
                _log.warning(f"[Publisher] Failed to update asset metadata index: {_e}")
            
            # ---------------------------------------------------------------
            # 6. Final Commit
            # ---------------------------------------------------------------
            _log.info("[Publisher] Final commit...")
            session.commit()
            
            # Update cache: load new entities so cache is warm for browser/finput
            try:
                _ = session.get('AssetVersion', asset_version['id'])
                for cid in component_ids:
                    session.get('Component', cid)
                session.get('Asset', asset['id'])
                _log.debug("[Publisher] Cache updated with new version/components/asset")
            except Exception as cache_err:
                _log.debug(f"[Publisher] Cache warm-up (non-critical): {cache_err}")
            
            _log.info(f"[Publisher] Publish complete! Version {version_number}, {len(created_components)} components")

            # ---------------------------------------------------------------
            # 7. Auto-timelog
            # ---------------------------------------------------------------
            timelog_id = None
            timelog_seconds = 0.0
            if self.auto_timelog:
                try:
                    from ...common.timelog import record_publish, create_ftrack_timelog
                    per_task_secs, _total_str = record_publish(task_count=1)
                    timelog_seconds = per_task_secs
                    timelog_id = create_ftrack_timelog(
                        session, job.task_id, per_task_secs,
                        comment="Auto-logged on publish",
                    )
                    if timelog_id:
                        _log.info(f"[Publisher] Timelog created: {timelog_id} ({per_task_secs:.0f}s)")
                except Exception as tl_err:
                    _log.warning(f"[Publisher] Auto-timelog failed (non-critical): {tl_err}")

            return PublishResult(
                success=True,
                asset_version_id=asset_version['id'],
                asset_version_number=version_number,
                asset_id=asset['id'],
                asset_name=asset['name'],
                component_ids=component_ids,
                component_paths=component_paths,
                created_components=[
                    {
                        'name': c.get('name', ''),
                        'type': c.get('file_type', ''),
                        'id': c.get('id', '')
                    }
                    for c in created_components
                ],
                timelog_id=timelog_id,
                timelog_seconds=timelog_seconds,
            )
            
        except Exception as e:
            _log.error(f"[Publisher] Publish failed: {e}", exc_info=True)
            return PublishResult(
                success=False,
                error_message=str(e)
            )
