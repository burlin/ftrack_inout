# HDA Setup for Universal Publisher

## Реальная структура параметров publish HDA

Основано на дампе `burlin::fpublish::2.6` (HDA-файл; паблишем теперь занимается publisher)

---

## Важно: Flow параметров

```
[User Input]          [Selector]              [Storage (p_*)]         [Publish]
     │                    │                         │                     │
     │  task_Id ──────────┼─► applyTaskId() ──────►│ p_task_id          │
     │  (вводится)        │                        │ task_project        │
     │                    │                        │ task_parent         │
     │                    │                        │ task_name           │
     │                    │                         │                     │
     │  asset_name ───────┼─► applyAssetParams() ─►│ p_asset_name       │
     │  asset_id          │                        │ p_asset_id          │──► PublishJob
     │  type              │                        │ p_asset_type        │
     │                    │                        │ p_project           │
     │                    │                        │ p_parent            │
     │                    │                         │                     │
     │  [Динамические]    │                         │                     │
     │  assets (меню) ────┼─► applyName() ─────────►│ (в selector поля)  │
     │  name, ass_type    │                         │                     │
```

**При publish читаются p_* параметры (storage), а НЕ selector поля!**

---

## Selector секция (верхняя часть, рабочая область)

### Статические параметры

| Parameter Name | Type | Callback | Description |
|---------------|------|----------|-------------|
| `use_custom` | Toggle | - | Включить кастомные компоненты |
| `task_Id` | String | `hou.phm().checkTaskId(**kwargs)` | **Поле ввода Task ID** (НЕ p_task_id!) |
| `apply_taskid_to_asset` | Button | `hou.phm().applyTaskId()` | Применить task → p_task_id, task_* |
| `get_from_env` | Button | `hou.phm().get_from_env(**kwargs)` | Получить из ENV |
| `get_from_scene` | Button | `hou.phm().get_from_scene(**kwargs)` | Получить из сцены |
| `check_taskid` | Button | `hou.phm().checkTaskId(**kwargs)` | Проверить task_id |
| `test` | Label | - | Сообщение/статус |
| `create_new` | Button | `hou.phm().create_new(**kwargs)` | **Создаёт** динамические поля `name`, `ass_type` |
| `get_ex_assets` | Button | `hou.phm().initialize(**kwargs)` | **Создаёт** динамическое меню `assets` |
| `set_this` | Button | `hou.phm().applyName()` | Читает из `assets`/`name` → `asset_id`, `asset_name`, `type` |
| `asset_id` | String | - | Asset ID (рабочее поле selector) |
| `asset_name` | String | `hou.phm().cleanAssetId()` | Asset Name (при изменении чистит asset_id) |
| `type` | String | - | Asset Type (рабочее поле) |
| `apply_params_to_asset` | Button | `hou.phm().applyAssetParams(**kwargs)` | Копирует selector → p_* storage |
| `target_asset` | String | - | Путь к целевой ноде |

### Динамические параметры (создаются кнопками)

| Parameter Name | Type | Создаётся | Description |
|---------------|------|-----------|-------------|
| `assets` | Menu | `initialize()` | Меню существующих ассетов (menu_items=id, menu_labels=name+type) |
| `name` | String | `create_new()` | Поле для ввода нового имени ассета |
| `ass_type` | String+Menu | `create_new()` | Меню типов ассетов (Geometry, Animation, etc.) |

**Важно:** Эти параметры добавляются/удаляются динамически через `node.setParmTemplateGroup(ptg)`

---

## Task folder (Collapsible) — хранилище данных таска

| Parameter Name | Label | Type | Description |
|---------------|-------|------|-------------|
| `p_task_id` | Task task_id | String | Сохранённый Task ID |
| `task_project` | Task Project | String | Проект таска |
| `task_parent` | Task parent | String | Парент таска |
| `task_name` | Task name | String | Имя таска |

---

## Asset folder (Collapsible) — хранилище данных ассета

| Parameter Name | Label | Type | Description |
|---------------|-------|------|-------------|
| `p_project` | Project | String | Проект ассета |
| `p_parent` | Parent | String | Парент ассета |
| `p_asset_type` | Type | String | Тип ассета |
| `p_asset_name` | Name | String | Имя ассета |
| `p_asset_id` | Asset asset_id | String | ID ассета |

---

## Publish параметры

| Parameter Name | Type | Description |
|---------------|------|-------------|
| `use_snapshot` | Toggle | Включить snapshot |
| `playblast` | String | Путь к playblast |
| `use_playblast` | Toggle | Включить playblast |
| **`comment`** | String (multiline) | **ДОБАВИТЬ! Комментарий к версии** |

---

## Components (Tabbed Multiparm)

| Parameter Name | Type | Description |
|---------------|------|-------------|
| `components` | Folder (TabbedMultiparmBlock) | Количество компонентов |
| `export#` | Toggle | Экспортировать компонент |
| `comp_name#` | String | Имя компонента |
| `file_path#` | String | Путь к файлу |
| `meta_count#` | Folder (MultiparmBlock) | Количество метаданных |
| `key#_#` | String | Ключ метаданных |
| `value#_#` | String | Значение метаданных |

---

## Publish (ROP section)

| Parameter Name | Type | Description |
|---------------|------|-------------|
| `execute` | Button (Render) | Стандартная кнопка Render |
| `renderdialog` | Button | Controls... |
| `msg` | Label | Сообщение о результате |
| `lastversionid` | String | ID последней версии |

---

## Prerender Script для Shell ROP

Так как к кнопке Render нельзя напрямую привязать callback, используется вложенный Shell ROP с prerender скриптом:

```python
# В Shell ROP внутри publish HDA:
# Scripts > Pre-Render Script (Python)

hou.pwd().parent().hdaModule().publish()
```

---

## PythonModule для HDA

**Обратная совместимость (fpublish):** Если делаете копию publish HDA как fpublish (те же параметры, старые сцены/полки), укажите в копии **PythonModule = `ftrack_houdini.fpublish_compat`**. Там те же имена callback'ов (publish, checkTaskId, applyTaskId, create_new, …), делегирование в fselector и publisher.

**Рекомендация для нового HDA:** Для selector — `f_io.fselector`, для publish — `ftrack_inout.publisher` (см. пример ниже или используйте `ftrack_houdini.fpublish_compat` как единый модуль).

```python
"""
PythonModule для publish HDA (Universal Publisher version)

Selector функции: используют f_io.fselector
Publish функции: используют ftrack_inout.publisher
"""

import hou
import logging

_log = logging.getLogger(__name__)


# ============================================================================
# SELECTOR CALLBACKS — используют f_io.fselector напрямую
# ============================================================================

def checkTaskId(**kwargs):
    """Callback при вводе task_id — использует fselector."""
    from f_io import fselector
    fselector.checkTaskId()


def applyTaskId():
    """Применить task_id к asset параметрам — использует fselector."""
    from f_io import fselector
    fselector.applyTaskId()


def cleanAssetId():
    """Callback при изменении asset_name — использует fselector."""
    from f_io import fselector
    fselector.cleanAssetId()


def applyName():
    """Применить выбранный ассет — использует fselector."""
    from f_io import fselector
    fselector.applyName()


def applyAssetParams(**kwargs):
    """Применить asset параметры — использует fselector."""
    from f_io import fselector
    fselector.applyAssetParams()


def initialize(**kwargs):
    """Создать меню существующих ассетов — использует fselector."""
    from f_io import fselector
    fselector.initialize()


def create_new(**kwargs):
    """Создать поля для нового ассета — использует fselector."""
    from f_io import fselector
    fselector.create_new()


def get_from_env(**kwargs):
    """Получить task_id из ENV — использует fselector."""
    from f_io import fselector
    fselector.get_from_env()


def get_from_scene(**kwargs):
    """Получить task_id из сцены — использует fselector."""
    from f_io import fselector
    fselector.get_from_scene()


# ============================================================================
# PUBLISH CALLBACKS
# ============================================================================

def publish():
    """Main publish callback (вызывается из prerender Shell ROP)."""
    node = hou.pwd()
    
    _log.info(f"[publisher] Publishing from: {node.path()}")
    
    try:
        from ftrack_inout.publisher.dcc.houdini import build_job_from_hda
        from ftrack_inout.publisher.core import Publisher
        
        # Build job
        job = build_job_from_hda(node)
        
        # Validate
        is_valid, errors = job.validate()
        if not is_valid:
            error_msg = "Validation failed:\n" + "\n".join(f"  - {e}" for e in errors)
            hou.ui.displayMessage(error_msg, severity=hou.severityType.Error)
            node.parm('msg').set(f'Validation failed: {len(errors)} errors')
            raise hou.NodeError("Publish validation failed")
        
        # Get session
        session = _get_session()
        if not session:
            hou.ui.displayMessage("Ftrack session not available", severity=hou.severityType.Error)
            node.parm('msg').set('No Ftrack session')
            raise hou.NodeError("No Ftrack session")
        
        # Execute publish
        publisher = Publisher(session=session, dry_run=False)
        result = publisher.execute(job)
        
        if result.success:
            node.parm('msg').set(f'Published v{result.asset_version_number}')
            node.parm('lastversionid').set(result.asset_version_id or '')
            
            hou.ui.displayMessage(
                f"Published successfully!\n\n"
                f"Version: #{result.asset_version_number}\n"
                f"Components: {len(result.component_ids)}",
                severity=hou.severityType.Message
            )
        else:
            node.parm('msg').set(f'Publish failed')
            hou.ui.displayMessage(
                f"Publish failed:\n{result.error_message}",
                severity=hou.severityType.Error
            )
            raise hou.NodeError(f"Publish failed: {result.error_message}")
            
    except hou.NodeError:
        raise
    except Exception as e:
        import traceback
        _log.error(f"[publisher] Publish error: {e}", exc_info=True)
        node.parm('msg').set(f'Error: {e}')
        hou.ui.displayMessage(
            f"Publish error:\n{e}\n\n{traceback.format_exc()}",
            severity=hou.severityType.Error
        )
        raise hou.NodeError(f"Publish error: {e}")


def publish_dry_run():
    """Dry-run publish для тестирования."""
    node = hou.pwd()
    
    try:
        from ftrack_inout.publisher.dcc.houdini import build_job_from_hda
        from ftrack_inout.publisher.core import Publisher
        
        job = build_job_from_hda(node)
        
        is_valid, errors = job.validate()
        if not is_valid:
            node.parm('msg').set(f'Invalid: {len(errors)} errors')
        
        publisher = Publisher(session=None, dry_run=True)
        result = publisher.execute(job)
        
        node.parm('msg').set(f'DRY RUN: {len(result.component_ids)} components')
        hou.ui.displayMessage(
            f"DRY RUN completed.\n\n"
            f"Check Houdini console for details.\n"
            f"Would create {len(result.component_ids)} components.",
            severity=hou.severityType.Message
        )
        
    except Exception as e:
        node.parm('msg').set(f'Error: {e}')
        _log.error(f"[publisher] Dry-run error: {e}", exc_info=True)


# ============================================================================
# HELPERS
# ============================================================================

def _get_session():
    """Get Ftrack session."""
    try:
        if hasattr(hou.session, 'ftrack_session'):
            return hou.session.ftrack_session
        
        import ftrack_api
        session = ftrack_api.Session(auto_connect_event_hub=False)
        hou.session.ftrack_session = session
        return session
    except Exception as e:
        _log.warning(f"Failed to get Ftrack session: {e}")
        return None
```

---

## Параметр comment

**Добавь в HDA новый параметр:**

| Name | Label | Type | Location |
|------|-------|------|----------|
| `comment` | Comment | String (multiline) | После `use_playblast`, перед `sepparm2` |

Настройки:
- Type: String
- Tags: Enable multiline
- Default: пусто

---

## Параметр «Паблишить в фоне» (publish_in_background)

Чекбокс: запускать паблиш в отдельном потоке, чтобы Houdini не блокировался (копирование файлов и API идут в фоне).

| Name | Label | Type | Location |
|------|-------|------|----------|
| `publish_in_background` | Publish in background | Toggle | Рядом с кнопкой Publish / перед comment |

Настройки:
- Type: Toggle
- Default: 0 (выключено)
- Label можно: «Publish in background» / «Паблишить в фоне» / «Не блокировать Houdini»

Если включено: после нажатия Publish показывается «Publish started in background...», паблиш выполняется в потоке, по завершении на главном потоке показывается результат и обновляются параметры ноды.

---

## Checklist для обновления HDA

- [ ] Добавить параметр `comment` (String, multiline)
- [ ] Добавить параметр `publish_in_background` (Toggle) — паблиш в отдельном потоке
- [ ] Обновить PythonModule с новыми callback функциями
- [ ] Настроить prerender скрипт на Shell ROP: `hou.pwd().parent().hdaModule().publish()`
- [ ] Опционально: добавить кнопку Test с callback `hou.phm().publish_dry_run()`
- [ ] Протестировать dry-run
- [ ] Протестировать реальный publish
