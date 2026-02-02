# 🏗️ Модульная архитектура Ftrack Browser

Полное руководство по использованию модульных компонентов браузера ftrack.

## 📋 **Обзор модулей**

### 🎯 **Основные модули**

| Модуль | Назначение | Зависимости |
|--------|------------|-------------|
| `browser_ui.py` | UI компоненты браузера | PySide2 |
| `simple_api_client.py` | API клиент ftrack | ftrack_api |
| `cache_preloader.py` | Система кеширования | ftrack_api |

### 🔧 **Специализированные модули**

| Модуль | Назначение | Использование |
|--------|------------|---------------|
| `houdini_integration.py` | Houdini HDA операции | Только в Houdini |
| `standalone_browser.py` | Универсальный браузер | Любые приложения |
| `lightweight_cache.py` | Легковесное кеширование | HDA ноды |

---

## 🎯 **Сценарии использования**

### 1. **Houdini HDA - установка параметров**

```python
from ftrack_inout.browser.houdini_integration import HoudiniIntegration

# Создаем интегратор
houdini = HoudiniIntegration()

# Получаем выбранные ноды
selected_nodes = houdini.get_selected_nodes()

# Устанавливаем параметры
result = houdini.set_hda_params(
    nodes=selected_nodes,
    asset_version_id="12345",
    component_name="main",
    component_id="67890"
)

print(f"✅ Success: {result['success']}, ❌ Failed: {result['failed']}")
```

### 2. **Универсальный браузер (вне Houdini)**

```python
from ftrack_inout.browser.standalone_browser import StandaloneBrowserApp

# Запуск как самостоятельное приложение
app = StandaloneBrowserApp()
app.run()
```

### 3. **Встраивание в другое приложение**

```python
from ftrack_inout.browser.standalone_browser import create_browser_widget
from PySide2.QtWidgets import QMainWindow, QVBoxLayout, QWidget

class MyApp(QMainWindow):
    def __init__(self):
        super().__init__()
        
        # Создаем виджет браузера
        browser_widget = create_browser_widget(self)
        
        # Встраиваем в наше приложение
        central_widget = QWidget()
        layout = QVBoxLayout(central_widget)
        layout.addWidget(browser_widget)
        self.setCentralWidget(central_widget)
```

### 4. **Легковесное кеширование в HDA**

```python
# В finput.py или другой HDA ноде
from ftrack_inout.browser.lightweight_cache import get_asset_version_info, get_component_info

# Получаем параметры ноды
asset_version_id = hou.pwd().parm("assetversionid").eval()
component_id = hou.pwd().parm("componentid").eval()

# Быстро получаем данные (с кешированием)
if asset_version_id:
    asset_info = get_asset_version_info(asset_version_id)
    if asset_info:
        print(f"📁 Asset: {asset_info['asset_name']}")
        print(f"🔢 Version: {asset_info['version_number']}")

if component_id:
    comp_info = get_component_info(component_id)
    if comp_info and comp_info['file_path']:
        # Используем путь к файлу
        file_path = comp_info['file_path']
        # Загружаем геометрию, текстуры и т.д.
```

### 5. **Скрипты без UI**

```python
from ftrack_inout.browser.standalone_browser import get_ftrack_data

# Получаем данные для скрипта
data = get_ftrack_data(
    asset_name="Character_Main", 
    project_name="MyProject"
)

if data:
    for av in data['asset_versions']:
        print(f"Version {av['version']}: {av['name']}")
```

---

## ⚙️ **Конфигурация**

### **HDA параметры (hda_params_config.yaml)**

```yaml
hda_parameters:
  asset_version_id:
    - "assetversionid"      # Основной (строчные)
    - "AssetVersionId"      # Запасной (заглавные)
  component_name:
    - "componentname"
    - "ComponentName"
  component_id:
    - "componentid"
    - "ComponentId"
  task_id:
    - "task_Id"             # Существующий формат
    - "taskid"
    - "TaskId"

logging:
  show_found_params: false  # Показывать найденные параметры
  show_param_values: true   # Показывать установленные значения
```

---

## 🚀 **Производительность**

### **Кеширование**

| Модуль | Время кеша | Назначение |
|--------|------------|------------|
| `cache_preloader.py` | Сессия | Полный кеш браузера |
| `lightweight_cache.py` | 5 минут | Быстрые запросы в HDA |

### **Оптимизация**

```python
# Для HDA нод - используйте легковесный кеш
from ftrack_inout.browser.lightweight_cache import get_global_cache

# Настройка времени кеша (в секундах)
cache = get_global_cache(cache_duration=600)  # 10 минут

# Очистка кеша при необходимости
cache.clear_cache()

# Статистика кеша
stats = cache.get_cache_stats()
print(f"📊 Cache: {stats['valid_items']}/{stats['total_items']} items")
```

---

## 🔌 **Интеграция с finput**

### **Пример использования в finput**

```python
# В finput HDA ноде
import hou
from ftrack_inout.browser.lightweight_cache import get_component_info

def update_geometry():
    """Обновляет геометрию из ftrack компонента"""
    
    # Получаем ID компонента из параметра
    component_id = hou.pwd().parm("componentid").eval()
    
    if not component_id:
        return
    
    # Быстро получаем информацию о компоненте
    comp_info = get_component_info(component_id)
    
    if comp_info and comp_info['file_path']:
        file_path = comp_info['file_path']
        
        # Проверяем тип файла
        if file_path.endswith('.abc'):
            # Загружаем Alembic
            load_alembic_file(file_path)
        elif file_path.endswith('.bgeo'):
            # Загружаем Houdini геометрию
            load_bgeo_file(file_path)
        
        print(f"✅ Loaded: {comp_info['name']} ({comp_info['file_type']})")
    else:
        print(f"❌ Component {component_id} not found or no file")

# Вызываем при изменении параметра
if hou.pwd().parm("componentid").eval():
    update_geometry()
```

---

## 🛠️ **Разработка и расширение**

### **Добавление нового модуля**

1. **Создайте файл модуля**
```python
# my_custom_module.py
from simple_api_client import SimpleFtrackClient

class MyCustomModule:
    def __init__(self):
        self.client = SimpleFtrackClient()
    
    def my_function(self):
        # Ваша логика
        pass
```

2. **Обновите __init__.py**
```python
from .my_custom_module import MyCustomModule
```

3. **Добавьте в документацию**

### **Тестирование модулей**

```python
# test_modules.py
def test_houdini_integration():
    from ftrack_inout.browser.houdini_integration import HoudiniIntegration
    houdini = HoudiniIntegration()
    assert houdini.load_config() is not None

def test_lightweight_cache():
    from ftrack_inout.browser.lightweight_cache import LightweightFtrackCache
    cache = LightweightFtrackCache()
    stats = cache.get_cache_stats()
    assert 'total_items' in stats
```

---

## 📚 **API Reference**

### **HoudiniIntegration**

```python
class HoudiniIntegration:
    def find_hda_params(node, param_types=None) -> dict
    def set_hda_params(nodes, **params) -> dict
    def load_snapshot(snapshot_path) -> bool
    def get_selected_nodes() -> list
```

### **LightweightFtrackCache**

```python
class LightweightFtrackCache:
    def get_asset_version(asset_version_id) -> dict
    def get_component(component_id) -> dict
    def get_task(task_id) -> dict
    def clear_cache() -> None
    def get_cache_stats() -> dict
```

### **StandaloneFtrackBrowser**

```python
class StandaloneFtrackBrowser(QMainWindow):
    def get_selected_component_data() -> dict
    def get_current_asset_version_id() -> str
    def refresh_data() -> None
```

---

## ✅ **Лучшие практики**

### **1. Выбор правильного модуля**

- **Houdini HDA** → `houdini_integration.py`
- **Другие приложения** → `standalone_browser.py`
- **Быстрые запросы** → `lightweight_cache.py`
- **Полный браузер** → `browser_widget.py`

### **2. Управление памятью**

```python
# Очищайте кеш периодически
from ftrack_inout.browser.lightweight_cache import clear_global_cache

# В конце сессии
clear_global_cache()
```

### **3. Обработка ошибок**

```python
try:
    from ftrack_inout.browser.houdini_integration import HoudiniIntegration
    houdini = HoudiniIntegration()
    result = houdini.set_hda_params(nodes, asset_version_id="123")
    
    if result['errors']:
        for error in result['errors']:
            print(f"❌ {error}")
            
except ImportError:
    print("⚠️ Houdini integration not available")
```

---

## 🎯 **Заключение**

Модульная архитектура позволяет:

- ✅ **Использовать только нужные компоненты**
- ✅ **Легко интегрировать в разные приложения**
- ✅ **Оптимизировать производительность**
- ✅ **Упростить разработку и тестирование**

Каждый модуль решает конкретную задачу и может использоваться независимо от других. 