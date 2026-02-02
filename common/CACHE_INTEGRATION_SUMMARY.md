# Интеграция общего механизма кеширования

## Обзор

Все модули проекта теперь используют общий механизм кеширования из `ftrack_inout/common/`, который обеспечивает:
- Оптимизированное многоуровневое кеширование (FileCache → MemoryCache → LoggingCache)
- Единую точку создания сессий через `get_shared_session()`
- Использование переменной окружения `FTRACK_CACHE` для настройки кеша
- Автоматическую предзагрузку данных через `CachePreloader`

## Обновленные модули

### 1. Publisher модули

#### `publisher/dcc/maya/__init__.py`
- **Функция:** `_get_ftrack_session()`
- **Изменения:** Использует `get_shared_session()` из `common.session_factory`
- **Fallback:** Сохраняет совместимость с локальным кешем в `cmds._ftrack_session`

#### `publisher/dcc/houdini/__init__.py`
- **Функция:** `_get_ftrack_session()`
- **Изменения:** Использует `get_shared_session()` из `common.session_factory`
- **Fallback:** Сохраняет совместимость с `hou.session.ftrack_session`

#### `publisher/ui/publisher_widget.py`
- **Метод:** `__init__()` (инициализация сессии)
- **Изменения:** Использует `get_shared_session()` при создании виджета
- **Fallback:** Создает новую сессию, если общий механизм недоступен

### 2. Houdini Utils модули

#### `ftrack_hou_utils/ftrack_utils.py`
- **Функция:** `get_session()`
- **Изменения:** Использует `get_shared_session()` из `common.session_factory`
- **Fallback:** Сохраняет локальный кеш `_ftrack_session` для обратной совместимости

#### `ftrack_hou_utils/api_client.py`
- **Функция:** `get_session()`
- **Изменения:** Использует `get_shared_session()` из `common.session_factory`
- **Fallback:** Сохраняет локальный кеш `_ftrack_session` для обратной совместимости

### 3. Browser модули

#### `browser/browser_widget.py`
- **Метод:** `_create_session_with_cache()`
- **Изменения:** Использует `get_shared_session()` перед созданием локальной сессии
- **Fallback:** Сохраняет логику создания кеша через `cache_maker` для специфичных случаев

- **Класс:** `TransferWorker`
- **Метод:** `run()`
- **Изменения:** Использует `get_shared_session()` для создания сессии в фоновом потоке
- **Fallback:** Создает новую сессию, если общий механизм недоступен

#### `browser/browser_widget_optimized.py`
- **Метод:** `_create_basic_session()`
- **Изменения:** Использует `get_shared_session()` перед созданием базовой сессии
- **Fallback:** Создает базовую сессию без кеша, если общий механизм недоступен

### 4. Уже обновленные модули (из предыдущих задач)

#### `mroya_asset_watcher/hook/asset_watcher.py`
- ✅ Уже использует `CachePreloader` из `common.cache_preloader`
- ✅ Использует `get_shared_session()` (через параметр `session`)

#### `hsite/packages_common/mroya_taskhub_browser/python3.11libs/ftrack_houdini/finput.py`
- ✅ Уже использует `get_shared_session()` из `common.session_factory`

## Архитектура

### Иерархия fallback

```
1. Попытка использовать get_shared_session() из common.session_factory
   ↓ (если ImportError или session=None)
2. Fallback к локальному механизму кеширования
   ↓ (если недоступно)
3. Создание базовой сессии без кеша
```

### Преимущества

1. **Единая точка конфигурации:** Все модули используют `FTRACK_CACHE` из переменной окружения
2. **Оптимизированное кеширование:** Многоуровневый кеш обеспечивает быстрый доступ (~0.0ms)
3. **Обратная совместимость:** Все модули сохраняют fallback к локальным механизмам
4. **Централизованное управление:** Изменения в логике кеширования применяются ко всем модулям

## Использование

### Для разработчиков

Все модули автоматически используют общий механизм кеширования. Никаких изменений в коде не требуется.

### Настройка кеша

Установите переменную окружения `FTRACK_CACHE` для указания пути к кешу:

```bash
# Windows
set FTRACK_CACHE=X:\ftrack_cache\ftrack_cache_db

# Linux/Mac
export FTRACK_CACHE=/path/to/ftrack_cache/ftrack_cache_db
```

### Проверка работы

Все модули логируют использование общего механизма:

```
[OK] Using shared session from common session factory
```

Если общий механизм недоступен, модули используют fallback:

```
Common session factory not available, using local session cache
```

## Производительность

См. `CACHE_REFRESH_ANALYSIS.md` для детального анализа производительности.

### Ключевые метрики:

- **Доступ из MemoryCache:** ~0.0ms
- **Ускорение от кеша:** ~14,000x (0.1ms vs 1465ms для query)
- **Рефреш:** ~1.5s для 39 версий (с обновлением метаданных)

## Совместимость

Все изменения обратно совместимы:
- Модули продолжают работать, если `common` модуль недоступен
- Локальные механизмы кеширования сохранены как fallback
- Существующий код не требует изменений

## Следующие шаги

1. ✅ Интеграция общего механизма кеширования
2. ⏳ Тестирование производительности в реальных условиях
3. ⏳ Мониторинг использования кеша через логи
4. ⏳ Оптимизация на основе метрик использования
