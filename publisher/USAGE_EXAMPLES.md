



## 2. Custom Component Types

You can inherit from `ComponentData` or create specialized classes:

```python
from dataclasses import dataclass
from typing import Optional, Tuple
from ftrack_inout.publisher.core import ComponentData

@dataclass
class CameraComponentData(ComponentData):
    """Specialized component for camera."""
    focal_length: Optional[float] = None
    sensor_width: Optional[float] = None
    near_clip: Optional[float] = None
    far_clip: Optional[float] = None
    
    def __post_init__(self):
        self.component_type = 'camera'
        # Automatically add metadata
        if self.focal_length:
            self.metadata['focal_length'] = self.focal_length
        if self.sensor_width:
            self.metadata['sensor_width'] = self.sensor_width


@dataclass
class RenderComponentData(ComponentData):
    """Component for render."""
    resolution: Optional[Tuple[int, int]] = None
    samples: Optional[int] = None
    render_engine: Optional[str] = None
    
    def __post_init__(self):
        self.component_type = 'render'
        if self.resolution:
            self.metadata['resolution'] = f"{self.resolution[0]}x{self.resolution[1]}"
        if self.render_engine:
            self.metadata['render_engine'] = self.render_engine
```

## 3. Pipeline Integration (Houdini ROP callback)

```python
# In Houdini ROP callback
def on_render_complete(rop_node):
    from ftrack_inout.publisher.core import JobBuilder, Publisher
    
    # Automatically build job from node
    job = JobBuilder.from_houdini_node(rop_node)
    
    # Publish
    publisher = Publisher(session=hou.session.ftrack_session)
    result = publisher.execute(job)
    
    return result.component_ids  # For transfer queue
```

## 4. Dry Run Mode (Testing)

```python
# Test without actually publishing to Ftrack
publisher = Publisher(session=None, dry_run=True)
result = publisher.execute(job)

# Console will show what WOULD be published
# No changes made to Ftrack
```

## 5. Using JobBuilder

```python
from ftrack_inout.publisher.core import JobBuilder

# From Qt widget
job = JobBuilder.from_qt_widget(widget, source_dcc="standalone")

# From dictionary (useful for testing)
job = JobBuilder.from_dict({
    'task_id': 'abc123',
    'asset_name': 'test_asset',
    'asset_type': 'Geometry',
    'components': [
        {'name': 'main', 'file_path': '/path/to/file.abc', 'component_type': 'file'}
    ],
    'thumbnail_path': '/path/to/preview.png',  # optional
})

# From Houdini node (TODO)
job = JobBuilder.from_houdini_node(hou.node('/out/fpublish1'))

# From Maya node (TODO)
job = JobBuilder.from_maya_node('mroya_publisher1')
```

## Architecture

```
┌─────────────────────────────────────────────────────────┐
│                     API Layer                           │
│  (can be used directly without UI)                      │
├─────────────────────────────────────────────────────────┤
│  ComponentData  │  PublishJob  │  Publisher             │
│  (dataclass)    │  (dataclass) │  (executor)            │
├─────────────────────────────────────────────────────────┤
│                  JobBuilder                             │
│  from_qt_widget() │ from_houdini_node() │ from_dict()   │
├─────────────────────────────────────────────────────────┤
│                     UI Layer (optional)                 │
│  PublisherWidget │ Houdini HDA │ Maya Node              │
└─────────────────────────────────────────────────────────┘
```

The library is **headless-ready** - UI is just one way to create a `PublishJob`.

## Component Types

| Type | Description | file_path |
|------|-------------|-----------|
| `file` | Single file | Required |
| `sequence` | File sequence | Pattern with `%04d` |
| `snapshot` | Scene archive | Generated during publish |
| `playblast` | Preview video | Required |

## Thumbnail (Version Preview) — поведение

Версия в ftrack может иметь превью (thumbnail). Варианты:

| Сценарий | Поведение |
|----------|-----------|
| **Только playblast** | `encode_media()` создаёт видео и автоматически ставит thumbnail (кадр из видео). |
| **Только thumbnail_path** | Используйте, когда нет видео (snapshot, геометрия, кэш). `create_thumbnail(path)` задаёт превью. |
| **Playblast + thumbnail_path** | Сначала playblast даёт auto-thumbnail, затем `create_thumbnail(thumbnail_path)` перезаписывает его. Удобно для кастомного кадра или отдельной картинки. |

Playblast и thumbnail_path **не взаимоисключающие** — можно указать оба.

```python
# Без playblast — нужен thumbnail_path для превью
job = PublishJob(
    task_id='...',
    asset_name='my_asset',
    asset_type='Geometry',
    components=[ComponentData(name='main', file_path='/path/to/cache.abc', component_type='file')],
    thumbnail_path='/path/to/preview.png',
)

# С playblast — thumbnail ставится автоматически, thumbnail_path опционален
job = PublishJob(
    task_id='...',
    asset_name='my_asset',
    components=[
        ComponentData(name='playblast', file_path='/path/to/video.mp4', component_type='playblast'),
    ],
    thumbnail_path='/path/to/custom_frame.png',  # перезапишет auto-thumbnail
)
```

## PublishResult Fields

After `publisher.execute(job)`:

| Field | Description |
|-------|-------------|
| `success` | True/False |
| `error_message` | Error if failed |
| `asset_version_id` | Ftrack version ID |
| `asset_version_number` | Version number (1, 2, 3...) |
| `asset_id` | Asset ID |
| `component_ids` | List of created component IDs |
| `component_paths` | Dict {comp_id: file_path} |

Use `component_ids` for transfer queue integration.

## PublishJob Fields

| Field | Type | Description |
|-------|------|-------------|
| `task_id` | str | Ftrack Task ID (required) |
| `asset_id` | str \| None | Existing Asset ID |
| `asset_name` | str \| None | Asset name (when creating new) |
| `asset_type` | str \| None | Asset type (when creating new) |
| `comment` | str | Version comment |
| `components` | List[ComponentData] | Components to publish |
| `thumbnail_path` | str \| None | Optional image for version preview. With playblast: overrides auto-thumbnail. Without: sets preview. |
