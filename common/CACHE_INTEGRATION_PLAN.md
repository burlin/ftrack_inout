# План интеграции кеша в модули проекта

## Обзор
Этот документ описывает план интеграции оптимизированного кеша ftrack во все модули проекта.

## Текущее состояние

### ✅ Уже используют кеш:
1. **Browser** (`ftrack_plugins/ftrack_inout/browser/`)
   - Использует `OptimizedFtrackApiClient` с кешем
   - Использует `common.session_factory.get_shared_session()`
   - ✅ Готово

2. **finput** (`hsite/packages_common/mroya_taskhub_browser/python3.11libs/ftrack_houdini/finput.py`)
   - Использует `ftrack_utils.get_session()` → `common.session_factory.get_shared_session()`
   - ✅ Готово

3. **fselector** (`hsite/packages_common/mroya_taskhub_browser/python3.11libs/f_io/fselector.py`)
   - Использует `ftrack_utils.get_session()` → `common.session_factory.get_shared_session()`
   - ✅ Готово

---

## 🔴 Требуют изменений

### 1. Publisher (`ftrack_plugins/ftrack_inout/publisher/`)

#### Текущее состояние:
- **`publisher/core/publisher.py`**: Принимает `session` в конструкторе, но не использует общий session factory
- **`publisher/ui/publisher_widget.py`**: Создает новую сессию через `ftrack_api.Session()` (строки 540, 545)
- **`publisher/dcc/houdini/__init__.py`**: Создает новую сессию через `ftrack_api.Session()` (строка 677)
- **`publisher/dcc/maya/__init__.py`**: Создает новую сессию через `ftrack_api.Session()` (строка 749)

#### Что нужно сделать:

**1.1. Заменить создание сессий на общий session factory:**
- ✅ `publisher/core/publisher.py`: Если `session=None`, использовать `get_shared_session()` из `common.session_factory`
- ✅ `publisher/ui/publisher_widget.py`: Заменить `ftrack_api.Session()` на `get_shared_session()`
- ✅ `publisher/dcc/houdini/__init__.py`: Заменить `ftrack_api.Session()` на `get_shared_session()`
- ✅ `publisher/dcc/maya/__init__.py`: Заменить `ftrack_api.Session()` на `get_shared_session()`

**1.2. Оптимизировать запросы:**
- ✅ `publisher/core/publisher.py` строка 408: `session.query(f"Asset where id is '{job.asset_id}'").one()` → `session.get('Asset', job.asset_id)`
- ✅ `publisher/core/publisher.py` строка 428: `session.query(f'AssetType where name is "{job.asset_type}"').one()` → можно оставить query (AssetType редко меняется)
- ✅ `publisher/core/publisher.py` строка 461: `session.query(f'User where username is "{api_user}"').first()` → можно оптимизировать через кеш

**1.3. Обновление кеша после изменений:**
- ✅ После `session.commit()` (строки 452, 490, 572) нужно обновить кеш для:
  - Созданного `AssetVersion` (если новый)
  - Созданных `Component` (если новые)
  - Обновленного `Asset` (metadata изменился)
- ✅ Использовать `session.populate()` для загрузки новых сущностей в кеш после commit

---

### 2. Asset Watcher (`ftrack_plugins/mroya_asset_watcher/`)

#### Текущее состояние:
- **`hook/asset_watcher.py`**: Принимает `session` в конструкторе `AssetWatcherManager.__init__()`
- Создается в hook bootstrap (нужно проверить, как создается сессия там)

#### Что нужно сделать:

**2.1. Использование сессии:**
- ✅ Сессия передается из ftrack Connect в `register()` функцию (строка 1406)
- ✅ Использовать переданную сессию (она уже может быть с кешем, если Connect использует общий session factory)
- ✅ Если нужно, можно проверить, использует ли Connect общий session factory, и если нет - заменить сессию на `get_shared_session()` внутри `AssetWatcherManager`

**2.2. Оптимизировать запросы:**
- ✅ `asset_watcher.py` строка 351: `self._session.query(...)` для получения latest version → использовать relationship или оптимизированный подход
- ✅ `asset_watcher.py` строка 408: `self._session.query(...)` для получения version → использовать `session.get()` если есть ID
- ✅ `asset_watcher.py` строка 666: `self._session.query(...)` для получения component → использовать `session.get()` если есть ID
- ✅ `asset_watcher.py` строка 748: `self._session.query(...)` для получения component → использовать `session.get()` если есть ID
- ✅ `asset_watcher.py` строка 840: `self._session.query(f'AssetVersion where id is "{version_id}"').first()` → `session.get('AssetVersion', version_id)`
- ✅ `asset_watcher.py` строка 850: `self._session.query(f'Location where id is "{location_id}"').first()` → `session.get('Location', location_id)`
- ✅ `asset_watcher.py` строка 916: `self._session.get('Component', component_id)` → ✅ уже использует get
- ✅ `asset_watcher.py` строка 962: `self._session.query(...)` для получения latest version → оптимизировать
- ✅ `asset_watcher.py` строка 1181: `self.session.query('Location').all()` → можно оставить (Location редко меняется)
- ✅ `asset_watcher.py` строка 1264: `self.session.query(f'AssetVersion where id is "{version_id}"').first()` → `session.get('AssetVersion', version_id)`
- ✅ `asset_watcher.py` строка 1308: `self.session.query(f'Location where id is "{location_id}"').first()` → `session.get('Location', location_id)`

**2.3. Обновление кеша после событий:**
- ✅ После получения события `ftrack.update` (новая версия) → использовать `CachePreloader` для предзагрузки
- ✅ После получения события `ftrack.location.component-added` → обновить кеш для компонента
- ✅ После успешного трансфера → обновить кеш для `component_locations`

---

### 3. Transfer Manager (`ftrack_plugins/mroya_transfer_manager/`)

#### Текущее состояние:
- **`hook/transfer_manager.py`**: Принимает `session` в конструкторе `TransferManager.__init__()`
- Создается в hook bootstrap (нужно проверить, как создается сессия там)

#### Что нужно сделать:

**3.1. Использование сессии:**
- ✅ Сессия передается из ftrack Connect в `register()` функцию (строка 2532)
- ✅ Использовать переданную сессию (она уже может быть с кешем, если Connect использует общий session factory)
- ✅ Если нужно, можно проверить, использует ли Connect общий session factory, и если нет - заменить сессию на `get_shared_session()` внутри `TransferManager`

**3.2. Оптимизировать запросы:**
- ✅ `transfer_manager.py` строка 617: `self._session.get("User", user_id)` → ✅ уже использует get
- ✅ `transfer_manager.py` строка 801: `self._session.get('Job', job_id)` → ✅ уже использует get
- ✅ `transfer_manager.py` строка 884: `self._session.get('Job', job_id)` → ✅ уже использует get
- ✅ `transfer_manager.py` строка 912: `self._session.get('Job', job_id)` → ✅ уже использует get
- ✅ `transfer_manager.py` строка 1029: `self._session.get("Location", str(from_location_id))` → ✅ уже использует get
- ✅ `transfer_manager.py` строка 1030: `self._session.get("Location", str(to_location_id))` → ✅ уже использует get
- ✅ `transfer_manager.py` строка 1048: `self._session.get("Job", str(job_id))` → ✅ уже использует get
- ✅ `transfer_manager.py` строка 250: `_get_components_in_location()` использует `session.query()` → можно оптимизировать для больших выборок

**3.3. Обновление кеша после изменений:**
- ✅ После `session.commit()` (строки 887, 1069, 1079, 1104, 1122, 1154, 1215, 1444, 1522, 1540, 2208, 2255, 2300) нужно обновить кеш для:
  - Обновленного `Job` (status изменился)
  - Обновленных `Component` (component_locations изменились после трансфера)
- ✅ После успешного трансфера → использовать `CachePreloader` для обновления `component_locations` в кеше
- ✅ После создания нового `Job` → загрузить его в кеш через `session.get()`

---

## 📋 Приоритеты

### Высокий приоритет:
1. **Publisher** - активно используется, создает много данных
2. **Asset Watcher** - постоянно опрашивает ftrack, нужен кеш для производительности

### Средний приоритет:
3. **Transfer Manager** - уже использует `session.get()` в большинстве мест, но можно оптимизировать запросы компонентов

---

## 🔧 Общие рекомендации

### Паттерн замены сессий:
```python
# БЫЛО:
session = ftrack_api.Session(auto_connect_event_hub=True)

# СТАЛО:
from ftrack_inout.common.session_factory import get_shared_session
session = get_shared_session()
```

### Паттерн оптимизации запросов:
```python
# БЫЛО:
entity = session.query(f'EntityType where id is "{entity_id}"').first()

# СТАЛО:
entity = session.get('EntityType', entity_id)
```

### Паттерн обновления кеша после изменений:
```python
# После session.commit():
# 1. Загрузить новые сущности в кеш
new_entity = session.get('EntityType', new_entity_id)

# 2. Обновить связанные сущности
session.populate([related_entities], 'field1, field2')

# 3. Для компонентов после трансфера - использовать CachePreloader
from ftrack_inout.common.cache_preloader import CachePreloader
preloader = CachePreloader(session)
preloader.preload_component_locations([component_ids])
```

---

## ✅ Чеклист выполнения

### Publisher:
- [ ] Заменить создание сессий на `get_shared_session()`
- [ ] Оптимизировать запросы по ID на `session.get()`
- [ ] Добавить обновление кеша после `session.commit()`

### Asset Watcher:
- [ ] Заменить создание сессий на `get_shared_session()`
- [ ] Оптимизировать запросы по ID на `session.get()`
- [ ] Добавить использование `CachePreloader` после событий

### Transfer Manager:
- [ ] Заменить создание сессий на `get_shared_session()`
- [ ] Оптимизировать запросы компонентов в `_get_components_in_location()`
- [ ] Добавить обновление кеша после успешного трансфера

---

## 📝 Примечания

1. **Event Hub**: Некоторые модули требуют `auto_connect_event_hub=True`. `get_shared_session()` создает сессию с `auto_connect_event_hub=True` по умолчанию, но можно добавить параметр если нужно.

2. **Кеш после commit**: После `session.commit()` новые сущности автоматически попадают в кеш при следующем `session.get()`, но для немедленного обновления можно использовать `session.populate()`.

3. **CachePreloader**: Уже используется в Asset Watcher для предзагрузки после появления компонента на локации. Можно расширить использование в других модулях.

4. **Обратная совместимость**: Все изменения должны сохранять обратную совместимость - если сессия передана в конструктор, использовать её, иначе использовать общий session factory.
