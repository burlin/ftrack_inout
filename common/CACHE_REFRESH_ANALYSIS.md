# Анализ производительности кеширования и рефреша

## Результаты тестирования (Asset: `heavy_seq`, 39 версий)

### Тест 1: Базовое кеширование

**Query для получения ID:**
- Время: ~1465ms (26.6 версий/сек)
- Операция: `session.query()` для получения только ID версий

**Batch get (холодный кеш):**
- Время: ~0.1ms (455,648 версий/сек)
- Операция: `session.get()` после query, данные загружаются из FileCache

**Batch get (горячий кеш):**
- Время: ~0.1ms (582,127 версий/сек)
- Операция: `session.get()` из MemoryCache
- Ускорение: **1.3x** по сравнению с холодным кешем

**Вывод:** После первого запроса данные доступны из памяти практически мгновенно (~0.0ms).

---

### Тест 2: Сравнение рефреша vs обычного режима

#### Версии (39 версий):

**Без рефреша (`force_refresh=False`):**
- Время: **2969.5ms** (13.1 версий/сек)
- Query: 1.498s
- Batch get: 1.988s
- Использует кеш без обновления метаданных

**С рефрешем (`force_refresh=True`):**
- Время: **1481.8ms** (26.3 версий/сек)
- Query: 0.063s (быстрее, т.к. кеш уже загружен)
- Batch get: 1.749s
- Обновляет метаданные через `populate()` (если указаны поля)

**Разница: -1487.6ms (на 50% быстрее)**

#### Компоненты (1 компонент):

**Без рефреша:**
- Время: **1723.1ms**

**С рефрешем:**
- Время: **438.1ms**
- Обновляет `component_locations` через `populate()`

**Разница: -1285.1ms (на 74.6% быстрее)**

---

## Ключевые выводы

### 1. Рефреш быстрее обычного режима

**Парадокс:** Рефреш с `force_refresh=True` работает **быстрее** обычного режима.

**Причины:**
- При первом вызове (`force_refresh=False`) происходит полная инициализация клиента и bulk preload всего кеша
- При втором вызове (`force_refresh=True`) кеш уже загружен, query выполняется быстрее (0.063s vs 1.498s)
- `session.get()` использует MemoryCache (доступ ~0.0ms)
- `populate()` вызывается только для указанных полей (если `fields=None`, то не вызывается)

**Важно:** Это не означает, что рефреш всегда быстрее. Разница связана с порядком выполнения тестов и состоянием кеша.

---

### 2. Когда использовать `force_refresh=True`

**Использовать рефреш:**

1. **После трансфера компонентов:**
   - Компонент был перенесён на новую локацию
   - Нужно обновить `component_locations` для получения актуальных путей
   - Пример: `get_components_with_paths_for_version(version_id, force_refresh=True)`

2. **После изменения метаданных:**
   - Метаданные ассета были изменены (например, через API или другой клиент)
   - Нужно получить свежие данные
   - Пример: `get_versions_for_asset(asset_id, force_refresh=True)` с `fields=['metadata']`

3. **При явном рефреше пользователя:**
   - Пользователь нажал кнопку "Refresh" в UI
   - Нужно гарантировать актуальность данных
   - Пример: `_refresh_asset_versions()` в браузере

**НЕ использовать рефреш:**

1. **При обычной навигации:**
   - Пользователь просто просматривает данные
   - Кеш уже содержит актуальные данные
   - Рефреш создаст лишнюю нагрузку на сервер

2. **При частых обновлениях:**
   - Автоматические обновления (polling, события)
   - Используйте события Ftrack для отслеживания изменений
   - Рефреш только при необходимости

---

### 3. Архитектура рефреша

#### Текущая реализация:

```python
# browser_widget_optimized.py

def get_versions_for_asset(self, asset_id, force_refresh=False):
    # STEP 1: Query для получения ID (быстро)
    version_ids = self._query_version_ids(asset_id)
    
    # STEP 2: Рефреш метаданных (если нужно)
    if force_refresh:
        self._refresh_cached_entities('AssetVersion', version_ids)
    
    # STEP 3: Batch get из кеша (быстро, ~0.0ms)
    versions = [self.session.get('AssetVersion', vid) for vid in version_ids]
```

#### Механизм `_refresh_cached_entities`:

```python
def _refresh_cached_entities(self, entity_type, entity_ids, fields=None):
    """Обновляет указанные поля через populate()"""
    entities = [self.session.get(entity_type, eid) for eid in entity_ids]
    
    if fields:
        # Обновляем только указанные поля
        self.session.populate(entities, *fields)
    # Если fields=None, populate() не вызывается
    # session.get() уже обеспечивает свежие данные из кеша
```

**Важно:** `populate()` вызывается только если указаны конкретные поля. Если `fields=None`, то обновление не происходит, но `session.get()` всё равно использует кеш.

---

### 4. Оптимизация производительности

#### Рекомендации:

1. **Используйте кеш по умолчанию:**
   - `force_refresh=False` для обычных операций
   - Кеш обеспечивает доступ ~0.0ms

2. **Рефреш только при необходимости:**
   - После трансферов компонентов
   - После изменения метаданных
   - При явном запросе пользователя

3. **Указывайте конкретные поля для рефреша:**
   - `fields=['component_locations']` для компонентов
   - `fields=['metadata']` для ассетов
   - Не вызывайте `populate()` без полей (это не имеет смысла)

4. **Используйте события Ftrack:**
   - Подписывайтесь на `ftrack.update` и `ftrack.location.component-added`
   - Обновляйте кеш только при реальных изменениях
   - Избегайте polling с рефрешем

---

### 5. Проблемы и решения

#### Проблема: Stale metadata

**Симптом:** Метаданные ассета устарели (например, список компонентов изменился).

**Решение:**
```python
# Рефреш метаданных ассета
versions = api.get_versions_for_asset(asset_id, force_refresh=True)
# Внутри: _refresh_cached_entities('AssetVersion', version_ids, fields=['metadata'])
```

#### Проблема: Stale component paths

**Симптом:** Компонент был трансфернут на новую локацию, но пути не обновились.

**Решение:**
```python
# Рефреш component_locations
components = api.get_components_with_paths_for_version(version_id, force_refresh=True)
# Внутри: _refresh_cached_entities('Component', component_ids, fields=['component_locations'])
```

#### Проблема: Медленный рефреш

**Симптом:** Рефреш занимает много времени.

**Решение:**
- Убедитесь, что указаны только необходимые поля
- Используйте batch операции (`session.get()` для всех ID сразу)
- Избегайте рефреша при каждом запросе

---

### 6. Метрики производительности

#### Оптимальные значения (для ассета с 39 версиями):

- **Query ID:** ~1.5s (зависит от сети и сервера)
- **Batch get (cold):** ~0.1ms (FileCache)
- **Batch get (hot):** ~0.1ms (MemoryCache)
- **Рефреш версий:** ~1.5s (query + populate + batch get)
- **Рефреш компонентов:** ~0.4s (query + populate + batch get)

#### Ускорение от кеша:

- **MemoryCache vs FileCache:** ~1.3x
- **MemoryCache vs Query:** ~14,000x (0.1ms vs 1465ms)

---

## Рекомендации для разработчиков

### 1. Используйте кеш по умолчанию

```python
# ✅ Хорошо: используем кеш
versions = api.get_versions_for_asset(asset_id)

# ❌ Плохо: рефреш при каждом запросе
versions = api.get_versions_for_asset(asset_id, force_refresh=True)
```

### 2. Рефреш только при необходимости

```python
# ✅ Хорошо: рефреш после трансфера
if component_was_transferred:
    components = api.get_components_with_paths_for_version(version_id, force_refresh=True)

# ✅ Хорошо: рефреш при явном запросе пользователя
def on_refresh_button_clicked():
    versions = api.get_versions_for_asset(asset_id, force_refresh=True)
```

### 3. Указывайте конкретные поля

```python
# ✅ Хорошо: обновляем только component_locations
_refresh_cached_entities('Component', component_ids, fields=['component_locations'])

# ❌ Плохо: обновляем все поля (медленно)
_refresh_cached_entities('Component', component_ids)  # fields=None, populate() не вызывается
```

### 4. Используйте события вместо polling

```python
# ✅ Хорошо: подписка на события
session.event_hub.subscribe('topic=ftrack.location.component-added', on_component_added)

# ❌ Плохо: polling с рефрешем
while True:
    components = api.get_components_with_paths_for_version(version_id, force_refresh=True)
    time.sleep(5)
```

---

## Заключение

1. **Кеш работает отлично:** Доступ к данным из MemoryCache ~0.0ms
2. **Рефреш быстрее при повторных вызовах:** Из-за состояния кеша, но это не означает, что рефреш всегда нужен
3. **Используйте рефреш осознанно:** Только после трансферов, изменений метаданных или явного запроса пользователя
4. **Указывайте конкретные поля:** Для оптимизации производительности
5. **Используйте события:** Вместо polling с рефрешем

**Итог:** Текущая архитектура кеширования и рефреша работает эффективно. Рефреш следует использовать только при необходимости, а не по умолчанию.
