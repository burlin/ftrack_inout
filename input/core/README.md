# Ftrack Input Core

DCC-agnostic logic for Ftrack asset version and component loading. No Houdini, Maya, or other DCC imports. Works with `ftrack_api.Session` and returns plain data structures. UI/DCC adapters are responsible for rendering.

## Architecture

```
input/
├── core/                     # Pure logic (no DCC)
│   ├── asset_version_component.py   # Load version/component data
│   ├── version_indicators.py        # Compute (*) labels
│   ├── component_menu.py            # Component menu data + selection
│   ├── path_resolution.py           # Resolve filesystem path
│   └── README.md                    # This file
├── dcc/
│   ├── houdini.py           # Houdini HDA adapter
│   ├── maya.py              # Maya adapter (to be implemented)
│   └── standalone.py        # Qt / FtrackApiClient
└── INPUT_FLOW_DIAGRAM.md    # Flow and API call optimization
```

### Data Flow

1. **Load** — `load_asset_version_component_data(session, asset_id)` fetches versions and components, returns `cached_data`.
2. **Display** — All menu building uses `cached_data` only (no extra API calls).
3. **Path** — `resolve_component_path(session, component)` is the only place that hits the API after load.

## CachedData Structure

Returned by `load_asset_version_component_data`:

```python
{
    "version_info": [
        {"name": "v044", "id": "<uuid>", "version": 44},
        {"name": "v043", "id": "<uuid>", "version": 43},
        ...
    ],
    "components_map": {
        "<version_id>": ["<comp_id_1>", "<comp_id_2>", ...],
        ...
    },
    "components_file_types": {
        "<version_id>": {"<comp_id>": "sc", ...},
        ...
    },
    "components_names": {
        "<version_id>": {"<comp_id>": "maya_part", ...},
        ...
    },
    "asset_name": "character_rig",
    "asset_type": "Character",
}
```

## API Reference

### load_asset_version_component_data

Load versions and components for an asset. Same logic as Houdini `build_version_component_menus`.

```python
from ftrack_inout.input.core import load_asset_version_component_data

session = get_shared_session()
asset_id = "abc-123-def"

# Fast path: uses relationship cache (may miss new versions)
cached = load_asset_version_component_data(session, asset_id, force_refresh=False)

# Full path: query fresh from server (~1.5 s)
cached = load_asset_version_component_data(session, asset_id, force_refresh=True)

if cached:
    versions = cached["version_info"]
    for v in versions:
        print(v["name"], v["id"])
```

**Args:**
- `session` — `ftrack_api.Session`
- `asset_id` — Ftrack asset ID
- `force_refresh` — If `True`, uses query instead of relationship (fresh from server)

**Returns:** `CachedData` dict or `None` on failure.

---

### get_component_menu_data

Build component menu items and labels for a version. No API calls.

```python
from ftrack_inout.input.core import get_component_menu_data

items, labels = get_component_menu_data(cached_data, version_id)
# items: ["comp-uuid-1", "comp-uuid-2", ...]
# labels: ["maya_part (.sc)", "cache (.bgeo)", ...]
```

**Args:**
- `cached_data` — From `load_asset_version_component_data`
- `version_id` — AssetVersion ID

**Returns:** `Tuple[List[str], List[str]]` — (component_ids, labels)

---

### resolve_component_to_select

Choose which component ID to select when switching versions.

Priority: 1) by name+file_type, 2) by name only, 3) previous comp_id, 4) first in list.

```python
from ftrack_inout.input.core import resolve_component_to_select

comp_id = resolve_component_to_select(
    cached_data,
    version_id,
    component_to_select_name="maya_part",
    previous_comp_id="old-comp-uuid",
    component_to_select_file_type="sc",
)
# Returns component ID to set in menu, or None if empty
```

**Args:**
- `cached_data` — From `load_asset_version_component_data`
- `version_id` — AssetVersion ID
- `component_to_select_name` — Name to match (optional)
- `previous_comp_id` — Previous selection (optional)
- `component_to_select_file_type` — File type for matching (optional)

**Returns:** `Optional[str]` — Component ID to select, or first in list.

---

### compute_version_labels_with_indicators

Build version labels with `(*)` for versions that contain the same component (by name + file_type).

```python
from ftrack_inout.input.core import compute_version_labels_with_indicators

labels = compute_version_labels_with_indicators(
    cached_data,
    selected_comp_id="current-comp-uuid",
    current_version_id="current-version-uuid",
    selected_comp_name=None,    # Optional override
    selected_comp_file_type=None,
)
# ["v044 (*)", "v043 (*)", "v042", "v041 (*)", ...]
```

**Args:**
- `cached_data` — From `load_asset_version_component_data`
- `selected_comp_id` — Currently selected component ID
- `current_version_id` — Version where selected component is from
- `selected_comp_name` — Override (default: from components_names)
- `selected_comp_file_type` — Override (default: from components_file_types)

**Returns:** `List[str]` — Version labels with `(*)` where applicable.

---

### resolve_component_path

Resolve filesystem path for a component.

- If `location` is passed: uses that location.
- If `location=None`: uses primary Disk location (e.g. burlin.local); component must be 100% available there. If only in secondary Disk or S3, raises `ValueError` with "Transfer to primary first".

```python
from ftrack_inout.input.core import resolve_component_path

# Auto primary Disk
path = resolve_component_path(session, component)
# "/path/to/project/assets/character/rig_v044.ma"

# Explicit location
path = resolve_component_path(session, component, location=my_location)
```

**Args:**
- `session` — `ftrack_api.Session`
- `component` — Component entity or `{"id": "<uuid>"}`
- `location` — Optional. Explicit location, or `None` for auto primary Disk

**Returns:** `str` — Filesystem path

**Raises:** `ValueError` when path cannot be resolved (no session, not in primary, etc.)

---

### get_primary_disk_location

Return the primary Disk location (highest precedence, lowest priority value). Excludes built-in ftrack locations.

```python
from ftrack_inout.input.core import get_primary_disk_location

location = get_primary_disk_location(session)
if location:
    path = location.get_filesystem_path(component)
```

**Args:** `session` — `ftrack_api.Session`

**Returns:** Location entity or `None` if no user Disk locations.

---

## Usage Examples

### Houdini HDA Adapter

```python
# HDA Python Module delegates to ftrack_inout.input.dcc.houdini
import ftrack_inout.input.dcc.houdini as ftrack_hda

def get_data(**kwargs):
    return ftrack_hda.get_data(**kwargs)

def applyCompSelection(**kwargs):
    return ftrack_hda.applyCompSelection(**kwargs)

def applyVersionSelection(**kwargs):
    return ftrack_hda.applyVersionSelection(**kwargs)
```

The Houdini adapter:
- Uses `load_asset_version_component_data` for menu building
- Uses `get_component_menu_data` and `resolve_component_to_select` on version change
- Uses `compute_version_labels_with_indicators` when component changes
- Uses path resolution for "get from asset" / create_node

### Standalone (Qt Widget)

```python
from ftrack_inout.input.core import load_asset_version_component_data
from ftrack_inout.input.dcc.standalone import load_asset_version_data_for_standalone

# Via api_client (FtrackApiClient with get_session)
cached = load_asset_version_data_for_standalone(api_client, asset_id, force_refresh=True)
```

### Maya

Use `ftrack_inout.input.dcc.maya` or core directly. Example script: `tools/maya_input_example.py`.

```python
from ftrack_inout.input.dcc.maya import (
    get_session_for_maya,
    load_asset_version_data_for_maya,
    resolve_component_path_maya,
)
from ftrack_inout.input.core import (
    get_component_menu_data,
    resolve_component_to_select,
    compute_version_labels_with_indicators,
)

session = get_session_for_maya()
cached = load_asset_version_data_for_maya(session, asset_id, force_refresh=True)
items, labels = get_component_menu_data(cached, version_id)
comp_id = resolve_component_to_select(cached, version_id)
path = resolve_component_path_maya(session, component, normalize_frames=True)
```

## Subscription to Updates (Asset Watcher)

The HDA can subscribe to asset updates. When a new version appears in Ftrack, Asset Watcher notifies the user. This is DCC-dependent and implemented in the Houdini adapter.

### Flow

1. **Subscribe** — User enables "Subscribe to updates" on the HDA (after selecting a component). Sends `mroya.asset.watch` event.
2. **Monitor** — Asset Watcher (mroya_asset_watcher) tracks the asset and detects new versions.
3. **Notify** — When a new version is available, the node is highlighted (e.g. green in Houdini).
4. **Accept** — User clicks "Accept Update" to switch to the new version and refresh the node.

### Usage in Houdini HDA

The HDA Python Module delegates to the adapter:

```python
import ftrack_inout.input.dcc.houdini as ftrack_hda

def toggle_subscribe_updates(**kwargs):
    return ftrack_hda.toggle_subscribe_updates(**kwargs)

def accept_update(**kwargs):
    return ftrack_hda.accept_update(**kwargs)
```

**HDA parameters:**
- `subscribe_updates` (Toggle) — Callback: `toggle_subscribe_updates`. Enables subscription when checked.
- `accept_update` (Button) — Callback: `accept_update`. Appears when an update is available; switches node to new version.

**Requirements:**
- Component must be selected first.
- mroya_asset_watcher plugin must be running (ftrack Connect).
- Asset Watcher stores watchlist in `~/.ftrack/mroya_asset_watcher.json`.

### Events (Asset Watcher)

| Event | Direction | Purpose |
|-------|-----------|---------|
| `mroya.asset.watch` | DCC -> Asset Watcher | Add asset/component to watchlist |
| `mroya.asset.unwatch` | DCC -> Asset Watcher | Remove from watchlist |
| `mroya.asset.update-available` | Asset Watcher -> DCC | New version detected (triggers node highlight) |
| `mroya.asset.transfer-complete` | Asset Watcher -> DCC | Transfer finished |

See `ftrack_plugins/mroya_asset_watcher/README.md` for full Asset Watcher documentation.

### Example: Subscribe programmatically (Houdini)

```python
# From Houdini Python or shelf script
import hou
import socket
import ftrack_api
from ftrack_api.event.base import Event

session = ftrack_api.Session()
component = session.get("Component", "your-component-id")
version = component["version"]
asset = version["asset"]

# Get target location (e.g. primary Disk)
location = session.pick_location()
target_location_id = location["id"] if location else None

session.event_hub.connect()
session.event_hub.publish(
    Event(
        topic="mroya.asset.watch",
        data={
            "asset_id": asset["id"],
            "asset_name": asset["name"],
            "component_name": component["name"],
            "component_id": component["id"],
            "target_location_id": target_location_id,
            "current_version_id": version["id"],
            "current_version_number": version["version"],
            "source_dcc": "houdini",
            "scene_path": hou.hipFile.path() if hou.hipFile.isLoaded() else "",
            "update_action": "wait_location",
            "notify_dcc": True,
        },
        source={"hostname": socket.gethostname().lower(), "user": {"username": session.api_user or ""}},
    ),
    on_error="ignore",
)
```

## force_refresh

| Value | Behavior | API | Speed |
|-------|----------|-----|-------|
| `False` | Uses `asset["versions"]` relationship (cached) | Fewer calls | Fast |
| `True` | Query `AssetVersion where asset.id=...` | Full query | ~1.5 s |

Houdini HDA uses `force_refresh=True` for get_data/get_fromcomp to ensure fresh versions. applyName can use `False` for faster initial load.

## Dependencies

- `ftrack_api.Session`
- Python standard library

No Houdini (`hou`), Maya (`maya.cmds`), or Qt imports in core.
