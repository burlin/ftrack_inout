# Universal Publisher Architecture Plan

## Overview
Create a modular, DCC-agnostic publisher that can handle different component types (snapshot, playblast, file components) with configurable rules, while maintaining separation between DCC-dependent and DCC-independent code.

## Directory Structure

```
ftrack_plugins/ftrack_inout/publisher/
├── __init__.py                    # Package initialization, dependency setup
├── core.py                        # Main publisher engine (DCC-agnostic)
├── component_types.py             # Component type definitions and base classes
├── rules/                         # Component publishing rules
│   ├── __init__.py
│   ├── base_rule.py              # Base rule class
│   ├── snapshot_rule.py          # Snapshot component rules
│   ├── playblast_rule.py         # Playblast component rules
│   ├── file_component_rule.py    # File component rules (includes sequences)
│   └── custom_component_rule.py  # Custom/plugin component rules
├── dcc/                           # DCC-specific implementations
│   ├── __init__.py
│   ├── base.py                   # Base DCC interface
│   ├── houdini/
│   │   ├── __init__.py
│   │   ├── functions.py          # DCC-specific functions (saveArchive, find_nodes, etc.)
│   │   └── ui_bridge.py          # HDA parameter reading bridge (supports target_asset)
│   ├── maya/
│   │   └── __init__.py
│   ├── blender/
│   │   └── __init__.py
│   └── ue5/
│       └── __init__.py
├── ui/                            # Standalone Qt UI (DCC-independent)
│   ├── __init__.py
│   ├── publisher_widget.py       # Main Qt widget (copy of Houdini HDA interface)
│   ├── component_tab_widget.py    # Component tab UI
│   └── metadata_widget.py        # Metadata key/value UI
└── utils/                         # Shared utilities
    ├── __init__.py
    ├── metadata.py                # Metadata handling utilities
    ├── asset_index.py             # Asset metadata indexing (name.ext -> component_id)
    └── dcc_tagger.py              # DCC name tagging on components
```

## Component Types

### 1. Snapshot Component
- **Purpose**: Save scene file (.hip, .ma, .blend, etc.)
- **DCC Functions**: `save_scene_archive()` - DCC-specific scene saving
- **Metadata**: 
  - `ilink`: JSON array of component IDs used in scene
  - No `dcc` tag (to avoid conflicts with other DCCs)
- **Rules**:
  - Check if `use_snapshot` parameter is enabled
  - Collect linked component IDs from scene
  - Save scene archive
  - Create component with metadata

### 2. Playblast Component
- **Purpose**: Encode media file (video/sequence)
- **DCC Functions**: `get_playblast_path()` - Get playblast file path from UI
- **Metadata**:
  - `dcc`: DCC name (e.g., "houdini")
- **Rules**:
  - Check if `use_playblast` parameter is enabled
  - Validate playblast file exists
  - Use `asset_version.encode_media()` for encoding
  - No component name needed (handled by encode_media)

### 3. File Component (including Sequences)
- **Purpose**: Publish file or file sequence
- **Note**: Sequences are just a component type in Ftrack, handled the same way
- **DCC Functions**: 
  - `get_component_count()` - Get number of components from UI
  - `get_component_data(index)` - Get component name, path, metadata for index
  - `validate_file_path(path)` - Check if file/sequence exists
  - `normalize_sequence_path(path)` - Convert sequence to proper format (if needed)
- **Metadata**:
  - Custom metadata from UI (key/value pairs)
  - `dcc`: DCC name (parent DCC that created the component)
- **Rules**:
  - Iterate through component count
  - Check `export{n}` toggle for each component
  - Validate file/sequence exists (skip if missing and not sequence token)
  - Handle sequence formatting (`.vdb`, `.exr`, etc.) - normalize to Ftrack format
  - Create component with name and metadata

### 4. Custom Component (Extensible)
- **Purpose**: Allow adding custom component types (e.g., JSON metadata, special elements)
- **Rules**:
  - Enable/disable via parameter (like `use_snapshot`, `use_playblast`)
  - Custom preparation logic via plugin/rule
  - Follows same metadata and indexing rules

## Core Publisher Engine

### `publisher/core.py`

```python
class Publisher:
    """Main publisher engine - DCC-agnostic."""
    
    def __init__(self, session, dcc_bridge, rules_config):
        self.session = session
        self.dcc_bridge = dcc_bridge  # DCC-specific functions bridge
        self.rules = rules_config      # Component rules configuration
    
    def prepare_all_components(self, target_node, task_id, asset_id=None, asset_name=None, asset_type=None):
        """Prepare all components before creating asset version.
        
        This stage:
        - Validates prerequisites
        - Prepares all component data (including saving snapshot file)
        - Validates all components
        - Does NOT create asset version or components in Ftrack
        
        Returns:
            (success: bool, error_message: str, prepared_components: list[dict])
        
        prepared_components: List of component data dicts ready for publishing.
        """
        prepared_components = []
        
        try:
            # 1. Validate prerequisites (task_id, asset_id/name)
            validation_result = self._validate_prerequisites(target_node, task_id, asset_id, asset_name, asset_type)
            if not validation_result[0]:
                return False, validation_result[1], []
            
            # 2. Prepare each component type according to rules
            #    Each rule checks its own enable/disable parameter
            for rule_name, rule in self.rules.items():
                if not rule.should_publish(target_node, self.dcc_bridge):
                    continue  # Skip if disabled
                
                try:
                    # Prepare component(s) - this includes saving files (e.g., snapshot)
                    if hasattr(rule, 'prepare_components'):  # File components (multiple)
                        components_data = rule.prepare_components(target_node, self.dcc_bridge)
                        # Validate all components
                        for comp_data in components_data:
                            is_valid, error_msg = rule.validate_component_data(comp_data, self.dcc_bridge)
                            if not is_valid:
                                return False, f"{rule_name} component '{comp_data.get('name', 'unknown')}': {error_msg}", []
                        prepared_components.extend(components_data)
                    else:  # Single component (snapshot, playblast)
                        component_data = rule.prepare_component(target_node, self.dcc_bridge)
                        # Validate
                        is_valid, error_msg = rule.validate_component_data(component_data, self.dcc_bridge)
                        if not is_valid:
                            return False, f"{rule_name}: {error_msg}", []
                        prepared_components.append(component_data)
                
                except Exception as e:
                    error_msg = f"Error preparing {rule_name}: {str(e)}"
                    return False, error_msg, []
            
            return True, "", prepared_components
            
        except Exception as e:
            # On any error: return error message
            error_msg = f"Preparation failed: {str(e)}"
            return False, error_msg, []
    
    def publish(self, target_node, task_id, asset_id=None, asset_name=None, asset_type=None):
        """Main publish method.
        
        Process:
        1. Prepare all components (including saving snapshot file)
        2. Get or create asset
        3. Create asset version
        4. Publish all prepared components
        5. Update asset metadata index
        6. Commit session
        7. Update node parameters
        
        Returns:
            (success: bool, error_message: str, created_components: list)
        
        On error: Does NOT commit session, returns error message.
        """
        try:
            # 1. Prepare all components (this includes saving snapshot file)
            prep_success, prep_error, prepared_components = self.prepare_all_components(
                target_node, task_id, asset_id, asset_name, asset_type
            )
            if not prep_success:
                return False, prep_error, []
            
            # 2. Get or create asset
            asset, asset_id, asset_name, asset_type = self._get_or_create_asset(
                task_id, asset_id, asset_name, asset_type
            )
            
            # 3. Create asset version
            task = self.session.get('Task', task_id)
            comment = self.dcc_bridge.read_parameter(target_node, 'comment') or ''
            asset_version = self.session.create('AssetVersion', {
                'asset': asset,
                'task': task,
                'comment': comment
            })
            
            # 4. Publish all prepared components
            created_components = []
            for comp_data in prepared_components:
                # Find the rule that prepared this component
                rule = self._find_rule_for_component(comp_data)
                if not rule:
                    return False, f"Could not find rule for component: {comp_data.get('name')}", []
                
                # Publish component
                component = rule.publish(self.session, asset_version, comp_data, self.dcc_bridge)
                created_components.append(component)
            
            # 5. Update asset metadata index
            if created_components:
                self._update_asset_metadata_index(asset, created_components)
            
            # 6. Commit session (only if all succeeded)
            self.session.commit()
            
            # 7. Update node parameters
            self._update_node_parameters(target_node, asset_version, asset, task)
            
            return True, "", created_components
            
        except Exception as e:
            # On any error: do NOT commit, return error message
            error_msg = f"Publish failed: {str(e)}"
            return False, error_msg, []
```

## DCC Bridge Interface

### `publisher/dcc/base.py`

```python
class DCCBridge:
    """Base interface for DCC-specific functions."""
    
    def get_dcc_name(self) -> str:
        """Return DCC name (e.g., 'houdini', 'maya')."""
        raise NotImplementedError
    
    def get_target_node(self, source_node) -> Any:
        """Get target node from target_asset parameter.
        
        Note: Only implemented in Houdini (for HDA parameter forwarding).
        In Maya/Qt standalone, returns source_node.
        """
        return source_node  # Default: no target_asset support
    
    def read_parameter(self, node, param_name: str) -> Any:
        """Read parameter value from node."""
        raise NotImplementedError
    
    # Snapshot functions
    def save_scene_archive(self, node) -> str:
        """Save scene archive and return path."""
        raise NotImplementedError
    
    def find_linked_component_ids(self, attribute_name: str) -> list[str]:
        """Find all component IDs from scene nodes."""
        raise NotImplementedError
    
    # Playblast functions
    def get_playblast_path(self, node) -> str | None:
        """Get playblast file path from node."""
        raise NotImplementedError
    
    # File component functions
    def get_component_count(self, node) -> int:
        """Get number of components to publish."""
        raise NotImplementedError
    
    def get_component_data(self, node, index: int) -> dict:
        """Get component data (name, path, metadata) for index.
        
        Returns:
            {
                'name': str,
                'file_path': str,
                'export_enabled': bool,
                'metadata': dict  # key/value pairs
            }
        """
        raise NotImplementedError
    
    def validate_file_path(self, path: str) -> bool:
        """Validate file or sequence exists.
        
        For sequences: check if sequence tokens are present (%04d, @, [1-100])
        For files: check if file exists on disk
        """
        raise NotImplementedError
    
    def normalize_sequence_path(self, path: str) -> str:
        """Normalize sequence path to Ftrack format if needed.
        
        Handles sequence extensions: .vdb, .exr, .jpg, .bgeo, .tiff, .png, .bgeo.sc
        Converts to format: dirname/basename%04d.ext [start-end]
        """
        raise NotImplementedError
```

### `publisher/dcc/houdini/ui_bridge.py`

```python
class HoudiniUIBridge(DCCBridge):
    """Houdini-specific UI bridge with target_asset support."""
    
    def get_target_node(self, source_node):
        """Get target node from target_asset parameter (Houdini-specific)."""
        try:
            p = source_node.parm("target_asset")
            if p is not None:
                path = p.eval()
                if isinstance(path, (tuple, list)):
                    path = path[0] if path else ""
                path = str(path).strip() if path else ""
                if path:
                    target_node = hou.node(path)
                    if target_node is not None:
                        return target_node
        except Exception:
            pass
        return source_node
```

## Component Rules

### `publisher/rules/base_rule.py`

```python
class ComponentRule:
    """Base class for component publishing rules."""
    
    def __init__(self, config: dict):
        """Initialize rule with configuration."""
        self.config = config
        self.enabled_param = config.get('enabled_param')  # e.g., 'use_snapshot'
    
    def should_publish(self, node, dcc_bridge) -> bool:
        """Check if this component type should be published."""
        if not self.enabled_param:
            return True  # Always enabled if no toggle parameter
        return dcc_bridge.read_parameter(node, self.enabled_param) != 0
    
    def prepare_component(self, node, dcc_bridge) -> dict:
        """Prepare component data (name, path, metadata).
        
        This stage:
        - Saves files if needed (e.g., snapshot saves scene archive)
        - Collects metadata (e.g., ilink for snapshot)
        - Does NOT create component in Ftrack
        
        Returns:
            {
                'name': str,
                'file_path': str,
                'metadata': dict,
                'rule_type': str  # Identifier for which rule prepared this
            }
        """
        raise NotImplementedError
    
    def validate_component_data(self, component_data: dict, dcc_bridge) -> tuple[bool, str]:
        """Validate component data before publishing.
        
        Returns:
            (is_valid: bool, error_message: str)
        """
        # Default validation: check file exists (if not sequence)
        file_path = component_data.get('file_path', '')
        if not file_path:
            return False, "File path is empty"
        
        # Check if sequence token present
        is_sequence = ('%' in file_path) or ('@' in file_path) or ('[' in file_path and ']' in file_path)
        if not is_sequence:
            if not dcc_bridge.validate_file_path(file_path):
                return False, f"File does not exist: {file_path}"
        
        return True, ""
    
    def publish(self, session, asset_version, component_data: dict, dcc_bridge):
        """Create component in Ftrack.
        
        This is called AFTER asset version is created.
        Component data is already prepared (files saved, metadata collected).
        
        Returns created component entity.
        """
        file_path = component_data.get('file_path', '')
        name = component_data.get('name', '')
        metadata = component_data.get('metadata', {})
        
        # Normalize sequence path if needed
        file_path = dcc_bridge.normalize_sequence_path(file_path)
        
        component = asset_version.create_component(
            file_path,
            data={
                'name': name,
                'metadata': metadata
            },
            location='auto'
        )
        
        return component
    
    def update_asset_metadata_index(self, asset, component):
        """Update asset metadata index: component_name.ext -> component_id.
        
        This is called after component creation to maintain asset-level index.
        """
        try:
            asset_meta = asset.get('metadata') or {}
            if not isinstance(asset_meta, dict):
                asset_meta = dict(asset_meta) if asset_meta else {}
            
            comp_name = component.get('name', '') or ''
            raw_ext = component.get('file_type', '') or ''
            ext = str(raw_ext).lstrip('.')
            key = f"{comp_name}.{ext}" if (comp_name and ext) else comp_name or ''
            comp_id = component.get('id')
            
            if key and comp_id:
                asset_meta[key] = comp_id
                asset['metadata'] = asset_meta
        except Exception as e:
            print(f"Warning: Failed to update asset metadata index: {e}")
```

### `publisher/rules/snapshot_rule.py`

```python
class SnapshotRule(ComponentRule):
    """Rules for snapshot component publishing."""
    
    def __init__(self, config: dict):
        super().__init__(config)
        self.name = config.get('name', 'snapshot')
        self.link_attribute = config.get('link_attribute', '__ftrack_used_CompId')
    
    def prepare_component(self, node, dcc_bridge):
        """Prepare snapshot component.
        
        This stage:
        - Saves scene archive file (e.g., .hip file)
        - Collects linked component IDs from scene
        - Prepares metadata (ilink)
        """
        # Get linked component IDs from scene
        linked_ids = dcc_bridge.find_linked_component_ids(self.link_attribute)
        
        # Save scene archive (DCC-specific) - THIS HAPPENS DURING PREPARATION
        file_path = dcc_bridge.save_scene_archive(node)
        
        # Prepare metadata
        # Note: No 'dcc' tag for snapshot to avoid conflicts with other DCCs
        metadata = {}
        if linked_ids:
            valid_links = [str(v).strip() for v in linked_ids if v and str(v).strip()]
            if valid_links:
                try:
                    metadata['ilink'] = json.dumps(valid_links)
                except Exception:
                    # Fallback: comma-separated string
                    metadata['ilink'] = ",".join(valid_links)
        
        return {
            'name': self.name,
            'file_path': file_path,
            'metadata': metadata,
            'rule_type': 'snapshot'  # Identifier for rule matching
        }
```

### `publisher/rules/file_component_rule.py`

```python
class FileComponentRule(ComponentRule):
    """Rules for file component publishing (includes sequences).
    
    Each component has its own enable/disable toggle (export{n} parameter).
    If export{n} != 1, component is skipped.
    """
    
    def __init__(self, config: dict):
        super().__init__(config)
        # No global enabled_param - each component has individual export{n} toggle
        self.export_toggle_template = config.get('export_toggle_template', 'export{index}')
    
    def should_publish(self, node, dcc_bridge) -> bool:
        # Always enabled at rule level - individual components check export{n} toggle
        # But we still need at least one component to process
        comp_count = dcc_bridge.get_component_count(node)
        return comp_count > 0
    
    def prepare_components(self, node, dcc_bridge) -> list[dict]:
        """Prepare all file components (returns list).
        
        Only includes components where export{n} == 1.
        This stage only prepares data, does NOT create components in Ftrack.
        """
        components = []
        comp_count = dcc_bridge.get_component_count(node)
        
        for idx in range(comp_count):
            comp_data = dcc_bridge.get_component_data(node, idx)
            
            # Check export toggle (enable/disable per component)
            # If export{n} parameter exists and != 1, skip this component
            if not comp_data.get('export_enabled', True):
                continue  # Component is disabled, skip it
            
            # Add DCC name to metadata
            dcc_name = dcc_bridge.get_dcc_name()
            comp_data['metadata']['dcc'] = dcc_name
            
            # Add rule type identifier
            comp_data['rule_type'] = 'file_component'
            
            components.append(comp_data)
        
        return components
```

## UI Bridge

### Standalone Qt UI (`publisher/ui/publisher_widget.py`)

- **Structure**: Copy of Houdini HDA interface structure
- **Purpose**: Run publisher without DCC (standalone)
- **Data Source**: 
  - Task ID: User input (can paste from browser)
  - Asset data: Read from Ftrack (after task_id is set)
  - Component data: User input in UI
- **Features**:
  - Task selection/input
  - Asset selection/creation
  - Snapshot toggle
  - Playblast path input
  - Component tabs (like HDA interface)
  - Metadata key/value pairs
  - Publish button

### DCC UI Bridge

- **Houdini**: Read from HDA parameters (supports `target_asset`)
- **Maya**: Read from node attributes
- **Qt Standalone**: Read from Qt widget values

## Configuration

### Rules Configuration (YAML or Python dict)

```yaml
component_rules:
  snapshot:
    enabled_param: "use_snapshot"
    name: "snapshot"
    link_attribute: "__ftrack_used_CompId"
    # No 'dcc' metadata tag for snapshot
  
  playblast:
    enabled_param: "use_playblast"
    path_param: "playblast"
    use_encode_media: true
    metadata:
      dcc: "{dcc_name}"  # Tag with parent DCC
  
  file_components:
    count_param: "components"
    name_param_template: "comp_name{index}"
    path_param_template: "file_path{index}"
    export_toggle_template: "export{index}"
    metadata_count_template: "meta_count{index}"
    metadata_key_template: "key{index}_{meta_index}"
    metadata_value_template: "value{index}_{meta_index}"
    sequence_extensions: [".vdb", ".exr", ".jpg", ".bgeo", ".tiff", ".png", ".bgeo.sc"]
    default_metadata:
      dcc: "{dcc_name}"  # Tag with parent DCC
  
  custom_components:  # Extensible - can add custom types
    - enabled_param: "use_custom_json"
      name: "custom_json"
      type: "json_metadata"
      # ... custom preparation logic
```

## Asset Metadata Indexing

### `publisher/utils/asset_index.py`

```python
def update_asset_metadata_index(asset, components: list):
    """Update asset metadata index after publishing components.
    
    Index format: "component_name.ext" -> "component_id"
    
    Logic:
    - If component name is new: add to index
    - If component name exists: update component_id (new version)
    - This allows tracking component IDs across versions
    """
    asset_meta = asset.get('metadata') or {}
    if not isinstance(asset_meta, dict):
        asset_meta = dict(asset_meta) if asset_meta else {}
    
    for comp in components:
        comp_name = comp.get('name', '') or ''
        raw_ext = comp.get('file_type', '') or ''
        ext = str(raw_ext).lstrip('.')
        key = f"{comp_name}.{ext}" if (comp_name and ext) else comp_name or ''
        comp_id = comp.get('id')
        
        if key and comp_id:
            asset_meta[key] = comp_id  # Add or update
    
    asset['metadata'] = asset_meta
```

## DCC Tagging

### `publisher/utils/dcc_tagger.py`

```python
def tag_component_with_dcc(metadata: dict, dcc_name: str):
    """Add parent DCC name to component metadata.
    
    This tags which DCC created the component (e.g., "houdini", "maya").
    Note: Snapshot components do NOT get dcc tag to avoid conflicts.
    """
    if 'dcc' not in metadata:  # Don't overwrite if already set
        metadata['dcc'] = dcc_name
```

## Validation

**What we mean by validation:**
- **File existence**: Check if file exists on disk (skip if missing and not sequence token)
- **Sequence format**: Validate sequence tokens are correct (%04d, @, [1-100])
- **Required fields**: Check that component name and path are provided
- **Metadata format**: Ensure metadata keys/values are valid strings
- **Path normalization**: Ensure paths are in correct format for Ftrack

**Validation behavior:**
- Validation happens in `ComponentRule.validate_component_data()` before publishing
- **If validation fails**: Entire publish is aborted, session is NOT committed, error message is returned
- **Disabled components**: If `export{n} == 0` or `use_snapshot == 0`, component is skipped (not an error)

## Two-Stage Publishing Process

### Stage 1: Preparation (`prepare_all_components`)
- **Purpose**: Prepare all component data BEFORE creating asset version
- **Actions**:
  - Validate prerequisites (task_id, asset_id/name)
  - Save files (e.g., snapshot saves scene archive)
  - Collect metadata (e.g., ilink for snapshot)
  - Validate all component data
- **Result**: List of prepared component data dicts
- **No Ftrack operations**: Does NOT create asset version or components

### Stage 2: Publishing (`publish`)
- **Purpose**: Create asset version and publish all prepared components
- **Actions**:
  - Get or create asset
  - Create asset version
  - Publish all prepared components (create in Ftrack)
  - Update asset metadata index
  - Commit session
  - Update node parameters
- **Result**: Created components list

**Benefits:**
- All data is ready before creating version
- If preparation fails, version is not created
- Clean separation: preparation vs. publishing
- Snapshot file is saved during preparation, not during publish

## Error Handling

**Error handling strategy:**
1. **Preparation errors**: If any component preparation fails (e.g., save_scene_archive fails) → entire publish fails, no version created, no commit
2. **Validation errors**: If any component fails validation during preparation → entire publish fails, no version created, no commit
3. **Publish errors**: If component creation fails → entire publish fails, no commit (but version may be created)
4. **Session commit**: Only happens if ALL components succeed
5. **Error messages**: Clear error messages are returned to caller for user display

**Example error flow:**
```python
success, error_msg, components = publisher.publish(target_node, task_id, asset_id, asset_name, asset_type)
if not success:
    # Display error_msg to user
    # Session is NOT committed, no components were created, no version created
    display_error(error_msg)
else:
    # All components published successfully
    # Session was committed
    display_success(f"Published {len(components)} components")
```

## Implementation Steps

1. **Phase 1: Core Structure**
   - Create directory structure
   - Implement base classes (DCCBridge, ComponentRule)
   - Create core Publisher engine
   - Implement asset metadata indexing utilities

2. **Phase 2: DCC Bridge for Houdini**
   - Implement HoudiniDCCBridge
   - Move DCC-specific functions from fpublish.py (saveArchive, find_nodes_with_attribute_value)
   - Implement target_asset support (Houdini-specific)
   - Test bridge functions

3. **Phase 3: Component Rules**
   - Implement SnapshotRule (with ilink metadata)
   - Implement PlayblastRule (with encode_media)
   - Implement FileComponentRule (includes sequences, metadata, export toggles)
   - Implement base validation logic

4. **Phase 4: Core Publisher Integration**
   - Integrate rules into Publisher
   - Add configuration system
   - Implement asset metadata index updates
   - Implement DCC tagging
   - Test full publish workflow

5. **Phase 5: Standalone Qt UI**
   - Create Qt widget matching Houdini HDA interface structure
   - Implement task_id input (paste from browser)
   - Implement asset selection/creation
   - Implement component tabs and metadata UI
   - Connect to Publisher engine

6. **Phase 6: Extensibility**
   - Add plugin system for custom component types
   - Document how to add new component rules
   - Support enable/disable toggles for custom components

## Key Features to Preserve

1. **Asset Metadata Indexing**:
   - Format: `"component_name.ext" -> "component_id"`
   - New component name: add to index
   - Existing component name: update component_id (new version)

2. **DCC Tagging**:
   - Tag components with parent DCC name (`metadata["dcc"] = "houdini"`)
   - Exception: Snapshot does NOT get dcc tag (to avoid conflicts)

3. **Target Asset Support** (Houdini only):
   - Read/write parameters on node specified by `target_asset` parameter
   - Not needed in Maya/Qt standalone

4. **Sequence Handling**:
   - Sequences are just component type in Ftrack
   - Normalize sequence paths to Ftrack format
   - Support sequence extensions: .vdb, .exr, .jpg, .bgeo, .tiff, .png, .bgeo.sc

5. **Enable/Disable Toggles**:
   - **Snapshot**: `use_snapshot` parameter (global toggle)
   - **Playblast**: `use_playblast` parameter (global toggle)
   - **File components**: `export{n}` toggles per component (each component can be individually disabled)
   - **Custom components**: Configurable enable parameters per component type
   - **Note**: If a component is disabled, it is skipped during publish (no error)

6. **Error Handling**:
   - **On any error**: Do NOT commit session, return error message
   - **Validation errors**: Component validation fails → entire publish fails
   - **Preparation errors**: Component preparation fails → entire publish fails
   - **Publish errors**: Component creation fails → entire publish fails
   - **User feedback**: Error message is returned and can be displayed to user

## Benefits

1. **Modularity**: Each component type has its own rule class
2. **Extensibility**: Easy to add new component types (custom rules)
3. **DCC Independence**: Core logic is DCC-agnostic
4. **Testability**: Rules can be tested independently
5. **Configuration**: Rules can be configured without code changes
6. **Maintainability**: Clear separation of concerns
7. **Standalone Support**: Qt UI allows publishing without DCC
8. **Backward Compatibility**: Can coexist with existing fpublish.py
